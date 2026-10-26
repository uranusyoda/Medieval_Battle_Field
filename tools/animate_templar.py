# -*- coding: utf-8 -*-
"""给 templar_rig 做四套基础动作：walk / run / jump / crouch，渲预览、导出带蒙皮的 GLB。

用法：
  /Applications/Blender.app/Contents/MacOS/Blender --background --threads 4 \
    --python tools/animate_templar.py
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rig_util import (MODELS, RENDERS, apply_pose, ensure_eevee, key_pose, log,  # noqa: E402
                      place_cam, quat_continuity, reset_continuity, reset_pose, shift,
                      studio)

RIG_BLEND = os.path.join(MODELS, "templar_rig.blend")
OUT_GLB = os.path.join(MODELS, "templar_rig.glb")
ANIM_DIR = os.path.join(RENDERS, "anim")

FPS = 24
FOOT_IDS = []
PALM_FWD = 0.18  # 掌心朝向里带一点前倾，纯内侧会显得手背死平


def _flip_x(val):
    """swap L/R 时方向向量的 x 必须取反，绕该方向的扭转角也要一起反号。"""
    d, tw = val
    return ((-d[0], d[1], d[2]), -tw)


def _flip_axis(vec):
    """掌心方向镜像：x 取反（左右手互换后掌心仍朝身体）。"""
    return (-vec[0], vec[1], vec[2])


def mirror(pose):
    """左右互换：换键名，并把 x 分量取反。"""
    out = {}
    for k, v in pose.items():
        if k == "__palm__":
            out[k] = {_swap_name(n): _flip_axis(a) for n, a in v.items()}
        elif k.startswith("__"):  # __shift__ / __ground__ 等元数据原样带过
            out[k] = v
        else:
            out[_swap_name(k)] = _flip_x(v)
    return out


def _swap_name(name):
    if name.endswith(".L"):
        return name[:-2] + ".R"
    if name.endswith(".R"):
        return name[:-2] + ".L"
    return name


def make(legL, legR, armL, armR, hips_dz=0.0, lean=0.0, cape=(0, 0.12, -1),
         head=(0, 0, 1), hips_fwd=0.0, hips_tilt=0.0, ground=True):
    """legX=(thigh, shin, foot)，armX=(upper, fore)，方向都按左侧写，右侧自动镜像 x。"""
    d = {}
    d["hips"] = ((0, -hips_fwd, 1), hips_tilt)
    d["spine"] = ((0, -lean * 0.45, 1), 0)
    d["chest"] = ((0, -lean * 0.55, 1), 0)
    d["neck"] = ((0, lean * 0.25, 1), 0)
    d["head"] = (head, 0)
    for side, leg, arm in (("L", legL, armL), ("R", legR, armR)):
        sx = 1 if side == "L" else -1
        th, sh, ft = leg
        up, fore = arm
        d[f"thigh.{side}"] = ((sx * th[0], th[1], th[2]), 0)
        d[f"shin.{side}"] = ((sx * sh[0], sh[1], sh[2]), 0)
        d[f"foot.{side}"] = ((sx * ft[0], ft[1], ft[2]), 0)
        d[f"toe.{side}"] = ((sx * ft[0], ft[1], ft[2]), 0)
        d[f"upper_arm.{side}"] = ((sx * up[0], up[1], up[2]), 0)
        d[f"forearm.{side}"] = ((sx * fore[0], fore[1], fore[2]), 0)
        d[f"hand.{side}"] = ((sx * fore[0] * 0.8, fore[1] - 0.1, fore[2]), 0)
        d[f"shoulder.{side}"] = ((sx * 0.9, -0.05, 0.35), 0)
    d["cape.01"] = (cape, 0)
    d["cape.02"] = ((cape[0], cape[1] * 1.4, cape[2]), 0)
    d["sword"] = ((0, 0.02, -1), 0)
    d["__shift__"] = {"hips": (0, 0, hips_dz)}
    # 掌心朝向身体（左右手各朝内侧，略偏前）：摆臂再大也不会翻成摊掌
    d["__palm__"] = {"hand.L": (-1.0, -PALM_FWD, 0.0), "hand.R": (1.0, -PALM_FWD, 0.0)}
    d["__ground__"] = ground
    return d


# ---------------------------------------------------------------- 动作定义

STAND = make(
    ((0.05, -0.02, -1), (0.04, 0.02, -1), (0.02, -1, 0)),
    ((0.05, -0.02, -1), (0.04, 0.02, -1), (0.02, -1, 0)),
    ((0.22, 0.05, -1), (0.18, -0.05, -1)),
    ((0.22, 0.05, -1), (0.18, -0.05, -1)),
)

WALK_CONTACT = make(
    ((0.05, -0.45, -0.95), (0.03, -0.10, -0.99), (0.02, -1.0, -0.15)),
    ((0.05, 0.35, -0.95), (0.03, 0.60, -0.80), (0.02, -0.90, 0.45)),
    ((0.16, 0.46, -0.88), (0.12, 0.34, -0.93)),
    ((0.16, -0.48, -0.86), (0.12, -0.66, -0.74)),
    hips_dz=-0.02, lean=0.06, cape=(0, 0.05, -1),
)
WALK_PASS = make(
    ((0.05, -0.05, -1), (0.03, 0.02, -1), (0.02, -1, 0)),
    ((0.05, -0.12, -0.99), (0.03, 0.55, -0.83), (0.02, -0.75, -0.35)),
    ((0.16, 0.10, -0.98), (0.12, -0.02, -0.99)),
    ((0.16, -0.10, -0.98), (0.12, -0.22, -0.97)),
    hips_dz=0.0, lean=0.03, cape=(0, 0.16, -1),
)

RUN_CONTACT = make(
    ((0.04, -0.62, -0.78), (0.03, -0.30, -0.95), (0.02, -1.0, -0.25)),
    ((0.04, 0.55, -0.83), (0.03, 0.85, -0.50), (0.02, -0.60, 0.60)),
    ((0.14, 0.64, -0.75), (0.10, 0.46, -0.88)),
    ((0.14, -0.66, -0.73), (0.10, -0.86, -0.50)),
    hips_dz=-0.03, lean=0.18, cape=(0, -0.10, -1),
)
RUN_FLIGHT = make(
    ((0.04, -0.20, -0.98), (0.03, 0.40, -0.90), (0.02, -0.80, 0.30)),
    ((0.04, -0.35, -0.93), (0.03, 0.70, -0.70), (0.02, -0.70, 0.20)),
    ((0.14, 0.22, -0.96), (0.10, 0.05, -0.99)),
    ((0.14, -0.22, -0.96), (0.10, -0.42, -0.90)),
    hips_dz=0.06, lean=0.12, cape=(0, -0.22, -1), ground=False,
)

JUMP_CROUCH = make(
    ((0.06, -0.50, -0.85), (0.03, 0.55, -0.83), (0.02, -1, 0.02)),
    ((0.06, -0.50, -0.85), (0.03, 0.55, -0.83), (0.02, -1, 0.02)),
    ((0.22, 0.42, -0.90), (0.18, 0.30, -0.94)),
    ((0.22, 0.42, -0.90), (0.18, 0.30, -0.94)),
    hips_dz=-0.20, lean=0.14, cape=(0, 0.20, -1),
)
JUMP_DIP = make(
    ((0.055, -0.28, -0.96), (0.03, 0.32, -0.95), (0.02, -1, 0.02)),
    ((0.055, -0.28, -0.96), (0.03, 0.32, -0.95), (0.02, -1, 0.02)),
    ((0.22, 0.22, -0.95), (0.18, 0.12, -0.97)),
    ((0.22, 0.22, -0.95), (0.18, 0.12, -0.97)),
    hips_dz=-0.10, lean=0.07, cape=(0, 0.14, -1),
)
JUMP_LAUNCH = make(
    ((0.05, -0.10, -1), (0.03, 0.02, -1), (0.02, -0.55, -0.83)),
    ((0.05, -0.10, -1), (0.03, 0.02, -1), (0.02, -0.55, -0.83)),
    ((0.20, -0.25, 0.93), (0.16, -0.30, 0.94)),
    ((0.20, -0.25, 0.93), (0.16, -0.30, 0.94)),
    hips_dz=0.06, lean=-0.02, cape=(0, 0.30, -1),
)
JUMP_APEX = make(
    ((0.06, -0.60, -0.75), (0.03, 0.80, -0.60), (0.02, -0.70, -0.35)),
    ((0.06, -0.60, -0.75), (0.03, 0.80, -0.60), (0.02, -0.70, -0.35)),
    ((0.48, -0.15, 0.86), (0.42, -0.20, 0.88)),
    ((0.48, -0.15, 0.86), (0.42, -0.20, 0.88)),
    hips_dz=0.38, lean=-0.04, cape=(0, 0.45, -1), ground=False,
)
JUMP_FALL = make(
    ((0.05, -0.25, -0.96), (0.03, -0.05, -1), (0.02, -1, -0.30)),
    ((0.05, -0.25, -0.96), (0.03, -0.05, -1), (0.02, -1, -0.30)),
    ((0.50, 0.05, -0.62), (0.36, -0.10, -0.75)),
    ((0.50, 0.05, -0.62), (0.36, -0.10, -0.75)),
    hips_dz=0.15, lean=0.05, cape=(0, 0.55, -1), ground=False,
)
JUMP_LAND = make(
    ((0.06, -0.55, -0.82), (0.03, 0.60, -0.80), (0.02, -1, 0.02)),
    ((0.06, -0.55, -0.82), (0.03, 0.60, -0.80), (0.02, -1, 0.02)),
    ((0.26, -0.50, -0.70), (0.20, -0.40, -0.80)),
    ((0.26, -0.50, -0.70), (0.20, -0.40, -0.80)),
    hips_dz=-0.26, lean=0.18, cape=(0, -0.15, -1),
)

CROUCH = make(
    ((0.06, -0.72, -0.66), (0.03, 0.72, -0.62), (0.02, -1, 0.02)),
    ((0.06, -0.72, -0.66), (0.03, 0.72, -0.62), (0.02, -1, 0.02)),
    ((0.25, -0.25, -0.95), (0.20, -0.45, -0.85)),
    ((0.25, -0.25, -0.95), (0.20, -0.45, -0.85)),
    hips_dz=-0.30, lean=0.24, cape=(0, 0.28, -1), head=(0, 0.10, 1),
)
CROUCH_BREATHE = make(
    ((0.06, -0.69, -0.69), (0.03, 0.69, -0.65), (0.02, -1, 0.02)),
    ((0.06, -0.69, -0.69), (0.03, 0.69, -0.65), (0.02, -1, 0.02)),
    ((0.26, -0.30, -0.94), (0.22, -0.52, -0.82)),
    ((0.26, -0.30, -0.94), (0.22, -0.52, -0.82)),
    hips_dz=-0.285, lean=0.195, cape=(0, 0.34, -1), head=(0, 0.04, 1),
)

ACTIONS = {
    "walk": {"loop": 24, "keys": [(0, WALK_CONTACT), (6, WALK_PASS),
                                  (12, mirror(WALK_CONTACT)), (18, mirror(WALK_PASS)),
                                  (24, WALK_CONTACT)]},
    "run": {"loop": 16, "keys": [(0, RUN_CONTACT), (4, RUN_FLIGHT),
                                 (8, mirror(RUN_CONTACT)), (12, mirror(RUN_FLIGHT)),
                                 (16, RUN_CONTACT)]},
    "jump": {"loop": 36, "keys": [(0, STAND), (3, JUMP_DIP), (6, JUMP_CROUCH), (8, JUMP_CROUCH), (10, JUMP_LAUNCH),
                                  (16, JUMP_APEX), (22, JUMP_FALL), (26, JUMP_LAND),
                                  (30, JUMP_CROUCH), (33, JUMP_DIP), (36, STAND)]},
    "crouch": {"loop": 32, "keys": [(0, CROUCH), (8, CROUCH_BREATHE), (16, CROUCH),
                                    (24, CROUCH_BREATHE), (32, CROUCH)]},
}

PREVIEW = {"walk": [0, 6, 12, 18], "run": [0, 4, 8, 12],
           "jump": [6, 10, 16, 26], "crouch": [0, 8, 16, 24]}


def all_fcurves(act):
    """兼容 Blender 4.4+ 的 slotted action（Action 不再直接暴露 fcurves）。"""
    if hasattr(act, "fcurves") and not hasattr(act, "layers"):
        yield from act.fcurves
        return
    for layer in getattr(act, "layers", []):
        for strip in getattr(layer, "strips", []):
            for bag in getattr(strip, "channelbags", []):
                yield from bag.fcurves


def purge_old(arm):
    """清掉旧的 action / NLA，否则重跑会生成 walk.001、walk.002…"""
    if arm.animation_data:
        arm.animation_data.action = None
        for tr in list(arm.animation_data.nla_tracks):
            arm.animation_data.nla_tracks.remove(tr)
    for act in list(bpy.data.actions):
        bpy.data.actions.remove(act, do_unlink=True)


def foot_vertices(mesh):
    ids = set()
    for gname in ("foot.L", "foot.R", "toe.L", "toe.R"):
        vg = mesh.vertex_groups.get(gname)
        if vg is None:
            continue
        gi = vg.index
        for v in mesh.data.vertices:
            for g in v.groups:
                if g.group == gi and g.weight > 0.3:
                    ids.add(v.index)
                    break
    return sorted(ids)


def foot_min_z(mesh, ids):
    deps = bpy.context.evaluated_depsgraph_get()
    ev = mesh.evaluated_get(deps)
    me = ev.to_mesh()
    mw = mesh.matrix_world
    z = min((mw @ me.vertices[i].co).z for i in ids)
    ev.to_mesh_clear()
    return z


def build_actions(arm, mesh):
    global FOOT_IDS
    FOOT_IDS = foot_vertices(mesh)
    log(f"foot verts={len(FOOT_IDS)}")
    if arm.animation_data is None:
        arm.animation_data_create()
    purge_old(arm)
    made = {}
    for name, spec in ACTIONS.items():
        act = bpy.data.actions.new(name)
        act.use_fake_user = True
        arm.animation_data.action = act
        reset_continuity()
        for frame, pose in spec["keys"]:
            apply_pose(arm, pose)
            if pose.get("__ground__", True):
                dz = -foot_min_z(mesh, FOOT_IDS)
                if abs(dz) > 1e-4:
                    shift(arm, "hips", (0, 0, dz))
            flips = quat_continuity(arm)
            if flips:
                log(f"  {name}@{frame}: flipped {flips} quats")
            key_pose(arm, frame)
        for fc in all_fcurves(act):
            for kp in fc.keyframe_points:
                kp.interpolation = "BEZIER"
                kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"
        act.frame_range  # touch
        made[name] = act
        log(f"action {name}: {len(list(all_fcurves(act)))} fcurves, "
            f"{int(act.frame_range[0])}-{int(act.frame_range[1])}")
    # 全部压进 NLA，导出时每个 track 一条动画
    for name, act in made.items():
        arm.animation_data.action = act
        track = arm.animation_data.nla_tracks.new()
        track.name = name
        strip = track.strips.new(name, int(act.frame_range[0]), act)
        strip.name = name
        track.mute = False
    arm.animation_data.action = None
    return made


def render_previews(arm, acts):
    os.makedirs(ANIM_DIR, exist_ok=True)
    scene, cam = studio(res=(420, 540))
    ensure_eevee()
    place_cam(scene, cam, (3.1, -3.7, 1.85), (0, 0, 1.02), 2.70)
    for name, frames in PREVIEW.items():
        arm.animation_data.action = acts[name]
        for f in frames:
            scene.frame_set(f)
            bpy.context.view_layer.update()
            scene.render.filepath = os.path.join(ANIM_DIR, f"{name}_{f:02d}.png")
            bpy.ops.render.render(write_still=True)
            log("preview", f"{name}@{f}")
    arm.animation_data.action = None
    scene.frame_set(0)


def export(arm, mesh):
    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    base = dict(filepath=OUT_GLB, export_format="GLB", export_yup=True,
                use_selection=True, export_apply=True, export_animations=True)
    variants = [dict(export_animation_mode="ACTIONS", export_nla_strips=True),
                dict(export_animation_mode="ACTIONS"),
                dict()]
    for extra in variants:
        try:
            bpy.ops.export_scene.gltf(**base, **extra)
            log(f"exported {OUT_GLB} with {list(extra)} "
                f"({os.path.getsize(OUT_GLB) // 1024} KB)")
            return
        except TypeError as e:
            log("export kwargs rejected:", e)
    raise SystemExit("GLTF 导出失败")


def main():
    bpy.ops.wm.open_mainfile(filepath=RIG_BLEND)
    scene = bpy.context.scene
    scene.render.fps = FPS
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
    bpy.context.view_layer.objects.active = arm
    log(f"rig={arm.name} mesh={mesh.name} bones={len(arm.data.bones)} "
        f"verts={len(mesh.data.vertices)}")

    acts = build_actions(arm, mesh)
    render_previews(arm, acts)
    export(arm, mesh)
    reset_pose(arm)
    scene.frame_set(0)
    bpy.ops.wm.save_as_mainfile(filepath=RIG_BLEND)
    log("DONE")


main()
