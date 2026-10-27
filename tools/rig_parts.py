# -*- coding: utf-8 -*-
"""对「16 块分块模型」绑骨。

与 tools/rig_templar.py 的区别：
  - rig_templar.py 是「高模 → 减面 → 单壳网格 → 25 骨 → bone heat」，用于整模。
  - 这里不动网格、不分块合并，直接给 16 个部件各建一套顶点组 + Armature 修改器，
    16 块共用一套骨架；权重按「骨段反距离」解析计算（与 rig_templar 的兜底算法同源），
    因此接缝两侧权重连续，不会撕开。

骨架沿用项目 25 骨命名与层级，但位置取自本次分块的实测关节：
  髋 0.930 / 腰 1.100 / 胸 1.306 / 颈 1.496 / 头 1.556 / 头顶 1.830
  肩 (±0.185, 0.050, 1.455) / 肘 (±0.470, 0.076, 1.462) / 腕 (±0.732, 0.065, 1.474)
  膝 (±0.170, 0.017, 0.500) / 踝 (±0.228, 0.079, 0.090)
（rig_templar 的骨架肘在 0.537、腕在 0.796，手臂骨 y=0，与实体差 6 cm，故不复用。）

用法：
  Blender --background --threads 4 --python tools/rig_parts.py
"""
import os
import sys
import math

import bpy
import numpy as np
from mathutils import Vector, Quaternion, Matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "assets", "models", "characters", "parts")
RENDERS = os.path.join(ROOT, "assets", "renders", "parts")
SRC = os.path.join(MODELS, "templar_tpose_unarmored_parts.blend")
NAME = "templar_tpose_unarmored_parts_rig"
sys.path.insert(0, os.path.join(ROOT, "tools"))
import rig_util  # noqa: E402


def log(*a):
    print("[RIG]", *a, flush=True)


# ---------------------------------------------------------------- 骨架

Z_HIP, Z_WAIST, Z_CHEST, Z_NECK, Z_HEAD, Z_TOP = 0.930, 1.100, 1.306, 1.496, 1.556, 1.830
SH = (0.185, 0.050, 1.455)
EL = (0.470, 0.076, 1.462)
WR = (0.732, 0.065, 1.474)
HT = (0.905, 0.058, 1.472)          # 指尖
HIP = (0.113, 0.000, Z_HIP)
KNEE = (0.170, 0.017, 0.500)
ANKLE = (0.228, 0.079, 0.090)
BALL = (0.228, -0.090, 0.030)
TOE = (0.228, -0.190, 0.020)


def mir(p):
    return (-p[0], p[1], p[2])


def bone_table():
    b = [
        ("root", (0, 0, 0), (0, -0.22, 0), None, False),
        ("hips", (0, 0, Z_HIP), (0, 0, Z_WAIST), "root", False),
        ("spine", (0, 0, Z_WAIST), (0, 0, Z_CHEST), "hips", True),
        ("chest", (0, 0, Z_CHEST), (0, 0, Z_NECK), "spine", True),
        ("neck", (0, 0, Z_NECK), (0, 0, Z_HEAD), "chest", True),
        ("head", (0, 0, Z_HEAD), (0, 0, Z_TOP), "neck", True),
    ]
    for s, f in (("L", 1.0), ("R", -1.0)):
        def q(p):
            return (f * p[0], p[1], p[2])
        b += [
            (f"shoulder.{s}", (f * 0.035, 0.020, Z_CHEST + 0.124), q(SH), "chest", False),
            (f"upper_arm.{s}", q(SH), q(EL), f"shoulder.{s}", True),
            (f"forearm.{s}", q(EL), q(WR), f"upper_arm.{s}", True),
            (f"hand.{s}", q(WR), q(HT), f"forearm.{s}", True),
            (f"thigh.{s}", q(HIP), q(KNEE), "hips", False),
            (f"shin.{s}", q(KNEE), q(ANKLE), f"thigh.{s}", True),
            (f"foot.{s}", q(ANKLE), q(BALL), f"shin.{s}", True),
            (f"toe.{s}", q(BALL), q(TOE), f"foot.{s}", True),
        ]
    # 无披风 / 佩剑几何，但保留挂点，骨架与 templar_rig 25 骨一致
    b += [
        ("cape.01", (0, 0.10, Z_CHEST + 0.05), (0, 0.15, 1.02), "chest", False),
        ("cape.02", (0, 0.15, 1.02), (0, 0.18, 0.66), "cape.01", True),
        ("sword", (0.16, 0.02, Z_HIP + 0.03), (0.17, 0.05, Z_HIP - 0.36), "hips", False),
    ]
    return b


