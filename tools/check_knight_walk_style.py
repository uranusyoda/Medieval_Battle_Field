"""Check that the relaxed walking upper body preserves the accepted locomotion.

python3 tools/check_knight_walk_style.py --baseline
python3 tools/check_knight_walk_style.py

This reads GLB arrays directly without Blender. The baseline lives outside the
project; the JSON report describes numeric preservation and finger flexion,
not subjective animation quality.
"""
from pathlib import Path
import argparse
import json

import numpy as np

from patch_anatomical_glb import read_glb
from patch_anatomical_animations import _array

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GLB = ROOT / 'assets/models/characters/parts/templar_anatomical_animated.glb'
DEFAULT_REPORT = ROOT / 'assets/renders/parts/animated/knight_walk_style.json'
DEFAULT_BASELINE = Path('/tmp/knight_walk_before.npz')
LOWER_BODY = {'root', 'hips'} | {
    f'{bone}.{side}' for side in ('L', 'R')
    for bone in ('thigh', 'shin', 'foot', 'toe')}
ARM_BONES = [f'{bone}.{side}' for side in ('L', 'R')
             for bone in ('shoulder', 'upper_arm', 'forearm', 'hand')]
FINGERS = ('index', 'middle', 'ring', 'pinky')


def load_tracks(path):
    document, binary = read_glb(path)
    tracks, metadata = {}, []
    for animation in document.get('animations', []):
        clip = animation['name']
        if clip not in ('walk', 'run'):
            continue
        for channel in animation['channels']:
            node = document['nodes'][channel['target']['node']]['name']
            target = channel['target']['path']
            sampler = animation['samplers'][channel['sampler']]
            key = f'{clip}|{node}|{target}'
            assert key + '|input' not in tracks, f'Duplicate track: {key}'
            tracks[key + '|input'] = _array(document, binary, sampler['input'])
            tracks[key + '|output'] = _array(document, binary, sampler['output'])
            metadata.append(dict(key=key, clip=clip, node=node, path=target,
                                 interpolation=sampler.get('interpolation', 'LINEAR')))
    return document, tracks, metadata


def values(tracks, item):
    output = tracks[item['key'] + '|output']
    return output[1::3] if item['interpolation'] == 'CUBICSPLINE' else output


def multiply_quaternions(a, b):
    """Quaternion product in glTF's x,y,z,w convention, with broadcasting."""
    return np.concatenate((a[..., 3:] * b[..., :3] + b[..., 3:] * a[..., :3]
                           + np.cross(a[..., :3], b[..., :3]),
                           a[..., 3:] * b[..., 3:]
                           - np.sum(a[..., :3] * b[..., :3], axis=-1, keepdims=True)), axis=-1)


def flexion_degrees(document, tracks, by_key, clip, node):
    rest = np.array(next(n for n in document['nodes'] if n.get('name') == node)
                    .get('rotation', [0, 0, 0, 1]), dtype=float)
    rest[:3] *= -1
    animated = values(tracks, by_key[f'{clip}|{node}|rotation']).astype(float)
    relative = multiply_quaternions(rest, animated)
    relative *= np.where(relative[:, 3:] < 0, -1, 1)
    # Authored flexion is negative local X. MCP side spread contributes local Z;
    # extracting the X twist avoids counting that spread as finger flexion.
    return np.degrees(2 * np.arctan2(-relative[:, 0], relative[:, 3]))


