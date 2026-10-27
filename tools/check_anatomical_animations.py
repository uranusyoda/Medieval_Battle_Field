"""Validate baked anatomical clips, authoring poses and representative renders.

blender --background --threads 4 --factory-startup --python tools/check_anatomical_animations.py
Pass --no-render for numerical QA, --renders-only to refresh the eight images.
Only writes assets/renders/parts/animated; source model files are read-only.
"""
from pathlib import Path
import sys
import json
import hashlib

import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from patch_anatomical_glb import read_glb, accessor
from check_anatomical_rig import coordinates, shared_seams, measure_seams
import rig_util

MODELS = ROOT / 'assets/models/characters/parts'
FULL = MODELS / 'templar_anatomical_animated.glb'
PREVIEW = MODELS / 'templar_anatomical_animated_preview.glb'
BLEND = MODELS / 'templar_anatomical_animated.blend'
SOURCE = MODELS / 'templar_tpose_unarmored_parts.glb'
BASE = MODELS / 'templar_tpose_unarmored_parts_rig_anatomical.glb'
MANIFEST = MODELS / 'templar_anatomical_animations.json'
RENDERS = ROOT / 'assets/renders/parts/animated'
CLIPS = ('idle', 'walk', 'run', 'jump', 'crouch', 'grip', 'finger_wave', 'wrist')
FRACTIONS = {'idle': .25, 'walk': .25, 'run': .25, 'jump': .39,
             'crouch': .5, 'grip': .5, 'finger_wave': .5, 'wrist': .25}
EXPECTED_MOVING = {
    'idle': ('spine', 'chest', 'neck', 'head'),
    'walk': ('thigh.L', 'thigh.R', 'shin.L', 'shin.R'),
    'run': ('thigh.L', 'thigh.R', 'shin.L', 'shin.R'),
    'jump': ('hips', 'root', 'thigh.L', 'thigh.R'),
    'crouch': ('thigh.L', 'thigh.R', 'shin.L', 'shin.R'),
    'grip': ('index.01.L', 'index.01.R', 'thumb.metacarpal.L', 'thumb.metacarpal.R'),
    'finger_wave': ('index.01.L', 'middle.01.L', 'ring.01.L', 'pinky.01.L'),
    'wrist': ('hand.L', 'hand.R'),
}


def log(*args):
    print('[ANIM_QA]', *args, flush=True)


def mesh_nodes(doc):
    return {n['name']: n for n in doc['nodes'] if 'mesh' in n}