def build_armature():
    data = bpy.data.armatures.new(NAME)
    arm = bpy.data.objects.new(NAME, data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for name, head, tail, parent, connected in bone_table():
        eb = data.edit_bones.new(name)
        eb.head, eb.tail, eb.roll = Vector(head), Vector(tail), 0.0
        if parent:
            eb.parent = data.edit_bones[parent]
            eb.use_connect = connected
    bpy.ops.object.mode_set(mode="OBJECT")
    log(f"armature '{NAME}' bones={len(data.bones)}")
    return arm


# ---------------------------------------------------------------- 手型
# 以下三函数取自 tools/rig_templar.py（同一套手型处理）：Tripo 的 T-pose 五指大张，
# 没有指骨时摆臂会变成摊掌，先把手指往掌心中线收拢 + 屈一点，纯几何、权重不变。

def hand_vertices(ob, wrist, u, hand_len):
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


def palm_normal(pts, u):
    fixed = Vector((0.0, 1.0, 0.0))
    fixed = fixed - u * fixed.dot(u)
    if fixed.length > 1e-6:
        fixed.normalize()
        if abs(fixed.y) > 0.85:
            return fixed
    return None


def relax_hands(ob, arm, gather=0.35, curl=22.0):
    mw = ob.matrix_world
    side = ob["part_en"].split(".")[-1]
    bone = arm.data.bones[f"hand.{side}"]
    wrist = bone.head_local.copy()
    hand_len = (bone.tail_local - bone.head_local).length
    u = (bone.tail_local - bone.head_local).normalized()
    u0 = hand_len * 0.42
    u_gather, u_curl = hand_len * 0.75, hand_len * 0.95
    pts = hand_vertices(ob, wrist, u, hand_len)
    n = palm_normal(pts, u)
    if n is None:
        log(f"  relax_hands hand.{side}: 取不到掌心法线，跳过")
        return
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
        pos = wrist + u * nd.x + e3 * nd.y + n * nd.z
        if curl:
            tc = smooth((a - u0) / (u_curl - u0))
            pos = knuckle + Quaternion(e3, -math.radians(curl) * tc) @ (pos - knuckle)
        v.co = mw.inverted() @ pos
        moved += 1
    ob.data.update()
    log(f"  relax_hands hand.{side}: gather={gather:.2f} curl={curl:.0f}deg verts={moved}")


# ---------------------------------------------------------------- 权重

# 每个部件允许影响它的骨骼（限制集合可避免跨部位串味，且接缝两侧集合重叠→权重连续）
ALLOW = {
    "head": ["head", "neck"],
    "neck": ["neck", "head", "chest"],
    "torso": ["chest", "spine", "neck", "hips", "shoulder.L", "shoulder.R",
              "upper_arm.L", "upper_arm.R"],
    "hips": ["hips", "spine"],          # 盆腔 + 袍摆一律跟 hips（袍摆不跟腿甩）
    "upper_arm.L": ["shoulder.L", "upper_arm.L", "forearm.L", "chest"],
    "forearm.L": ["upper_arm.L", "forearm.L", "hand.L"],
    "hand.L": ["forearm.L", "hand.L"],
    "upper_arm.R": ["shoulder.R", "upper_arm.R", "forearm.R", "chest"],
    "forearm.R": ["upper_arm.R", "forearm.R", "hand.R"],
    "hand.R": ["forearm.R", "hand.R"],
    "thigh.L": ["hips", "thigh.L", "shin.L"],
    "shin.L": ["thigh.L", "shin.L", "foot.L"],
    "foot.L": ["shin.L", "foot.L", "toe.L"],
    "thigh.R": ["hips", "thigh.R", "shin.R"],
    "shin.R": ["thigh.R", "shin.R", "foot.R"],
    "foot.R": ["shin.R", "foot.R", "toe.R"],
}
K, POWER = 3, 4.0
QUANT = 255  # 权重按 1/255 量化后批量写组，避免 200 万次单点调用


def seg_dist(P, a, b):
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    ab = b - a
    L2 = float(ab @ ab)
    t = np.clip(((P - a) @ ab) / (L2 if L2 > 1e-12 else 1.0), 0.0, 1.0)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)


