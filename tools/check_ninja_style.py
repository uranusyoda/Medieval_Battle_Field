"""Measure wider relaxed arms and the low, asymmetric ninja crouch.

blender --background --threads 4 --python tools/check_ninja_style.py

This reads the finished GLB and Blender scene. It leaves the previous athletic
report intact, compares the accepted legs/jump/hand demonstrations exactly,
and reports objective skeletal silhouette and contact measurements.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from check_athletic_style import (LOWER_BODY, check_finger_structure, load_tracks,
                                  ranges, world_heads)

MODELS = ROOT/'assets/models/characters/parts'
DEFAULT_GLB = MODELS/'templar_anatomical_animated.glb'
DEFAULT_BLEND = MODELS/'templar_anatomical_animated.blend'
DEFAULT_BASELINE = Path('/tmp/knight_ninja_before.npz')
DEFAULT_REPORT = ROOT/'assets/renders/parts/animated/ninja_style.json'
PRESERVED_CLIPS = {'jump', 'grip', 'finger_wave', 'wrist'}


def compare_protected(before, after, failures):
    checked = []
    for key in sorted(k.rsplit('|', 1)[0] for k in before if k.endswith('|input')):
        clip, node, _ = key.split('|')
        if clip not in PRESERVED_CLIPS and not (clip in ('walk', 'run') and node in LOWER_BODY):
            continue
        row = {'key': key, 'exact': True, 'max_abs_difference': 0.}
        for field in ('input', 'output', 'interpolation'):
            a, b = before[key+'|'+field], after.get(key+'|'+field)
            exact = b is not None and np.array_equal(a, b)
            row['exact'] &= exact
            if not exact:
                failures.append(f'preserved_{field}_changed:{key}')
            if field != 'interpolation' and b is not None and a.shape == b.shape:
                row['max_abs_difference'] = max(row['max_abs_difference'], float(np.max(np.abs(a.astype(float)-b))))
        checked.append(row)
    if len(checked) != 780:
        failures.append(f'protected_track_count_changed:{len(checked)}')
    return {'count': len(checked), 'all_exact': all(row['exact'] for row in checked), 'tracks': checked}


def measure_arm_opening(document, before, after, failures):
    report = {}
    for clip in ('idle', 'walk', 'run'):
        duration = max(float(v.ravel()[-1]) for k, v in after.items()
                       if k.startswith(clip+'|') and k.endswith('|input'))
        poses = [world_heads(document, after, clip, t) for t in np.linspace(0, duration, 41)]
        old_poses = [world_heads(document, before, clip, t) for t in np.linspace(0, duration, 41)]
        sides = {}
        for side in ('L', 'R'):
            now, old, elbow = [], [], []
            for source, target in ((poses, now), (old_poses, old)):
                for pose in source:
                    upper = pose[f'forearm.{side}']-pose[f'upper_arm.{side}']
                    forearm = pose[f'hand.{side}']-pose[f'forearm.{side}']
                    upper /= np.linalg.norm(upper)
                    forearm /= np.linalg.norm(forearm)
                    target.append(math.degrees(math.asin(np.clip(abs(upper[0]), 0, 1))))
                    if source is poses:
                        elbow.append(math.degrees(math.acos(np.clip(upper@forearm, -1, 1))))
            delta = float(np.mean(now)-np.mean(old))
            sides[side] = {'outward_component_deg': ranges(now), 'before_outward_component_deg': ranges(old),
                           'mean_outward_increase_deg': delta, 'elbow_flexion_deg': ranges(elbow)}
            if delta < 4.-1e-3:
                failures.append(f'arm_mean_outward_increase_below_4deg:{clip}:{side}:{delta:.4f}')
            if min(elbow) < 2 or max(elbow) > 145:
                failures.append(f'elbow_outside_check_range:{clip}:{side}')
        report[clip] = sides
    return report


def measure_crouch(blend, failures):
    import bpy
    from check_anatomical_animations import activate
    from mathutils import Vector

    bpy.ops.wm.open_mainfile(filepath=str(blend))
    arm = next(ob for ob in bpy.context.scene.objects if ob.type == 'ARMATURE')
    feet = [ob for ob in bpy.context.scene.objects if ob.type == 'MESH' and ob.name.startswith('body_foot.')]
    scene = bpy.context.scene

    def point(name, tail=False):
        bone = arm.pose.bones[name]
        return arm.matrix_world @ (bone.tail if tail else bone.head)

    def direction(name):
        return (point(name, True)-point(name)).normalized()

    def upright_angle(name):
        return math.degrees(math.acos(max(-1., min(1., direction(name).dot(Vector((0, 0, 1)))))))

    def sole_heights():
        deps = bpy.context.evaluated_depsgraph_get()
        heights = {}
        for ob in feet:
            evaluated = ob.evaluated_get(deps)
            vertices = np.empty(len(evaluated.data.vertices)*3)
            evaluated.data.vertices.foreach_get('co', vertices)
            transform = np.asarray(evaluated.matrix_world)
            z = vertices.reshape(-1, 3) @ transform[2, :3]+transform[2, 3]
            side = 'L' if ob.name.startswith('body_foot.L') else 'R'
            heights[side] = min(heights.get(side, float('inf')), float(z.min()))
        return heights

    activate(arm, bpy.data.actions['idle'])
    scene.frame_set(0)
    bpy.context.view_layer.update()
    upright_hip, upright_head = point('hips').z, point('head').z
    action = bpy.data.actions['crouch']
    activate(arm, action)
    start, end = map(float, action.frame_range)
    samples = []
    for frame in np.linspace(start, end, round(end-start)+1):
        scene.frame_set(int(frame), subframe=float(frame-int(frame)))
        bpy.context.view_layer.update()
        f = (frame-start)/(end-start)
        hip, head = point('hips'), point('head')
        ankle_l, ankle_r = point('foot.L'), point('foot.R')
        elbow_l, elbow_r = point('forearm.L'), point('forearm.R')
        wrist_l, wrist_r = point('hand.L'), point('hand.R')
        floor = sole_heights()
        # Compare positions relative to hips, then mirror only the lateral X
        # axis. Y/Z differences describe the staggered, unequal arm placement.
        mirrored_elbow_l = elbow_l-hip
        mirrored_elbow_l.x *= -1
        mirrored_wrist_l = wrist_l-hip
        mirrored_wrist_l.x *= -1
        samples.append({'frame': float(frame), 'fraction': float(f), 't_s': float(frame/scene.render.fps),
                        'hip_z_m': float(hip.z), 'head_z_m': float(head.z),
                        'hip_drop_from_idle_m': float(upright_hip-hip.z),
                        'head_drop_from_idle_m': float(upright_head-head.z),
                        'lowest_sole_m': min(floor.values()),
                        'left_lowest_sole_m': floor['L'], 'right_lowest_sole_m': floor['R'],
                        'chest_tilt_from_upright_deg': upright_angle('chest'),
                        'head_tilt_from_upright_deg': upright_angle('head'),
                        'ankle_fore_aft_stagger_m': abs(float(ankle_l.y-ankle_r.y)),
                        'ankle_lateral_separation_m': abs(float(ankle_l.x-ankle_r.x)),
                        'elbow_nonmirror_distance_m': float((mirrored_elbow_l-(elbow_r-hip)).length),
                        'wrist_nonmirror_distance_m': float((mirrored_wrist_l-(wrist_r-hip)).length),
                        'elbow_fore_aft_difference_m': abs(float(elbow_l.y-elbow_r.y)),
                        'wrist_fore_aft_difference_m': abs(float(wrist_l.y-wrist_r.y))})
    hold = [sample for sample in samples if .35 <= sample['fraction'] <= .65]
    if not hold:
        failures.append('crouch_has_no_hold_samples')
        return {'samples': samples}
    measured = ['hip_z_m', 'head_z_m', 'hip_drop_from_idle_m', 'head_drop_from_idle_m',
                'lowest_sole_m', 'left_lowest_sole_m', 'right_lowest_sole_m',
                'chest_tilt_from_upright_deg', 'head_tilt_from_upright_deg',
                'ankle_fore_aft_stagger_m', 'ankle_lateral_separation_m',
                'elbow_nonmirror_distance_m', 'wrist_nonmirror_distance_m',
                'elbow_fore_aft_difference_m', 'wrist_fore_aft_difference_m']
    hold_ranges = {key: ranges([sample[key] for sample in hold]) for key in measured}
    low = min(sample['lowest_sole_m'] for sample in samples)
    if low < -.012:
        failures.append(f'crouch_sole_below_floor:{low:.5f}')
    if hold_ranges['hip_drop_from_idle_m']['min'] < .15:
        failures.append('crouch_hold_hip_drop_below_15cm')
    if hold_ranges['head_drop_from_idle_m']['min'] < .15:
        failures.append('crouch_hold_head_drop_below_15cm')
    if hold_ranges['ankle_fore_aft_stagger_m']['min'] < .10:
        failures.append('crouch_hold_foot_stagger_below_10cm')
    if hold_ranges['wrist_nonmirror_distance_m']['min'] < .06:
        failures.append('crouch_hold_arms_too_close_to_mirrored')
    for side in ('left', 'right'):
        if hold_ranges[side+'_lowest_sole_m']['max'] > .02:
            failures.append(f'crouch_hold_{side}_sole_floating_above_2cm')
    if hold_ranges['chest_tilt_from_upright_deg']['min'] < 12:
        failures.append('crouch_hold_chest_has_little_forward_lean')
    if hold_ranges['head_tilt_from_upright_deg']['max'] > 25:
        failures.append('crouch_hold_head_not_held_upright')
    return {'upright_idle_hip_z_m': float(upright_hip), 'upright_idle_head_z_m': float(upright_head),
            'lowest_sole_m': low, 'hold_fraction': [.35, .65], 'hold_measurements': hold_ranges,
            'samples': samples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--glb', type=Path, default=DEFAULT_GLB)
    parser.add_argument('--blend', type=Path, default=DEFAULT_BLEND)
    parser.add_argument('--baseline', type=Path, default=DEFAULT_BASELINE)
    parser.add_argument('--output', type=Path, default=DEFAULT_REPORT)
    parser.add_argument('--no-blend', action='store_true')
    argv = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else ([] if any('blender' in arg.lower() for arg in sys.argv[:1]) else None)
    options = parser.parse_args(argv)
    document, after = load_tracks(options.glb)
    with np.load(options.baseline, allow_pickle=False) as data:
        before = {key: data[key].copy() for key in data.files}
    failures = []
    report = {'glb': str(options.glb), 'sha256': hashlib.sha256(options.glb.read_bytes()).hexdigest(),
              'baseline': str(options.baseline),
              'scope': 'Exact protected tracks; skeletal arm opening and low-crouch contact, height, head orientation, foot stagger and arm asymmetry. Naturalness still requires visual review.'}
    report['preserved_tracks'] = compare_protected(before, after, failures)
    report['skeleton'] = check_finger_structure(document, failures)
    report['arms'] = measure_arm_opening(document, before, after, failures)
    if not options.no_blend:
        report['crouch'] = measure_crouch(options.blend, failures)
    report['failures'], report['passed'] = failures, not failures
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'passed': report['passed'], 'protected_tracks': report['preserved_tracks']['count'],
                      'arms': report['arms'], 'failures': failures, 'report': str(options.output)}, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
