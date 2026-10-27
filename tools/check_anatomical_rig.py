"""Round-trip geometry, skinning, finger isolation and visual rig acceptance.

blender --background --threads 4 --factory-startup --python tools/check_anatomical_rig.py
Only writes validation data and images under assets/renders/parts/anatomical.
"""
from pathlib import Path
import sys
import json
from math import radians

import bpy
import numpy as np
from mathutils import Vector, Quaternion, kdtree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import rig_util

MODELS = ROOT / 'assets/models/characters/parts'
SOURCE = MODELS / 'templar_tpose_unarmored_parts.glb'
OUTPUT = MODELS / 'templar_tpose_unarmored_parts_rig_anatomical.glb'
RENDERS = ROOT / 'assets/renders/parts/anatomical'
FINGERS = ['thumb', 'index', 'middle', 'ring', 'pinky']
TIP_XY = {'thumb': (.825, -.033), 'index': (.917, .025),
          'middle': (.925, .059), 'ring': (.916, .092), 'pinky': (.886, .119)}
COLORS = {'thumb': (1.0, .39, .05, 1), 'index': (.1, .6, 1, 1),
          'middle': (.08, .95, .5, 1), 'ring': (1, .20, .36, 1),
          'pinky': (.68, .28, 1, 1), 'hand': (1, .85, .16, 1)}


def coordinates(ob, evaluated=False):
    if evaluated:
        ob = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    arr = np.empty(len(ob.data.vertices) * 3, dtype=np.float64)
    ob.data.vertices.foreach_get('co', arr)
    matrix = np.asarray(ob.matrix_world)
    return arr.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]


def load(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path))
    # The glTF importer creates a mesh for bone display shapes in a hidden
    # collection; validate the sixteen named character parts only.
    return {o.name: o for o in bpy.context.scene.objects
            if o.type == 'MESH' and o.name.startswith('body_')}


def nearest_distances(a, b):
    tree = kdtree.KDTree(len(b))
    for i, p in enumerate(b):
        tree.insert(p, i)
    tree.balance()
    return np.array([tree.find(p)[2] for p in a])


def check_geometry(source, meshes):
    assert set(source) == set(meshes), 'Source and result part names differ'
    result = {}
    for name, p in source.items():
        q = coordinates(meshes[name], evaluated=True)
        assert len(p) == len(q), (name, len(p), len(q))
        distance = nearest_distances(p, q)
        assert distance.max() < 1e-5, (name, float(distance.max()))
        result[name] = {'vertices': len(p), 'max_rest_distance_m': float(distance.max()),
                        'rms_rest_distance_m': float(np.sqrt(np.mean(distance ** 2)))}
    return result


def check_weights(meshes, arm):
    result = {}
    for name, ob in meshes.items():
        names = {g.index: g.name for g in ob.vertex_groups}
        sums, counts = [], []
        for v in ob.data.vertices:
            groups = [g for g in v.groups if g.weight > 1e-8]
            assert all(names[g.group] in arm.data.bones for g in groups)
            sums.append(sum(g.weight for g in groups))
            counts.append(len(groups))
        assert min(sums) > .9999 and max(sums) < 1.0001, (name, min(sums), max(sums))
        assert min(counts) > 0 and max(counts) <= 4, (name, min(counts), max(counts))
        result[name] = {'weight_sum_min': min(sums), 'weight_sum_max': max(sums),
                        'max_influences': max(counts), 'unweighted_vertices': counts.count(0)}
    return result