def skin_part(ob, arm):
    name = ob["part_en"]
    cand = ALLOW[name]
    bones = {b.name: b for b in arm.data.bones}
    n = len(ob.data.vertices)
    P = np.empty(n * 3, np.float64)
    ob.data.vertices.foreach_get("co", P)
    P = P.reshape(n, 3) + np.array(ob.location)          # 世界坐标（armature 在原点）
    D = np.stack([seg_dist(P, bones[c].head_local, bones[c].tail_local) for c in cand], axis=1)
    k = min(K, len(cand))
    idx = np.argsort(D, axis=1)[:, :k]
    dsel = np.take_along_axis(D, idx, axis=1)
    W = 1.0 / np.power(dsel + 1e-3, POWER)
    W /= W.sum(1, keepdims=True)
    # 清小权重、重归一
    W[W < 0.02] = 0.0
    W /= np.maximum(W.sum(1, keepdims=True), 1e-9)
    for g in list(ob.vertex_groups):
        ob.vertex_groups.remove(g)
    # 折回「骨骼 × 顶点」的完整矩阵：同一根骨骼可能出现在不同 slot
    Wfull = np.zeros((n, len(cand)))
    rows = np.arange(n)
    for j in range(k):
        np.add.at(Wfull, (rows, idx[:, j]), W[:, j])
    used = 0
    for c, cname in enumerate(cand):
        w = Wfull[:, c]
        mask = w > 0
        if not mask.any():
            continue
        used += 1
        vg = ob.vertex_groups.new(name=cname)
        q = np.round(w[mask] * QUANT).astype(np.int32)
        vidx = np.nonzero(mask)[0]
        for level in np.unique(q):
            if level <= 0:
                continue
            sel = vidx[q == level]
            vg.add(sel.tolist(), float(level) / QUANT, "REPLACE")
    # 统计
    sums = W.sum(1)
    zero = int((sums < 1e-6).sum())
    log(f"  {name:14s} verts={n:7d} bones={used} wsum[{sums.min():.2f},{sums.max():.2f}] zero={zero}")
    return zero


def bind(ob, arm):
    ob.parent = arm
    ob.matrix_parent_inverse = arm.matrix_world.inverted()
    mod = ob.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    mod.use_vertex_groups = True


# ---------------------------------------------------------------- 姿态

# 关节测试姿态（方向为 armature 空间单位向量；脚掌保持水平=静止方向，避免看起来像悬空）
FOOT_FLAT = (0.0, -0.94, -0.34)

