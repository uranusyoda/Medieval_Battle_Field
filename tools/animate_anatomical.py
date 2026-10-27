"""Author eight baked animations on the 60-bone anatomical rig.

blender --background --threads 4 --python tools/animate_anatomical.py
Saves a full editable blend, geometry-preserving animated GLB, and a web LOD.
"""
from pathlib import Path
import sys
import json
import math
import hashlib

import bpy
import numpy as np
from mathutils import Vector, Quaternion, Matrix

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import rig_util
from patch_anatomical_animations import patch

MODELS = ROOT / 'assets/models/characters/parts'
SOURCE = MODELS / 'templar_tpose_unarmored_parts_rig_anatomical.blend'
BASE = MODELS / 'templar_tpose_unarmored_parts_rig_anatomical.glb'
NAME = 'templar_anatomical_animated'
RENDERS = ROOT / 'assets/renders/parts/animated'
FPS = 60
TAU = math.tau
FINGERS = ('index', 'middle', 'ring', 'pinky')
SPECS = [
    dict(id='idle', label='呼吸待机', frames=72, loop=True, focus='body',
         description='挺拔松弛的骑士站姿：舒胸沉肩、缓慢呼吸，双臂自然悬垂。'),
    dict(id='walk', label='行走', frames=32, loop=True, focus='body',
         description='原地步态：脚掌交替支撑，双臂反向摆动。'),
    dict(id='run', label='奔跑', frames=20, loop=True, focus='body',
         description='原地跑步：屈肘摆臂、提膝与短暂腾空。'),
    dict(id='jump', label='跳跃', frames=48, loop=False, focus='body',
         description='弹性起跳：快速蹬地、屈膝腾空，前脚掌落地后缓冲回弹。'),
    dict(id='crouch', label='忍者低姿', frames=72, loop=True, focus='body',
         description='前后错步压低重心，前手探出、后手侧收，警觉潜行后站起。'),
    dict(id='grip', label='握拳与松开', frames=72, loop=True, focus='hand',
         description='四指逐节屈曲，拇指对掌，随后放松张开。'),
    dict(id='finger_wave', label='逐指弯曲', frames=120, loop=True, focus='hand',
         description='食指、中指、无名指、小指与拇指依次独立活动。'),
    dict(id='wrist', label='转腕与伸屈', frames=72, loop=True, focus='hand',
         description='手腕屈伸与侧偏，检查掌根和袖口过渡。'),
]
for _spec in SPECS:
    _spec['frames'] = round(_spec['frames']*FPS/24)
GAITS = {}


def log(*args):
    print('[ANIMATE60]', *args, flush=True)


def ease(x):
    x = max(0., min(1., x))
    return x*x*(3-2*x)


def frame(y, dorsal):
    y = Vector(y).normalized()
    z = Vector(dorsal)
    z = (z-y*z.dot(y)).normalized()
    x = y.cross(z)
    return Matrix(((x.x, y.x, z.x), (x.y, y.y, z.y), (x.z, y.z, z.z)))


