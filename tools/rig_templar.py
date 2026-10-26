# -*- coding: utf-8 -*-
"""给 Tripo 高模做游戏化处理并绑骨：减面 → 贴图降采样 → 25 骨人形骨架 → 蒙皮 → 静态姿态验收。

用法：
  /Applications/Blender.app/Contents/MacOS/Blender --background --threads 4 \
    --python tools/rig_templar.py -- --decimate 150000 --tex 2048

给别的模型绑骨时用 --src / --name（默认仍是有甲版 templar_rig）：
  ... --python tools/rig_templar.py -- \
    --src templar_tpose_unarmored.blend --name templar_tpose_unarmored_rigged \
    --decimate 150000 --tex 2048

产物：
  assets/models/characters/<name>.blend
  assets/models/characters/<name>.glb        （带蒙皮，未做动作）
  assets/renders/<name>_pose_{front,threequarter}.png
"""
import math
import os
import sys
from math import radians

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rig_util import aim_palm  # noqa: E402  手部两向量定姿，与动画脚本共用

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "assets", "models", "characters")
RENDERS = os.path.join(ROOT, "assets", "renders")

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(flag, default=None, cast=str):
    return cast(argv[argv.index(flag) + 1]) if flag in argv else default


def has(flag):
    return flag in argv


RIG_NAME = arg("--name", "templar_rig")
PRESET = arg("--preset", "full")          # full = 25 骨（含披风/佩剑/脚趾）；body = 大关节 20 骨
SRC = os.path.join(MODELS, arg("--src", "templar_tpose.blend"))
OUT_BLEND = os.path.join(MODELS, arg("--out", f"{RIG_NAME}.blend"))
OUT_GLB = os.path.join(MODELS, f"{RIG_NAME}.glb")


def log(*a):
    print("[RIG]", *a)


# ---------------------------------------------------------------- mesh prep

def load_mesh():
    bpy.ops.wm.open_mainfile(filepath=SRC)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("源文件里没有 mesh")
    ob = meshes[0]
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    return ob


def decimate(ob, target):
    tris = sum(max(len(p.vertices) - 2, 0) for p in ob.data.polygons)
    if target <= 0 or tris <= target:
        log(f"tris={tris}, skip decimate")
        return
    ratio = target / float(tris)
    m = ob.modifiers.new("dec", "DECIMATE")
    m.decimate_type = "COLLAPSE"
    m.ratio = ratio
    bpy.ops.object.modifier_apply(modifier=m.name)
    after = sum(max(len(p.vertices) - 2, 0) for p in ob.data.polygons)
    log(f"decimate {tris} -> {after} tris (ratio {ratio:.4f})")


def downscale_textures(size):
    if size <= 0:
        return
    for img in bpy.data.images:
        if img.size[0] > size:
            log(f"texture {img.name} {img.size[0]} -> {size}")
            img.scale(size, size)
            img.pack()


# ---------------------------------------------------------------- armature

def landmarks(ob):
    """量出手臂轴线的真实斜度（图里 T-pose 手臂是微微下垂的）与臂展。"""
    co = [ob.matrix_world @ v.co for v in ob.data.vertices]
    top = max(c.z for c in co)
    span = max(abs(c.x) for c in co)

    def fit(sign):
        pts = [(abs(c.x), c.z) for c in co
               if c.x * sign > 0.30 and 0.95 < c.z < 1.70 and abs(c.y) < 0.25]
        n = len(pts)
        mx = sum(p[0] for p in pts) / n
        mz = sum(p[1] for p in pts) / n
        sxx = sum((p[0] - mx) ** 2 for p in pts)
        sxy = sum((p[0] - mx) * (p[1] - mz) for p in pts)
        b = sxy / sxx if sxx else 0.0
        return b, mz - b * mx, n

    bL, aL, nL = fit(1)
    bR, aR, nR = fit(-1)
    b = (bL + bR) / 2.0
    a = (aL + aR) / 2.0
    z_at = lambda ax: a + b * ax
    return {"top": top, "span": span, "slope": b, "z_shoulder": z_at(0.20),
            "z_elbow": z_at(span * 0.58), "z_wrist": z_at(span * 0.86), "n": (nL, nR)}