def check_anatomy(arm):
    assert len(arm.data.bones) == 60, len(arm.data.bones)
    canonical = json.loads((RENDERS / 'binding_validation.json').read_text())['landmarks']
    report = {}
    for side in ['L', 'R']:
        assert f'thumb.03.{side}' not in arm.data.bones, 'Thumb must have two phalanges'
        hand = arm.data.bones[f'hand.{side}']
        assert hand.parent and hand.parent.name == f'forearm.{side}'
        side_report = {}
        for finger in FINGERS:
            count = 2 if finger == 'thumb' else 3
            base = arm.data.bones[f'{finger}.metacarpal.{side}']
            assert base.parent == hand, base.name
            chain = [base]
            for j in range(1, count + 1):
                bone = arm.data.bones[f'{finger}.{j:02d}.{side}']
                assert bone.parent == chain[-1], bone.name
                assert (bone.head_local - chain[-1].tail_local).length < 1e-5, bone.name
                assert bone.length > .005, bone.name
                chain.append(bone)
            path = np.asarray(canonical[side]['fingers'][finger])
            if finger != 'thumb':
                path = np.vstack([canonical[side]['metacarpal_bases'][finger], path])
            path[:, 0] *= 1 if side == 'L' else -1
            # glTF stores joint locations but no bone display tails. Check
            # actual joints, and report the authored distal length separately
            # from Blender's arbitrary inferred display tail.
            errors = [float(np.linalg.norm(np.asarray(b.head_local) - path[j]))
                      for j, b in enumerate(chain)]
            assert max(errors) < 1e-5, (side, finger, errors)
            side_report[finger] = {'segments': [b.name for b in chain],
                                   'lengths_m': np.linalg.norm(np.diff(path, axis=0), axis=1).tolist(),
                                   'max_joint_location_error_m': max(errors),
                                   'gltf_leaf_display_tail_is_inferred': True}
        report[side] = side_report
    return report


def check_opposition(arm, meshes, pose_hand):
    rig_util.reset_pose(arm)
    rest = {side: coordinates(meshes[f'body_hand.{side}'], True) for side in ['L', 'R']}
    pose_hand(arm, amount=1, opposition=True)
    report = {}
    for side in ['L', 'R']:
        moved = coordinates(meshes[f'body_hand.{side}'], True)
        mask = tip_mask(rest[side], side, 'thumb')
        before, after = rest[side][mask].mean(0), moved[mask].mean(0)
        delta = after - before
        report[side] = {'tip_rest_m': before.tolist(), 'tip_opposed_m': after.tolist(),
                        'tip_motion_m': float(np.linalg.norm(delta)),
                        'tip_delta_m': delta.tolist()}
        assert np.linalg.norm(delta) > .01, (side, 'Thumb did not oppose')
        assert delta[2] < -.005, (side, 'Thumb did not move towards palm')
    rig_util.reset_pose(arm)
    return report


def tip_mask(points, side, finger):
    p = points.copy()
    p[:, 0] *= 1 if side == 'L' else -1
    xy = np.asarray(TIP_XY[finger])
    return (np.linalg.norm(p[:, :2] - xy, axis=1) < .009) & (p[:, 0] > xy[0] - .008)


def check_isolation(arm, meshes):
    result = {}
    for side in ['L', 'R']:
        rig_util.reset_pose(arm)
        hand = meshes[f'body_hand.{side}']
        rest = coordinates(hand, True)
        pb = arm.pose.bones[f'index.01.{side}']
        pb.rotation_quaternion = Quaternion((1, 0, 0), -radians(35))
        bpy.context.view_layer.update()
        delta = coordinates(hand, True) - rest
        fingers = {}
        for finger in FINGERS:
            mask = tip_mask(rest, side, finger)
            assert mask.any(), (side, finger, 'No tip vertices')
            distances = np.linalg.norm(delta[mask], axis=1)
            fingers[finger] = {'tip_vertices': int(mask.sum()),
                               'max_motion_m': float(distances.max()),
                               'mean_motion_m': float(distances.mean()),
                               'mean_delta_z_m': float(delta[mask, 2].mean())}
            if finger == 'index':
                assert distances.mean() > .02, (side, 'Index did not curl')
                assert delta[mask, 2].mean() < -.015, (side, 'Index curl direction wrong')
            else:
                assert distances.max() < .0001, (side, finger, float(distances.max()))
        result[side] = fingers
    rig_util.reset_pose(arm)
    assert abs(result['L']['index']['mean_delta_z_m'] -
               result['R']['index']['mean_delta_z_m']) < .005, 'Mirrored curl differs'
    return result


