"""Repair hands on the supplied parts GLB; write a separate GLB and editable blend.

blender --background --threads 4 --python tools/fix_parts_hand_rig.py
The original GLB is the source of truth. No mesh geometry is relaxed or rebuilt.
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
import rig_util

NAME = 'templar_tpose_unarmored_parts_rig_handfix'
MODELS = ROOT / 'assets/models/characters/parts'
RENDERS = ROOT / 'assets/renders/parts/handfix'
SOURCE = MODELS / 'templar_tpose_unarmored_parts_rig.glb'
FINGERS = {
    'thumb': [(0.774, .030), (.789, .006), (.807, -.019), (.826, -.034)],
    'index': [(.817, .038), (.858, .047), (.893, .063), (.919, .067)],
    'middle': [(.822, .066), (.863, .079), (.897, .096), (.921, .100)],
    'ring': [(.816, .091), (.849, .099), (.878, .121), (.898, .126)],
    'pinky': [(.807, .111), (.831, .125), (.851, .139), (.864, .139)],
}


def coords(ob):
    p = np.empty(len(ob.data.vertices) * 3)
    ob.data.vertices.foreach_get('co', p)
    m = np.array(ob.matrix_world)
    return p.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]


def smoothstep(x):
    t = np.clip(x, 0, 1)
    return t*t*(3-2*t)


def fit_paths(p):
    """Fit depth to each hand's actual skin, using paired surface quantiles.

    XY guides follow the existing, already relaxed fingers. Using both depth
    extremes avoids bias from unequal tessellation on the palm and dorsum.
    """
    paths = {}
    for name, guide in FINGERS.items():
        q = np.array(guide)
        result = []
        for j, xy in enumerate(q):
            direction = q[min(j+1, 3)] - q[max(j-1, 0)]
            direction /= np.linalg.norm(direction)
            delta = p[:, :2] - xy
            axial = delta @ direction
            lateral = np.abs(delta[:, 0]*direction[1] - delta[:, 1]*direction[0])
            region = p[(np.abs(axial) < .004) & (lateral < .010)]
            assert len(region) > 5, (name, j, len(region))
            z = float(np.mean(np.quantile(region[:, 2], [.05, .95])))
            result.append([*xy, z])
        paths[name] = np.array(result)
    return paths


def project(p, path):
    a, d = path[:-1], np.diff(path, axis=0)
    length = np.linalg.norm(d, axis=1)
    t = np.einsum('nsi,si->ns', p[:, None, :] - a, d) / length**2
    tc = np.clip(t, 0, 1)
    closest = a + tc[:, :, None]*d
    dist = np.linalg.norm(p[:, None, :] - closest, axis=2)
    seg = dist.argmin(1)
    rows = np.arange(len(p))
    # Allow a signed extension at the first joint for the palm blend.
    tt = tc[rows, seg]
    tt = np.where((seg == 0) & (t[:, 0] < 0), t[:, 0], tt)
    arc = np.r_[0, np.cumsum(length)]
    return dist[rows, seg], arc[seg] + tt*length[seg], arc


def add_fingers(arm, side, paths):
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.data.edit_bones
    for finger, path in paths.items():
        for j in range(3):
            b = eb.new(f'{finger}.{j+1:02d}.{side}')
            b.head, b.tail = Vector(path[j]), Vector(path[j+1])
            b.parent = eb[f'hand.{side}' if j == 0 else f'{finger}.{j:02d}.{side}']
            b.use_connect = j > 0
            # Local X is the flexion axis, local Z points out of the dorsum.
            b.align_roll(Vector((0, 0, 1)))
    bpy.ops.object.mode_set(mode='OBJECT')


def set_weights(ob, names, weights):
    for g in list(ob.vertex_groups):
        ob.vertex_groups.remove(g)
    weights[weights < .0001] = 0
    # Keep the four strongest influences for standard realtime skinning.
    order = np.argsort(weights, axis=1)[:, :-4]
    np.put_along_axis(weights, order, 0, axis=1)
    weights /= weights.sum(1, keepdims=True)
    for k, name in enumerate(names):
        group = ob.vertex_groups.new(name=name)
        # 16-bit quantization keeps batch assignment fast and errors negligible.
        levels = np.rint(weights[:, k]*65535).astype(np.int32)
        for level in np.unique(levels):
            if level:
                group.add(np.flatnonzero(levels == level).tolist(), float(level)/65535, 'REPLACE')
    # Correct the final quantization residual exactly.
    for v in ob.data.vertices:
        total = sum(g.weight for g in v.groups)
        if total and abs(total-1) > 1e-7:
            for g in v.groups:
                ob.vertex_groups[g.group].add([v.index], g.weight/total, 'REPLACE')


def skin_hand(ob, side, p, paths):
    names = [f'forearm.{side}', f'hand.{side}']
    for f in FINGERS:
        names += [f'{f}.{j:02d}.{side}' for j in range(1, 4)]
    w = np.zeros((len(p), len(names)))
    projections = [project(p, path) for path in paths.values()]
    # Anatomical chains separate close fingers; surface adjacency below smooths
    # only across connected skin, so weights do not jump across finger gaps.
    planar = p.copy()
    planar[:, 2] = 0
    planar_paths = {n: q*np.array([1, 1, 0]) for n, q in paths.items()}
    nearest = np.stack([project(planar, q)[0] for q in planar_paths.values()], axis=1).argmin(1)
    for k, (distance, s, arc) in enumerate(projections):
        mask = nearest == k
        start = smoothstep((s+.010)/.023)
        pip = smoothstep((s-arc[1]+.007)/.014)
        dip = smoothstep((s-arc[2]+.006)/.012)
        w[mask, 1] = (1-start)[mask]
        w[mask, 2+k*3] = (start*(1-pip))[mask]
        w[mask, 3+k*3] = (start*pip*(1-dip))[mask]
        w[mask, 4+k*3] = (start*pip*dip)[mask]
    # Weld UV duplicates for weight smoothing, without touching exported geometry.
    _, inverse = np.unique(np.round(p, 6), axis=0, return_inverse=True)
    count = np.bincount(inverse)
    merged = np.zeros((len(count), len(names)))
    np.add.at(merged, inverse, w)
    merged /= count[:, None]
    edges = np.array([e.vertices[:] for e in ob.data.edges])
    edges = np.unique(np.sort(inverse[edges], axis=1), axis=0)
    edges = edges[edges[:, 0] != edges[:, 1]]
    degree = np.bincount(edges.ravel(), minlength=len(count))
    for _ in range(28):
        sums = np.zeros_like(merged)
        np.add.at(sums, edges[:, 0], merged[edges[:, 1]])
        np.add.at(sums, edges[:, 1], merged[edges[:, 0]])
        avg = sums / np.maximum(degree[:, None], 1)
        merged = .65*merged + .35*np.where(degree[:, None] > 0, avg, merged)
    w = merged[inverse]
    wrist = smoothstep((p[:, 0]-.718)/.036)
    w *= wrist[:, None]
    w[:, 0] = 1-wrist
    set_weights(ob, names, w)


def skin_forearm(ob, side):
    p = coords(ob)
    x = p[:, 0] * (1 if side == 'L' else -1)
    wrist = smoothstep((x-.718)/.036)
    # Only the last 3.6 cm at the wrist changes; retain the elbow weights exactly.
    names = [f'forearm.{side}', f'hand.{side}']
    groups = {n: ob.vertex_groups.get(n) or ob.vertex_groups.new(name=n) for n in names}
    for vi in np.flatnonzero(x > .718):
        for gi in [g.group for g in ob.data.vertices[int(vi)].groups]:
            ob.vertex_groups[gi].remove([int(vi)])
        for n, val in zip(names, (1-wrist[vi], wrist[vi])):
            if val > 1e-7:
                groups[n].add([int(vi)], float(val), 'REPLACE')
    return int((x > .718).sum())


def validate(objs):
    report = {}
    for ob in objs:
        if not any(t in ob.name for t in ('body_hand.', 'body_forearm.')):
            continue
        sums = [sum(g.weight for g in v.groups) for v in ob.data.vertices]
        maxinf = max(sum(g.weight > 0 for g in v.groups) for v in ob.data.vertices)
        assert min(sums) > .9999 and max(sums) < 1.0001, (ob.name, min(sums), max(sums))
        assert maxinf <= 4
        report[ob.name] = {'vertices': len(sums), 'weight_sum_min': min(sums),
                           'weight_sum_max': max(sums), 'max_influences': maxinf}
    return report


def pose_fingers(arm, amount=1):
    for side in ['L', 'R']:
        for name in FINGERS:
            angles = (18, 30, 22) if name == 'thumb' else (48, 62, 38)
            for j, angle in enumerate(angles, 1):
                pb = arm.pose.bones[f'{name}.{j:02d}.{side}']
                pb.rotation_mode = 'QUATERNION'
                pb.rotation_quaternion = Quaternion((1, 0, 0), -radians(angle*amount))
    bpy.context.view_layer.update()


def render_checks(arm):
    sc, cam = rig_util.studio(res=(960, 800))
    sc.render.engine = 'CYCLES'
    sc.cycles.samples = 20
    sc.cycles.use_denoising = True
    for tag in ['rest', 'grip', 'wrist']:
        rig_util.reset_pose(arm)
        if tag == 'grip':
            pose_fingers(arm)
        if tag == 'wrist':
            for side in ['L', 'R']:
                pb = arm.pose.bones[f'hand.{side}']
                axis = pb.bone.matrix_local.to_3x3().inverted() @ Vector((0, 1, 0))
                pb.rotation_quaternion = Quaternion(axis, radians(-35 if side == 'L' else 35))
        bpy.context.view_layer.update()
        for side in ['L', 'R']:
            s = 1 if side == 'L' else -1
            target = Vector((s*.823, .054, 1.467))
            rig_util.place_cam(sc, cam, target + Vector((s*.04, -.12, .65)), target, .30)
            sc.render.filepath = str(RENDERS / f'{tag}_{side}.png')
            bpy.ops.render.render(write_still=True)
    rig_util.reset_pose(arm)


def main():
    RENDERS.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(SOURCE))
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    for ob in list(bpy.data.objects):
        if ob.type == 'MESH' and not ob.name.startswith('body_'):
            bpy.data.objects.remove(ob, do_unlink=True)
    objs = [o for o in bpy.data.objects if o.type == 'MESH']
    landmarks = {}
    for side in ['L', 'R']:
        hand = bpy.data.objects[f'body_hand.{side}']
        p = coords(hand)
        p[:, 0] *= 1 if side == 'L' else -1
        local_paths = fit_paths(p)
        paths = {n: q*np.array([1 if side == 'L' else -1, 1, 1]) for n, q in local_paths.items()}
        add_fingers(arm, side, paths)
        skin_hand(hand, side, p, local_paths)
        skin_forearm(bpy.data.objects[f'body_forearm.{side}'], side)
        landmarks[side] = {n: q.tolist() for n, q in paths.items()}
    report = validate(objs)
    rig_util.reset_pose(arm)
    arm.show_in_front = True
    arm.data.display_type = 'OCTAHEDRAL'
    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True)
    for ob in objs:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.wm.save_as_mainfile(filepath=str(MODELS / (NAME+'.blend')), compress=True)
    bpy.ops.export_scene.gltf(filepath=str(MODELS / (NAME+'.glb')), export_format='GLB',
        use_selection=True, export_apply=False, export_skins=True, export_yup=True,
        export_animations=False, export_materials='EXPORT', export_texcoords=True,
        export_normals=True, export_all_influences=False)
    from patch_parts_hand_glb import patch
    patch(SOURCE, MODELS / (NAME+'.glb'))
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == source_hash
    results = {'source_sha256': source_hash, 'bones': len(arm.data.bones),
               'meshes': len(objs), 'weights': report, 'landmarks': landmarks}
    (RENDERS / 'validation.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    render_checks(arm)
    print('HAND_FIX_DONE', json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