def hand_vertices(ob, wrist, u, hand_len):
    """粗选手掌区域（此时还没蒙皮，只能按空间范围取）：返回 [(vertex, d)]。"""
    mw = ob.matrix_world
    out = []
    for v in ob.data.vertices:
        d = (mw @ v.co) - wrist
        a = d.dot(u)
        if a < -0.45 * hand_len or a > 1.6 * hand_len:
            continue
        if (d - u * a).length > 0.9 * hand_len:
            continue
        out.append((v, d))
    return out


def palm_normal(pts, u, u_cut):
    """掌心法线。

    源模型按管线约定面朝 -Y，T-pose 掌心朝前，所以手背方向就是 +Y；先试这个确定性
    方向，只有在手背明显不朝 +Y 时才退回点云 PCA（防止换了朝向的源模型收错方向）。
    """
    fixed = Vector((0.0, 1.0, 0.0))
    fixed = (fixed - u * fixed.dot(u))
    if fixed.length > 1e-6:
        fixed.normalize()
        if abs(fixed.y) > 0.85:
            return fixed

    distal = [d for _, d in pts if d.dot(u) > u_cut]
    if len(distal) < 32:
        return None
    mean = sum(distal, Vector()) / len(distal)
    cov = [[0.0] * 3 for _ in range(3)]
    for p in distal:
        q = p - mean
        for i in range(3):
            for j in range(3):
                cov[i][j] += q[i] * q[j]
    # 协方差阵对称：用 (tr·I - C) 的幂迭代拿最小特征向量
    tr = cov[0][0] + cov[1][1] + cov[2][2]
    m = Matrix([[tr - cov[i][j] for j in range(3)] for i in range(3)])
    vec = Vector((0.0, 1.0, 0.0))
    for _ in range(48):
        vec = m @ vec
        if vec.length < 1e-9:
            return None
        vec.normalize()
    n = vec - u * vec.dot(u)
    if n.length < 1e-6:
        return None
    n.normalize()
    # 统一指到手背（+Y 一侧）：源模型 T-pose 掌心朝 -Y
    return -n if n.y < 0 else n


def relax_hands(ob, arm, gather=0.35, curl=22.0):
    """把 T-pose 里五指大张的摊手收成自然下垂的松手。

    Tripo 生成的是五指张开的 T-pose，而且没有指骨。这里做两步纯几何处理（只动手指区，
    掌根不动，顶点权重不变，所有动作与 GLB 都继承）：
      1) 扇面收拢 gather：绕掌心法线把手指往掌心中线合拢；
      2) 屈指 curl：绕指根轴把指尖往掌心方向压一点，避免手指像一把直叉。
    真正的抓握动作仍需要指骨，这里只解决静止/摆臂时的手型。
    """
    if gather <= 0 and curl <= 0:
        log("relax_hands: gather/curl 都为 0，保持 Tripo 原始手型（手指不动）")
        return
    mw = ob.matrix_world
    for side in ("L", "R"):
        bone = arm.data.bones[f"hand.{side}"]
        wrist = bone.head_local.copy()
        hand_len = (bone.tail_local - bone.head_local).length
        u = (bone.tail_local - bone.head_local).normalized()
        u0 = hand_len * 0.42
        u_gather, u_curl = hand_len * 0.75, hand_len * 0.95
        pts = hand_vertices(ob, wrist, u, hand_len)
        n = palm_normal(pts, u, u0)
        if n is None:
            log(f"relax_hands hand.{side}: 取不到掌心法线，跳过")
            continue
        e3 = n.cross(u).normalized()
        knuckle = wrist + u * u0

        def smooth(t):
            t = max(0.0, min(1.0, t))
            return t * t * (3 - 2 * t)

        moved = 0
        for v, d in pts:
            a, b = d.dot(u), d.dot(e3)
            if a <= u0:
                continue
            t = smooth((a - u0) / (u_gather - u0))
            q = Quaternion(n, -gather * t * math.atan2(b, a))
            nd = q @ Vector((a, b, d.dot(n)))
            p = wrist + u * nd.x + e3 * nd.y + n * nd.z
            if curl:
                tc = smooth((a - u0) / (u_curl - u0))
                p = knuckle + Quaternion(e3, -math.radians(curl) * tc) @ (p - knuckle)
            v.co = mw.inverted() @ p
            moved += 1
        log(f"relax_hands hand.{side}: gather={gather:.2f} curl={curl:.0f}deg "
            f"verts={moved}/{len(pts)} n=({n.x:+.2f},{n.y:+.2f},{n.z:+.2f})")
    ob.data.update()