def validate_assets():
    original, original_bin = read_glb(SOURCE)
    base, base_bin = read_glb(BASE)
    doc, binary = read_glb(FULL)
    preview, preview_bin = read_glb(PREVIEW)
    assert binary[:len(base_bin)] == base_bin, 'Full export changed base binary data'
    original_nodes, full_nodes = mesh_nodes(original), mesh_nodes(doc)
    assert set(original_nodes) == set(full_nodes) and len(full_nodes) == 16
    vertices, triangles = 0, 0
    weight_error, max_influences = 0., 0
    for name, old_node in original_nodes.items():
        node = full_nodes[name]
        for key in ('translation', 'rotation', 'scale', 'matrix'):
            assert old_node.get(key) == node.get(key), (name, key)
        old_mesh = original['meshes'][old_node['mesh']]
        mesh = doc['meshes'][node['mesh']]
        assert len(old_mesh['primitives']) == len(mesh['primitives'])
        for oldp, p in zip(old_mesh['primitives'], mesh['primitives']):
            for attribute, index in oldp['attributes'].items():
                assert attribute in p['attributes']
                assert np.array_equal(accessor(original, original_bin, index),
                                      accessor(doc, binary, p['attributes'][attribute])), (name, attribute)
            assert np.array_equal(accessor(original, original_bin, oldp['indices']),
                                  accessor(doc, binary, p['indices'])), (name, 'indices')
            n = doc['accessors'][p['attributes']['POSITION']]['count']
            vertices += n
            triangles += doc['accessors'][p['indices']]['count']//3
            total = np.zeros(n)
            influences = np.zeros(n, dtype=np.int16)
            for key, index in p['attributes'].items():
                if not key.startswith('WEIGHTS_'):
                    continue
                weights = accessor(doc, binary, index, normalized=True)
                jointkey = 'JOINTS_'+key[8:]
                joints = accessor(doc, binary, p['attributes'][jointkey])
                assert np.all(np.isfinite(weights)) and np.all(weights >= 0)
                assert np.all(joints < len(doc['skins'][node['skin']]['joints']))
                total += weights.sum(axis=1)
                influences += (weights > 1e-8).sum(axis=1)
            assert np.min(influences) > 0 and np.max(influences) <= 4, name
            weight_error = max(weight_error, float(np.max(np.abs(total-1))))
            max_influences = max(max_influences, int(influences.max()))
    assert weight_error < 1e-4
    for key in ('materials', 'textures', 'images', 'samplers'):
        assert doc.get(key) == original.get(key), key
    all_joints = {j for skin in doc['skins'] for j in skin['joints']}
    assert len(all_joints) == 60
    assert len(preview['meshes']) == 16
    preview_joint_names = {preview['nodes'][j]['name']
                           for s in preview['skins'] for j in s['joints']}
    assert len(preview_joint_names) == 60
    preview_tris = sum(preview['accessors'][p['indices']]['count']//3
                       for m in preview['meshes'] for p in m['primitives'])
    assert preview_tris < triangles, 'Web preview should reduce geometry'
    preview_weight_error = 0.
    preview_influences = 0
    for node in preview['nodes']:
        if 'mesh' not in node:
            continue
        for primitive in preview['meshes'][node['mesh']]['primitives']:
            attrs = primitive['attributes']
            n = preview['accessors'][attrs['POSITION']]['count']
            total, influences = np.zeros(n), np.zeros(n, dtype=np.int16)
            for key, index in attrs.items():
                if not key.startswith('WEIGHTS_'):
                    continue
                weights = accessor(preview, preview_bin, index, normalized=True)
                joints = accessor(preview, preview_bin, attrs['JOINTS_'+key[8:]])
                assert np.all(np.isfinite(weights)) and np.all(weights >= 0)
                assert np.all(joints < len(preview['skins'][node['skin']]['joints']))
                total += weights.sum(axis=1)
                influences += (weights > 1e-8).sum(axis=1)
            assert influences.min() > 0 and influences.max() <= 4
            preview_weight_error = max(preview_weight_error, float(np.max(np.abs(total-1))))
            preview_influences = max(preview_influences, int(influences.max()))
    assert preview_weight_error < 1e-4
    return {'full_sha256': hashlib.sha256(FULL.read_bytes()).hexdigest(),
            'preview_sha256': hashlib.sha256(PREVIEW.read_bytes()).hexdigest(),
            'original_geometry_normals_uv_indices_exact': True,
            'original_materials_textures_exact': True, 'base_binary_prefix_exact': True,
            'bones': len(all_joints), 'mesh_parts': len(full_nodes), 'vertices': vertices,
            'triangles': triangles, 'preview_triangles': preview_tris,
            'max_weight_sum_error': weight_error, 'max_skin_influences': max_influences,
            'preview_max_weight_sum_error': preview_weight_error,
            'preview_max_skin_influences': preview_influences}


def quaternion_motion(values):
    norm = np.linalg.norm(values, axis=1)
    assert np.max(np.abs(norm-1)) < 1e-3, 'Non-unit baked quaternion'
    q = values/np.maximum(norm[:, None], 1e-12)
    dots = np.abs(q @ q[0])
    return float(np.max(2*np.arccos(np.clip(dots, 0, 1))))


