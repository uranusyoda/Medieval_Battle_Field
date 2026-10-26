# -*- coding: utf-8 -*-
"""渲四套动作的逐帧图（每套 8 帧），供 tools/make_anim_sheet.py 拼版。

  Blender --background --threads 4 --python tools/anim_sheet.py
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rig_util import MODELS, RENDERS, ensure_eevee, log, place_cam, studio  # noqa: E402

ANIM_DIR = os.path.join(RENDERS, "anim")
FRAMES = {
    "walk": list(range(0, 24, 3)),                       # 0 3 6 … 21
    "run": list(range(0, 16, 2)),                        # 0 2 4 … 14
    "jump": [0, 4, 8, 12, 16, 20, 26, 32],
    "crouch": list(range(0, 32, 4)),                     # 0 4 8 … 28
}


def main():
    bpy.ops.wm.open_mainfile(filepath=os.path.join(MODELS, "templar_rig.blend"))
    scene = bpy.context.scene
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    os.makedirs(ANIM_DIR, exist_ok=True)
    studio_scene, cam = studio(res=(420, 540))
    ensure_eevee()
    place_cam(studio_scene, cam, (3.1, -3.7, 1.85), (0, 0, 1.02), 2.70)

    if arm.animation_data is None:
        arm.animation_data_create()
    for tr in arm.animation_data.nla_tracks:
        tr.mute = True

    for name, frames in FRAMES.items():
        act = bpy.data.actions.get(name)
        if act is None:
            log(f"跳过 {name}：没有该动作")
            continue
        arm.animation_data.action = act
        for f in frames:
            scene.frame_set(f)
            bpy.context.view_layer.update()
            scene.render.filepath = os.path.join(ANIM_DIR, f"{name}_{f:02d}.png")
            bpy.ops.render.render(write_still=True)
        log(f"{name}: {len(frames)} 帧")
    arm.animation_data.action = None
    log("DONE")


main()