def compare_arrays(a, b):
    if a.shape != b.shape:
        return dict(shape_equal=False, before_shape=list(a.shape), after_shape=list(b.shape))
    return dict(shape_equal=True, max_abs_difference=float(np.max(np.abs(a.astype(float) - b))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--glb', type=Path, default=DEFAULT_GLB)
    parser.add_argument('--baseline-file', type=Path, default=DEFAULT_BASELINE)
    parser.add_argument('--output', type=Path, default=DEFAULT_REPORT)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--tolerance', type=float, default=2e-5)
    options = parser.parse_args()
    document, tracks, metadata = load_tracks(options.glb)
    if options.baseline:
        payload = dict(tracks)
        payload['__meta__'] = np.array(json.dumps(metadata))
        np.savez_compressed(options.baseline_file, **payload)
        print(f'Saved {len(metadata)} walk/run tracks to {options.baseline_file}')
        return

    with np.load(options.baseline_file, allow_pickle=False) as source:
        baseline = {key: source[key].copy() for key in source.files if key != '__meta__'}
        old_metadata = json.loads(str(source['__meta__']))
    old_by_key = {item['key']: item for item in old_metadata}
    by_key = {item['key']: item for item in metadata}
    failures, protected = [], []
    protected_old = {key for key, item in old_by_key.items()
                     if item['clip'] == 'run' or item['node'] in LOWER_BODY}
    protected_new = {key for key, item in by_key.items()
                     if item['clip'] == 'run' or item['node'] in LOWER_BODY}
    if protected_old != protected_new:
        failures.append('protected_track_inventory_changed')
    for key in sorted(protected_old):
        if key not in by_key:
            failures.append(f'missing_track:{key}')
            continue
        old_item, item = old_by_key[key], by_key[key]
        row = dict(key=key, interpolation_equal=old_item['interpolation'] == item['interpolation'])
        if not row['interpolation_equal']:
            failures.append(f'interpolation_changed:{key}')
        for field in ('input', 'output'):
            difference = compare_arrays(baseline[key + '|' + field], tracks[key + '|' + field])
            row[field] = difference
            if not difference['shape_equal'] or difference.get('max_abs_difference', 0) > options.tolerance:
                failures.append(f'protected_{field}_changed:{key}')
        protected.append(row)

    arm_changes = []
    for node in ARM_BONES:
        key = f'walk|{node}|rotation'
        if key not in by_key or key not in old_by_key:
            failures.append(f'missing_arm_rotation:{node}')
            continue
        before, after = values(baseline, old_by_key[key]), values(tracks, by_key[key])
        difference = compare_arrays(before, after)
        changed = not difference['shape_equal'] or difference.get('max_abs_difference', 0) > options.tolerance
        arm_changes.append(dict(node=node, changed=changed, values=difference))
        if not changed:
            failures.append(f'walk_arm_did_not_change:{node}')

    hands = {}
    for side in ('L', 'R'):
        side_report = {}
        for joint, label, bounds in ((1, 'MCP', (12, 30)), (2, 'PIP', (18, 40)), (3, 'DIP', (9, 25))):
            means = []
            for finger in FINGERS:
                node = f'{finger}.{joint:02d}.{side}'
                angle = flexion_degrees(document, tracks, by_key, 'walk', node)
                run_angle = flexion_degrees(document, tracks, by_key, 'run', node)
                row = dict(min_deg=float(angle.min()), mean_deg=float(angle.mean()), max_deg=float(angle.max()),
                           run_mean_deg=float(run_angle.mean()))
                side_report[f'{finger}_{label}'] = row
                means.append(row['mean_deg'])
                if angle.min() < bounds[0] or angle.max() > bounds[1]:
                    failures.append(f'walk_finger_outside_soft_curl_range:{node}')
                if angle.max() >= .65 * run_angle.min():
                    failures.append(f'walk_finger_too_close_to_run_fist:{node}')
            if np.any(np.diff(means) <= .5):
                failures.append(f'walk_finger_curl_not_graded:{side}:{label}')
        hands[side] = side_report

    report = dict(glb=str(options.glb), baseline=str(options.baseline_file), tolerance=options.tolerance,
                  scope='Numeric scope preservation and graded relaxed finger flexion; visual style requires viewing the animation.',
                  checked_run_tracks=sum(item['clip'] == 'run' for item in old_metadata),
                  checked_walk_lower_body_tracks=sum(item['clip'] == 'walk' and item['node'] in LOWER_BODY for item in old_metadata),
                  protected_tracks=protected, walking_arm_changes=arm_changes,
                  walking_finger_flexion=hands, failures=failures, passed=not failures)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=report['passed'], protected_tracks=len(protected),
                         changed_arm_rotations=sum(row['changed'] for row in arm_changes),
                         failures=failures, report=str(options.output)), ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
