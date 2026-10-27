"""Transfer corrected garment weights without rewriting the preserved geometry.

The corrected bind asset is reconstructed with patch_anatomical_glb first,
so both inputs use the original vertex order, geometry and UV seams.
"""
from pathlib import Path
import json
import struct

import numpy as np

from patch_anatomical_glb import read_glb, accessor


def patch_animation_skin(animated_path, corrected_bind_path, parts):
    path = Path(animated_path)
    document, original = read_glb(path)
    corrected, source = read_glb(corrected_bind_path)
    binary = bytearray(original)
    source_nodes = {node['name']: node for node in corrected['nodes'] if 'mesh' in node}
    report = {}

    def append(values, component, dtype):
        values = np.ascontiguousarray(values, dtype=dtype)
        binary.extend(b'\0'*(-len(binary)%4))
        view = len(document['bufferViews'])
        document['bufferViews'].append(dict(buffer=0, byteOffset=len(binary),
                                          byteLength=values.nbytes, target=34962))
        binary.extend(values.tobytes())
        index = len(document['accessors'])
        document['accessors'].append(dict(bufferView=view, componentType=component,
                                         count=len(values), type='VEC4'))
        return index

    for node in document['nodes']:
        if node.get('name') not in parts or 'mesh' not in node:
            continue
        name = node['name']
        other = source_nodes[name]
        old_skin, new_skin = document['skins'][node['skin']], corrected['skins'][other['skin']]
        old_names = [document['nodes'][j]['name'] for j in old_skin['joints']]
        new_names = [corrected['nodes'][j]['name'] for j in new_skin['joints']]
        assert set(old_names) == set(new_names)
        remap = np.array([old_names.index(n) for n in new_names], dtype=np.uint16)
        meshes = document['meshes'][node['mesh']]['primitives']
        others = corrected['meshes'][other['mesh']]['primitives']
        assert len(meshes) == len(others)
        changed_count = 0
        for primitive, new_primitive in zip(meshes, others):
            attrs, new_attrs = primitive['attributes'], new_primitive['attributes']
            for key in ('POSITION', 'NORMAL', 'TEXCOORD_0'):
                assert np.array_equal(accessor(document, original, attrs[key]),
                                      accessor(corrected, source, new_attrs[key])), (name, key)
            assert np.array_equal(accessor(document, original, primitive['indices']),
                                  accessor(corrected, source, new_primitive['indices']))
            joints = accessor(document, original, attrs['JOINTS_0']).astype(np.uint16)
            weights = accessor(document, original, attrs['WEIGHTS_0'], normalized=True).astype(np.float32)
            new_joints = remap[accessor(corrected, source, new_attrs['JOINTS_0']).astype(int)]
            new_weights = accessor(corrected, source, new_attrs['WEIGHTS_0'], normalized=True).astype(np.float32)
            assert joints.shape == new_joints.shape == weights.shape == new_weights.shape
            before = np.zeros((len(joints), len(old_names)), dtype=np.float32)
            after = np.zeros_like(before)
            rows = np.arange(len(joints))[:, None]
            np.add.at(before, (rows, joints), weights)
            np.add.at(after, (rows, new_joints), new_weights)
            changed = np.max(np.abs(after-before), axis=1) > 1e-5
            joints[changed], weights[changed] = new_joints[changed], new_weights[changed]
            assert np.max(np.abs(weights.sum(1)-1)) < 1e-4
            if np.any(changed):
                attrs['JOINTS_0'] = append(joints, 5123, '<u2')
                attrs['WEIGHTS_0'] = append(weights, 5126, '<f4')
            changed_count += int(changed.sum())
        report[name] = changed_count

    binary.extend(b'\0'*(-len(binary)%4))
    document['buffers'][0]['byteLength'] = len(binary)
    encoded = json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode('utf8')
    encoded += b' '*(-len(encoded)%4)
    output = struct.pack('<4sII', b'glTF', 2, 28+len(encoded)+len(binary))
    output += struct.pack('<II', len(encoded), 0x4E4F534A)+encoded
    output += struct.pack('<II', len(binary), 0x004E4942)+binary
    temporary = path.with_suffix('.skin-patching')
    temporary.write_bytes(output)
    temporary.replace(path)
    return dict(changed_vertices=report, original_binary_prefix_exact=True,
                original_geometry_materials_exact=True)
