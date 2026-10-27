"""Read-only walk/run continuity and fist-pose diagnostics on authored actions.

blender --background --threads 4 --factory-startup --python tools/check_gait_continuity.py
Use -- --baseline to preserve the old gait measurement before regenerating it.
No model or Blender source is written; only a JSON report is produced.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys

import bpy
import numpy as np
from mathutils import Quaternion

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / 'assets/models/characters/parts'
OUT = ROOT / 'assets/renders/parts/animated'
DEFAULT_BLEND = MODELS / 'templar_anatomical_animated.blend'
TRACK = ['root', 'hips', 'spine', 'chest', 'head'] + [
    f'{name}.{side}' for side in ('L', 'R')
    for name in ('upper_arm', 'forearm', 'hand', 'thigh', 'shin', 'foot', 'toe')]


def args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blend', type=Path, default=DEFAULT_BLEND)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--samples-per-frame', type=int, default=4)
    parser.add_argument('--strict', action='store_true', help='Fail on reported diagnostic warnings')
    return parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])


def norms(a):
    return np.linalg.norm(a, axis=-1)


def stats(a):
    a = np.asarray(a, dtype=float)
    return {'min': float(a.min()), 'median': float(np.median(a)),
            'p95': float(np.quantile(a, .95)), 'max': float(a.max())}


def rotation_velocities(quaternions, dt):
    result = []
    for a, b in zip(quaternions[:-1], quaternions[1:]):
        qa, qb = Quaternion(a), Quaternion(b)
        if qa.dot(qb) < 0:
            qb.negate()
        relative = qa.conjugated() @ qb
        relative.normalize()
        if relative.w < 0:
            relative.negate()
        axis, angle = relative.to_axis_angle()
        result.append(np.asarray(axis)*angle/dt)
    return np.asarray(result)


def joint_metrics(positions, rotations, dt, authored_dt):
    linear = np.diff(positions, axis=0)/dt
    angular = rotation_velocities(rotations, dt)
    # The seam joins the final interval to the first interval, so matching
    # endpoint poses alone cannot make this diagnostic pass.
    linear_acc = np.diff(np.vstack([linear, linear[:1]]), axis=0)/dt
    angular_acc = np.diff(np.vstack([angular, angular[:1]]), axis=0)/dt
    velocity_jump = float(np.linalg.norm(linear[0]-linear[-1]))
    omega_jump = float(np.linalg.norm(angular[0]-angular[-1]))
    angle = Quaternion(rotations[0]).rotation_difference(Quaternion(rotations[-1])).angle
    angle = min(angle, 2*math.pi-angle)
    p95_v = float(np.quantile(norms(linear), .95))
    p95_w = float(np.quantile(norms(angular), .95))
    warnings = []
    if velocity_jump > max(.06, .15*p95_v):
        warnings.append('loop_linear_velocity_changes_abruptly')
    if omega_jump > max(.5, .25*p95_w):
        warnings.append('loop_angular_velocity_changes_abruptly')
    if float(norms(linear).max()) > 8:
        warnings.append('joint_speed_above_8m_s')
    if float(norms(angular).max()) > 24:
        warnings.append('joint_angular_speed_above_24rad_s')
    return {
        'position_endpoint_error_m': float(np.linalg.norm(positions[0]-positions[-1])),
        'rotation_endpoint_error_deg': math.degrees(angle),
        'speed_m_s': stats(norms(linear)),
        'acceleration_m_s2': stats(norms(linear_acc)),
        'angular_speed_rad_s': stats(norms(angular)),
        'angular_acceleration_rad_s2': stats(norms(angular_acc)),
        'max_approx_authored_frame_rotation_deg': math.degrees(float(norms(angular).max())*authored_dt),
        'loop_velocity_before_m_s': linear[-1].tolist(),
        'loop_velocity_after_m_s': linear[0].tolist(),
        'loop_velocity_jump_m_s': velocity_jump,
        'loop_angular_velocity_before_rad_s': angular[-1].tolist(),
        'loop_angular_velocity_after_rad_s': angular[0].tolist(),
        'loop_angular_velocity_jump_rad_s': omega_jump,
        'diagnostic_warnings': warnings,
    }


def main():
    options = args()
    assert 1 <= options.samples_per_frame <= 16
    source_hash = hashlib.sha256(options.blend.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(options.blend))
    scene = bpy.context.scene
    arm = next(o for o in scene.objects if o.type == 'ARMATURE')
    # Only skeleton matrices are sampled. Skipping mesh deformation makes
    # subframe continuity checks inexpensive even for the 1.46M-triangle asset.
    for obj in scene.objects:
        if obj.type == 'MESH':
            obj.hide_viewport = True
    fps = scene.render.fps/scene.render.fps_base
    report = {'blend': options.blend.name, 'source_sha256': source_hash,
              'fps': fps, 'samples_per_authored_frame': options.samples_per_frame,
              'units': {'position': 'm', 'linear_velocity': 'm/s', 'angular_velocity': 'rad/s'},
              'clips': {}, 'warnings': [],
              'notes': ['Thresholds flag abrupt transitions and implausible spikes; they do not judge visual acting quality.',
                        'Subframe differences estimate velocity on the exported linear animation segments.']}
    for track in arm.animation_data.nla_tracks:
        track.mute = True
    for clip in ('walk', 'run'):
        action = bpy.data.actions[clip]
        arm.animation_data.action = action
        if action.slots:
            arm.animation_data.action_slot = action.slots[0]
        start, end = map(float, action.frame_range)
        assert end > start
        count = round((end-start)*options.samples_per_frame)+1
        frames = np.linspace(start, end, count)
        dt = (end-start)/(count-1)/fps
        positions = {n: [] for n in TRACK}
        rotations = {n: [] for n in TRACK}
        flexion = {f'{f}.{j:02d}.{s}': [] for s in ('L', 'R')
                   for f in ('index', 'middle', 'ring', 'pinky') for j in (1, 2, 3)}
        for f in frames:
            integer = math.floor(f)
            scene.frame_set(integer, subframe=f-integer)
            bpy.context.view_layer.update()
            for name in TRACK:
                bone = arm.pose.bones[name]
                matrix = arm.matrix_world @ bone.matrix
                positions[name].append(tuple(matrix.translation))
                rotations[name].append(tuple(matrix.to_quaternion()))
            for name in flexion:
                bone = arm.pose.bones[name]
                q = bone.rotation_quaternion if bone.rotation_mode == 'QUATERNION' else bone.rotation_euler.to_quaternion()
                flexion[name].append(-math.degrees(q.to_euler('XYZ').x))
        joints = {}
        for name in TRACK:
            pos, rot = np.asarray(positions[name]), np.asarray(rotations[name])
            assert np.isfinite(pos).all() and np.isfinite(rot).all()
            joints[name] = joint_metrics(pos, rot, dt, 1/fps)
            for warning in joints[name]['diagnostic_warnings']:
                report['warnings'].append(f'{clip}:{name}:{warning}')
        curls = {n: stats(a) for n, a in flexion.items()}
        step_width = np.asarray(positions['foot.L'])[:,0]-np.asarray(positions['foot.R'])[:,0]
        if not options.baseline:
            assert float(step_width.min()) > .035, (clip,'Feet crossed',float(step_width.min()))
            assert float(step_width.max()) < .26, (clip,'Step width is still splayed',float(step_width.max()))
        fists = all(curls[f'{finger}.{j:02d}.{side}']['min'] >= minimum
                    for side in ('L', 'R') for finger in ('index', 'middle', 'ring', 'pinky')
                    for j, minimum in ((1, 30), (2, 40), (3, 20)))
        if clip == 'run' and not fists:
            report['warnings'].append('run:fingers:requested_fist_pose_not_closed')
        report['clips'][clip] = {'frame_start': start, 'frame_end': end,
                                'duration_s': (end-start)/fps, 'sample_count': count,
                                'joints': joints, 'finger_flexion_degrees': curls,
                                'step_width_m': stats(step_width),
                                'run_fists_meet_requested_pose': fists if clip == 'run' else None}
        print('[GAIT_QA]', clip, count, 'samples', 'foot seam velocity jumps',
              joints['foot.L']['loop_velocity_jump_m_s'], joints['foot.R']['loop_velocity_jump_m_s'], flush=True)
    assert hashlib.sha256(options.blend.read_bytes()).hexdigest() == source_hash
    out = options.output or OUT/('gait_before.json' if options.baseline else 'gait_continuity.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding='utf8')
    print('[GAIT_QA] REPORT', str(out), 'warnings', len(report['warnings']), flush=True)
    if options.strict:
        assert not report['warnings'], report['warnings']


if __name__ == '__main__':
    main()