class Pose:
    """Solve FK in memory; evaluate the dense skin once per frame, not per bone."""
    def __init__(self, arm):
        self.arm = arm
        self.rest = {b.name: b.matrix_local.to_3x3() for b in arm.data.bones}
        self.rh = {b.name: b.head_local.copy() for b in arm.data.bones}
        self.head, self.rot = {}, {}
        self.local_q, self.local_p = {}, {}

    def parent_frame(self, name):
        bone = self.arm.data.bones[name]
        if bone.parent:
            pn = bone.parent.name
            if pn not in self.rot:
                self.local(pn)
            offset = self.rot[pn] @ self.rest[pn].inverted()
            head = self.head[pn]+offset @ (self.rh[name]-self.rh[pn])
            rot = offset @ self.rest[name]
        else:
            head, rot = self.rh[name].copy(), self.rest[name].copy()
        return head, rot

    def local(self, name, q=None, world_shift=None):
        h, base_rot = self.parent_frame(name)
        q = q or Quaternion()
        shift = Vector(world_shift or (0, 0, 0))
        self.head[name], self.rot[name] = h+shift, base_rot @ q.to_matrix()
        self.local_q[name], self.local_p[name] = q, base_rot.inverted() @ shift

    def world(self, name, rotation):
        h, base_rot = self.parent_frame(name)
        self.head[name], self.rot[name] = h, rotation
        self.local_q[name] = (base_rot.inverted() @ rotation).to_quaternion()
        self.local_p[name] = Vector((0, 0, 0))

    def aim(self, name, direction, dorsal=None):
        direction = Vector(direction).normalized()
        if dorsal is None:
            b = self.arm.data.bones[name]
            rotation = (b.tail_local-b.head_local).normalized().rotation_difference(direction).to_matrix() @ self.rest[name]
        else:
            rotation = frame(direction, dorsal)
        self.world(name, rotation)

    def finish(self):
        for bone in self.arm.data.bones:
            if bone.name not in self.rot:
                self.local(bone.name)
        for name, q in self.local_q.items():
            pb = self.arm.pose.bones[name]
            pb.rotation_mode = 'QUATERNION'
            pb.rotation_quaternion = q
            pb.location = self.local_p[name]
            pb.scale = (1, 1, 1)


def ik_leg(pose, side, ankle, pitch=0):
    thigh, shin, foot, toe = [f'{b}.{side}' for b in ('thigh', 'shin', 'foot', 'toe')]
    a, _ = pose.parent_frame(thigh)
    c = Vector(ankle)
    l1, l2 = pose.arm.data.bones[thigh].length, pose.arm.data.bones[shin].length
    delta = c-a
    d = min(max(delta.length, abs(l1-l2)+.00001), l1+l2-.00001)
    u = delta.normalized()
    c = a+u*d
    bend = Vector((0, -1, 0))
    bend = (bend-u*bend.dot(u)).normalized()
    along = (l1*l1-l2*l2+d*d)/(2*d)
    height = math.sqrt(max(0, l1*l1-along*along))
    b = a+u*along+bend*height
    pose.aim(thigh, b-a)
    pose.aim(shin, c-b)
    direction = Vector((0, -.169, -.060))
    direction = Quaternion((1, 0, 0), math.radians(pitch)) @ direction
    pose.aim(foot, direction)
    pose.aim(toe, Quaternion((1, 0, 0), math.radians(pitch)) @ Vector((0, -.10, -.01)))


def fingers(pose, side, amount=.12, selected=None, spread=0, closed=False, relaxed=False):
    sign = 1 if side == 'L' else -1
    for finger in FINGERS:
        a = amount if selected is None or selected == finger else 0
        if relaxed:
            a *= {'index':.86,'middle':1.,'ring':1.08,'pinky':1.16}[finger]
        # A little ulnar palm cupping accompanies a grasp, without introducing
        # impossible finger-axis twist. MCP retains its natural spreading DOF.
        cup = {'index': 0, 'middle': 0, 'ring': 3, 'pinky': 5}[finger]*a
        pose.local(f'{finger}.metacarpal.{side}', Quaternion((1, 0, 0), -math.radians(cup)))
        for j, angle in enumerate((65, 85, 45) if closed else (48, 65, 38), 1):
            # Demonstrate independent IP flexion without dragging the shared
            # finger web into a deep isolated MCP fold.
            joint_angle = angle*(.25 if selected is not None and j == 1 else 1)
            q = Quaternion((1, 0, 0), -math.radians(joint_angle*a))
            if j == 1 and spread:
                fsign = {'index': -1, 'middle': -.15, 'ring': .4, 'pinky': 1}[finger]
                q = q @ Quaternion((0, 0, 1), math.radians(sign*spread*fsign))
            pose.local(f'{finger}.{j:02d}.{side}', q)
    a = amount if selected is None or selected == 'thumb' else 0
    if relaxed:
        a *= .75
    pose.local(f'thumb.metacarpal.{side}',
               Quaternion((1, 0, 0), -math.radians(18*a)) @
               Quaternion((0, 0, 1), sign*math.radians(42*a)))
    for j, angle in enumerate((25, 30), 1):
        pose.local(f'thumb.{j:02d}.{side}', Quaternion((1, 0, 0), -math.radians(angle*a)))


