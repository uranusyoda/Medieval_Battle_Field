"""Bind the exact, unmodified parts GLB with an anatomical FK hand skeleton.

blender --background --threads 4 --python tools/rig_parts_anatomical.py
The source is never overwritten. Four fingers have metacarpals + 3 phalanges;
the thumb has a first metacarpal + 2 phalanges, with an opposition axis.
"""
from pathlib import Path
import sys
import json
import hashlib
from math import radians

import bpy
import numpy as np
from mathutils import Vector, Quaternion

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import rig_parts as body
from fix_parts_hand_rig import coords, smoothstep, project
import rig_util

NAME = 'templar_tpose_unarmored_parts_rig_anatomical'
MODELS = ROOT / 'assets/models/characters/parts'
SOURCE = MODELS / 'templar_tpose_unarmored_parts.glb'
RENDERS = ROOT / 'assets/renders/parts/anatomical'
FINGERS = ('index', 'middle', 'ring', 'pinky')
# Guides measured on the ORIGINAL spread hand, never on the older relaxed rig.
GUIDES = {
    'thumb': [(.774, .030), (.789, .006), (.807, -.019), (.825, -.033)],
    'index': [(.817, .034), (.858, .032), (.893, .028), (.917, .025)],
    'middle': [(.822, .061), (.869, .060), (.902, .059), (.925, .059)],
    'ring': [(.816, .087), (.860, .085), (.892, .089), (.916, .092)],
    'pinky': [(.807, .105), (.840, .110), (.868, .117), (.886, .119)],
}
MC_BASE = {'index': (.753, .043), 'middle': (.751, .060),
           'ring': (.749, .077), 'pinky': (.748, .092)}


def log(*args):
    print('[ANATOMICAL]', *args, flush=True)


def depth(p, xy, direction, lateral=.008):
    direction = np.asarray(direction, dtype=float)
    direction /= np.linalg.norm(direction)
    delta = p[:, :2] - xy
    band = p[(np.abs(delta @ direction) < .004) &
             (np.abs(delta[:, 0]*direction[1] - delta[:, 1]*direction[0]) < lateral)]
    assert len(band) > 5, (xy, len(band))
    return float(np.mean(np.quantile(band[:, 2], [.05, .95])))


def fit_hand(p):
    paths = {}
    for name, guide in GUIDES.items():
        guide = np.array(guide)
        paths[name] = np.array([[*xy, depth(p, xy, guide[min(i+1, 3)]-guide[max(0, i-1)])]
                               for i, xy in enumerate(guide)])
    bases = {f: np.array([*xy, depth(p, np.array(xy), (1, 0), lateral=.010)])
             for f, xy in MC_BASE.items()}
    return paths, bases


