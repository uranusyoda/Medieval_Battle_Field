# -*- coding: utf-8 -*-
"""给 templar_rig 补手部骨骼：腕 + 掌 + 拇指/食指/中指/无名指/小指各两节。

原骨架只有一根 hand.L/R 从腕一直到指尖，整只手是一块刚性，摆臂时手掌会跟着扭。
本脚本把 hand 缩成腕骨，再加掌骨和十根指骨（每侧 12 根），并且只重算手部顶点的权重，
身体其它部分保持原来的 bone heat 结果不动。

用法：
  Blender --background --threads 4 --python tools/rig_hands.py [-- --rods]

  --rods   额外渲几张带“骨棍”的手部特写，用来检查骨骼是否落在指头里
"""
import os
import sys
from math import radians

import bpy
import numpy as np
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "assets", "models", "characters")
RENDERS = os.path.join(ROOT, "assets", "renders")
BLEND = os.path.join(MODELS, "templar_rig.blend")

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
WANT_RODS = "--rods" in argv

FINGERS = ["pinky", "ring", "middle", "index"]


def log(*a):
    print("[HAND]", *a)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ---------------------------------------------------------------- landmarks

def kmeans_1d(vals, k, iters=60):
    c = np.array([vals.min() + (vals.max() - vals.min()) * i / (k - 1) for i in range(k)])
    lab = np.zeros(len(vals), dtype=int)
    for _ in range(iters):
        lab = np.abs(vals[:, None] - c[None, :]).argmin(1)
        for kk in range(k):
            if (lab == kk).any():
                c[kk] = vals[lab == kk].mean()
    return c, lab


def hand_landmarks(coords, sign):
    """掌形：用指尖聚类定四指位置，骨头按指根→指尖的直线摆，两节各占一半。

    这样即使 AI 网格的手指挤在一起（间距 1~2 cm），也不会把两根手指的骨分到同一根上。
    拇指单独处理：它从掌心长向上方，用 z 切片追中心线。
    """
    ax = coords[:, 0] * sign
    sel = coords[(ax > 0.762) & (coords[:, 2] > 1.15) & (coords[:, 2] < 1.44)
                 & (coords[:, 1] > -0.26) & (coords[:, 1] < 0.16)]
    sel_ax = sel[:, 0] * sign

    palm = sel[(sel_ax > 0.786) & (sel_ax < 0.842)]
    palm_c = palm.mean(0)
    wrist_head = np.array([0.772 * sign, 0.0, 1.259])
    wrist_tail = np.array([0.800 * sign, palm_c[1], palm_c[2]])

    tips = sel[sel_ax > 0.858]
    ys = tips[:, 1]
    centers, lab = kmeans_1d(ys, 4)
    centers = np.sort(centers)

    sizes = []
    for k in range(4):
        sizes.append(int((np.abs(ys - centers[k]) < (centers[1] - centers[0]) / 2 + 1e-6).sum()))

    z_tips = float(tips[:, 2].mean())
    x_tip = float(np.percentile(tips[:, 0] * sign, 92))
    x_base = 0.845
    fingers = []
    for rank, y_c in enumerate(centers):
        m = np.abs(tips[:, 1] - y_c) < 0.009
        z_c = float(tips[m][:, 2].mean()) if m.any() else z_tips
        base = np.array([x_base * sign, y_c, z_c + 0.006])
        tip = np.array([x_tip * sign, y_c, z_c - 0.010])
        mid = (base + tip) / 2
        # 中指略长、小指略短
        taper = {0: -0.004, 1: 0.002, 2: 0.004, 3: 0.0}[rank]
        tip = tip + np.array([taper * sign, 0, 0])
        fingers.append({"name": FINGERS[rank], "knuckle": base, "mid": mid,
                        "tip": tip, "n": int(m.sum())})

    # 拇指：z 切片追中心线（掌心上方只有拇指这一根柱状结构）
    zs = np.linspace(1.292, 1.366, 4)
    pts = []
    for z in zs:
        band = sel[(np.abs(sel[:, 2] - z) < 0.010) & ((sel[:, 0] * sign) > 0.775)
                   & ((sel[:, 0] * sign) < 0.855)]
        if len(band) > 8:
            pts.append(band.mean(0))
    if len(pts) < 2:
        base_t = np.array([0.796 * sign, palm_c[1] - 0.005, 1.288])
        tip_t = np.array([0.790 * sign, palm_c[1] - 0.018, 1.368])
    else:
        base_t = np.array([pts[0][0], pts[0][1], 1.288])
        tip_t = np.array([pts[-1][0], pts[-1][1], 1.370])
    thumb = {"base": base_t, "mid": (base_t + tip_t) / 2, "tip": tip_t,
             "n": len(pts)}

    knuckle_c = np.mean([f["knuckle"] for f in fingers], axis=0)
    return {"wrist_head": wrist_head, "wrist_tail": wrist_tail, "palm_c": palm_c,
            "knuckle_c": knuckle_c, "fingers": fingers, "thumb": thumb}