def validate_clips(path, manifest):
    doc, binary = read_glb(path)
    animations = {a['name']: a for a in doc.get('animations', [])}
    assert set(animations) == set(CLIPS), (path.name, sorted(animations))
    clips = {c['id']: c for c in manifest['clips']}
    report = {}
    for name in CLIPS:
        anim, meta = animations[name], clips[name]
        maximum, minimum = 0., np.inf
        moved = set()
        max_loop_error = 0.
        channels = []
        assert anim['channels'], name
        for channel in anim['channels']:
            sampler = anim['samplers'][channel['sampler']]
            interpolation = sampler.get('interpolation', 'LINEAR')
            assert interpolation in ('LINEAR', 'STEP', 'CUBICSPLINE')
            times = accessor(doc, binary, sampler['input']).ravel()
            values = accessor(doc, binary, sampler['output']).astype(float)
            assert np.all(np.isfinite(times)) and np.all(np.diff(times) > 0), name
            assert np.all(np.isfinite(values)), name
            assert len(times) >= 2 and times.min() >= -1e-6
            if interpolation == 'CUBICSPLINE':
                assert len(values) == len(times)*3
                values = values.reshape(len(times), 3, -1)[:, 1]
            else:
                assert len(values) == len(times), name
            target = channel['target']
            node = doc['nodes'][target['node']]['name']
            kind = target['path']
            assert kind in ('rotation', 'translation', 'scale'), (name, kind)
            if kind == 'rotation':
                motion = quaternion_motion(values)
                first, last = values[0], values[-1]
                loop_error = float(min(np.linalg.norm(first-last), np.linalg.norm(first+last)))
            else:
                motion = float(np.max(np.linalg.norm(values-values[0], axis=1)))
                loop_error = float(np.max(np.abs(values[0]-values[-1])))
            if motion > 1e-4:
                moved.add(node)
            if meta['loop']:
                assert loop_error < 2e-4, (name, node, kind, loop_error)
            max_loop_error = max(max_loop_error, loop_error)
            maximum = max(maximum, float(times[-1]))
            minimum = min(minimum, float(times[0]))
            channels.append({'node': node, 'path': kind, 'keys': len(times), 'motion': motion})
        expected = set(EXPECTED_MOVING[name])
        assert expected & moved, (name, 'Expected joints have no baked motion', sorted(moved))
        assert abs(maximum-float(meta['duration'])) < .05, (name, maximum, meta['duration'])
        report[name] = {'duration_s': maximum, 'start_time_s': minimum,
                        'channels': len(channels), 'moving_joints': sorted(moved),
                        'loop': meta['loop'], 'max_loop_endpoint_error': max_loop_error,
                        'key_count_max': max(c['keys'] for c in channels)}
    return report


def activate(arm, action):
    arm.animation_data_create()
    for track in arm.animation_data.nla_tracks:
        track.mute = True
    arm.animation_data.action = action
    if hasattr(action, 'slots') and action.slots:
        arm.animation_data.action_slot = action.slots[0]
    rig_util.reset_pose(arm)
    bpy.context.view_layer.update()


def foot_height(meshes):
    values = [coordinates(ob, True)[:, 2] for name, ob in meshes.items()
              if name.startswith('body_foot.')]
    return float(min(p.min() for p in values))


def check_blend_poses(arm, meshes):
    rig_util.reset_pose(arm)
    seams = shared_seams(meshes)
    report = {}
    for name in CLIPS:
        action = bpy.data.actions.get(name)
        assert action is not None, (name, 'Missing authoring action')
        activate(arm, action)
        start, end = map(float, action.frame_range)
        assert end > start
        frames = sorted(set([round(start+(end-start)*f, 3) for f in (0, .125, .25, .5, .75, .875, 1)]))
        samples = []
        for frame in frames:
            base = int(frame)
            bpy.context.scene.frame_set(base, subframe=frame-base)
            bpy.context.view_layer.update()
            seam = measure_seams(meshes, seams)
            assert seam['max_gap_m'] is None or seam['max_gap_m'] < .0001, (name, frame, seam)
            low = foot_height(meshes)
            assert low > -.012, (name, frame, 'Foot below floor', low)
            samples.append({'frame': frame, 'lowest_foot_m': low,
                            'max_seam_gap_m': seam['max_gap_m']})
        report[name] = {'frame_start': start, 'frame_end': end, 'samples': samples,
                        'lowest_foot_m': min(s['lowest_foot_m'] for s in samples),
                        'highest_lowest_foot_m': max(s['lowest_foot_m'] for s in samples),
                        'max_seam_gap_m': max(s['max_seam_gap_m'] or 0 for s in samples)}
        log(name, 'poses passed', 'feet', report[name]['lowest_foot_m'])
    return report


