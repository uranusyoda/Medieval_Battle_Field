"""Measure the athletic upper-body revision and jump, without judging style.

blender --background --threads 4 --python tools/check_athletic_style.py

The baseline is an immutable pre-revision GLB track snapshot in /tmp. Compare
the accepted locomotion legs and unrelated clips exactly; then measure actual
world-space arm directions and the saved Blender jump's sole/hip trajectory.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from patch_anatomical_glb import read_glb
from patch_anatomical_animations import _array

MODELS = ROOT / 'assets/models/characters/parts'
DEFAULT_GLB = MODELS / 'templar_anatomical_animated.glb'
DEFAULT_BLEND = MODELS / 'templar_anatomical_animated.blend'
DEFAULT_BASELINE = Path('/tmp/knight_athletic_before.npz')
DEFAULT_REPORT = ROOT / 'assets/renders/parts/animated/athletic_style.json'
LOWER_BODY = {'root', 'hips'} | {
    f'{bone}.{side}' for bone in ('thigh', 'shin', 'foot', 'toe') for side in ('L', 'R')}
PRESERVED_CLIPS = {'crouch', 'grip', 'finger_wave', 'wrist'}


def load_tracks(path):
    document, binary = read_glb(path)
    tracks = {}
    for clip in document['animations']:
        for channel in clip['channels']:
            target = channel['target']
            sampler = clip['samplers'][channel['sampler']]
            key = f"{clip['name']}|{document['nodes'][target['node']]['name']}|{target['path']}"
            tracks[key+'|input'] = _array(document, binary, sampler['input'])
            tracks[key+'|output'] = _array(document, binary, sampler['output'])
            tracks[key+'|interpolation'] = np.array(sampler.get('interpolation', 'LINEAR'))
    return document, tracks


def protected_tracks(before, after, failures):
    keys = sorted(k.rsplit('|', 1)[0] for k in before if k.endswith('|input'))
    checked = []
    for key in keys:
        clip, node, _ = key.split('|')
        if clip not in PRESERVED_CLIPS and not (clip in ('walk', 'run') and node in LOWER_BODY):
            continue
        row = {'key': key, 'exact': True, 'max_abs_difference': 0.}
        for field in ('input', 'output', 'interpolation'):
            a, b = before[key+'|'+field], after.get(key+'|'+field)
            same = b is not None and np.array_equal(a, b)
            row['exact'] &= same
            if not same:
                failures.append(f'preserved_{field}_changed:{key}')
            if field != 'interpolation' and b is not None and a.shape == b.shape:
                row['max_abs_difference'] = max(row['max_abs_difference'], float(np.max(np.abs(a.astype(float)-b))))
        checked.append(row)
    return {'count': len(checked), 'all_exact': all(r['exact'] for r in checked), 'tracks': checked}


def quaternion_matrix(q):
    x, y, z, w = np.asarray(q)/np.linalg.norm(q)
    return np.array([[1-2*y*y-2*z*z, 2*x*y-2*z*w, 2*x*z+2*y*w],
                     [2*x*y+2*z*w, 1-2*x*x-2*z*z, 2*y*z-2*x*w],
                     [2*x*z-2*y*w, 2*y*z+2*x*w, 1-2*x*x-2*y*y]])


def sample_track(tracks, key, seconds):
    times = tracks[key+'|input'].ravel().astype(float)
    values = tracks[key+'|output'].astype(float)
    kind = str(tracks[key+'|interpolation'])
    if kind == 'CUBICSPLINE':
        values = values.reshape(len(times), 3, -1)
    i = min(max(0, int(np.searchsorted(times, seconds, side='right')-1)), len(times)-2)
    dt = times[i+1]-times[i]
    u = max(0., min(1., (seconds-times[i])/dt))
    if kind == 'CUBICSPLINE':
        a, b = values[i, 1], values[i+1, 1]
        return ((2*u**3-3*u*u+1)*a + (u**3-2*u*u+u)*dt*values[i, 2]
                + (-2*u**3+3*u*u)*b + (u**3-u*u)*dt*values[i+1, 0])
    if kind == 'STEP':
        return values[i]
    a, b = values[i], values[i+1]
    if key.endswith('|rotation'):
        a, b = a/np.linalg.norm(a), b/np.linalg.norm(b)
        dot = float(np.dot(a, b))
        if dot < 0:
            dot, b = -dot, -b
        if dot < .9995:
            angle = math.acos(max(-1., min(1., dot)))
            return (math.sin((1-u)*angle)*a+math.sin(u*angle)*b)/math.sin(angle)
    return a*(1-u)+b*u


def world_heads(document, tracks, clip, seconds):
    nodes = document['nodes']
    parents = {child: parent for parent, node in enumerate(nodes) for child in node.get('children', [])}
    world = {}

    def matrix(index):
        if index in world:
            return world[index]
        node = nodes[index]
        transforms = {}
        for path, default in [('translation', [0, 0, 0]), ('rotation', [0, 0, 0, 1]), ('scale', [1, 1, 1])]:
            key = f"{clip}|{node.get('name', '')}|{path}"
            transforms[path] = sample_track(tracks, key, seconds) if key+'|input' in tracks else np.array(node.get(path, default))
        local = np.eye(4)
        if 'matrix' in node:
            local = np.array(node['matrix']).reshape(4, 4).T
        else:
            local[:3, :3] = quaternion_matrix(transforms['rotation']) @ np.diag(transforms['scale'])
            local[:3, 3] = transforms['translation']
        world[index] = matrix(parents[index]) @ local if index in parents else local
        return world[index]

    return {node['name']: matrix(i)[:3, 3] for i, node in enumerate(nodes) if 'name' in node}


def ranges(values):
    return {'min': float(np.min(values)), 'mean': float(np.mean(values)), 'max': float(np.max(values))}


def measure_arms(document, before, after, failures):
    report = {}
    for clip, minimum in [('idle', 12.), ('walk', 15.), ('run', 16.)]:
        duration = max(float(v.ravel()[-1]) for k, v in after.items() if k.startswith(clip+'|') and k.endswith('|input'))
        poses = [world_heads(document, after, clip, t) for t in np.linspace(0, duration, 33)]
        old_poses = [world_heads(document, before, clip, t) for t in np.linspace(0, duration, 33)]
        sides = {}
        for side in ('L', 'R'):
            data, old = [], []
            elbow = []
            for source, target in [(poses, data), (old_poses, old)]:
                for p in source:
                    upper = p[f'forearm.{side}']-p[f'upper_arm.{side}']
                    forearm = p[f'hand.{side}']-p[f'forearm.{side}']
                    upper /= np.linalg.norm(upper)
                    forearm /= np.linalg.norm(forearm)
                    target.append(math.degrees(math.asin(np.clip(abs(upper[0]), 0, 1))))
                    if source is poses:
                        elbow.append(math.degrees(math.acos(np.clip(upper@forearm, -1, 1))))
            delta = float(np.mean(data)-np.mean(old))
            sides[side] = {'outward_component_deg': ranges(data), 'before_outward_component_deg': ranges(old),
                           'mean_outward_increase_deg': delta, 'elbow_flexion_deg': ranges(elbow)}
            if min(data) < minimum:
                failures.append(f'arm_outward_clearance_below_target:{clip}:{side}:{min(data):.3f}')
            if delta < 2:
                failures.append(f'arm_outward_clearance_did_not_increase:{clip}:{side}:{delta:.3f}')
            if min(elbow) < 2 or max(elbow) > 140:
                failures.append(f'elbow_flexion_outside_check_range:{clip}:{side}')
        report[clip] = sides
    return report


def check_finger_structure(document, failures):
    base, _ = read_glb(MODELS/'templar_tpose_unarmored_parts_rig_anatomical.glb')

    def hierarchy(doc):
        names = {j: doc['nodes'][j]['name'] for skin in doc['skins'] for j in skin['joints']}
        return {names[child]: names[parent] for parent, node in enumerate(doc['nodes']) if parent in names
                for child in node.get('children', []) if child in names}

    expected, actual = hierarchy(base), hierarchy(document)
    finger_names = {name for name in expected if name.split('.')[0] in ('thumb', 'index', 'middle', 'ring', 'pinky')}
    same = all(actual.get(name) == expected[name] for name in finger_names)
    if not same:
        failures.append('finger_joint_parentage_changed')
    joints = {j for skin in document['skins'] for j in skin['joints']}
    if len(joints) != 60:
        failures.append('skeleton_bone_count_changed')
    return {'bones': len(joints), 'checked_finger_joint_parents': len(finger_names), 'finger_parentage_exact': same}


def measure_jump(blend, failures):
    import bpy
    import rig_util
    from check_anatomical_animations import activate
    try:
        import athletic_jump
        takeoff = float(getattr(athletic_jump, 'TAKEOFF', .45))
        landing = float(getattr(athletic_jump, 'LANDING', 1.10))
    except ImportError:
        takeoff, landing = .45, 1.10
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    feet = [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.name.startswith('body_foot.')]
    activate(arm, bpy.data.actions['jump'])
    scene = bpy.context.scene
    duration = float(bpy.data.actions['jump'].frame_range[1])/scene.render.fps
    samples = []
    for t in np.unique(np.r_[np.linspace(0, duration, round(duration*scene.render.fps)+1),
                            takeoff-.02, takeoff, takeoff+.02, (takeoff+landing)/2, landing-.02, landing, landing+.02]):
        frame = max(0, t*scene.render.fps)
        scene.frame_set(int(frame), subframe=frame-int(frame))
        bpy.context.view_layer.update()
        deps = bpy.context.evaluated_depsgraph_get()
        low = float('inf')
        for ob in feet:
            ev = ob.evaluated_get(deps)
            vertices = np.empty(len(ev.data.vertices)*3)
            ev.data.vertices.foreach_get('co', vertices)
            m = np.asarray(ev.matrix_world)
            z = vertices.reshape(-1, 3) @ m[2, :3]+m[2, 3]
            low = min(low, float(z.min()))
        h = arm.matrix_world @ arm.pose.bones['hips'].head
        samples.append({'t_s': float(t), 'hip_z_m': float(h.z), 'lowest_sole_m': low})
    times = np.array([s['t_s'] for s in samples])
    heights = np.array([s['hip_z_m'] for s in samples])
    soles = np.array([s['lowest_sole_m'] for s in samples])
    airborne = (times >= takeoff+.10) & (times <= landing-.10)
    fit = np.polyfit(times[airborne], heights[airborne], 2)
    residual = heights[airborne]-np.polyval(fit, times[airborne])
    apex = int(np.argmax(heights))
    if soles.min() < -.012:
        failures.append(f'jump_sole_below_floor:{soles.min():.6f}')
    if not takeoff < times[apex] < landing:
        failures.append('jump_apex_outside_airborne_phase')
    if heights[apex]-heights[0] < .30:
        failures.append('jump_pelvis_rise_below_30cm')
    if np.min(soles[airborne]) < .025:
        failures.append('jump_airborne_interval_lacks_sole_clearance')
    if not -14 < 2*fit[0] < -6:
        failures.append(f'jump_airborne_acceleration_unexpected:{2*fit[0]:.4f}')
    return {'takeoff_s': takeoff, 'landing_s': landing, 'duration_s': duration,
            'apex_s': float(times[apex]), 'pelvis_rise_m': float(heights[apex]-heights[0]),
            'lowest_sole_m': float(soles.min()), 'interior_airborne_min_sole_m': float(soles[airborne].min()),
            'fitted_airborne_acceleration_m_s2': float(2*fit[0]),
            'airborne_quadratic_fit_max_residual_m': float(np.max(np.abs(residual))), 'samples': samples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--glb', type=Path, default=DEFAULT_GLB)
    parser.add_argument('--blend', type=Path, default=DEFAULT_BLEND)
    parser.add_argument('--baseline', type=Path, default=DEFAULT_BASELINE)
    parser.add_argument('--output', type=Path, default=DEFAULT_REPORT)
    parser.add_argument('--no-blend', action='store_true')
    args = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else ([] if any('blender' in s.lower() for s in sys.argv[:1]) else None)
    options = parser.parse_args(args)
    document, after = load_tracks(options.glb)
    with np.load(options.baseline, allow_pickle=False) as data:
        before = {key: data[key].copy() for key in data.files}
    failures = []
    report = {'glb': str(options.glb), 'sha256': hashlib.sha256(options.glb.read_bytes()).hexdigest(),
              'baseline': str(options.baseline),
              'scope': 'Exact preserved tracks, world-space skeletal arm directions and saved Blender jump trajectory; naturalness requires visual review.'}
    report['preserved_tracks'] = protected_tracks(before, after, failures)
    report['skeleton'] = check_finger_structure(document, failures)
    report['arms'] = measure_arms(document, before, after, failures)
    if not options.no_blend:
        report['jump'] = measure_jump(options.blend, failures)
    report['failures'], report['passed'] = failures, not failures
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'passed': report['passed'], 'preserved_tracks': report['preserved_tracks']['count'],
                      'arms': report['arms'], 'failures': failures, 'report': str(options.output)}, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