def body_basis(up, left):
    up = Vector(up).normalized()
    left = Vector(left)
    left = (left-up*left.dot(up)).normalized()
    back = up.cross(left)
    return Matrix(((left.x,back.x,up.x),(left.y,back.y,up.y),(left.z,back.z,up.z)))


def knight_gait_arms(gait, t, prefix, sign, running=False):
    """Open axillary clearance for this broad tunic, with independent arm lag."""
    phase = TAU*t+(0 if sign == 1 else math.pi)
    def upper_direction(capture):
        v = Vector(capture[prefix+'humerus']-capture[prefix+'clavicle']).normalized()
        x = sign*math.sin(math.radians((26. if running else 24.)+1.2*math.sin(phase)))
        y = v.y if running else (v.y-.08)*1.55+.02
        y = max(-.78,min(.78,y))
        return Vector((x,y,-math.sqrt(max(.08,1-x*x-y*y)))).normalized()
    now, delayed = gait.sample(t), gait.sample(t-(.025 if running else .045))
    upper = upper_direction(now)
    lagged_upper = upper_direction(delayed)
    raw_upper = Vector(delayed[prefix+'humerus']-delayed[prefix+'clavicle']).normalized()
    raw_forearm = Vector(delayed[prefix+'radius']-delayed[prefix+'humerus']).normalized()
    captured_bend = math.degrees(math.acos(max(-1.,min(1.,raw_upper.dot(raw_forearm)))))
    bend = math.radians(max(65.,min(105.,captured_bend)) if running else 14+.30*(captured_bend-28))
    forward = Vector((-sign*.17 if running else -sign*.055,-1,0))
    forward = (forward-lagged_upper*forward.dot(lagged_upper)).normalized()
    forearm = lagged_upper*math.cos(bend)+forward*math.sin(bend)
    clavicle = now[prefix+'clavicle']-now['thorax']
    shoulder = Vector((sign*abs(clavicle[0]), .018+.20*clavicle[1],
                       .014+.12*(clavicle[2]-.055)))
    return shoulder, upper, forearm


def solve_relaxed_idle(arm, t):
    """Breathing chest, settled collarbones and soft asymmetric hanging arms."""
    phase = TAU*t
    breath = math.sin(phase)
    p = Pose(arm)
    p.local('root')
    p.local('hips', Quaternion((0,0,1),math.radians(.6)*math.sin(phase-.5)),
            (.006*math.sin(phase-.4), .002*math.sin(phase+.4), -.012+.003*breath))
    p.aim('spine', (.005*math.sin(phase-.4), .008+.004*breath, 1))
    p.aim('chest', (.004*math.sin(phase-.2), .038+.010*breath, 1))
    p.aim('neck', (.002*math.sin(phase+.2), .012+.003*breath, 1))
    p.aim('head', (.002*math.sin(phase+.4), .004, 1))
    for side, sign in [('L',1),('R',-1)]:
        lag = phase-.45+(0 if side=='L' else .7)
        p.aim(f'shoulder.{side}', (sign*.20,.022,.014+.002*math.sin(phase-.25)))
        x = sign*math.sin(math.radians(21.5+.8*math.sin(lag)))
        y = .02+.023*math.sin(lag)
        upper = Vector((x,y,-math.sqrt(1-x*x-y*y)))
        forearm = Vector((sign*(.31+.008*math.sin(lag-.2)),
                          -.13+.032*math.sin(lag-.25),-1)).normalized()
        p.aim(f'upper_arm.{side}',upper)
        p.aim(f'forearm.{side}',forearm)
        p.aim(f'hand.{side}',forearm,(sign,.08,0))
        p.world(f'hand.{side}',p.rot[f'hand.{side}'] @
                Quaternion((1,0,0),-math.radians(4+1.8*math.sin(lag-.5))).to_matrix())
        fingers(p,side,.34+.012*math.sin(lag-.45),spread=-4,relaxed=True)
        ik_leg(p,side,(sign*.18,.079+(0 if side=='L' else .025),.09))
    p.finish()
    return 0.