# ---------------------------------------------------------------- armature

def add_hand_bones(arm, side, lm):
    sign = 1 if side == "L" else -1
    med = (
        lambda p: Vector((clamp(float(p[0]), -0.95, 0.95), float(p[1]), float(p[2])))
    )
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones

    hand = eb.get(f"hand.{side}")
    if hand is None:
        raise SystemExit(f"缺 hand.{side}")
    hand.tail = med(lm["wrist_tail"])
    hand.head = med(lm["wrist_head"])

    def new_bone(name, head, tail, parent, connect=False):
        b = eb.new(name)
        b.head = med(head)
        b.tail = med(tail)
        b.roll = 0.0
        b.parent = eb[parent]
        b.use_connect = connect
        return b

    knuckle_c = np.array(lm["knuckle_c"])
    palm = new_bone(f"palm.{side}", lm["wrist_tail"], knuckle_c, f"hand.{side}", True)

    # 拇指两节
    new_bone(f"thumb.01.{side}", lm["thumb"]["base"], lm["thumb"]["mid"],
             f"palm.{side}", False)
    new_bone(f"thumb.02.{side}", lm["thumb"]["mid"], lm["thumb"]["tip"],
             f"thumb.01.{side}", True)

    for f in lm["fingers"]:
        new_bone(f"{f['name']}.01.{side}", f["knuckle"], f["mid"], f"palm.{side}", False)
        new_bone(f"{f['name']}.02.{side}", f["mid"], f["tip"], f"{f['name']}.01.{side}", True)

    bpy.ops.object.mode_set(mode="OBJECT")
    hb = arm.data.bones[f"hand.{side}"]
    pb = arm.data.bones[f"palm.{side}"]
    log(f"{side}: 腕 {tuple(round(v, 3) for v in hb.head_local)}→"
        f"{tuple(round(v, 3) for v in hb.tail_local)} 掌长 {(pb.tail_local - pb.head_local).length:.3f}")


def hand_bone_names(side):
    names = [f"hand.{side}", f"palm.{side}", f"thumb.01.{side}", f"thumb.02.{side}"]
    for f in FINGERS:
        names += [f"{f}.01.{side}", f"{f}.02.{side}"]
    return names


# ---------------------------------------------------------------- weights

def seg_dist(p, a, b):
    ab = b - a
    l2 = ab.dot(ab)
    t = 0.0 if l2 == 0 else clamp((p - a).dot(ab) / l2, 0.0, 1.0)
    return (p - (a + ab * t)).length