def build_armature(lm):
    span = lm["span"]
    wrist_x = span * 0.86
    elbow_x = span * 0.58
    shoulder_x = span * 0.20
    z_sh = lm["z_shoulder"]
    z_el = lm["z_elbow"]
    z_wr = lm["z_wrist"]

    z_hips = 0.95
    z_spine = 1.10
    z_chest = z_sh - 0.14
    z_neck = z_sh + 0.05
    z_head = z_neck + 0.06
    z_knee, z_ankle = 0.50, 0.09
    z_headtop = lm["top"] - 0.02

    bones = [
        ("root", (0, 0, 0), (0, -0.22, 0), None, False),
        ("hips", (0, 0, z_hips), (0, 0, z_spine), "root", False),
        ("spine", (0, 0, z_spine), (0, 0, z_chest), "hips", True),
        ("chest", (0, 0, z_chest), (0, 0, z_neck), "spine", True),
        ("neck", (0, 0, z_neck), (0, 0, z_head), "chest", True),
        ("head", (0, 0, z_head), (0, 0, z_headtop), "neck", True),
        # 左臂（+X，沿拟合斜度）
        ("shoulder.L", (0.035, 0, z_neck - 0.05), (shoulder_x, 0, z_sh), "chest", False),
        ("upper_arm.L", (shoulder_x, 0, z_sh), (elbow_x, 0, z_el), "shoulder.L", True),
        ("forearm.L", (elbow_x, 0, z_el), (wrist_x, 0, z_wr), "upper_arm.L", True),
        ("hand.L", (wrist_x, 0, z_wr), (span - 0.02, 0, z_wr - 0.02), "forearm.L", True),
        # 右臂（-X）
        ("shoulder.R", (-0.035, 0, z_neck - 0.05), (-shoulder_x, 0, z_sh), "chest", False),
        ("upper_arm.R", (-shoulder_x, 0, z_sh), (-elbow_x, 0, z_el), "shoulder.R", True),
        ("forearm.R", (-elbow_x, 0, z_el), (-wrist_x, 0, z_wr), "upper_arm.R", True),
        ("hand.R", (-wrist_x, 0, z_wr), (-(span - 0.02), 0, z_wr - 0.02), "forearm.R", True),
        # 左腿
        ("thigh.L", (0.11, 0, z_hips - 0.02), (0.115, 0, z_knee), "hips", False),
        ("shin.L", (0.115, 0, z_knee), (0.12, 0, z_ankle), "thigh.L", True),
        ("foot.L", (0.12, 0, z_ankle), (0.12, -0.15, 0.025), "shin.L", True),
        ("toe.L", (0.12, -0.15, 0.025), (0.12, -0.25, 0.02), "foot.L", True),
        # 右腿
        ("thigh.R", (-0.11, 0, z_hips - 0.02), (-0.115, 0, z_knee), "hips", False),
        ("shin.R", (-0.115, 0, z_knee), (-0.12, 0, z_ankle), "thigh.R", True),
        ("foot.R", (-0.12, 0, z_ankle), (-0.12, -0.15, 0.025), "shin.R", True),
        ("toe.R", (-0.12, -0.15, 0.025), (-0.12, -0.25, 0.02), "foot.R", True),
        # 披风 + 佩剑挂点
        ("cape.01", (0, 0.10, z_chest + 0.05), (0, 0.15, 1.02), "chest", False),
        ("cape.02", (0, 0.15, 1.02), (0, 0.18, 0.66), "cape.01", True),
        ("sword", (0.16, 0.02, z_hips + 0.03), (0.17, 0.05, z_hips - 0.36), "hips", False),
    ]

    if PRESET == "body":
        # 只绑大关节：躯干 / 头 / 四肢，手当刚体整体（hand 一根骨到指尖），
        # 不带脚趾、披风、佩剑挂点——这几个没有对应几何或这版不需要。
        drop = {"toe.L", "toe.R", "cape.01", "cape.02", "sword"}
        bones = [b for b in bones if b[0] not in drop]
        # hand 骨延伸到指尖，覆盖整只手
        fixed = []
        for name, head, tail, parent, connected in bones:
            if name in ("hand.L", "hand.R"):
                sx = 1 if name.endswith(".L") else -1
                head = (sx * wrist_x, 0, z_wr)
                tail = (sx * (span + 0.015), 0, z_wr - 0.015)
            fixed.append((name, head, tail, parent, connected))
        bones = fixed

    arm_data = bpy.data.armatures.new(RIG_NAME)
    arm = bpy.data.objects.new(RIG_NAME, arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for name, head, tail, parent, connected in bones:
        eb = arm_data.edit_bones.new(name)
        eb.head = Vector(head)
        eb.tail = Vector(tail)
        eb.roll = 0.0
        if parent:
            eb.parent = arm_data.edit_bones[parent]
            eb.use_connect = connected
    bpy.ops.object.mode_set(mode="OBJECT")
    log(f"armature bones={len(arm_data.bones)} shoulder_z={z_sh:.3f} elbow_z={z_el:.3f} "
        f"wrist_z={z_wr:.3f} span={span:.3f}")
    return arm


# ---------------------------------------------------------------- skinning

def bone_segments(arm):
    segs = []
    for b in arm.data.bones:
        if b.name == "root":
            continue
        segs.append((b.name, b.head_local.copy(), b.tail_local.copy()))
    return segs


def dist_to_segment(p, a, b):
    ab = b - a
    t = 0.0 if ab.length_squared == 0 else max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (p - (a + ab * t)).length


def nearest_weights(ob, arm, k=3, power=4.0):
    """按到骨段的距离做反距离加权，作为 bone heat 失败时的兜底。"""
    segs = bone_segments(arm)
    groups = {}
    for name, _, _ in segs:
        groups[name] = ob.vertex_groups.new(name=name)
    mw = ob.matrix_world
    for v in ob.data.vertices:
        p = mw @ v.co
        ds = sorted(((dist_to_segment(p, a, b), name) for name, a, b in segs))[:k]
        ws = [(1.0 / (d + 1e-3) ** power, name) for d, name in ds]
        total = sum(w for w, _ in ws)
        for w, name in ws:
            groups[name].add([v.index], w / total, "REPLACE")


def check_weights(ob):
    zero = 0
    for v in ob.data.vertices:
        if sum(g.weight for g in v.groups) < 1e-5:
            zero += 1
    log(f"unweighted verts={zero} / {len(ob.data.vertices)}")
    return zero


def clean_mesh(ob):
    """AI 生成的网格常有重复点与法线错乱，热蒙皮前先清理。"""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    before = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0006)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(ob.data)
    bm.free()
    log(f"clean: verts {before} -> {len(ob.data.vertices)}")