def solve_captured_gait(arm, name, normalized):
    gait = GAITS[name]
    t = normalized % 1
    sample = gait.sample(t)
    p = Pose(arm)
    p.local('root')
    scale = (arm.data.bones['thigh.L'].length+arm.data.bones['shin.L'].length)/gait.source_leg_length
    shift = gait.pelvis(t)*scale
    # Pelvis height is grounded from the resulting boot soles later. Captured
    # lateral transfer and small fore/aft sway remain present.
    shift[2] -= .025
    hips_basis = body_basis(sample['lowerback']-(sample['lhipjoint']+sample['rhipjoint'])/2,
                            sample['lhipjoint']-sample['rhipjoint'])
    _, base_rotation = p.parent_frame('hips')
    p.local('hips', (base_rotation.inverted()@hips_basis@p.rest['hips']).to_quaternion(), tuple(shift))
    shoulder_axis = sample['lclavicle']-sample['rclavicle']
    spine_up = sample['thorax']-sample['lowerback']
    if name == 'walk':
        # Upright sternum and steadier shoulders read as confident weight,
        # rather than the forward, slightly guarded pose of the source take.
        spine_up[0] *= .65
        spine_up[1] = spine_up[1]*.35+.010
    else:
        spine_up[1] *= .80
    spine_basis = body_basis(spine_up, shoulder_axis)
    # Keep actual pelvis/shoulder counter-rotation and torso side bend.
    for bone in ('spine','chest'):
        p.world(bone, spine_basis@p.rest[bone])
    neck_up = sample['head']-sample['thorax']
    if name == 'walk':
        neck_up[0] *= .7
        neck_up[1] = neck_up[1]*.45+.004
    neck_basis = body_basis(neck_up, shoulder_axis)
    p.world('neck', neck_basis@p.rest['neck'])
    p.world('head', neck_basis@p.rest['head'])
    for side, prefix, sign in [('L','l',1),('R','r',-1)]:
        hip,knee,ankle = [sample[prefix+n] for n in ('hipjoint','femur','tibia')]
        p.aim(f'thigh.{side}', knee-hip)
        p.aim(f'shin.{side}', ankle-knee)
        foot_direction = sample[prefix+'foot']-ankle
        # The source performer is mildly toe-in. Shoes point almost forward;
        # keep the captured heel lift rather than a permanent wide toe-out.
        foot_direction[0] = sign*.008
        p.aim(f'foot.{side}', foot_direction)
        toe_direction = sample[prefix+'toes']-sample[prefix+'foot']
        toe_direction[0] = sign*.004
        p.aim(f'toe.{side}', toe_direction)
        # Clavicle endpoints include natural shoulder movement; limb lengths
        # remain those of this character, while captured directions coordinate
        # the elbows with the opposite leg instead of independent sine waves.
        clavicle_direction = sample[prefix+'clavicle']-sample['thorax']
        upper = sample[prefix+'humerus']-sample[prefix+'clavicle']
        forearm = sample[prefix+'radius']-sample[prefix+'humerus']
        clavicle_direction, upper, forearm = knight_gait_arms(gait,t,prefix,sign,name=='run')
        p.aim(f'shoulder.{side}', clavicle_direction)
        p.aim(f'upper_arm.{side}', upper)
        p.aim(f'forearm.{side}', forearm)
        p.aim(f'hand.{side}', forearm, (sign,.08,0))
        if name == 'walk':
            wrist_flex = 4+2.2*math.sin(TAU*t+(0 if side=='L' else math.pi)-.8)
            hand_rotation = p.rot[f'hand.{side}']@Quaternion((1,0,0),-math.radians(wrist_flex)).to_matrix()
            p.world(f'hand.{side}',hand_rotation)
            fingers(p,side,.38,spread=-5.,relaxed=True)
        else:
            wrist_flex = 3+1.5*math.sin(TAU*t+(0 if side=='L' else math.pi)-.7)
            p.world(f'hand.{side}',p.rot[f'hand.{side}'] @
                    Quaternion((1,0,0),-math.radians(wrist_flex)).to_matrix())
            fingers(p,side,.97,closed=True)
    p.finish()
    return gait.flight(t)*scale


