# -*- coding: utf-8 -*-
"""绑骨/动画共用工具：姿态求解、棚拍、渲染。"""
import os
import sys
from math import radians

import bpy
from mathutils import Matrix, Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "assets", "models", "characters")
RENDERS = os.path.join(ROOT, "assets", "renders")

# 父级到子级的处理顺序（aim 依赖父级已摆好）
ORDER = [
    "hips", "spine", "chest", "neck", "head",
    "shoulder.L", "upper_arm.L", "forearm.L", "hand.L",
    "shoulder.R", "upper_arm.R", "forearm.R", "hand.R",
    "thigh.L", "shin.L", "foot.L", "toe.L",
    "thigh.R", "shin.R", "foot.R", "toe.R",
    "cape.01", "cape.02", "sword",
]


def log(*a):
    print("[ANIM]", *a)


def rest_dir(pb):
    return (pb.bone.tail_local - pb.bone.head_local).normalized()


def current_orient(pb):
    if pb.parent:
        par = pb.parent
        return (par.matrix.to_3x3()
                @ par.bone.matrix_local.to_3x3().inverted()
                @ pb.bone.matrix_local.to_3x3())
    return pb.bone.matrix_local.to_3x3()


def aim(arm, name, direction, twist=0.0):
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


def _frame(y, z_hint):
    """以 y 为方向、z_hint 为滚转参考，构造右手正交基（列为 x, y, z）。"""
    y = Vector(y).normalized()
    z = Vector(z_hint)
    z = z - y * z.dot(y)
    if z.length < 1e-6:
        z = y.orthogonal()
    z.normalize()
    x = y.cross(z)
    return Matrix(((x.x, y.x, z.x),
                   (x.y, y.y, z.y),
                   (x.z, y.z, z.z)))


# T-pose 里掌心朝 -Y（源模型面朝 -Y）；掌手法线指离开掌心的一侧
REST_PALM = Vector((0.0, -1.0, 0.0))


def aim_palm(arm, name, direction, palm):
    """同时指定骨骼朝向和掌心朝向：摆臂怎么甩，掌心都朝 palm 指的方向。

    只用 aim() 的 twist 是绕「目标方向」转固定角度，手臂大幅摆动时掌心会跟着翻，
    所以手部姿态改用两向量定姿（方向 + 掌方法线）。
    """
    pb = arm.pose.bones[name]
    R0 = _frame(rest_dir(pb), REST_PALM)
    R1 = _frame(direction, palm)
    q = R1 @ R0.inverted()
    W = q @ pb.bone.matrix_local.to_3x3()
    cur = current_orient(pb)
    pb.rotation_mode = "QUATERNION"
    pb.rotation_quaternion = (cur.inverted() @ W).to_quaternion()
    bpy.context.view_layer.update()


def shift(arm, name, delta):
    pb = arm.pose.bones[name]
    m = pb.matrix.copy()
    m.translation = m.translation + Vector(delta)
    pb.matrix = m
    bpy.context.view_layer.update()


_LAST_Q = {}


def reset_continuity():
    _LAST_Q.clear()


def quat_continuity(arm):
    """关键帧之间把四元数掰到半球同侧，否则 Bezier 插值会绕远路（手臂甩过头顶）。"""
    flips = 0
    for pb in arm.pose.bones:
        q = pb.rotation_quaternion.copy()
        prev = _LAST_Q.get(pb.name)
        if prev is not None and q.dot(prev) < 0:
            q.negate()
            pb.rotation_quaternion = q
            flips += 1
        _LAST_Q[pb.name] = q.copy()
    if flips:
        bpy.context.view_layer.update()
    return flips


def reset_pose(arm):
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)
    bpy.context.view_layer.update()


def apply_pose(arm, pose):
    """pose: {bone: (dir_vec, twist_deg)}，可含 {"__shift__": {...}} / {"__palm__": {...}}。"""
    reset_pose(arm)
    shifts = pose.get("__shift__", {})
    for name in ORDER:
        if name in pose:
            d, tw = pose[name]
            aim(arm, name, d, tw)
        if name in shifts:
            shift(arm, name, shifts[name])
    # 手部两向量定姿放在最后：掌心朝向不受摆臂方向影响
    for name, palm in pose.get("__palm__", {}).items():
        aim_palm(arm, name, pose[name][0], palm)


def key_pose(arm, frame):
    for pb in arm.pose.bones:
        pb.keyframe_insert("rotation_quaternion", frame=frame)
        pb.keyframe_insert("location", frame=frame)


# ---------------------------------------------------------------- render

def ensure_eevee():
    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        try:
            scene.render.engine = engine
            return engine
        except TypeError:
            continue
    return scene.render.engine


def studio(res=(420, 540), samples=24):
    scene = bpy.context.scene
    if not any(o.type == "LIGHT" for o in bpy.data.objects):
        w = bpy.data.worlds.new("studio_world")
        scene.world = w
        w.use_nodes = True
        bg = next(n for n in w.node_tree.nodes if n.type == "BACKGROUND")
        bg.inputs[0].default_value = (0.48, 0.49, 0.51, 1)
        bg.inputs[1].default_value = 1.15

        def area(name, loc, energy, color, size):
            d = bpy.data.lights.new(name, "AREA")
            d.energy, d.color, d.size = energy, color, size
            o = bpy.data.objects.new(name, d)
            scene.collection.objects.link(o)
            o.location = loc
            o.rotation_euler = (Vector((0, 0, 1.0)) - o.location).to_track_quat("-Z", "Y").to_euler()

        area("key", (-2.4, -3.2, 3.6), 320, (1.0, 0.97, 0.93), 4.0)
        area("fill", (2.8, -2.0, 1.9), 160, (0.94, 0.96, 1.0), 3.5)
        area("rim", (1.4, 2.6, 3.2), 260, (0.90, 0.94, 1.0), 2.5)

    cam = bpy.data.objects.get("camera")
    if cam is None:
        cam_data = bpy.data.cameras.new("camera")
        cam = bpy.data.objects.new("camera", cam_data)
        scene.collection.objects.link(cam)
    scene.camera = cam
    cam.data.type = "ORTHO"
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    return scene, cam


def place_cam(scene, cam, loc, target, scale):
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    cam.data.ortho_scale = scale