def render_checks(arm, meshes):
    scene, cam = rig_util.studio(res=(960, 1000))
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 16
    scene.cycles.use_denoising = True
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = 4
    if 'animation_qa_floor' not in bpy.data.objects:
        bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, -.004))
        floor = bpy.context.object
        floor.name = 'animation_qa_floor'
        mat = bpy.data.materials.new('animation_qa_floor')
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get('Principled BSDF')
        bsdf.inputs['Base Color'].default_value = (.32, .34, .35, 1)
        bsdf.inputs['Roughness'].default_value = .9
        floor.data.materials.append(mat)
    only = next((arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--clip=')), None)
    if only is not None:
        only = set(only.split(','))
        assert only <= set(CLIPS), only
    for name in CLIPS:
        if only is not None and name not in only:
            continue
        action = bpy.data.actions[name]
        activate(arm, action)
        start, end = action.frame_range
        frame = start+(end-start)*FRACTIONS[name]
        scene.frame_set(int(frame), subframe=frame-int(frame))
        bpy.context.view_layer.update()
        if name in ('grip', 'finger_wave', 'wrist'):
            p = coordinates(meshes['body_hand.L'], True)
            target = Vector((p.min(0)+p.max(0))/2)
            offset = Vector((.04, -.24, -.55))
            if name == 'wrist':
                offset = Vector((.04, -.34, .50))
            scale = max(.28, float(np.max(p.max(0)-p.min(0)))*1.35)
            scene.render.resolution_x, scene.render.resolution_y = 1050, 850
        else:
            scene.render.resolution_x, scene.render.resolution_y = 960, 1050
            target = Vector((0, 0, .98 if name != 'crouch' else .80))
            offset = Vector((2.6, -4.6, .65))
            scale = 2.25 if name != 'jump' else 2.55
            if name == 'jump':
                # Raised arms and airborne feet move beyond the standing
                # framing; fit the actual pose to keep fingertips visible.
                bounds = [coordinates(ob, True) for ob in meshes.values()]
                lowest = min(float(p[:, 2].min()) for p in bounds)
                highest = max(float(p[:, 2].max()) for p in bounds)
                target.z = (lowest+highest)*.5
                scale = max(2.55, (highest-lowest)*1.3)
        rig_util.place_cam(scene, cam, target+offset, target, scale)
        scene.render.filepath = str(RENDERS/(name+'.png'))
        bpy.ops.render.render(write_still=True)
        log('rendered', name, frame)


def main():
    RENDERS.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text())
    report = None
    if '--renders-only' not in sys.argv:
        report = {'assets': validate_assets(), 'full_clips': validate_clips(FULL, manifest),
                  'preview_clips': validate_clips(PREVIEW, manifest)}
    bpy.ops.wm.open_mainfile(filepath=str(BLEND))
    meshes = {o.name: o for o in bpy.context.scene.objects
              if o.type == 'MESH' and o.name.startswith('body_')}
    arms = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    assert len(meshes) == 16 and len(arms) == 1
    arm = arms[0]
    assert len(arm.data.bones) == 60
    if report is not None:
        report['authoring_poses'] = check_blend_poses(arm, meshes)
        (RENDERS/'validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        log('ALL NUMERIC CHECKS PASSED')
    if '--no-render' not in sys.argv:
        render_checks(arm, meshes)


if __name__ == '__main__':
    main()