def solve(arm, spec, normalized):
    # Use exactly the same floating-point phase at loop endpoints.
    t = 0. if normalized == 1 and spec['loop'] else normalized
    phase = TAU*t
    name = spec['id']
    if name == 'idle':
        return solve_relaxed_idle(arm,t)
    if name == 'jump':
        from athletic_jump import solve_athletic_jump
        return solve_athletic_jump(arm,t*spec['frames']/FPS,Pose,ik_leg,fingers)
    if name == 'crouch':
        from ninja_crouch import solve_ninja_crouch
        return solve_ninja_crouch(arm,t,Pose,ik_leg,fingers)
    if name in ('walk','run'):
        if name not in GAITS:
            from mocap_gait import Gait
            GAITS[name] = Gait(name=='run')
        return solve_captured_gait(arm, name, t)
    hand_demo = spec['focus'] == 'hand'
    p = Pose(arm)
    p.local('root')
    hip_z, hip_y, hip_x, lean, yaw = -.012, 0., 0., .015, 0.
    ankle_targets = {s: [sign*.228, .079, .09, 0.] for s, sign in [('L', 1), ('R', -1)]}
    upper, fore = {}, {}
    p.local('hips', Quaternion((0, 1, 0), yaw), (hip_x, hip_y, hip_z))
    p.aim('spine', (0, -lean*.45, 1))
    p.aim('chest', (0, -lean, 1))
    p.aim('neck', (0, -.005, 1))
    p.aim('head', (0, .012, 1))
    for s, sign in [('L', 1), ('R', -1)]:
        p.local(f'shoulder.{s}')
        if hand_demo:
            p.local(f'upper_arm.{s}')
            p.local(f'forearm.{s}')
            if name == 'wrist':
                p.local(f'hand.{s}', Quaternion((1, 0, 0), math.radians(28)*math.sin(phase)) @
                        Quaternion((0, 0, 1), math.radians(15*sign)*math.sin(2*phase)))
            else:
                p.local(f'hand.{s}')
            amount, selected = 0., None
            if name == 'grip':
                amount = ease((1-math.cos(phase))*.5)
            elif name == 'finger_wave':
                stage = min(4, int(t*5))
                selected = ('index', 'middle', 'ring', 'pinky', 'thumb')[stage]
                # Isolated finger flexion stays moderate; a full isolated ring
                # curl excessively compresses this source mesh's shared web.
                amount = .65*math.sin(math.pi*((t*5) % 1))**2
            else:
                amount = .13
            fingers(p, s, amount, selected)
        else:
            up = upper.get(s, (sign*.13, .035, -1))
            fo = fore.get(s, (sign*.10, -.085, -1))
            p.aim(f'upper_arm.{s}', up)
            p.aim(f'forearm.{s}', fo)
            # Original palm points -Z. Keep palms towards the thighs, with
            # each dorsal normal facing outwards, during all arm swings.
            p.aim(f'hand.{s}', fo, (sign, .10, 0))
            fingers(p, s, .30 if name == 'run' else .14)
        ik_leg(p, s, ankle_targets[s][:3], ankle_targets[s][3])
    p.finish()
    desired_floor = max(0, min(v[2]-.09 for v in ankle_targets.values()))
    return desired_floor


def floor_height(feet):
    deps = bpy.context.evaluated_depsgraph_get()
    height = float('inf')
    for ob in feet:
        ev = ob.evaluated_get(deps)
        v = np.empty(len(ev.data.vertices)*3)
        ev.data.vertices.foreach_get('co', v)
        m = np.asarray(ev.matrix_world)
        z = v.reshape(-1, 3) @ m[2, :3]+m[2, 3]
        height = min(height, float(z.min()))
    return height


def curves(action):
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                yield from bag.fcurves


