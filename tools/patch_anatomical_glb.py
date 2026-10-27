"""Add an exported anatomical rig without round-tripping source geometry.

Blender can bake part translations into exported positions.  Each original
part therefore receives its own skin with inverse bind matrices adjusted from
the exported mesh coordinate system to that part's original coordinates.
All original geometry, normals, UVs, materials, textures, and part transforms
remain byte-for-byte or JSON-value identical to the unrigged source.
"""
from __future__ import annotations

import copy
import hashlib
import json
import struct
from pathlib import Path

import numpy as np


_DTYPES = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2",
           5125: "<u4", 5126: "<f4"}
_WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
           "MAT2": 4, "MAT3": 9, "MAT4": 16}


def read_glb(path):
    raw = Path(path).read_bytes()
    magic, version, total = struct.unpack_from("<4sII", raw)
    assert magic == b"glTF" and version == 2 and total == len(raw), path
    chunks, offset = {}, 12
    while offset < len(raw):
        length, kind = struct.unpack_from("<II", raw, offset)
        offset += 8
        assert offset + length <= len(raw)
        assert kind not in chunks, "Duplicate GLB chunk"
        chunks[kind] = raw[offset:offset + length]
        offset += length
    assert offset == len(raw)
    assert set(chunks) == {0x4E4F534A, 0x004E4942}, "Expected JSON and BIN chunks"
    return json.loads(chunks[0x4E4F534A]), chunks[0x004E4942]


def accessor(doc, binary, index, *, normalized=False):
    a = doc["accessors"][index]
    assert "sparse" not in a, "Sparse accessors need explicit expansion"
    view = doc["bufferViews"][a["bufferView"]]
    assert view.get("buffer", 0) == 0
    dtype = np.dtype(_DTYPES[a["componentType"]])
    width = _WIDTHS[a["type"]]
    result = np.ndarray(
        (a["count"], width), dtype=dtype, buffer=binary,
        offset=view.get("byteOffset", 0) + a.get("byteOffset", 0),
        strides=(view.get("byteStride", dtype.itemsize * width), dtype.itemsize),
    ).copy()
    if normalized and a.get("normalized", False):
        assert a["componentType"] != 5126
        result = result.astype(np.float64) / np.iinfo(dtype).max
        if np.issubdtype(dtype, np.signedinteger):
            result = np.maximum(result, -1)
    return result


def node_matrix(node):
    if "matrix" in node:
        return np.asarray(node["matrix"], dtype=np.float64).reshape(4, 4).T
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    rotation = np.array([
        [1 - 2*y*y - 2*z*z, 2*x*y - 2*z*w, 2*x*z + 2*y*w],
        [2*x*y + 2*z*w, 1 - 2*x*x - 2*z*z, 2*y*z - 2*x*w],
        [2*x*z - 2*y*w, 2*y*z + 2*x*w, 1 - 2*x*x - 2*y*y],
    ])
    matrix = np.eye(4)
    matrix[:3, :3] = rotation @ np.diag(node.get("scale", [1, 1, 1]))
    matrix[:3, 3] = node.get("translation", [0, 0, 0])
    return matrix


def world_matrices(doc):
    nodes = doc["nodes"]
    parents = {}
    for parent, node in enumerate(nodes):
        for child in node.get("children", []):
            assert child not in parents, "A node has multiple parents"
            parents[child] = parent
    cache, visiting = {}, set()

    def world(index):
        if index in cache:
            return cache[index]
        assert index not in visiting, "Cyclic node hierarchy"
        visiting.add(index)
        value = node_matrix(nodes[index])
        if index in parents:
            value = world(parents[index]) @ value
        visiting.remove(index)
        cache[index] = value
        return value

    for index in range(len(nodes)):
        world(index)
    return cache, parents


