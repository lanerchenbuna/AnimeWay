"""Exact-source continuity, reviewed ID migrations and retained deletion tombstones."""
from copy import deepcopy

from core.map_catalog import source_key


def reconcile_catalog(catalog: dict, previous: dict | None, review: dict | None = None) -> dict:
    current = deepcopy(catalog)
    if not previous:
        return current
    review = review or {}
    for key, ref in current['source_refs'].items():
        prior = previous['source_refs'].get(key, {})
        if ref.get('identity_kind') == 'editorial_mapping':
            for flag in ('superseded_by', 'upstream_removed'):
                if prior.get(flag):
                    ref[flag] = prior[flag]

    old_scene_map, new_scene_map = {}, {}
    for scene in previous['scenes'].values():
        for key in scene.get('source_ref_ids', []):
            old_scene_map.setdefault(key, []).append(scene)
    for scene in current['scenes'].values():
        for key in scene.get('source_ref_ids', []):
            new_scene_map.setdefault(key, []).append(scene)

    def preserve(old_key, new_key):
        if old_key not in previous['place_by_source'] or new_key not in current['place_by_source']:
            raise ValueError(f'Migration references missing source: {old_key} -> {new_key}')
        old_id = previous['place_by_source'][old_key]
        new_id = current['place_by_source'][new_key]
        if new_id != old_id:
            incoming = current['places'].pop(new_id)
            if old_id not in current['places']:
                current['places'][old_id] = {**incoming, 'id': old_id}
            for key, value in list(current['place_by_source'].items()):
                if value == new_id:
                    current['place_by_source'][key] = old_id
            for source in current['source_refs'].values():
                if source['location_id'] == new_id:
                    source['location_id'] = old_id
            for scene in current['scenes'].values():
                if scene['location_id'] == new_id:
                    scene['location_id'] = old_id
        old_scenes = old_scene_map.get(old_key, [])
        new_scenes = new_scene_map.get(new_key, [])
        if len(old_scenes) == len(new_scenes) == 1:
            old_scene, new_scene = old_scenes[0], new_scenes[0]
            if old_scene['id'] != new_scene['id']:
                current['scenes'].pop(new_scene['id'])
                replacement = current['scenes'].get(old_scene['id'], {**new_scene, 'id': old_scene['id']})
                replacement['source_ref_ids'] = sorted(set(replacement.get('source_ref_ids', []) + [new_key]))
                current['scenes'][old_scene['id']] = replacement
                new_scene_map[new_key] = [replacement]
        current['place_by_source'][old_key] = old_id
        if old_key != new_key:
            current['source_refs'][old_key] = {**deepcopy(previous['source_refs'][old_key]), 'superseded_by': new_key}

    # A known composite source key retains its already published Place/Scene IDs.
    for key in sorted(set(previous['source_refs']) & set(current['source_refs'])):
        preserve(key, key)
    for mapping in review.get('migrations', []):
        preserve(source_key(mapping['work_id'], mapping['old_id']), source_key(mapping['work_id'], mapping['new_id']))
    deleted_keys = {source_key(row['work_id'], row['point_id']) for row in review.get('deletions', [])}
    for key, source in previous['source_refs'].items():
        if key not in current['source_refs'] or key in deleted_keys:
            current['source_refs'][key] = {**deepcopy(source), 'upstream_removed': True}
            location_id = source['location_id']
            current['place_by_source'][key] = location_id
            current['places'].setdefault(location_id, deepcopy(previous['places'][location_id]))
            for scene in old_scene_map.get(key, []):
                scene_id = scene['id']
                if key in scene.get('source_ref_ids', []):
                    current['scenes'].setdefault(scene_id, deepcopy(scene))
                    current['scenes'][scene_id]['upstream_removed'] = True
    # Keep aliases from older migrations across repeated rebuilds.
    for key, location_id in previous['place_by_source'].items():
        if location_id in current['places']:
            current['place_by_source'].setdefault(key, location_id)
    active_places = {s['location_id'] for s in current['source_refs'].values()
                     if not s.get('upstream_removed') and not s.get('superseded_by')}
    for place_id, place in current['places'].items():
        if place_id not in active_places:
            place.update(withdrawn=True, upstream_removed=True)
        place['scene_ids'], place['anime_ids'] = [], []
    for work in current['works'].values():
        work['scene_ids'] = []
    for scene_id, scene in current['scenes'].items():
        refs = [current['source_refs'][key] for key in scene.get('source_ref_ids', [])]
        if refs and not any(not r.get('upstream_removed') and not r.get('superseded_by') for r in refs):
            scene['upstream_removed'] = True
        else:
            scene.pop('upstream_removed', None)
        work_id = scene['work_id']
        if work_id not in current['works']:
            current['works'][work_id] = deepcopy(previous['works'][work_id])
            current['works'][work_id]['scene_ids'] = []
        current['works'][work_id]['scene_ids'].append(scene_id)
        place = current['places'][scene['location_id']]
        place['scene_ids'].append(scene_id)
        if work_id not in place['anime_ids']:
            place['anime_ids'].append(work_id)
    return current
