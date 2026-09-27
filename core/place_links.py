"""Current public facts for saved choices, without rewriting private history."""
from copy import deepcopy

BLOCKED_ACCESS = {'closed', 'prohibited', 'forbidden', 'no_entry'}


def blocked(place):
    return not place or bool(place.get('withdrawn')) or (place.get('access') or {}).get('status') in BLOCKED_ACCESS


def places(catalog):
    return {**catalog.get('resolved_locations', {}), **{p['id']: p for p in catalog['locations']}}


def resolve_saved(saved, catalog):
    current = places(catalog).get(saved['id'])
    if current is None:
        return {**deepcopy(saved), 'withdrawn': True, 'missing': True,
                'access': {**deepcopy(saved.get('access', {})), 'status': 'unknown', 'summary': '当前资料无法解析此地点，历史选择保留；导航暂停。历史说明：' + saved.get('access', {}).get('summary', '')}}
    result = deepcopy(saved)
    # Only current public facts replace saved facts. Choice/stay/required/reason
    # and execution timestamps remain the user's original decisions.
    for key in ('name', 'lat', 'lon', 'city', 'anime_ids', 'scene_ids', 'source_url',
                'source_version', 'access', 'entry', 'viewpoint', 'content_level'):
        result[key] = deepcopy(current.get(key, {} if key == 'access' else '' if key in {'entry', 'viewpoint'} else saved.get(key)))
    result.update(withdrawn=bool(current.get('withdrawn')), missing=False, resolved_id=current['id'],
                  facts_changed=saved.get('facts_changed', False) or any(saved.get(k) != current.get(k) for k in ('source_version', 'lat', 'lon', 'access', 'withdrawn')))
    return result


def trip_view(trip, catalog):
    result = deepcopy(trip)
    result['stops'] = [resolve_saved(s, catalog) for s in trip['stops']]
    if any(blocked(p) or any(p.get(k) != s.get(k) for k in ('lat', 'lon')) for p, s in zip(result['stops'], trip['stops'])):
        result.update(connection_status='needs_recheck')
    return result


def trip_eligible(place, catalog):
    # Full-library discoveries never become trusted Trip candidates just because
    # their coordinate happens to fall within Tokyo.
    return not blocked(place) and any(p['id'] == place['id'] and p.get('destination_id') for p in catalog['locations']) and 35.4 <= place['lat'] <= 35.9 and 139.3 <= place['lon'] <= 139.95


def current_catalog(service, baseline, extra_ids=()):
    """Overlay system withdrawals in one SQL read; hydrate only requested IDs."""
    catalog = deepcopy(baseline)
    with service._connect() as db:
        removed = {r[0] for r in db.execute('SELECT id FROM map_places WHERE upstream_removed=1')}
        removed_scenes = {r[0] for r in db.execute("SELECT id FROM map_scenes WHERE json_extract(data,'$.upstream_removed')=1")}
    for place in catalog['locations']:
        place['withdrawn'] = bool(place.get('withdrawn')) or place['id'] in removed
    for scene in catalog['scenes']:
        if scene['id'] in removed_scenes or scene['location_id'] in removed:
            scene['upstream_removed'] = True
            scene['media'] = {**scene.get('media', {}), 'display_allowed': False, 'url': ''}
    known = {p['id'] for p in catalog['locations']}
    catalog['resolved_locations'] = {}
    for location_id in sorted(set(extra_ids) - known):
        detail = service.get_place(location_id)
        if detail:
            catalog['resolved_locations'][location_id] = detail['place']
            known_scenes = {s['id'] for s in catalog['scenes']}
            catalog['scenes'].extend(s for s in detail['scenes'] if s['id'] not in known_scenes)
    return catalog


def map_trip_plan(location_id, start_date, day_count, catalog):
    from core.trip import empty_plan, new_requirements, stop_spec
    place = places(catalog).get(location_id)
    if not trip_eligible(place, catalog):
        raise ValueError('当前仅东京试点地点可加入 Trip；其他地点仍可收藏或补记到访。')
    plan = empty_plan(new_requirements(start_date, day_count, anime_ids=list(map(str, place['anime_ids']))[:3]))
    plan['days'][0]['stops'] = [stop_spec(location_id)]
    return plan
