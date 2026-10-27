# -*- coding: utf-8 -*-
"""绑定验收：应用几组姿态、自动贴地、渲染整身与关节特写。

不改文件，只出图。
  Blender --background --threads 4 --python tools/rig_parts_check.py
"""
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import rig_util                      # noqa: E402
import rig_parts as R                 # noqa: E402  （已加 __main__ 保护，不会重跑绑定）

MODELS = os.path.join(ROOT, "assets", "models", "characters", "parts")
RENDERS = os.path.join(ROOT, "assets", "renders", "parts")
SRC = os.path.join(MODELS, f"{R.NAME}.blend")


def log(*a):
    print("[CHK]", *a, flush=True)


def ground(arm, objs):
    """按「脚」的最低点贴地（袍摆垂布会先着地，按它贴地会导致脚悬空）。"""
    feet = [o for o in objs if o["part_en"].startswith("foot.")] or objs
    objs = feet
    dg = bpy.context.evaluated_depsgraph_get()
    lo = 1e9
    for ob in objs:
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        n = len(me.vertices)
        if n:
            import numpy as np
            co = np.empty(n * 3, dtype=np.float64)
            me.vertices.foreach_get("co", co)
            mw = ev.matrix_world
            zs = (co.reshape(n, 3) @ [mw[0][2], mw[1][2], mw[2][2]]) + mw.translation.z
            lo = min(lo, float(zs.min()))
        ev.to_mesh_clear()
    if lo < 1e8:
        arm.location.z -= lo
        bpy.context.view_layer.update()
    return lo


def main():
    bpy.ops.wm.open_mainfile(filepath=SRC)
    arm = bpy.data.objects[R.NAME]
    objs = [o for o in bpy.data.objects if o.type == "MESH" and o.get("part_en")]
    log("armature", arm.name, "bones", len(arm.data.bones), "parts", len(objs))

    scene, cam = rig_util.studio(res=(820, 1040))
    rig_util.ensure_eevee()
    if "floor" not in bpy.data.objects:
        bpy.ops.mesh.primitive_plane_add(size=12.0, location=(0, 0, -0.001))
        floor = bpy.context.active_object
        floor.name = "floor"
        m = bpy.data.materials.new("floor_mat")
        m.use_nodes = True
        bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        bsdf.inputs["Base Color"].default_value = (0.55, 0.56, 0.58, 1)
        bsdf.inputs["Roughness"].default_value = 0.85
        floor.data.materials.append(m)
        log("floor added")

    poses = [("rest", {}), ("arm", R.POSE_ARM), ("knee", R.POSE_KNEE),
             ("walk", R.POSE_WALK), ("crouch", R.POSE_CROUCH)]
    for tag, pose in poses:
        rig_util.reset_pose(arm)
        arm.location = (0, 0, 0)
        if pose:
            rig_util.apply_pose(arm, pose)
        lo = ground(arm, objs)
        log(f"{tag}: lowest z before grounding = {lo:+.3f}")
        for view, loc, tgt, sc in (
            ("front", (2.4, -3.9, 1.15), (0, 0, 0.85), 2.20),
            ("side", (4.4, 0.1, 0.95), (0, 0, 0.85), 2.20),
        ):
            scene.render.resolution_x, scene.render.resolution_y = 820, 1040
            rig_util.place_cam(scene, cam, loc, tgt, sc)
            scene.render.filepath = os.path.join(RENDERS, f"{R.NAME}_v2_{tag}_{view}.png")
            bpy.ops.render.render(write_still=True)
            log("  render", os.path.basename(scene.render.filepath))

    # 关节特写：膝（侧 45°）、肘（后 3/4）
    rig_util.reset_pose(arm)
    arm.location = (0, 0, 0)
    rig_util.apply_pose(arm, R.POSE_ARM)
    ground(arm, objs)
    for tag, loc, tgt, sc in (
        ("knee_L", (1.30, -1.05, 0.62), (0.16, -0.06, 0.42), 0.62),
        ("knee_L_back", (0.85, 1.05, 0.55), (0.16, 0.02, 0.42), 0.62),
        ("elbow_L", (1.15, 0.75, 1.45), (0.52, -0.10, 1.28), 0.60),
        ("elbow_L_top", (0.95, -0.75, 1.95), (0.52, -0.10, 1.30), 0.60),
    ):
        scene.render.resolution_x, scene.render.resolution_y = 800, 800
        rig_util.place_cam(scene, cam, loc, tgt, sc)
        scene.render.filepath = os.path.join(RENDERS, f"{R.NAME}_v2_{tag}.png")
        bpy.ops.render.render(write_still=True)
        log("  render", os.path.basename(scene.render.filepath))


if __name__ == "__main__":
    main()