def shared_seams(meshes):
    """Collect matching original positions across separate parts, excluding UV duplicates."""
    names = sorted(meshes)
    arrays = [coordinates(meshes[n]) for n in names]
    owner = np.concatenate([np.full(len(p), k, dtype=np.int16) for k, p in enumerate(arrays)])
    local = np.concatenate([np.arange(len(p)) for p in arrays])
    _, inverse = np.unique(np.round(np.concatenate(arrays), 5), axis=0, return_inverse=True)
    min_owner = np.full(int(inverse.max()) + 1, 32767, dtype=np.int16)
    max_owner = np.full(len(min_owner), -1, dtype=np.int16)
    np.minimum.at(min_owner, inverse, owner)
    np.maximum.at(max_owner, inverse, owner)
    keys = np.flatnonzero(min_owner != max_owner)
    mask = np.isin(inverse, keys)
    return names, owner[mask], local[mask], inverse[mask], len(keys)


def measure_seams(meshes, seams):
    names, owner, local, inverse, count = seams
    if count == 0:
        return {'shared_position_groups': 0, 'max_gap_m': None}
    posed = [coordinates(meshes[name], True) for name in names]
    positions = np.array([posed[int(o)][int(i)] for o, i in zip(owner, local)])
    _, compact = np.unique(inverse, return_inverse=True)
    lo = np.full((count, 3), np.inf)
    hi = np.full((count, 3), -np.inf)
    np.minimum.at(lo, compact, positions)
    np.maximum.at(hi, compact, positions)
    gap = np.linalg.norm(hi - lo, axis=1)
    return {'shared_position_groups': count, 'max_gap_m': float(gap.max()),
            'groups_above_0_1mm': int((gap > .0001).sum())}


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = color
    bsdf.inputs['Emission Color'].default_value = color
    bsdf.inputs['Emission Strength'].default_value = .5
    bsdf.inputs['Roughness'].default_value = .5
    return mat


def overlay(arm, side):
    """Raise bone rods to the dorsum only for explanatory render overlays."""
    objects = []
    mats = {f: material('guide_' + f, col) for f, col in COLORS.items()}
    canonical = json.loads((RENDERS / 'binding_validation.json').read_text())['landmarks'][side]
    for bone in arm.data.bones:
        if not bone.name.endswith('.' + side):
            continue
        finger = bone.name.split('.')[0]
        if finger not in COLORS:
            continue
        a, b = (arm.matrix_world @ bone.head_local), (arm.matrix_world @ bone.tail_local)
        terminal = bone.name in [f'thumb.02.{side}'] + [f'{f}.03.{side}' for f in FINGERS[1:]]
        if terminal:
            # The glTF format omits terminal display tails. Draw the true
            # authored fingertip, instead of the importer's guessed tail.
            b = Vector(canonical['fingers'][finger][-1])
            b.x *= 1 if side == 'L' else -1
        a.z += .038
        b.z += .038
        d = b - a
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=.0012,
                                            depth=d.length, location=(a + b) * .5)
        rod = bpy.context.object
        rod.rotation_euler = d.to_track_quat('Z', 'Y').to_euler()
        rod.data.materials.append(mats[finger])
        objects.append(rod)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=.0022, location=a)
        joint = bpy.context.object
        joint.data.materials.append(mats[finger])
        objects.append(joint)
        if terminal:
            bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=.0015, location=b)
            tip = bpy.context.object
            tip.data.materials.append(mats[finger])
            objects.append(tip)
    return objects


