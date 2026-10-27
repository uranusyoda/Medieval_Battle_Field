"""Read CMU's original Acclaim ASF/AMC mocap without a Blender dependency.

Positions are bone ENDPOINTS, not heads: ``ltibia`` is the ankle,
``lfemur`` is the knee, ``lhipjoint`` is the hip, ``lradius`` is the wrist.
The default output is meters in Blender axes (+Z up, -Y forward). Recorded
root travel remains present; callers can subtract root XY for in-place clips.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import json
import numpy as np

CMU_METERS = (1.0 / .45) * 2.54 / 100
YUP_TO_ZUP = np.array([[1., 0., 0.], [0., 0., -1.], [0., 1., 0.]])


def rotation(axis: str, degrees: float) -> np.ndarray:
    a = math.radians(float(degrees))
    c, s = math.cos(a), math.sin(a)
    if axis.lower() == 'x':
        return np.array([[1., 0., 0.], [0., c, -s], [0., s, c]])
    if axis.lower() == 'y':
        return np.array([[c, 0., s], [0., 1., 0.], [-s, 0., c]])
    if axis.lower() == 'z':
        return np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])
    raise ValueError(axis)


def euler(values, order='XYZ') -> np.ndarray:
    """Acclaim Euler order: listed X then Y then Z, applied to columns."""
    r = np.eye(3)
    for axis, value in zip(order, values):
        r = rotation(axis, value) @ r
    return r


def parse_asf(path):
    lines = [x.split('#', 1)[0].strip() for x in Path(path).read_text().splitlines()]
    bones, hierarchy, root = {}, {}, {}
    section, current = '', None
    for line in lines:
        if not line:
            continue
        if line.startswith(':'):
            section = line[1:].split()[0].lower()
            continue
        words = line.split()
        if section == 'root':
            root[words[0].lower()] = words[1:]
        elif section == 'bonedata':
            if line == 'begin':
                current = {}
            elif line == 'end':
                if current:
                    bones[current['name']] = current
                current = None
            elif current is not None:
                key = words[0]
                if key in ('name', 'id'):
                    current[key] = words[1]
                elif key == 'direction':
                    current[key] = np.array(list(map(float, words[1:4])))
                elif key == 'length':
                    current[key] = float(words[1])*CMU_METERS
                elif key == 'axis':
                    current['axis'] = euler(list(map(float, words[1:4])), words[4])
                elif key == 'dof':
                    current['dof'] = words[1:]
        elif section == 'hierarchy' and line not in ('begin', 'end'):
            hierarchy[words[0]] = words[1:]
    assert bones and hierarchy and root
    return {'bones': bones, 'hierarchy': hierarchy, 'root': root}


def parse_amc(path):
    frames, current = [], None
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(('#', ':')):
            continue
        if line.isdigit():
            if current is not None:
                frames.append(current)
            current = {}
        else:
            words = line.split()
            assert current is not None
            current[words[0]] = np.array(list(map(float, words[1:])))
    if current is not None:
        frames.append(current)
    assert frames and all('root' in f for f in frames)
    return frames


@dataclass
class Motion:
    positions: dict[str, np.ndarray]
    rotations: dict[str, np.ndarray]
    hierarchy: dict[str, list[str]]
    fps: float
    asf_path: str
    amc_path: str

    def __len__(self):
        return len(self.positions['root'])

    def sample(self, frame: float):
        """Linearly sample endpoint positions at a zero-based frame index."""
        frame = float(np.clip(frame, 0, len(self)-1))
        lo = int(frame)
        hi = min(lo+1, len(self)-1)
        t = frame-lo
        return {name: values[lo]*(1-t)+values[hi]*t for name, values in self.positions.items()}

    def to_json(self, path):
        value = {'fps': self.fps, 'frames': len(self), 'coordinates': 'meters, +Z up, source +Z forward becomes -Y',
                 'joint_meaning': 'bone endpoints; ltibia=ankle, lfemur=knee, lhipjoint=hip, lradius=wrist',
                 'source_asf': self.asf_path, 'source_amc': self.amc_path,
                 'hierarchy': self.hierarchy, 'positions': {n: p.tolist() for n, p in self.positions.items()}}
        Path(path).write_text(json.dumps(value, separators=(',', ':')), encoding='utf-8')


def load_motion(asf_path, amc_path, fps=120., z_up=True):
    skeleton, frames = parse_asf(asf_path), parse_amc(amc_path)
    bones, hierarchy, root_spec = skeleton['bones'], skeleton['hierarchy'], skeleton['root']
    names = ['root']+list(bones)
    positions = {n: np.empty((len(frames), 3)) for n in names}
    rotations = {n: np.empty((len(frames), 3, 3)) for n in names}
    parent = {child: par for par, children in hierarchy.items() for child in children}
    ordered = []
    def walk(name):
        ordered.append(name)
        for child in hierarchy.get(name, []):
            walk(child)
    walk('root')
    assert set(ordered) == set(names)
    basis = YUP_TO_ZUP if z_up else np.eye(3)
    for index, values in enumerate(frames):
        root_values = dict(zip(root_spec['order'], values['root']))
        root_position = np.array([root_values['TX'], root_values['TY'], root_values['TZ']])*CMU_METERS
        root_rot = euler([root_values['RX'], root_values['RY'], root_values['RZ']], ''.join(root_spec['axis']))
        local_positions, local_rotations = {'root': root_position}, {'root': root_rot}
        for name in ordered[1:]:
            bone, par = bones[name], parent[name]
            channels = bone.get('dof', [])
            vals = values.get(name, np.zeros(len(channels)))
            assert len(vals) == len(channels), (name, channels, vals)
            m = np.eye(3)
            for channel, value in zip(channels, vals):
                assert channel.startswith('r'), channel
                m = rotation(channel[1], value) @ m
            c = bone['axis']
            orientation = local_rotations[par] @ c @ m @ c.T
            endpoint = local_positions[par]+orientation @ (bone['direction']*bone['length'])
            local_positions[name], local_rotations[name] = endpoint, orientation
        for name in names:
            positions[name][index] = basis @ local_positions[name]
            rotations[name][index] = basis @ local_rotations[name] @ basis.T
    return Motion(positions, rotations, hierarchy, float(fps), str(asf_path), str(amc_path))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('asf')
    parser.add_argument('amc')
    parser.add_argument('--json')
    args = parser.parse_args()
    m = load_motion(args.asf, args.amc)
    if args.json:
        m.to_json(args.json)
    print(json.dumps({'frames': len(m), 'fps': m.fps, 'duration': (len(m)-1)/m.fps,
                      'joints': len(m.positions),
                      'root_start': m.positions['root'][0].tolist(),
                      'root_end': m.positions['root'][-1].tolist(),
                      'left_ankle_min_z': float(m.positions['ltibia'][:, 2].min())}, indent=2))