def build_armature():
    data = bpy.data.armatures.new(NAME)
    arm = bpy.data.objects.new(NAME, data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for name, head, tail, parent, connected in body.bone_table():
        if name.startswith('cape.') or name == 'sword':
            continue
        b = data.edit_bones.new(name)
        b.head, b.tail = head, tail
        if parent:
            b.parent = data.edit_bones[parent]
            b.use_connect = connected
        if name.startswith('hand.'):
            b.tail = ((1 if name.endswith('.L') else -1)*.804, .063, 1.473)
            b.align_roll(Vector((0, 0, 1)))
        b.use_deform = name != 'root'
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm


def add_hand(arm, side, paths, bases):
    sign = 1 if side == 'L' else -1
    def point(q):
        return Vector((q[0]*sign, q[1], q[2]))
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    bones = arm.data.edit_bones
    def new(name, a, b, parent, connected=False, thumb=False):
        bone = bones.new(f'{name}.{side}')
        bone.head, bone.tail = point(a), point(b)
        bone.parent = bones[f'{parent}.{side}']
        bone.use_connect = connected
        # The thumb's nail/hinge plane is oblique to the palm; its CMC also
        # retains a separate local Z opposition/adduction axis.
        bone.align_roll(Vector((0, -.40, .9165)) if thumb else Vector((0, 0, 1)))
    for finger in FINGERS:
        path = paths[finger]
        new(f'{finger}.metacarpal', bases[finger], path[0], 'hand')
        for j in range(3):
            new(f'{finger}.{j+1:02d}', path[j], path[j+1],
                f'{finger}.metacarpal' if j == 0 else f'{finger}.{j:02d}', True)
    path = paths['thumb']
    new('thumb.metacarpal', path[0], path[1], 'hand')
    new('thumb.01', path[1], path[2], 'thumb.metacarpal', True, True)
    new('thumb.02', path[2], path[3], 'thumb.01', True, True)
    bpy.ops.object.mode_set(mode='OBJECT')


def body_weights(ob, arm):
    name = ob.name.removeprefix('body_')
    names = body.ALLOW[name]
    p = coords(ob)
    distances = np.stack([body.seg_dist(p, arm.data.bones[n].head_local,
                                       arm.data.bones[n].tail_local) for n in names], axis=1)
    w = 1/(distances+.001)**4
    order = np.argsort(w, axis=1)
    np.put_along_axis(w, order[:, :max(0, len(names)-4)], 0, axis=1)
    w /= w.sum(1, keepdims=True)
    w[w < .012] = 0
    w /= w.sum(1, keepdims=True)
    if name.startswith('forearm.'):
        side = name[-1]
        x = p[:, 0]*(1 if side == 'L' else -1)
        mask = x >= .718
        w[mask] = 0
        t = smoothstep((x[mask]-.718)/.036)
        w[mask, names.index(f'forearm.{side}')] = 1-t
        w[mask, names.index(f'hand.{side}')] = t
    return names, w


def hand_weights(ob, side, p, paths):
    names = [f'forearm.{side}', f'hand.{side}']
    chains = {'thumb': ['thumb.metacarpal', 'thumb.01', 'thumb.02']}
    chains.update({f: [f'{f}.metacarpal']+[f'{f}.{j:02d}' for j in range(1, 4)]
                   for f in FINGERS})
    for chain in chains.values():
        names += [f'{n}.{side}' for n in chain]
    w = np.zeros((len(p), len(names)))
    plane = p*np.array([1, 1, 0])
    near = np.stack([project(plane, q*np.array([1, 1, 0]))[0]
                     for q in paths.values()], axis=1).argmin(1)
    for k, (finger, path) in enumerate(paths.items()):
        _, s, arc = project(p, path)
        mask = near == k
        start = smoothstep((s+.008)/.019)
        pip = smoothstep((s-arc[1]+.006)/.012)
        dip = smoothstep((s-arc[2]+.005)/.010)
        if finger == 'thumb':
            values = [start*(1-pip), start*pip*(1-dip), start*pip*dip]
            w[mask, 1] = (1-start)[mask]
        else:
            mc = smoothstep((p[:, 0]-.750)/.040)*.90
            values = [(1-start)*mc, start*(1-pip), start*pip*(1-dip), start*pip*dip]
            w[mask, 1] = ((1-start)*(1-mc))[mask]
        for n, values_ in zip(chains[finger], values):
            w[mask, names.index(f'{n}.{side}')] = values_[mask]
    # Smooth along actual skin adjacency, including duplicated UV vertices.
    # Finger gaps have no connecting edges, so nearby fingertips cannot share
    # influences through Euclidean proximity alone.
    _, inverse = np.unique(np.round(p, 6), axis=0, return_inverse=True)
    count = np.bincount(inverse)
    merged = np.zeros((len(count), len(names)))
    np.add.at(merged, inverse, w)
    merged /= count[:, None]
    edges = np.array([e.vertices[:] for e in ob.data.edges])
    edges = np.unique(np.sort(inverse[edges], axis=1), axis=0)
    edges = edges[edges[:, 0] != edges[:, 1]]
    degree = np.bincount(edges.ravel(), minlength=len(count))
    for _ in range(12):
        sums = np.zeros_like(merged)
        np.add.at(sums, edges[:, 0], merged[edges[:, 1]])
        np.add.at(sums, edges[:, 1], merged[edges[:, 0]])
        merged = .7*merged+.3*np.where(degree[:, None] > 0,
                                      sums/np.maximum(degree[:, None], 1), merged)
    w = merged[inverse]
    wrist = smoothstep((p[:, 0]-.718)/.036)
    w *= wrist[:, None]
    w[:, 0] = 1-wrist
    return names, w


def unify_seams(objs, weights, bone_names):
    points = np.concatenate([coords(o) for o in objs])
    _, inverse = np.unique(np.round(points, 5), axis=0, return_inverse=True)
    counts = np.bincount(inverse)
    duplicate = counts[inverse] > 1
    dup_ids = np.unique(inverse[duplicate])
    sums = np.zeros((len(dup_ids), len(bone_names)))
    offset = 0
    for ob in objs:
        names, w = weights[ob.name]
        ids = inverse[offset:offset+len(w)]
        sel = counts[ids] > 1
        rows = np.searchsorted(dup_ids, ids[sel])
        for k, name in enumerate(names):
            np.add.at(sums[:, bone_names.index(name)], rows, w[sel, k])
        offset += len(w)
    sums /= counts[dup_ids, None]
    offset = 0
    for ob in objs:
        names, w = weights[ob.name]
        ids = inverse[offset:offset+len(w)]
        sel = counts[ids] > 1
        shared = sums[np.searchsorted(dup_ids, ids[sel])]
        extra = [name for k, name in enumerate(bone_names)
                 if name not in names and np.any(shared[:, k] > 0)]
        if extra:
            w = np.pad(w, ((0, 0), (0, len(extra))))
            names = names+extra
        for k, name in enumerate(names):
            w[sel, k] = shared[:, bone_names.index(name)]
        weights[ob.name] = (names, w)
        offset += len(w)
    return int(len(dup_ids))


def write_weights(ob, names, w):
    w[w < .00015] = 0
    if len(names) > 4:
        np.put_along_axis(w, np.argsort(w, axis=1)[:, :-4], 0, axis=1)
    w /= w.sum(1, keepdims=True)
    for group in list(ob.vertex_groups):
        ob.vertex_groups.remove(group)
    for k, name in enumerate(names):
        levels = np.rint(w[:, k]*4095).astype(np.int32)
        if not levels.any():
            continue
        group = ob.vertex_groups.new(name=name)
        for value in np.unique(levels):
            if value:
                group.add(np.flatnonzero(levels == value).tolist(), float(value)/4095, 'REPLACE')
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.vertex_group_normalize_all(lock_active=False)


def configure_controls(arm):
    body_collection = arm.data.collections.new('Body')
    left = arm.data.collections.new('Hand L')
    right = arm.data.collections.new('Hand R')
    for bone in arm.data.bones:
        is_hand = any(bone.name.startswith(f+'.') for f in (*FINGERS, 'thumb'))
        (left if bone.name.endswith('.L') else right).assign(bone) if is_hand else body_collection.assign(bone)
        if is_hand:
            bone.color.palette = 'THEME04' if bone.name.endswith('.L') else 'THEME03'
        pb = arm.pose.bones[bone.name]
        pb.rotation_mode = 'XYZ'
        if not is_hand:
            continue
        # Keep the long axis locked against accidental axial twisting. MCPs
        # retain modest spreading, IP joints are pure hinges, CMC is free.
        pb.lock_location = (True, True, True)
        pb.lock_scale = (True, True, True)
        if bone.name.startswith('thumb.metacarpal'):
            pb['anatomy'] = 'First metacarpal; CMC opposition and abduction'
        elif '.metacarpal.' in bone.name:
            pb['anatomy'] = 'Metacarpal; palm arch / cupping'
            pb.lock_rotation = (False, True, False)
        else:
            phalanx = int(bone.name.split('.')[1])
            spread = phalanx == 1 and not bone.name.startswith('thumb.')
            pb.lock_rotation = (False, True, not spread)
            pb['anatomy'] = 'Phalanx; negative local X flexes towards palm'
    arm['hand_structure'] = 'Each side: 5 metacarpals + 14 phalanges; thumb has only 2 phalanges'
    arm['source'] = str(SOURCE.relative_to(ROOT))
    arm['posing'] = 'FK. Finger flexion: local -X. Spread: local Z. Thumb CMC: local Z opposition.'
    arm.show_in_front = True
    arm.data.display_type = 'OCTAHEDRAL'


def pose_hand(arm, amount=1.0, opposition=True):
    """A moderate grasp used for deformation QA, not an exported animation."""
    for side, sign in [('L', 1), ('R', -1)]:
        for finger in FINGERS:
            for j, angle in enumerate((48, 65, 38), 1):
                pb = arm.pose.bones[f'{finger}.{j:02d}.{side}']
                pb.rotation_mode = 'QUATERNION'
                pb.rotation_quaternion = Quaternion((1, 0, 0), -radians(angle*amount))
        mc = arm.pose.bones[f'thumb.metacarpal.{side}']
        mc.rotation_mode = 'QUATERNION'
        mc.rotation_quaternion = (Quaternion((1, 0, 0), -radians(18*amount)) @
                                  Quaternion((0, 0, 1), sign*radians((42 if opposition else 0)*amount)))
        for j, angle in enumerate((25, 30), 1):
            pb = arm.pose.bones[f'thumb.{j:02d}.{side}']
            pb.rotation_mode = 'QUATERNION'
            pb.rotation_quaternion = Quaternion((1, 0, 0), -radians(angle*amount))
    bpy.context.view_layer.update()


def main():
    RENDERS.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(SOURCE))
    objs = sorted((o for o in bpy.data.objects if o.type == 'MESH'), key=lambda o: o.name)
    assert len(objs) == 16
    original = {o.name: coords(o).copy() for o in objs}
    arm = build_armature()
    landmarks, weights = {}, {}
    for side, sign in [('L', 1), ('R', -1)]:
        ob = bpy.data.objects[f'body_hand.{side}']
        p = coords(ob)
        p[:, 0] *= sign
        paths, bases = fit_hand(p)
        add_hand(arm, side, paths, bases)
        weights[ob.name] = hand_weights(ob, side, p, paths)
        landmarks[side] = {'fingers': {f: q.tolist() for f, q in paths.items()},
                           'metacarpal_bases': {f: q.tolist() for f, q in bases.items()},
                           'coordinates': 'mirrored +X, Blender Z up'}
    assert len(arm.data.bones) == 60
    for ob in objs:
        if ob.name not in weights:
            weights[ob.name] = body_weights(ob, arm)
    shared = unify_seams(objs, weights, [b.name for b in arm.data.bones])
    report = {}
    for ob in objs:
        names, w = weights[ob.name]
        write_weights(ob, names, w)
        world = ob.matrix_world.copy()
        ob.parent = arm
        ob.matrix_world = world
        mod = ob.modifiers.new('Anatomical skin', 'ARMATURE')
        mod.object = arm
        # Linear blend skinning matches GLB runtime deformation.
        mod.use_deform_preserve_volume = False
        sums = np.array([sum(g.weight for g in v.groups) for v in ob.data.vertices])
        maxinf = max(sum(g.weight > 0 for g in v.groups) for v in ob.data.vertices)
        assert maxinf <= 4 and np.max(np.abs(sums-1)) < 1e-5
        assert np.array_equal(coords(ob), original[ob.name])
        report[ob.name] = {'vertices': len(sums), 'max_influences': maxinf,
                           'max_weight_sum_error': float(np.max(np.abs(sums-1)))}
        log('bound', ob.name, report[ob.name])
    configure_controls(arm)
    rig_util.reset_pose(arm)
    for pb in arm.pose.bones:
        pb.rotation_mode = 'XYZ'
    bpy.ops.object.select_all(action='DESELECT')
    for ob in objs+[arm]:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.context.scene.unit_settings.system = 'METRIC'
    # Give the editable document a useful initial framing and visible bones.
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                space = area.spaces.active
                space.clip_end = 100
                space.region_3d.view_location = (0, 0, .94)
                space.region_3d.view_distance = 2.9
                space.region_3d.view_rotation = Quaternion((1, 0, 0), radians(90))
                space.shading.type = 'MATERIAL'
    bpy.ops.wm.save_as_mainfile(filepath=str(MODELS/(NAME+'.blend')), compress=True)
    output = MODELS/(NAME+'.glb')
    bpy.ops.export_scene.gltf(filepath=str(output), export_format='GLB', use_selection=True,
        export_apply=False, export_skins=True, export_yup=True, export_animations=False,
        export_materials='EXPORT', export_texcoords=True, export_normals=True,
        export_all_influences=False)
    from patch_anatomical_glb import patch
    preservation = patch(SOURCE, output)
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == source_hash
    result = {'source_sha256': source_hash, 'bones': len(arm.data.bones), 'meshes': len(objs),
              'shared_seam_coordinates': shared, 'weights': report, 'landmarks': landmarks,
              'preservation': preservation}
    (RENDERS/'binding_validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    log('DONE', output)


if __name__ == '__main__':
    main()