def build_actions(arm, meshes):
    if arm.animation_data:
        arm.animation_data_clear()
    for old in list(bpy.data.actions):
        bpy.data.actions.remove(old)
    arm.animation_data_create()
    feet = [m for m in meshes if m.name.startswith('body_foot.')]
    scene = bpy.context.scene
    report, made = {}, {}
    for spec in SPECS:
        action = bpy.data.actions.new(spec['id'])
        action.use_fake_user = True
        action['label'] = spec['label']
        action['loop'] = spec['loop']
        action['description'] = spec['description']
        arm.animation_data.action = action
        rig_util.reset_continuity()
        floor_data = []
        jump_state = {}
        for f in range(spec['frames']+1):
            scene.frame_set(f)
            desired_floor = solve(arm, spec, f/spec['frames'])
            bpy.context.view_layer.update()
            floor = floor_height(feet)
            root = arm.pose.bones['root']
            correction = desired_floor-floor
            if spec['id'] == 'jump':
                from athletic_jump import jump_grounding
                correction = jump_grounding(f/FPS,floor,jump_state)
            root.location = arm.data.bones['root'].matrix_local.to_3x3().inverted() @ Vector((0, 0, correction))
            rig_util.quat_continuity(arm)
            rig_util.key_pose(arm, f)
            floor_data.append(dict(frame=f, target=desired_floor, correction=correction))
        if spec['id'] in GAITS:
            # Per-frame minimum-of-two-soles grounding can introduce a cusp
            # when support changes. Fit a periodic correction so the pelvis
            # stays smooth through contact exchange as well as the loop seam.
            from mocap_gait import design
            times = np.linspace(0,1,spec['frames']+1)
            raw = np.array([item['correction'] for item in floor_data])
            x = design(times, min(8,spec['frames']//3))
            smooth = x@np.linalg.lstsq(x,raw,rcond=None)[0]
            bias = max(0.,float(np.max(raw-smooth)))+.0004
            smooth += bias
            inverse_root = arm.data.bones['root'].matrix_local.to_3x3().inverted()
            for f,value in enumerate(smooth):
                root = arm.pose.bones['root']
                root.location = inverse_root@Vector((0,0,float(value)))
                root.keyframe_insert('location',frame=f)
                floor_data[f]['raw_correction'] = floor_data[f]['correction']
                floor_data[f]['correction'] = float(value)
                floor_data[f]['periodic_smoothing_bias_m'] = bias
        for fc in curves(action):
            for key in fc.keyframe_points:
                key.interpolation = 'LINEAR'
            if (spec['id'] in GAITS or spec['id']=='idle') and len(fc.keyframe_points)>2:
                keys = list(fc.keyframe_points)
                coordinates = np.array([tuple(k.co) for k in keys])
                ff,values = coordinates[:,0],coordinates[:,1]
                tangents = np.empty(len(keys))
                tangents[1:-1] = (values[2:]-values[:-2])/(ff[2:]-ff[:-2])
                tangents[0] = (values[1]-values[-2])/(ff[1]-(ff[-2]-(ff[-1]-ff[0])))
                tangents[-1] = tangents[0]
                for j,key in enumerate(keys):
                    before = ff[j]-ff[j-1] if j else ff[-1]-ff[-2]
                    after = ff[j+1]-ff[j] if j<len(keys)-1 else ff[1]-ff[0]
                    key.interpolation = 'BEZIER'
                    key.handle_left_type = key.handle_right_type = 'FREE'
                    key.handle_left = (ff[j]-before/3,values[j]-tangents[j]*before/3)
                    key.handle_right = (ff[j]+after/3,values[j]+tangents[j]*after/3)
        made[spec['id']] = action
        report[spec['id']] = floor_data
        log('authored', spec['id'], spec['frames']+1, 'frames')
    arm.animation_data.action = None
    for spec in SPECS:
        act = made[spec['id']]
        arm.animation_data.action = act
        track = arm.animation_data.nla_tracks.new()
        track.name = spec['id']
        strip = track.strips.new(spec['id'], 0, act)
        strip.name = spec['id']
        track.mute = True
    arm.animation_data.action = made['idle']
    arm.animation_data.action_slot = list(made['idle'].slots)[0]
    scene.frame_start, scene.frame_end = 0, SPECS[0]['frames']
    scene.frame_set(0)
    return report


def export_glb(arm, meshes, path):
    bpy.ops.object.select_all(action='DESELECT')
    for ob in [arm]+meshes:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLB', use_selection=True,
        export_apply=True, export_yup=True, export_skins=True,
        export_animations=True, export_animation_mode='ACTIONS', export_nla_strips=True,
        export_frame_range=False, export_force_sampling=True,
        export_frame_step=1, export_rest_position_armature=True,
        export_optimize_animation_size=True, export_materials='EXPORT',
        export_all_influences=False, export_texcoords=True, export_normals=True)


def web_lod(arm, meshes):
    arm.animation_data.action = None
    rig_util.reset_pose(arm)
    arm.data.pose_position = 'REST'
    hand_tris = sum(len(o.data.polygons) for o in meshes if o.name.startswith('body_hand.'))
    other_tris = sum(len(o.data.polygons) for o in meshes if not o.name.startswith('body_hand.'))
    for ob in meshes:
        tri = len(ob.data.polygons)
        ratio = min(1., 22000/hand_tris) if ob.name.startswith('body_hand.') else min(1., 126000/other_tris)
        bpy.context.view_layer.objects.active = ob
        mod = ob.modifiers.new('Web LOD', 'DECIMATE')
        mod.ratio = ratio
        mod.use_collapse_triangulate = True
        bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
        bpy.ops.object.modifier_apply(modifier=mod.name)
        log('web LOD', ob.name, tri, '->', len(ob.data.polygons))
    arm.data.pose_position = 'POSE'
    for image in bpy.data.images:
        if image.size[0] > 2048 or image.size[1] > 2048:
            image.scale(2048, 2048)
    return sum(len(o.data.polygons) for o in meshes)


def main():
    RENDERS.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.name.startswith('body_')]
    assert len(meshes) == 16 and len(arm.data.bones) == 60
    scene = bpy.context.scene
    scene.render.fps = FPS
    from mocap_gait import Gait
    for spec in SPECS:
        if spec['id'] in ('walk','run'):
            capture = Gait(spec['id']=='run')
            GAITS[spec['id']] = capture
            spec['frames'] = round(capture.duration*FPS)
            spec['description'] = ('从容骑士步态：胸肩挺拔，双臂留出自然空间，松弛摆动。' if spec['id']=='walk' else
                                   '力量奔跑：沉肩开臂、轻松握拳，摆臂与提膝协调。')
            log('mocap', spec['id'], capture.info)
    grounding = build_actions(arm, meshes)
    full_blend = MODELS/(NAME+'.blend')
    bpy.ops.wm.save_as_mainfile(filepath=str(full_blend), compress=True)
    raw = Path('/tmp/templar_anatomical_animated_export.glb')
    export_glb(arm, meshes, raw)
    from smooth_gltf_gait import smooth
    smooth(raw)
    preserved = patch(BASE, raw, MODELS/(NAME+'.glb'))
    preview_triangles = web_lod(arm, meshes)
    export_glb(arm, meshes, MODELS/(NAME+'_preview.glb'))
    smooth(MODELS/(NAME+'_preview.glb'))
    preview_version = hashlib.sha256((MODELS/(NAME+'_preview.glb')).read_bytes()).hexdigest()[:16]
    manifest = dict(model=NAME+'.glb', preview=NAME+'_preview.glb', source=NAME+'.blend', assetVersion=preview_version,
                    bones=60, meshes=16, fps=FPS, preview_triangles=preview_triangles,
                    clips=[dict(s, duration=s['frames']/FPS) for s in SPECS])
    manifest['motionSources'] = {name:gait.info for name,gait in GAITS.items()}
    (MODELS/'templar_anatomical_animations.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (RENDERS/'creation_validation.json').write_text(json.dumps(dict(preservation=preserved, grounding=grounding,
        source_blend_sha256=source_hash, preview_triangles=preview_triangles), indent=2), encoding='utf-8')
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == source_hash
    log('DONE', NAME, '8 clips', preview_triangles, 'preview triangles')


if __name__ == '__main__':
    main()