POSE_ARM = {          # 双臂自然下垂 + 屈肘 90°，测肩与肘
    "upper_arm.L": ((0.30, 0.02, -0.95), 0),
    "forearm.L": ((0.06, -0.97, 0.22), 0),
    "hand.L": ((0.04, -0.98, 0.19), 0),
    "upper_arm.R": ((-0.30, 0.02, -0.95), 0),
    "forearm.R": ((-0.06, -0.97, 0.22), 0),
    "hand.R": ((-0.04, -0.98, 0.19), 0),
}
POSE_KNEE = {         # 左腿高抬屈膝 90°，右腿站直，测髋/膝/踝
    "thigh.L": ((0.03, -0.93, -0.36), 0),
    "shin.L": ((0.02, 0.12, -0.99), 0),
    "foot.L": (FOOT_FLAT, 0),
    "upper_arm.L": ((0.55, 0.10, -0.83), 0),
    "forearm.L": ((0.40, -0.10, -0.91), 0),
    "upper_arm.R": ((-0.35, -0.15, -0.92), 0),
    "forearm.R": ((-0.25, -0.30, -0.92), 0),
}
POSE_WALK = {         # 行走接触帧：左腿前、右腿后蹬，摆臂反向
    "upper_arm.L": ((0.34, 0.32, -0.88), 0),
    "forearm.L": ((0.28, 0.16, -0.95), 0),
    "hand.L": ((0.26, 0.10, -0.96), 0),
    "upper_arm.R": ((-0.32, -0.36, -0.88), 0),
    "forearm.R": ((-0.26, -0.46, -0.85), 0),
    "hand.R": ((-0.24, -0.50, -0.83), 0),
    "thigh.L": ((0.02, -0.36, -0.93), 0),
    "shin.L": ((0.01, -0.08, -1.0), 0),
    "foot.L": (FOOT_FLAT, 0),
    "thigh.R": ((-0.02, 0.28, -0.96), 0),
    "shin.R": ((-0.02, 0.56, -0.83), 0),
    "foot.R": ((0.0, -0.55, -0.84), 0),
    "toe.R": ((0.0, -0.95, -0.31), 0),
    "__shift__": {"hips": (0.0, 0.0, -0.02)},
}
POSE_CROUCH = {       # 深蹲：脚掌贴地，测髋/膝/踝极限
    "spine": ((0.0, -0.14, 0.99), 0),
    "chest": ((0.0, -0.20, 0.98), 0),
    "neck": ((0.0, 0.08, 1.0), 0),
    "head": ((0.0, 0.04, 1.0), 0),
    "upper_arm.L": ((0.34, -0.30, -0.89), 0),
    "forearm.L": ((0.24, -0.62, -0.75), 0),
    "upper_arm.R": ((-0.34, -0.30, -0.89), 0),
    "forearm.R": ((-0.24, -0.62, -0.75), 0),
    "thigh.L": ((0.06, -0.72, -0.69), 0),
    "shin.L": ((0.02, 0.66, -0.75), 0),
    "foot.L": (FOOT_FLAT, 0),
    "thigh.R": ((-0.06, -0.72, -0.69), 0),
    "shin.R": ((-0.02, 0.66, -0.75), 0),
    "foot.R": (FOOT_FLAT, 0),
    "__shift__": {"hips": (0.0, 0.02, -0.26)},
}


def shoot(scene, cam, path, loc, target, scale, res=(720, 900)):
    scene.render.resolution_x, scene.render.resolution_y = res
    rig_util.place_cam(scene, cam, loc, target, scale)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    log("render", os.path.basename(path))


# ---------------------------------------------------------------- main

def main():
    bpy.ops.wm.open_mainfile(filepath=SRC)
    objs = [o for o in bpy.data.objects if o.type == "MESH" and o.get("part_en")]
    objs.sort(key=lambda o: o["part_en"])
    log(f"loaded {len(objs)} parts from {os.path.basename(SRC)}")

    arm = build_armature()
    for ob in objs:
        if ob["part_en"].startswith("hand."):
            relax_hands(ob, arm, gather=0.35, curl=22.0)
    zero = 0
    for ob in objs:
        zero += skin_part(ob, arm)
        bind(ob, arm)
    log(f"skinned, zero-weight verts total={zero}")

    # 保存 + 导出
    out_blend = os.path.join(MODELS, f"{NAME}.blend")
    bpy.ops.wm.save_as_mainfile(filepath=out_blend, compress=True)
    log("saved", out_blend)
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    for ob in objs:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = arm
    out_glb = os.path.join(MODELS, f"{NAME}.glb")
    bpy.ops.export_scene.gltf(filepath=out_glb, export_format="GLB", use_selection=True,
                              export_apply=False, export_skins=True, export_yup=True,
                              export_materials="EXPORT", export_texcoords=True, export_normals=True)
    log("exported", out_glb, f"{os.path.getsize(out_glb)/1e6:.1f} MB")


if __name__ == "__main__":
    main()