def reweight_hand(mesh, arm, side, sign, lm):
    """按区域显式分配手部权重，避免腕骨吃掉整只手。

    袖口 → 腕骨/前臂过渡；掌心 → 掌骨；指节 → 就近那根手指的 01/02，指根附近混一点掌骨。
    """
    FINGER_BONES = [f"{f}.01.{side}" for f in FINGERS] + [f"{f}.02.{side}" for f in FINGERS]
    names = [f"hand.{side}", f"palm.{side}", f"thumb.01.{side}", f"thumb.02.{side}",
             f"forearm.{side}"] + FINGER_BONES
    groups = {n: (mesh.vertex_groups.get(n) or mesh.vertex_groups.new(name=n)) for n in names}

    finger_centers = [(f["name"], float(f["knuckle"][1]), float(f["knuckle"][2]),
                       float(f["tip"][0] * sign)) for f in lm["fingers"]]
    x_tip = max(fc[3] for fc in finger_centers)
    thumb_base, thumb_tip = lm["thumb"]["base"], lm["thumb"]["tip"]

    touch = []
    for v in mesh.data.vertices:
        p = mesh.matrix_world @ v.co
        axv = sign * p.x
        if axv > 0.768 and 1.13 < p.z < 1.46 and -0.27 < p.y < 0.17:
            touch.append((v.index, p, axv))

    # 先清空这些顶点的旧权重（含原来的 hand.L）
    for vi, _, _ in touch:
        for g in list(mesh.data.vertices[vi].groups):
            mesh.vertex_groups[g.group].remove([vi])

    stats = {"thumb": 0, "fingers": 0, "palm": 0, "cuff": 0}
    for vi, p, axv in touch:
        w = {}
        if axv < 0.800:                                  # 袖口 → 腕骨 ↔ 前臂
            t = clamp((axv - 0.768) / 0.032, 0.0, 1.0)
            w[f"hand.{side}"] = t
            w[f"forearm.{side}"] = 1.0 - t
            stats["cuff"] += 1
        elif axv < 0.848:                                # 掌心
            w[f"palm.{side}"] = 1.0
            if axv < 0.812:                              # 腕口和掌心之间过渡
                t = (axv - 0.800) / 0.012
                w[f"hand.{side}"] = 0.5 * (1.0 - t)
            stats["palm"] += 1
        else:                                            # 指节 / 拇指
            # 判断是拇指还是四指：拇指在 z 更高的位置且 x 更靠内
            d_thumb = min(seg_dist(p, Vector(thumb_base), Vector(thumb_tip)), 9.9)
            d_fingers = sorted((abs(p.y - fc[1]), fc[0]) for fc in finger_centers)[0]
            use_thumb = d_thumb < 0.030 and axv < 0.870 and p.z > 1.27
            if use_thumb:
                t = clamp((p.z - thumb_base[2]) / max(1e-4, thumb_tip[2] - thumb_base[2]), 0, 1)
                w[f"thumb.01.{side}"] = (1.0 - t) ** 1.5
                w[f"thumb.02.{side}"] = t ** 1.5
                stats["thumb"] += 1
            else:
                fname = d_fingers[1]
                t = clamp((axv - 0.848) / max(1e-4, x_tip - 0.848), 0.0, 1.0)
                w[f"{fname}.01.{side}"] = (1.0 - t)
                w[f"{fname}.02.{side}"] = t
                w[f"palm.{side}"] = max(0.0, 0.55 * (1.0 - t * 3.0))   # 指根和掌骨融合
                stats["fingers"] += 1

        tot = sum(w.values()) or 1.0
        for n, val in w.items():
            if val > 1e-4:
                groups[n].add([vi], val / tot, "REPLACE")

    log(f"{side}: 手部顶点 {len(touch)}（袖口 {stats['cuff']} / 掌 {stats['palm']} / "
        f"指 {stats['fingers']} / 拇指 {stats['thumb']}）")


# ---------------------------------------------------------------- debug rods

def make_rods(arm):
    objs = []
    mat = bpy.data.materials.new("rod")
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (1, 0.15, 0.05, 1)
    bsdf.inputs["Emission Color"].default_value = (1, 0.12, 0.03, 1)
    bsdf.inputs["Emission Strength"].default_value = 2.5

    for b in arm.data.bones:
        if not any(tag in b.name for tag in ("hand.", "palm.", "thumb.", "pinky.", "ring.",
                                            "middle.", "index.")):
            continue
        a = arm.matrix_world @ b.head_local
        c = arm.matrix_world @ b.tail_local
        d = (c - a).length
        if d < 1e-4:
            continue
        bpy.ops.mesh.primitive_cylinder_add(radius=0.0035, depth=d, location=(a + c) / 2)
        rod = bpy.context.object
        log(f"  rod {b.name:14s} len={d:.3f} at {tuple(round(v,3) for v in (a + c) / 2)}")
        rod.rotation_euler = (c - a).to_track_quat("Z", "Y").to_euler()
        rod.data.materials.append(mat)
        objs.append(rod)
    return objs


