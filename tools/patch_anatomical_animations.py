"""Copy baked animations onto the exact preserved anatomical GLB asset.

The Blender export supplies only its animation curves. Geometry, materials,
the shared skeleton, and each part's original inverse bind matrices come from
the previously validated anatomical GLB and remain byte-for-byte unchanged.

python3 tools/patch_anatomical_animations.py BASE.glb EXPORT.glb OUTPUT.glb
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct

import numpy as np

from patch_anatomical_glb import node_matrix, read_glb, world_matrices


EXPECTED_CLIPS = ('idle', 'walk', 'run', 'jump', 'crouch', 'grip', 'finger_wave', 'wrist')
DTYPES = {5120: 'i1', 5121: 'u1', 5122: '<i2', 5123: '<u2', 5125: '<u4', 5126: '<f4'}
WIDTHS = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT2': 4, 'MAT3': 9, 'MAT4': 16}


def _array(document, binary, index):
    """Read strided or sparse animation accessors for independent validation."""
    definition = document['accessors'][index]
    dtype = np.dtype(DTYPES[definition['componentType']])
    width = WIDTHS[definition['type']]
    count = definition['count']
    if 'bufferView' in definition:
        view = document['bufferViews'][definition['bufferView']]
        assert view.get('buffer', 0) == 0
        data = np.ndarray((count, width), dtype=dtype, buffer=binary,
                          offset=view.get('byteOffset', 0) + definition.get('byteOffset', 0),
                          strides=(view.get('byteStride', dtype.itemsize * width), dtype.itemsize)).copy()
    else:
        data = np.zeros((count, width), dtype=dtype)
    if 'sparse' in definition:
        sparse = definition['sparse']
        index_definition = sparse['indices']
        iview = document['bufferViews'][index_definition['bufferView']]
        indices = np.frombuffer(binary, dtype=DTYPES[index_definition['componentType']],
                                count=sparse['count'], offset=iview.get('byteOffset', 0) +
                                index_definition.get('byteOffset', 0))
        value_definition = sparse['values']
        vview = document['bufferViews'][value_definition['bufferView']]
        values = np.frombuffer(binary, dtype=dtype, count=sparse['count'] * width,
                               offset=vview.get('byteOffset', 0) + value_definition.get('byteOffset', 0))
        assert np.all(indices < count) and len(np.unique(indices)) == len(indices)
        data[indices] = values.reshape(-1, width)
    return data


def patch(base_path, exported_path, output_path):
    """Return a preservation and animation report after atomically writing output.

    Animation channels are remapped by their unique bone node names. A changed
    rest transform or parent fails before writing because local animation values
    cannot safely be transferred to a different rest skeleton.
    """
    base_path, exported_path, output_path = map(Path, (base_path, exported_path, output_path))
    assert base_path.resolve() != output_path.resolve(), 'Never overwrite the preserved bind asset'
    original_bytes = base_path.read_bytes()
    export_sha256 = hashlib.sha256(exported_path.read_bytes()).hexdigest()
    base, base_binary = read_glb(base_path)
    exported, export_binary = read_glb(exported_path)
    assert not base.get('animations'), 'Expected the preserved bind asset without animations'
    assert len(base.get('buffers', [])) == len(exported.get('buffers', [])) == 1
    assert 'uri' not in base['buffers'][0] and 'uri' not in exported['buffers'][0]
    assert base.get('skins') and exported.get('animations')
    doc = copy.deepcopy(base)
    binary = bytearray(base_binary)
    exported_world, exported_parents = world_matrices(exported)
    base_world, base_parents = world_matrices(base)
    base_names = {}
    for index, node in enumerate(base['nodes']):
        if 'name' in node:
            assert node['name'] not in base_names, ('Ambiguous base node', node['name'])
            base_names[node['name']] = index
    joint_ids = {j for skin in base['skins'] for j in skin['joints']}
    assert len(joint_ids) == 60, ('Expected sixty shared joints', len(joint_ids))
    exported_joint_ids = {j for skin in exported.get('skins', []) for j in skin['joints']}
    copied_views, copied_accessors, target_map = {}, {}, {}

    def copy_view(index):
        if index in copied_views:
            return copied_views[index]
        view = copy.deepcopy(exported['bufferViews'][index])
        assert view.get('buffer', 0) == 0
        offset, length = view.get('byteOffset', 0), view['byteLength']
        assert offset >= 0 and length >= 0 and offset + length <= len(export_binary)
        while len(binary) % 4:
            binary.append(0)
        view['buffer'], view['byteOffset'] = 0, len(binary)
        binary.extend(export_binary[offset:offset + length])
        new_index = len(doc['bufferViews'])
        doc['bufferViews'].append(view)
        copied_views[index] = new_index
        return new_index

    def copy_accessor(index):
        if index in copied_accessors:
            return copied_accessors[index]
        definition = copy.deepcopy(exported['accessors'][index])
        if 'bufferView' in definition:
            definition['bufferView'] = copy_view(definition['bufferView'])
        if 'sparse' in definition:
            for part in ('indices', 'values'):
                definition['sparse'][part]['bufferView'] = copy_view(definition['sparse'][part]['bufferView'])
        new_index = len(doc['accessors'])
        doc['accessors'].append(definition)
        copied_accessors[index] = new_index
        return new_index

    def target_node(export_index):
        if export_index in target_map:
            return target_map[export_index]
        node = exported['nodes'][export_index]
        name = node.get('name')
        assert name in base_names, ('Animation target is absent from bind skeleton', name)
        mapped = base_names[name]
        assert export_index in exported_joint_ids and mapped in joint_ids, ('Non-bone animation target', name)
        local_error = float(np.max(np.abs(node_matrix(node) - node_matrix(base['nodes'][mapped]))))
        world_error = float(np.max(np.abs(exported_world[export_index] - base_world[mapped])))
        assert local_error < 1e-5 and world_error < 1e-5, ('Animation rest transform differs', name, local_error, world_error)
        ep = exported_parents.get(export_index)
        bp = base_parents.get(mapped)
        # Armature object names may differ, but every bone-to-bone parent must
        # retain its identity for local transform animation to be meaningful.
        if ep in exported_joint_ids or bp in joint_ids:
            assert ep is not None and bp is not None
            assert exported['nodes'][ep].get('name') == base['nodes'][bp].get('name'), ('Bone parent differs', name)
        target_map[export_index] = mapped
        return mapped

    names = [a.get('name') for a in exported['animations']]
    assert len(names) == len(EXPECTED_CLIPS) and set(names) == set(EXPECTED_CLIPS), ('Unexpected clips', names)
    clips = []
    doc['animations'] = []
    for source_animation in exported['animations']:
        animation = copy.deepcopy(source_animation)
        samplers = source_animation.get('samplers', [])
        channels = source_animation.get('channels', [])
        assert samplers and channels, ('Empty clip', animation['name'])
        duplicate_targets = set()
        sampler_info = {}
        max_time, min_time = 0.0, float('inf')
        paths, animated_bones = set(), set()
        for channel in animation['channels']:
            target = channel['target']
            assert set(target) >= {'node', 'path'} and 'extensions' not in target
            assert target['path'] in ('translation', 'rotation', 'scale'), ('Unsupported skeletal channel', target)
            old_node = target['node']
            target['node'] = target_node(old_node)
            key = (target['node'], target['path'])
            assert key not in duplicate_targets, ('Duplicate target channel', animation['name'], key)
            duplicate_targets.add(key)
            paths.add(target['path'])
            animated_bones.add(exported['nodes'][old_node]['name'])
            sampler_index = channel['sampler']
            assert 0 <= sampler_index < len(samplers)
            sampler = samplers[sampler_index]
            interpolation = sampler.get('interpolation', 'LINEAR')
            assert interpolation in ('LINEAR', 'STEP', 'CUBICSPLINE'), interpolation
            input_definition = exported['accessors'][sampler['input']]
            output_definition = exported['accessors'][sampler['output']]
            assert input_definition['componentType'] == 5126 and input_definition['type'] == 'SCALAR'
            assert output_definition['componentType'] == 5126 and not output_definition.get('normalized', False)
            width = 4 if target['path'] == 'rotation' else 3
            assert output_definition['type'] == f'VEC{width}'
            times = _array(exported, export_binary, sampler['input']).ravel()
            values = _array(exported, export_binary, sampler['output'])
            assert len(times) > 0 and np.all(np.isfinite(times)) and np.all(times >= 0)
            assert np.all(np.diff(times) > 0), ('Non-increasing times', animation['name'], sampler_index)
            assert np.all(np.isfinite(values)), ('Nonfinite animation values', animation['name'])
            multiplier = 3 if interpolation == 'CUBICSPLINE' else 1
            assert len(values) == len(times) * multiplier
            if target['path'] == 'rotation':
                rotations = values[1::3] if interpolation == 'CUBICSPLINE' else values
                quaternion_error = float(np.max(np.abs(np.linalg.norm(rotations, axis=1) - 1)))
                assert quaternion_error < 1e-4, ('Nonunit quaternion key', animation['name'], quaternion_error)
            min_time, max_time = min(min_time, float(times[0])), max(max_time, float(times[-1]))
            sampler_info[sampler_index] = {'keys': len(times), 'interpolation': interpolation}
        assert max_time > min_time, ('Clip has no duration', animation['name'])
        assert len(sampler_info) == len(samplers), ('Unused animation sampler', animation['name'])
        for sampler in animation['samplers']:
            sampler['input'] = copy_accessor(sampler['input'])
            sampler['output'] = copy_accessor(sampler['output'])
        doc['animations'].append(animation)
        clips.append({'id': animation['name'], 'start': min_time, 'duration': max_time,
                      'channels': len(channels), 'samplers': len(samplers),
                      'animated_bones': len(animated_bones), 'paths': sorted(paths),
                      'max_keys_per_sampler': max(s['keys'] for s in sampler_info.values()),
                      'interpolations': sorted({s['interpolation'] for s in sampler_info.values()})})

    # New animation views/accessors are append-only. All original definitions,
    # including per-part IBMs, and every original BIN byte must stay untouched.
    for key in base:
        if key in ('buffers', 'accessors', 'bufferViews'):
            continue
        assert doc[key] == base[key], ('Original asset definition changed', key)
    assert doc['accessors'][:len(base['accessors'])] == base['accessors']
    assert doc['bufferViews'][:len(base['bufferViews'])] == base['bufferViews']
    assert bytes(binary[:len(base_binary)]) == base_binary
    while len(binary) % 4:
        binary.append(0)
    doc['buffers'][0]['byteLength'] = len(binary)
    encoded = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    encoded += b' ' * (-len(encoded) % 4)
    result = struct.pack('<4sII', b'glTF', 2, 28 + len(encoded) + len(binary))
    result += struct.pack('<II', len(encoded), 0x4E4F534A) + encoded
    result += struct.pack('<II', len(binary), 0x004E4942) + binary
    assert base_path.read_bytes() == original_bytes, 'Bind asset changed during patch'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + '.patching')
    temporary.write_bytes(result)
    temporary.replace(output_path)
    return {'base_sha256': hashlib.sha256(original_bytes).hexdigest(),
            'export_sha256': export_sha256,
            'output_sha256': hashlib.sha256(result).hexdigest(),
            'original_binary_prefix_exact': True, 'original_asset_definitions_exact': True,
            'bones': len(joint_ids), 'meshes': len(base['meshes']), 'skins': len(base['skins']),
            'copied_animation_accessors': len(copied_accessors), 'copied_animation_views': len(copied_views),
            'clips': clips, 'output_bytes': len(result)}


if __name__ == '__main__':
    import sys
    print(json.dumps(patch(*sys.argv[1:4]), ensure_ascii=False, indent=2))
