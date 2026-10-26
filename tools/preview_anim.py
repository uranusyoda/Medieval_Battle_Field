# -*- coding: utf-8 -*-
"""已绑骨 .blend 的逐帧预览：渲一组帧用于检查循环与姿态。

  Blender --background --python tools/preview_anim.py -- walk 0 3 6 9 12 15 18 21
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rig_util import MODELS, RENDERS, ensure_eevee, log, place_cam, studio  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
action = argv[0] if argv else "walk"
frames = [int(a) for a in argv[1:]] or [0, 6, 12, 18]

bpy.ops.wm.open_mainfile(filepath=os.path.join(MODELS, "templar_rig.blend"))
scene = bpy.context.scene
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
act = bpy.data.actions.get(action)
if act is None:
    raise SystemExit(f"没有动作 {action}，现有：{[a.name for a in bpy.data.actions]}")

if arm.animation_data is None:
    arm.animation_data_create()
for tr in arm.animation_data.nla_tracks:
    tr.mute = True
arm.animation_data.action = act

scene, cam = studio(res=(360, 460))
ensure_eevee()
place_cam(scene, cam, (3.1, -3.7, 1.85), (0, 0, 1.02), 2.70)

out = os.path.join(RENDERS, "anim")
os.makedirs(out, exist_ok=True)
for f in frames:
    scene.frame_set(f)
    bpy.context.view_layer.update()
    scene.render.filepath = os.path.join(out, f"{action}_{f:02d}.png")
    bpy.ops.render.render(write_still=True)
    log("frame", f)
log("DONE")