def render_hand_views():
    sc = bpy.context.scene
    cam = bpy.data.objects.get("camera")
    if cam is None:
        cam = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
        sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 0.52
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 32
    sc.cycles.use_denoising = True
    sc.render.resolution_x = 720
    sc.render.resolution_y = 720
    sc.render.image_settings.file_format = "PNG"
    target = Vector((0.835, -0.09, 1.27))
    views = {
        "top": (0.835, -0.09, 2.10),
        "front": (0.835, -1.60, 1.27),
        "palm": (0.835, 1.30, 1.27),
    }
    out = []
    for name, loc in views.items():
        cam.location = Vector(loc)
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        path = os.path.join("/tmp", f"handrig_{name}.png")
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        out.append(path)
        log("render", path)
    return out


def heat_skin(mesh, arm):
    """用 bone heat 重算整副骨架的权重：指骨细、间距小，热扩散比手写距离权重稳。"""
    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    try:
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    except RuntimeError as e:
        log("bone heat 失败:", e)
        return False
    nv = len(mesh.data.vertices)
    weighted = sum(1 for v in mesh.data.vertices if sum(g.weight for g in v.groups) > 1e-5)
    log(f"bone heat: {weighted}/{nv} 顶点有权重")

    # 平滑 + 限制影响数：AI 网格指尖有碎面，权重不平滑会拉出尖刺
    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = mesh
    bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
    bpy.ops.object.vertex_group_smooth(group_select_mode="ALL", factor=0.5, repeat=2)
    bpy.ops.object.vertex_group_limit_total(limit=4)
    bpy.ops.object.vertex_group_normalize_all(lock_active=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    log("权重已平滑 / 限制 4 影响 / 归一化")
    return weighted > nv * 0.5


def report_hand_weights(mesh, side):
    from collections import defaultdict
    names = {g.index: g.name for g in mesh.vertex_groups}
    tot = defaultdict(float)
    for v in mesh.data.vertices:
        p = mesh.matrix_world @ v.co
        if (p.x if side == "L" else -p.x) > 0.775 and 1.15 < p.z < 1.45:
            for g in v.groups:
                tot[names[g.group]] += g.weight
    top = sorted(tot.items(), key=lambda kv: -kv[1])[:7]
    log(f"  {side} 手部权重: " + "  ".join(f"{k}={v:.0f}" for k, v in top))


def main():
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))

    coords = np.array([(mesh.matrix_world @ v.co)[:] for v in mesh.data.vertices])
    landmarks = {}
    for side, sign in (("L", 1), ("R", -1)):
        lm = hand_landmarks(coords, sign)
        landmarks[side] = lm
        log(f"{side} 手指点数 {[f['n'] for f in lm['fingers']]} 拇指点数 {lm['thumb']['n']}")
        add_hand_bones(arm, side, lm)

    use_heat = "--region-weights" not in argv
    if use_heat and heat_skin(mesh, arm):
        log("权重来源：bone heat")
    else:
        for side, sign in (("L", 1), ("R", -1)):
            reweight_hand(mesh, arm, side, sign, landmarks[side])

    for side in ("L", "R"):
        report_hand_weights(mesh, side)

    log(f"骨架总数 {len(arm.data.bones)}")

    if WANT_RODS:
        rods = make_rods(arm)
        render_hand_views()
        for r in rods:
            bpy.data.objects.remove(r, do_unlink=True)

    bpy.ops.wm.save_as_mainfile(filepath=BLEND)
    log("saved", BLEND)


main()
