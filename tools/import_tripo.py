# -*- coding: utf-8 -*-
"""Tripo GLB → 项目资产的归一化 + 验收渲染 + 运行用 GLB 导出。

用法（在项目根目录）：
  /Applications/Blender.app/Contents/MacOS/Blender --background --threads 4 \
    --python tools/import_tripo.py -- \
    --glb tripo-out/templar_tpose/model.glb --name templar_tpose --height 1.85

可选参数：
  --yaw <deg>        绕 Z 轴校正朝向（默认 0；渲染发现背对镜头时用 180）
  --decimate <tris>  减面到目标三角面数（默认不减，保留 Tripo 原始高模）
  --no-render        跳过四视角渲染
  --no-export        跳过 GLB 导出
"""
import os
import sys

import bpy
from math import radians

from mathutils import Matrix, Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "assets", "models", "characters")
RENDERS = os.path.join(ROOT, "assets", "renders")

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(flag, default=None, cast=str):
    if flag in argv:
        return cast(argv[argv.index(flag) + 1])
    return default


def has(flag):
    return flag in argv


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_glb(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    mesh = [o for o in new if o.type == "MESH"]
    return new, mesh


def world_bounds(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        if o.type != "MESH":
            continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    return lo, hi


def flatten(mesh_objs):
    """拆掉 glTF 的父级空物体并把变换烘进网格（四元数模式下改 euler 无效）。"""
    bpy.ops.object.select_all(action="DESELECT")
    for o in mesh_objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objs[0]
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in list(bpy.data.objects):
        if o.type == "EMPTY":
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")


def apply_matrix(objs, M):
    for o in objs:
        o.matrix_world = M @ o.matrix_world
    bpy.context.view_layer.update()


def bake(objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.ops.object.select_all(action="DESELECT")


def normalize(mesh_objs, target_h, yaw_deg):
    lo, hi = world_bounds(mesh_objs)
    dims = hi - lo
    s = target_h / dims.z if dims.z > 0 else 1.0
    print(f"[NORM] raw bbox {dims.x:.3f} x {dims.y:.3f} x {dims.z:.3f} m, scale x{s:.4f}")

    M = Matrix.Rotation(radians(yaw_deg), 4, "Z") @ Matrix.Scale(s, 4)
    apply_matrix(mesh_objs, M)
    bake(mesh_objs)

    lo, hi = world_bounds(mesh_objs)
    offset = Vector((-(lo.x + hi.x) / 2.0, -(lo.y + hi.y) / 2.0, -lo.z))
    apply_matrix(mesh_objs, Matrix.Translation(offset))
    bake(mesh_objs)

    lo, hi = world_bounds(mesh_objs)
    print(f"[NORM] final bbox {hi.x - lo.x:.3f} x {hi.y - lo.y:.3f} x {hi.z - lo.z:.3f} m, "
          f"feet z={lo.z:.4f}, center x={(lo.x + hi.x) / 2:.4f} y={(lo.y + hi.y) / 2:.4f}")


def stats(mesh_objs):
    tris = sum(sum(max(len(p.vertices) - 2, 0) for p in o.data.polygons) for o in mesh_objs)
    verts = sum(len(o.data.vertices) for o in mesh_objs)
    mats = {m.name for o in mesh_objs for m in o.data.materials if m}
    imgs = [(i.name, i.size[0], i.size[1]) for i in bpy.data.images if i.size[0] > 1]
    print(f"[STATS] meshes={len(mesh_objs)} verts={verts} tris={tris} materials={len(mats)}")
    print(f"[STATS] images={imgs}")
    return tris


def decimate(mesh_objs, target):
    tris = stats(mesh_objs)
    if tris <= target:
        print(f"[DEC] {tris} <= {target}, skip")
        return
    ratio = target / float(tris)
    for o in mesh_objs:
        m = o.modifiers.new("dec", "DECIMATE")
        m.decimate_type = "COLLAPSE"
        m.ratio = ratio
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.modifier_apply(modifier=m.name)
    print(f"[DEC] {tris} -> {stats(mesh_objs)} tris")


def finish_names(roots, name):
    for i, o in enumerate(roots):
        o.name = name if i == 0 else f"{name}.{i}"


def export_glb(mesh_objs, name):
    os.makedirs(MODELS, exist_ok=True)
    path = os.path.join(MODELS, f"{name}.glb")
    bpy.ops.object.select_all(action="DESELECT")
    for o in mesh_objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objs[0]
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        export_yup=True,
        use_selection=True,
        export_apply=True,
    )
    print(f"[EXPORT] {path} ({os.path.getsize(path) // 1024} KB)")
    return path


def save_blend(name):
    os.makedirs(MODELS, exist_ok=True)
    path = os.path.join(MODELS, f"{name}.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    print(f"[BLEND] {path}")


def build_studio(style="grey"):
    """棚拍配置。grey = 中性灰底（金属有环境可反射，适合验收）；dark = 原角色渲染用的暗底。"""
    scene = bpy.context.scene
    grey = style == "grey"

    floor_mat = bpy.data.materials.new("studio_floor")
    floor_mat.use_nodes = True
    bsdf = next(n for n in floor_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (0.30, 0.305, 0.315, 1) if grey else (0.02, 0.021, 0.024, 1)
    bsdf.inputs["Roughness"].default_value = 0.95

    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, -0.002))
    floor = bpy.context.object
    floor.name = "studio_floor"
    floor.data.materials.append(floor_mat)

    world = bpy.data.worlds.new("studio_world")
    scene.world = world
    world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    if grey:
        bg.inputs[0].default_value = (0.48, 0.49, 0.51, 1)
        bg.inputs[1].default_value = 1.15
    else:
        bg.inputs[0].default_value = (0.055, 0.062, 0.075, 1)
        bg.inputs[1].default_value = 0.6

    def area(name, loc, energy, color, size, target=(0, 0, 1.0)):
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.color = color
        data.size = size
        o = bpy.data.objects.new(name, data)
        scene.collection.objects.link(o)
        o.location = loc
        o.rotation_euler = (Vector(target) - o.location).to_track_quat("-Z", "Y").to_euler()
        return o

    if grey:
        area("key", (-2.4, -3.2, 3.6), 320, (1.0, 0.97, 0.93), 4.0)
        area("fill", (2.8, -2.0, 1.9), 160, (0.94, 0.96, 1.0), 3.5)
        area("rim", (1.4, 2.6, 3.2), 260, (0.90, 0.94, 1.0), 2.5)
    else:
        area("key", (-2.2, -3.0, 3.4), 420, (1.0, 0.93, 0.84), 3.0)
        area("fill", (2.6, -1.6, 1.8), 130, (0.80, 0.86, 1.0), 2.5)
        area("rim", (1.2, 2.4, 3.0), 520, (0.72, 0.82, 1.0), 2.0)

    cam_data = bpy.data.cameras.new("camera")
    cam = bpy.data.objects.new("camera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam_data.type = "ORTHO"

    scene.render.engine = "CYCLES"
    scene.cycles.samples = 40
    scene.cycles.use_denoising = True
    scene.render.resolution_x = int(os.environ.get("RENDER_X", 900))
    scene.render.resolution_y = int(os.environ.get("RENDER_Y", 1200))
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    return scene, cam, cam_data


def render_views(scene, cam, cam_data, name):
    os.makedirs(RENDERS, exist_ok=True)
    views = {
        "hero": ((2.6, -4.2, 2.2), (0.05, 0.0, 0.98), 2.25),
        "front": ((0.0, -5.0, 1.05), (0.0, 0.0, 0.95), 2.20),
        "side": ((5.0, 0.0, 1.05), (0.0, 0.0, 0.95), 2.20),
        "back": ((0.0, 5.0, 1.15), (0.0, 0.0, 0.95), 2.20),
    }
    for view, (loc, target, scale) in views.items():
        cam.location = loc
        cam.rotation_euler = (Vector(target) - cam.location).to_track_quat("-Z", "Y").to_euler()
        cam_data.ortho_scale = scale
        scene.render.filepath = os.path.join(RENDERS, f"{name}_{view}.png")
        bpy.ops.render.render(write_still=True)
        print(f"[RENDER] {scene.render.filepath}")


def main():
    glb = arg("--glb")
    name = arg("--name", "templar_tpose")
    height = arg("--height", 1.85, float)
    yaw = arg("--yaw", 0.0, float)
    dec = arg("--decimate", 0, int)
    if not glb or not os.path.isabs(glb):
        glb = os.path.join(ROOT, glb or "")
    if not os.path.exists(glb):
        raise SystemExit(f"GLB 不存在: {glb}")

    reset_scene()
    roots, mesh_objs = import_glb(glb)
    if not mesh_objs:
        raise SystemExit("导入后没有 mesh，检查 GLB")
    print(f"[IMPORT] roots={[o.name for o in roots]} meshes={[o.name for o in mesh_objs]}")

    flatten(mesh_objs)
    normalize(mesh_objs, height, yaw)
    finish_names(mesh_objs, name)
    stats(mesh_objs)
    if dec:
        decimate(mesh_objs, dec)

    if not has("--no-export"):
        export_glb(mesh_objs, name)
    save_blend(name)

    if not has("--no-render"):
        scene, cam, cam_data = build_studio(arg("--studio", "grey"))
        render_views(scene, cam, cam_data, name)

    print("[TRIPO-IMPORT] DONE")


main()
