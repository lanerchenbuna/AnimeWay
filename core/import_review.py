"""Read-only import review. Import writes still use existing strict validators."""
from core.place_links import places, blocked


def review_backup(store, token, raw, catalog, *, journal=False, resolver=None):
    validated = (store.import_journal if journal else store.import_backup)(token, raw, preview=True)
    refs, snapshots = set(), {}
    def walk(value):
        if isinstance(value, dict):
            if value.get('location_id'):
                refs.add(value['location_id'])
            if {'id', 'lat', 'lon', 'name'} <= value.keys():
                refs.add(value['id'])
                snapshots[value['id']] = value
            for key, item in value.items():
                if key in {'must_ids', 'excluded_ids'}:
                    refs.update(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(validated)
    current = places(catalog)
    scenes = {s["id"]: s for s in catalog.get("scenes", [])}
    rows = []
    for lid in sorted(refs):
        point = current.get(lid)
        if point is None and resolver:
            detail = resolver(lid)
            point = detail['place'] if detail else None
            if detail:
                scenes.update({s['id']: s for s in detail['scenes']})
        old = snapshots.get(lid)
        changes = [k for k in ('name', 'lat', 'lon', 'access') if old and point and old.get(k) != point.get(k)]
        rows.append({'id': lid, 'current_id': point['id'] if point else None,
                     'name': point['name'] if point else (old or {}).get('name', lid),
                     'status': 'missing' if point is None else 'blocked' if blocked(point) else 'changed' if changes else 'current',
                     'changed_fields': changes})
    wish = {p['id']: p for p in store.list_wishlist(token)} if not journal else {}
    conflicts = [p['id'] for p in validated.get('wishlist', []) if p['id'] in wish and p != wish[p['id']]]
    entries = {e['id']: e for e in validated.get('entries', [])}
    invalid_pairs = [p['id'] for p in validated.get('photos', []) if p.get('scene_id') and
                     (p['scene_id'] not in scenes or scenes[p['scene_id']]['location_id'] != entries[p['entry_id']]['location_id'])]
    return {'digest': validated['digest'], 'already_imported': validated['already_imported'],
            'locations': rows, 'wishlist_conflicts_preserved': sorted(conflicts),
            'scene_pairs_unresolved': invalid_pairs,
            'copies': len(validated.get('trips', [])) + len(validated.get('personal_trips', [])),
            'entries': len(validated.get('entries', [])), 'photos': len(validated.get('photos', []))}