def assign_nearest(ob, segs, vert_indices, k=3, power=4.0):
    groups = {name: ob.vertex_groups.get(name) or ob.vertex_groups.new(name=name)
              for name, _, _ in segs}
    mw = ob.matrix_world
    for idx in vert_indices:
        p = mw @ ob.data.vertices[idx].co
        ds = sorted(((dist_to_segment(p, a, b), name) for name, a, b in segs))[:k]
        ws = [(1.0 / (d + 1e-3) ** power, name) for d, name in ds]
        total = sum(w for w, _ in ws)
        for w, name in ws:
            groups[name].add([idx], w / total, "REPLACE")


def skin(ob, arm, mode):
    clean_mesh(ob)
    segs = bone_segments(arm)

    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    heat_ok = False
    if mode in ("auto", "nearest"):
        try:
            bpy.ops.object.parent_set(type="ARMATURE_AUTO")
            nv = len(ob.data.vertices)
            weighted = sum(1 for v in ob.data.vertices if sum(g.weight for g in v.groups) > 1e-5)
            log(f"bone heat weighted {weighted}/{nv}")
            heat_ok = weighted > nv * 0.5
        except RuntimeError as e:
            log("bone heat raised:", e)

    if not heat_ok:
        log("fallback: nearest-bone weighting")
        for g in list(ob.vertex_groups):
            ob.vertex_groups.remove(g)
        assign_nearest(ob, segs, [v.index for v in ob.data.vertices])
    else:
        # 热蒙皮漏掉的顶点用最近骨补，避免局部塌陷
        missing = [v.index for v in ob.data.vertices
                   if sum(g.weight for g in v.groups) < 1e-5]
        if missing:
            log(f"patch {len(missing)} unweighted verts by nearest bone")
            assign_nearest(ob, segs, missing)

    check_weights(ob)


