"""Transfer repaired hand skin/bones while preserving original GLB asset bytes.

Blender round trips slightly quantize custom normals. This copies only the new
finger nodes, inverse bind matrices, and the four changed skin attribute pairs
into the original document, keeping geometry, materials, and textures exact.
"""
import copy
import json
import struct
from pathlib import Path
import numpy as np


def read_glb(path):
    raw = Path(path).read_bytes()
    magic, version, total = struct.unpack_from('<4sII', raw)
    assert magic == b'glTF' and version == 2 and total == len(raw)
    n = struct.unpack_from('<I', raw, 12)[0]
    return json.loads(raw[20:20+n]), raw[28+n:]


def accessor(doc, binary, index):
    a = doc['accessors'][index]
    v = doc['bufferViews'][a['bufferView']]
    dtype = {5126: '<f4', 5125: '<u4', 5123: '<u2', 5121: 'u1'}[a['componentType']]
    width = {'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'SCALAR': 1, 'MAT4': 16}[a['type']]
    item = np.dtype(dtype).itemsize
    return np.ndarray((a['count'], width), dtype=dtype, buffer=binary,
        offset=v.get('byteOffset', 0)+a.get('byteOffset', 0),
        strides=(v.get('byteStride', item*width), item)).copy()


def patch(original_path, exported_path):
    doc, binary = read_glb(original_path)
    fixed, fixed_binary = read_glb(exported_path)
    output = bytearray(binary)

    def append(data, component, typ):
        while len(output) % 4:
            output.append(0)
        view = len(doc['bufferViews'])
        doc['bufferViews'].append({'buffer': 0, 'byteOffset': len(output), 'byteLength': data.nbytes})
        output.extend(data.tobytes())
        index = len(doc['accessors'])
        doc['accessors'].append({'bufferView': view, 'componentType': component,
                                'count': len(data), 'type': typ})
        return index

    old_nodes = {n['name']: i for i, n in enumerate(doc['nodes'])}
    old_skin, new_skin = doc['skins'][0], fixed['skins'][0]
    new_node_to_old = {}
    new_bones = []
    for ni in new_skin['joints']:
        node = fixed['nodes'][ni]
        if node['name'] in old_nodes:
            new_node_to_old[ni] = old_nodes[node['name']]
        else:
            new_node_to_old[ni] = len(doc['nodes'])
            doc['nodes'].append(copy.deepcopy(node))
            new_bones.append(ni)
    assert len(new_bones) == 30
    new_set = set(new_bones)
    for ni in new_skin['joints']:
        oi = new_node_to_old[ni]
        children = fixed['nodes'][ni].get('children', [])
        if ni in new_set:
            doc['nodes'][oi]['children'] = [new_node_to_old[c] for c in children]
        else:
            additions = [new_node_to_old[c] for c in children if c in new_set]
            if additions:
                doc['nodes'][oi].setdefault('children', []).extend(additions)
    inverse_bind = accessor(doc, binary, old_skin['inverseBindMatrices'])
    new_inverse_bind = accessor(fixed, fixed_binary, new_skin['inverseBindMatrices'])
    rows = [new_skin['joints'].index(ni) for ni in new_bones]
    old_skin['joints'].extend(new_node_to_old[ni] for ni in new_bones)
    old_skin['inverseBindMatrices'] = append(np.concatenate([inverse_bind, new_inverse_bind[rows]]), 5126, 'MAT4')
    palette = np.array([old_skin['joints'].index(new_node_to_old[ni]) for ni in new_skin['joints']], dtype='<u2')
    fixed_meshes = {n['name']: fixed['meshes'][n['mesh']] for n in fixed['nodes'] if 'mesh' in n}
    for node in doc['nodes']:
        if 'mesh' not in node:
            continue
        if not any(tag in node['name'] for tag in ('body_hand.', 'body_forearm.')):
            continue
        oldmesh = doc['meshes'][node['mesh']]
        newmesh = fixed_meshes[node['name']]
        assert len(oldmesh['primitives']) == len(newmesh['primitives'])
        for op, np_ in zip(oldmesh['primitives'], newmesh['primitives']):
            # Transferring weights requires an identical vertex and face order.
            for attr in ['POSITION', 'TEXCOORD_0']:
                a = accessor(doc, binary, op['attributes'][attr])
                b = accessor(fixed, fixed_binary, np_['attributes'][attr])
                assert a.shape == b.shape and np.allclose(a, b, atol=2e-6), (node['name'], attr)
            assert np.array_equal(accessor(doc, binary, op['indices']),
                                  accessor(fixed, fixed_binary, np_['indices']))
            if any(tag in node['name'] for tag in ('body_hand.', 'body_forearm.')):
                joints = accessor(fixed, fixed_binary, np_['attributes']['JOINTS_0'])
                weights = accessor(fixed, fixed_binary, np_['attributes']['WEIGHTS_0'])
                op['attributes']['JOINTS_0'] = append(palette[joints], 5123, 'VEC4')
                op['attributes']['WEIGHTS_0'] = append(weights.astype('<f4'), 5126, 'VEC4')
    while len(output) % 4:
        output.append(0)
    doc['buffers'][0]['byteLength'] = len(output)
    data = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    data += b' ' * (-len(data) % 4)
    result = struct.pack('<4sII', b'glTF', 2, 28+len(data)+len(output))
    result += struct.pack('<II', len(data), 0x4E4F534A)+data
    result += struct.pack('<II', len(output), 0x004E4942)+output
    Path(exported_path).write_bytes(result)


if __name__ == '__main__':
    import sys
    patch(sys.argv[1], sys.argv[2])