def transform_positions(points, matrix):
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def patch(original_path, exported_path):
    """Replace exported_path with the preserved source plus its new rig.

    Raises before writing if topology, vertex order, UVs, rest geometry, or skin
    data differ unexpectedly.  Returns a JSON-serializable validation report.
    """
    original_path, exported_path = Path(original_path), Path(exported_path)
    assert original_path.resolve() != exported_path.resolve()
    source_raw = original_path.read_bytes()
    original, original_binary = read_glb(original_path)
    exported, exported_binary = read_glb(exported_path)
    assert not original.get("skins"), "Source must be the unrigged original"
    assert exported.get("skins"), "Export has no skin"
    for document in (original, exported):
        assert len(document["buffers"]) == 1 and "uri" not in document["buffers"][0]
    doc = copy.deepcopy(original)
    output = bytearray(original_binary)
    original_world, _ = world_matrices(original)
    exported_world, exported_parents = world_matrices(exported)

    def append(data, component, typ, *, normalized=False, target=None):
        data = np.ascontiguousarray(data, dtype=_DTYPES[component])
        while len(output) % 4:
            output.append(0)
        view_index = len(doc["bufferViews"])
        view = {"buffer": 0, "byteOffset": len(output), "byteLength": data.nbytes}
        if target is not None:
            view["target"] = target
        doc["bufferViews"].append(view)
        output.extend(data.tobytes())
        index = len(doc["accessors"])
        value = {"bufferView": view_index, "componentType": component,
                 "count": len(data), "type": typ}
        if normalized:
            value["normalized"] = True
        doc["accessors"].append(value)
        return index

    # Include every exported joint and its complete transform ancestry.  Mesh
    # children stay in the original scene at their original part transforms.
    skeleton_nodes = set()
    for skin in exported["skins"]:
        for start in skin["joints"] + ([skin["skeleton"]] if "skeleton" in skin else []):
            current = start
            while current not in skeleton_nodes:
                skeleton_nodes.add(current)
                if current not in exported_parents:
                    break
                current = exported_parents[current]
    mapping = {index: len(doc["nodes"]) + offset
               for offset, index in enumerate(sorted(skeleton_nodes))}
    for index in sorted(skeleton_nodes):
        node = copy.deepcopy(exported["nodes"][index])
        for key in ("mesh", "skin", "camera", "weights"):
            node.pop(key, None)
        if "children" in node:
            children = [mapping[c] for c in node["children"] if c in mapping]
            if children:
                node["children"] = children
            else:
                node.pop("children")
        doc["nodes"].append(node)
    roots = [mapping[n] for n in sorted(skeleton_nodes) if exported_parents.get(n) not in mapping]
    assert roots, "No skeleton scene root"
    for scene in doc["scenes"]:
        scene.setdefault("nodes", []).extend(roots)

    exported_meshes = {}
    for index, node in enumerate(exported["nodes"]):
        if "mesh" in node:
            name = node.get("name")
            assert name and name not in exported_meshes, "Ambiguous exported part name"
            exported_meshes[name] = index
    doc["skins"] = []
    max_position_error = 0.0
    max_rest_skin_error = 0.0
    reports = {}
    copied_joint_sets = set()
    for original_index, source_node in enumerate(original["nodes"]):
        if "mesh" not in source_node:
            continue
        name = source_node["name"]
        assert name in exported_meshes, (name, "Missing exported part")
        exported_index = exported_meshes[name]
        exported_node = exported["nodes"][exported_index]
        assert "skin" in exported_node, (name, "Missing exported part skin")
        skin = exported["skins"][exported_node["skin"]]
        joint_ids = skin["joints"]
        copied_joint_sets.add(tuple(joint_ids))
        if "inverseBindMatrices" in skin:
            inverse_bind = accessor(exported, exported_binary, skin["inverseBindMatrices"])
            inverse_bind = inverse_bind.reshape(-1, 4, 4).transpose(0, 2, 1).astype(np.float64)
        else:
            inverse_bind = np.repeat(np.eye(4)[None], len(joint_ids), axis=0)
        assert len(inverse_bind) == len(joint_ids)
        # p_export = to_export @ p_source, including Blender's baked translations.
        to_export = np.linalg.inv(exported_world[exported_index]) @ original_world[original_index]
        adjusted_bind = inverse_bind @ to_export
        bind_index = append(adjusted_bind.transpose(0, 2, 1).reshape(-1, 16), 5126, "MAT4")
        new_skin = {"name": f"{name}.anatomical_skin", "joints": [mapping[j] for j in joint_ids],
                    "inverseBindMatrices": bind_index}
        if "skeleton" in skin:
            new_skin["skeleton"] = mapping[skin["skeleton"]]
        doc["nodes"][original_index]["skin"] = len(doc["skins"])
        doc["skins"].append(new_skin)

        source_mesh = original["meshes"][source_node["mesh"]]
        export_mesh = exported["meshes"][exported_node["mesh"]]
        destination_mesh = doc["meshes"][source_node["mesh"]]
        assert len(source_mesh["primitives"]) == len(export_mesh["primitives"]), name
        vertices, exported_vertices, max_influences = 0, 0, 0
        split_vertices, max_split_weight_error = 0, 0.0
        sum_min, sum_max = float("inf"), 0.0
        part_position_error, part_rest_error = 0.0, 0.0
        # Validate against the float32 bind matrices that will actually be saved.
        rest_matrices = np.stack([exported_world[j] for j in joint_ids]) @ adjusted_bind.astype("<f4").astype(np.float64)
        for source_primitive, export_primitive, dest_primitive in zip(
                source_mesh["primitives"], export_mesh["primitives"], destination_mesh["primitives"]):
            old_attrs, new_attrs = source_primitive["attributes"], export_primitive["attributes"]
            old_position = accessor(original, original_binary, old_attrs["POSITION"])
            new_position = accessor(exported, exported_binary, new_attrs["POSITION"])
            assert source_primitive.get("mode", 4) == export_primitive.get("mode", 4) == 4, name
            old_indices = accessor(original, original_binary, source_primitive["indices"]).ravel()
            new_indices = accessor(exported, exported_binary, export_primitive["indices"]).ravel()
            assert old_indices.shape == new_indices.shape, (name, "Triangle corner count")
            assert len(old_indices) % 3 == 0
            assert np.all(old_indices < len(old_position)) and np.all(new_indices < len(new_position))
            # Blender may split vertices at custom-normal discontinuities.  The
            # original triangle corners retain their order, so use those corners
            # to recover a mapping while keeping the source topology untouched.
            lookup = np.full(len(old_position), -1, dtype=np.int64)
            lookup[old_indices] = new_indices
            assert np.all(lookup >= 0), (name, "Unused original vertex cannot be mapped")
            expected_position = transform_positions(old_position, to_export)
            error = float(np.max(np.abs(expected_position[old_indices] - new_position[new_indices])))
            assert error <= 2e-6, (name, "POSITION differs", error)
            part_position_error = max(part_position_error, error)
            for attr in old_attrs:
                if not attr.startswith("TEXCOORD_"):
                    continue
                assert attr in new_attrs, (name, attr)
                old_uv = accessor(original, original_binary, old_attrs[attr])
                new_uv = accessor(exported, exported_binary, new_attrs[attr])
                assert old_uv.shape[1:] == new_uv.shape[1:] and np.allclose(
                    old_uv[old_indices], new_uv[new_indices], atol=2e-6, rtol=0), (name, attr)

            sets = sorted(k[7:] for k in new_attrs if k.startswith("JOINTS_"))
            assert sets and set(sets) == {k[8:] for k in new_attrs if k.startswith("WEIGHTS_")}, name
            exported_skin = {}
            for number in sets:
                joints = accessor(exported, exported_binary, new_attrs[f"JOINTS_{number}"])
                weights = accessor(exported, exported_binary, new_attrs[f"WEIGHTS_{number}"], normalized=True)
                assert joints.shape == weights.shape == (len(new_position), 4), name
                assert np.all(joints < len(joint_ids)) and np.all(weights >= 0), name
                assert np.all(np.isfinite(weights)), name
                exported_skin[number] = (joints, weights)

            # A source vertex can occur as several exported normal splits.  Its
            # effective weight per joint must agree before collapsing those
            # copies back to the original vertex.  Compare bone contributions,
            # allowing exporter slot reordering and zero-weight joint padding.
            different = new_indices != lookup[old_indices]
            alternatives = np.unique(np.column_stack([
                old_indices[different], new_indices[different]]), axis=0)
            if len(alternatives):
                def palette_rows(indices):
                    values = np.zeros((len(indices), len(joint_ids)))
                    rows = np.repeat(np.arange(len(indices)), 4)
                    for joints, weights in exported_skin.values():
                        np.add.at(values, (rows, joints[indices].ravel()), weights[indices].ravel())
                    return values

                weight_error = float(np.max(np.abs(
                    palette_rows(lookup[alternatives[:, 0]]) - palette_rows(alternatives[:, 1]))))
                assert weight_error <= 2e-6, (name, "Normal-split skin weights differ", weight_error)
                max_split_weight_error = max(max_split_weight_error, weight_error)
                split_vertices += len(alternatives)
            weight_sum = np.zeros(len(old_position))
            influences = np.zeros(len(old_position), dtype=np.int32)
            rest_points = np.zeros((len(old_position), 3))
            homogeneous = np.column_stack([old_position, np.ones(len(old_position))])
            for number in sets:
                ja, wa = f"JOINTS_{number}", f"WEIGHTS_{number}"
                export_joints, export_weights = exported_skin[number]
                joints, weights = export_joints[lookup], export_weights[lookup]
                for attribute in (ja, wa):
                    definition = exported["accessors"][new_attrs[attribute]]
                    values = accessor(exported, exported_binary, new_attrs[attribute])[lookup]
                    dest_primitive["attributes"][attribute] = append(
                        values, definition["componentType"], definition["type"],
                        normalized=definition.get("normalized", False), target=34962)
                weight_sum += weights.sum(axis=1)
                influences += (weights > 0).sum(axis=1)
                for column in range(4):
                    posed = np.einsum("nij,nj->ni", rest_matrices[joints[:, column]], homogeneous)
                    rest_points += weights[:, column, None] * posed[:, :3]
            assert np.all(np.abs(weight_sum - 1) < 1e-4), (name, "Non-normalized skin")
            assert np.max(influences) <= 4, (name, "More than four skin influences")
            expected_world = transform_positions(old_position, original_world[original_index])
            rest_error = float(np.max(np.abs(rest_points - expected_world)))
            assert rest_error < 1e-5, (name, "Rest skin deformation", rest_error)
            part_rest_error = max(part_rest_error, rest_error)
            sum_min, sum_max = min(sum_min, float(weight_sum.min())), max(sum_max, float(weight_sum.max()))
            max_influences = max(max_influences, int(influences.max()))
            vertices += len(old_position)
            exported_vertices += len(new_position)
        reports[name] = {"vertices": vertices, "exported_vertices": exported_vertices,
                         "normal_split_alternatives": split_vertices,
                         "max_normal_split_weight_error": max_split_weight_error,
                         "max_influences": max_influences,
                         "weight_sum_min": sum_min, "weight_sum_max": sum_max,
                         "max_position_export_error": part_position_error,
                         "max_rest_skin_error": part_rest_error}
        max_position_error = max(max_position_error, part_position_error)
        max_rest_skin_error = max(max_rest_skin_error, part_rest_error)

    assert len(reports) == 16, ("Expected 16 original parts", len(reports))
    # These definitions and every original binary byte must remain untouched.
    for key in ("materials", "textures", "images", "samplers"):
        assert doc.get(key) == original.get(key), key
    for index, node in enumerate(original["nodes"]):
        patched = {k: v for k, v in doc["nodes"][index].items() if k != "skin"}
        assert patched == node, (node.get("name"), "Original part transform changed")
    for mesh, source_mesh in zip(doc["meshes"], original["meshes"]):
        restored = copy.deepcopy(mesh)
        for primitive in restored["primitives"]:
            primitive["attributes"] = {k: v for k, v in primitive["attributes"].items()
                                       if not k.startswith(("JOINTS_", "WEIGHTS_"))}
        assert restored == source_mesh, "Original mesh definition changed"
    assert output[:len(original_binary)] == original_binary
    while len(output) % 4:
        output.append(0)
    doc["buffers"][0]["byteLength"] = len(output)
    data = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    data += b" " * (-len(data) % 4)
    result = struct.pack("<4sII", b"glTF", 2, 28 + len(data) + len(output))
    result += struct.pack("<II", len(data), 0x4E4F534A) + data
    result += struct.pack("<II", len(output), 0x004E4942) + output
    assert original_path.read_bytes() == source_raw, "Source changed during patch"
    # Atomic replacement also leaves the Blender export intact on failed checks.
    temp = exported_path.with_suffix(exported_path.suffix + ".patching")
    temp.write_bytes(result)
    temp.replace(exported_path)
    return {
        "source_sha256": hashlib.sha256(source_raw).hexdigest(),
        "output_sha256": hashlib.sha256(result).hexdigest(),
        "original_binary_sha256": hashlib.sha256(original_binary).hexdigest(),
        "original_binary_prefix_exact": True,
        "geometry_normals_uv_indices_exact": True,
        "materials_textures_exact": True,
        "original_part_transforms_exact": True,
        "parts": len(reports), "skins": len(doc["skins"]),
        "joint_counts": sorted({len(j) for j in copied_joint_sets}),
        "max_position_export_error": max_position_error,
        "max_rest_skin_error": max_rest_skin_error,
        "weights": reports,
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(patch(sys.argv[1], sys.argv[2]), indent=2))