def rigid_hands(ob, arm):
    """手当一个整体：整只手（掌 + 指）权重全给 hand 骨，几何一点不动。

    没有指骨，骨骼数量再少也不影响手型——所以这里既不收拢也不弯曲手指，
    只是把这块顶点从 forearm 等组里摘出来、焊到 hand.{L,R} 上。
    """
    mw = ob.matrix_world
    for side in ("L", "R"):
        bone = arm.data.bones[f"hand.{side}"]
        head = bone.head_local.copy()
        axis = bone.tail_local - bone.head_local
        L = axis.length
        u = axis.normalized()
        idx = []
        for v in ob.data.vertices:
            d = (mw @ v.co) - head
            a = d.dot(u)
            if a < -0.10 * L or a > 1.05 * L:
                continue
            if (d - u * a).length > 0.62 * L:
                continue
            idx.append(v.index)
        g = ob.vertex_groups.get(f"hand.{side}") or ob.vertex_groups.new(name=f"hand.{side}")
        for other in ob.vertex_groups:
            if other.name != g.name:
                other.remove(idx)
        g.add(idx, 1.0, "REPLACE")
        log(f"rigid hand.{side}: {len(idx)} verts -> hand.{side} w=1.0 (hand_len={L:.3f})")


# ---------------------------------------------------------------- posing

def rest_dir(pb):
    return (pb.bone.tail_local - pb.bone.head_local).normalized()


def current_orient(pb):
    """父级已摆好时，本骨若局部旋转为 0 的 armature 空间朝向。"""
    if pb.parent:
        par = pb.parent
        return (par.matrix.to_3x3()
                @ par.bone.matrix_local.to_3x3().inverted()
                @ pb.bone.matrix_local.to_3x3())
    return pb.bone.matrix_local.to_3x3()


def aim(arm, name, direction, twist=0.0):
    """把骨骼指向 armature 空间里的目标方向（保持最小扭转）。"""
    pb = arm.pose.bones[name]
    tgt = Vector(direction).normalized()
    q = rest_dir(pb).rotation_difference(tgt)
    W = q.to_matrix() @ pb.bone.matrix_local.to_3x3()
    if twist:
        W = Matrix.Rotation(radians(twist), 3, tgt) @ W
    cur = current_orient(pb)
    pb.rotation_mode = "QUATERNION"
    pb.rotation_quaternion = (cur.inverted() @ W).to_quaternion()
    bpy.context.view_layer.update()


def reset_pose(arm):
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)
    bpy.context.view_layer.update()


# ---------------------------------------------------------------- render