def shot(scene, cam, filename, location, target, scale, resolution=(1000, 850)):
    scene.render.resolution_x, scene.render.resolution_y = resolution
    rig_util.place_cam(scene, cam, location, target, scale)
    scene.render.filepath = str(RENDERS / filename)
    bpy.ops.render.render(write_still=True)


def render_checks(arm, meshes, pose_hand):
    scene, cam = rig_util.studio(res=(1000, 850))
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 12
    scene.cycles.use_denoising = True
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = 4
    rig_util.reset_pose(arm)
    for side in ['L', 'R']:
        sign = 1 if side == 'L' else -1
        target = Vector((sign * .826, .045, 1.471))
        if '--overlays-only' not in sys.argv:
            shot(scene, cam, f'rest_{side}.png', target + Vector((0, -.015, .65)), target, .255)
        guides = overlay(arm, side)
        shot(scene, cam, f'skeleton_{side}.png', target + Vector((0, 0, .65)), target, .255)
        for ob in guides:
            bpy.data.objects.remove(ob, do_unlink=True)
    if '--overlays-only' in sys.argv:
        return
    pose_hand(arm, amount=1, opposition=True)
    for side in ['L', 'R']:
        sign = 1 if side == 'L' else -1
        target = Vector((sign * .816, .05, 1.43))
        shot(scene, cam, f'grip_{side}_back.png',
             target + Vector((sign * .05, -.15, .55)), target, .27)
        shot(scene, cam, f'grip_{side}_palm.png',
             target + Vector((sign * .05, -.15, -.55)), target, .27)
    rig_util.reset_pose(arm)
    shot(scene, cam, 'fullbody_front.png', (2.4, -4.3, 1.5), (0, 0, .94),
         2.15, resolution=(1050, 1100))


def main():
    RENDERS.mkdir(parents=True, exist_ok=True)
    source_meshes = load(SOURCE)
    source = {name: coordinates(ob) for name, ob in source_meshes.items()}
    meshes = load(OUTPUT)
    arms = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    assert len(arms) == 1 and len(meshes) == 16, (len(arms), len(meshes))
    arm = arms[0]
    report = {'source': SOURCE.name, 'output': OUTPUT.name,
              'bones': len(arm.data.bones), 'mesh_parts': len(meshes),
              'rest_geometry': check_geometry(source, meshes),
              'weights': check_weights(meshes, arm), 'anatomy': check_anatomy(arm),
              'index_isolation': check_isolation(arm, meshes)}
    seams = shared_seams(meshes)
    report['seams_rest'] = measure_seams(meshes, seams)
    from rig_parts_anatomical import pose_hand
    report['thumb_opposition'] = check_opposition(arm, meshes, pose_hand)
    pose_hand(arm, amount=1, opposition=True)
    report['seams_grip'] = measure_seams(meshes, seams)
    rig_util.reset_pose(arm)
    # Test the wrist transition without recording or saving the test pose.
    for side in ['L', 'R']:
        pb = arm.pose.bones[f'hand.{side}']
        pb.rotation_quaternion = Quaternion((1, 0, 0), -radians(30))
    bpy.context.view_layer.update()
    report['seams_wrist'] = measure_seams(meshes, seams)
    rig_util.reset_pose(arm)
    import rig_parts
    for tag, pose in [('elbows', rig_parts.POSE_ARM), ('knee', rig_parts.POSE_KNEE)]:
        rig_util.apply_pose(arm, pose)
        report['seams_' + tag] = measure_seams(meshes, seams)
    rig_util.reset_pose(arm)
    (RENDERS / 'roundtrip_validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    for tag, data in report.items():
        if tag.startswith('seams_') and data['max_gap_m'] is not None:
            assert data['max_gap_m'] < .0001, (tag, data)
    print('ANATOMICAL_VALIDATION', json.dumps(report), flush=True)
    if '--no-render' not in sys.argv:
        render_checks(arm, meshes, pose_hand)


if __name__ == '__main__':
    main()
