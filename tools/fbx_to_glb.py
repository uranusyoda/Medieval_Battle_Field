# -*- coding: utf-8 -*-
"""Tripo FBX → GLB（贴图内嵌），作为 import_tripo.py 的上游一步。

用法（在项目根目录）：
  /Applications/Blender.app/Contents/MacOS/Blender --background --threads 4 \
    --python tools/fbx_to_glb.py -- \
    --fbx tripo-out/templar_tpose_unarmored/.../model.fbx --out tripo-out/templar_tpose_unarmored/templar_tpose_unarmored.glb

为什么需要：tripo make 带 `--for game-pc` 时，最后一步是 convert:FBX，
CLI 只下载链尾产物，GLTF 原件不落盘。FBX 里贴图是内嵌的，Blender 转一道即可。
"""
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(flag, default=None, cast=str):
    return cast(argv[argv.index(flag) + 1]) if flag in argv else default


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


def main():
    fbx = arg("--fbx")
    out = arg("--out")
    if not fbx or not out:
        raise SystemExit("需要 --fbx 与 --out")
    fbx = fbx if os.path.isabs(fbx) else os.path.join(ROOT, fbx)
    out = out if os.path.isabs(out) else os.path.join(ROOT, out)
    if not os.path.exists(fbx):
        raise SystemExit(f"FBX 不存在: {fbx}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=fbx, use_anim=False, ignore_leaf_bones=True)

    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("FBX 里没有网格")
    lo, hi = world_bounds(meshes)
    dims = hi - lo
    print(f"[FBX] meshes={len(meshes)} bbox {dims.x:.4f} x {dims.y:.4f} x {dims.z:.4f}")

    tris = sum(sum(max(len(p.vertices) - 2, 0) for p in o.data.polygons) for o in meshes)
    verts = sum(len(o.data.vertices) for o in meshes)
    mats = sorted({m.name for o in meshes for m in o.data.materials if m})
    imgs = [(i.name, i.size[0], i.size[1], i.packed_file is not None) for i in bpy.data.images if i.size[0] > 1]
    print(f"[FBX] verts={verts} tris={tris} materials={mats}")
    print(f"[FBX] images={imgs}")

    # 拆父级空物体 + 烘变换，避免 GLB 里带一层缩放
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in list(bpy.data.objects):
        if o.type == "EMPTY":
            bpy.data.objects.remove(o, do_unlink=True)

    lo, hi = world_bounds(meshes)
    print(f"[FBX] baked bbox {(hi - lo).x:.4f} x {(hi - lo).y:.4f} x {(hi - lo).z:.4f}")

    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.export_scene.gltf(
        filepath=out,
        export_format="GLB",
        export_yup=True,
        use_selection=True,
        export_apply=True,
        export_image_format="AUTO",
    )
    print(f"[OUT] {out} ({os.path.getsize(out) // 1024} KB)")


main()