def studio(style="grey"):
    scene = bpy.context.scene
    fm = bpy.data.materials.new("studio_floor")
    fm.use_nodes = True
    b = next(n for n in fm.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (0.30, 0.305, 0.315, 1)
    b.inputs["Roughness"].default_value = 0.95
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, -0.002))
    floor = bpy.context.object
    floor.name = "studio_floor"
    floor.data.materials.append(fm)

    w = bpy.data.worlds.new("studio_world")
    scene.world = w
    w.use_nodes = True
    bg = next(n for n in w.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs[0].default_value = (0.48, 0.49, 0.51, 1)
    bg.inputs[1].default_value = 1.15

    def area(name, loc, energy, color, size, target=(0, 0, 1.0)):
        d = bpy.data.lights.new(name, "AREA")
        d.energy, d.color, d.size = energy, color, size
        o = bpy.data.objects.new(name, d)
        scene.collection.objects.link(o)
        o.location = loc
        o.rotation_euler = (Vector(target) - o.location).to_track_quat("-Z", "Y").to_euler()

    area("key", (-2.4, -3.2, 3.6), 320, (1.0, 0.97, 0.93), 4.0)
    area("fill", (2.8, -2.0, 1.9), 160, (0.94, 0.96, 1.0), 3.5)
    area("rim", (1.4, 2.6, 3.2), 260, (0.90, 0.94, 1.0), 2.5)

    cam_data = bpy.data.cameras.new("camera")
    cam = bpy.data.objects.new("camera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam_data.type = "ORTHO"

    scene.render.engine = "CYCLES"
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 640
    scene.render.resolution_y = 800
    scene.render.film_transparent = False
    return scene, cam, cam_data


def render_to(scene, cam, cam_data, loc, target, scale, path):
    cam.location = loc
    cam.rotation_euler = (Vector(target) - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam_data.ortho_scale = scale
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    log("render", os.path.basename(path))


def export(arm, mesh):
    """导出带蒙皮权重的 GLB（不含动作，动作由 animate_templar.py 补）。"""
    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(
        filepath=OUT_GLB,
        export_format="GLB",
        export_yup=True,
        use_selection=True,
        export_apply=True,
        export_animations=False,
        export_skins=True,
    )
    log(f"exported {OUT_GLB} ({os.path.getsize(OUT_GLB) // 1024} KB)")


def main():
    log(f"src={os.path.basename(SRC)} name={RIG_NAME}")
    ob = load_mesh()
    lm = landmarks(ob)
    log(f"landmarks shoulder_z={lm['z_shoulder']:.3f} slope={lm['slope']:+.3f} "
        f"span={lm['span']:.3f} top={lm['top']:.3f} samples={lm['n']}")
    decimate(ob, arg("--decimate", 150000, int))
    downscale_textures(arg("--tex", 2048, int))

    arm = build_armature(lm)
    relax_hands(ob, arm, arg("--hand-gather", 0.35, float),
                arg("--hand-curl", 22.0, float))
    skin(ob, arm, arg("--weights", "auto"))
    if has("--rigid-hands"):
        rigid_hands(ob, arm)

    scene, cam, cam_data = studio()
    os.makedirs(RENDERS, exist_ok=True)

    # 手部特写：rest pose 下手指原样，先看手有没有被处理坏
    hand = arm.data.bones["hand.L"]
    hz, hx = hand.head_local.z, hand.tail_local.x
    render_to(scene, cam, cam_data, (hx - 0.02, -1.2, hz + 0.10),
              (hx - 0.13, 0, hz - 0.01), 0.34,
              os.path.join(RENDERS, f"{RIG_NAME}_hand.png"))

    # 静态验收姿态：手臂下垂 15°、右腿前迈、躯干微转，检查肩/肘/胯变形
    reset_pose(arm)
    aim(arm, "hips", (0, 0, 1))
    aim(arm, "spine", (0, -0.05, 1))
    aim(arm, "chest", (0, -0.04, 1))
    for side, sx in (("L", 1), ("R", -1)):
        aim(arm, f"upper_arm.{side}", (sx * 0.30, 0.02, -1))
        aim(arm, f"forearm.{side}", (sx * 0.16, -0.10, -1))
        # 掌心朝大腿（略偏前），别把掌心摊给镜头
        aim_palm(arm, f"hand.{side}", (sx * 0.12, -0.16, -1), (-sx * 1.0, -0.18, 0.0))
    aim(arm, "thigh.L", (0.06, -0.35, -1))
    aim(arm, "shin.L", (0.04, 0.10, -1))
    aim(arm, "foot.L", (0.02, -1.0, -0.35))
    aim(arm, "thigh.R", (-0.05, 0.20, -1))
    aim(arm, "shin.R", (-0.03, 0.30, -1))
    aim(arm, "foot.R", (-0.02, -1.0, 0.10))
    if "cape.01" in arm.pose.bones:
        aim(arm, "cape.01", (0, 0.12, -1))
        aim(arm, "cape.02", (0, 0.18, -1))

    render_to(scene, cam, cam_data, (0, -5, 1.05), (0, 0, 0.95), 2.05,
              os.path.join(RENDERS, f"{RIG_NAME}_pose_front.png"))
    render_to(scene, cam, cam_data, (3.4, -3.4, 1.9), (0, 0, 0.95), 2.10,
              os.path.join(RENDERS, f"{RIG_NAME}_pose_threequarter.png"))

    # 姿态归零后保存，避免把测试姿势写进 rest
    reset_pose(arm)
    if not has("--no-glb"):
        export(arm, ob)
    bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)
    log("saved", OUT_BLEND)
    log("DONE")


main()
