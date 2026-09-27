"""Bounded public map/list queries. No private data or remote image fetching."""
import json
import math
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from core.pilot import load_pilot
from core.public_snapshot import resolve_snapshot
from data_factory.normalization import extract_lat_lon

MAX_FEATURES = 500
FILTER_KEYS = {'city', 'destination_id', 'content_levels', 'access_statuses', 'include_withdrawn'}


def _bounds(bbox):
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError('bbox must be west,south,east,north')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bbox):
        raise ValueError('bbox must contain finite numbers')
    west, south, east, north = bbox
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= north <= 90):
        raise ValueError('bbox out of range')
    return west, south, east, north


def _inside(lat, lon, box):
    west, south, east, north = box
    return south <= lat <= north and ((west <= lon <= east) if west <= east else (lon >= west or lon <= east))


def _feature(place):
    return {'id': place['id'], 'name': place['name'], 'lat': place['lat'], 'lon': place['lon'],
            'city': place.get('city'), 'destination_id': place.get('destination_id'),
            'content_level': place.get('content_level', 'basic'),
            'access_status': place.get('access', {}).get('status', 'unknown'),
            'geography_status': place.get('geography', {}).get('status', 'unknown'),
            'withdrawn': bool(place.get('withdrawn')), 'work_ids': sorted(set(map(str, place.get('anime_ids', []))))}


class MapQueryService:
    def __init__(self, db_path: str, editorial_provider=None):
        self.db_path = str(Path(db_path).resolve())
        self.editorial_provider = editorial_provider
        with self._connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='map_schema_version'").fetchone()
            if not row or json.loads(row[0]) != 1:
                raise ValueError('Map index missing; build a Stage 2 snapshot first')

    @classmethod
    def from_snapshot(cls, root, editorial_provider=load_pilot):
        selected = resolve_snapshot(root)
        service = cls(selected['db_path'], editorial_provider)
        service.snapshot = selected
        return service

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(Path(self.db_path).as_uri() + '?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        try:
            yield db
        finally:
            db.close()

    def _editorial(self):
        # Call once per operation: content changes/withdrawals are never cached.
        return deepcopy(self.editorial_provider()) if self.editorial_provider else None

    @staticmethod
    def _filters(filters):
        if filters is not None and not isinstance(filters, dict):
            raise ValueError('filters must be an object')
        filters = dict(filters or {})
        if set(filters) - FILTER_KEYS:
            raise ValueError('Unknown map filter')
        for key in ('content_levels', 'access_statuses'):
            if key in filters and (not isinstance(filters[key], (list, tuple)) or len(filters[key]) > 20 or any(not isinstance(v, str) or len(v) > 100 for v in filters[key])):
                raise ValueError(f'{key} must be a bounded list')
        if 'include_withdrawn' in filters and not isinstance(filters['include_withdrawn'], bool):
            raise ValueError('include_withdrawn must be boolean')
        for key in ('city', 'destination_id'):
            if key in filters and (not isinstance(filters[key], str) or len(filters[key]) > 200):
                raise ValueError(f'Invalid {key}')
        return filters

    def query_places(self, bbox, zoom, work_ids=None, filters=None, limit=500):
        box = _bounds(bbox)
        if isinstance(zoom, bool) or not isinstance(zoom, (int, float)) or not math.isfinite(zoom) or not 0 <= zoom <= 24:
            raise ValueError('zoom must be between 0 and 24')
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_FEATURES:
            raise ValueError('limit must be between 1 and 500')
        if work_ids is not None and (not isinstance(work_ids, (list, tuple)) or len(work_ids) > 100):
            raise ValueError('work_ids must contain at most 100 IDs')
        if work_ids is not None and any(isinstance(v, bool) or not str(v).isdigit() or len(str(v)) > 20 for v in work_ids):
            raise ValueError('work_ids must contain numeric source IDs')
        wanted = None if work_ids is None else {str(value) for value in work_ids}
        filters = self._filters(filters)
        overlay = self._editorial()
        west, south, east, north = box
        conditions = ['b.max_lat>=?', 'b.min_lat<=?', 'p.lat>=?', 'p.lat<=?']
        params = [south, north, south, north]
        if west <= east:
            conditions += ['b.max_lon>=?', 'b.min_lon<=?', 'p.lon>=?', 'p.lon<=?']
            params += [west, east, west, east]
        else:
            conditions += ['(b.max_lon>=? OR b.min_lon<=?)', '(p.lon>=? OR p.lon<=?)']
            params += [west, east, west, east]
        if not filters.get('include_withdrawn', False):
            conditions.append('p.withdrawn=0')
        if wanted is not None:
            if wanted:
                conditions.append('p.id IN (SELECT location_id FROM map_scenes WHERE work_id IN (' + ','.join('?' for _ in wanted) + '))')
                params += sorted(wanted)
            else:
                conditions.append('0')
        for key, column in [('city', 'city')]:
            if key in filters:
                conditions.append(f'p.{column}=?')
                params.append(filters[key])
        for key, column in [('content_levels', 'level'), ('access_statuses', 'access')]:
            if key in filters:
                values = filters[key]
                conditions.append(f'p.{column} IN (' + ','.join('?' for _ in values) + ')' if values else '0')
                params += list(values)
        overlay_points = []
        with self._connect() as db:
            destinations = None
            if 'destination_id' in filters:
                definitions = overlay.get('destinations', []) if overlay is not None else [json.loads(r[0]) for r in db.execute('SELECT data FROM map_destinations')]
                destinations = {filters['destination_id']}
                while True:
                    children = {d['id'] for d in definitions if d.get('parent_id') in destinations}
                    if children <= destinations:
                        break
                    destinations |= children
                conditions.append('p.destination IN (' + ','.join('?' for _ in destinations) + ')')
                params += sorted(destinations)
            if overlay is not None:
                locations = overlay.get('locations', [])
                if len(locations) > 1000:
                    raise ValueError('Live editorial overlay exceeds 1000 places; rebuild the spatial index')
                conditions.append('p.editorial=0')
                if locations:
                    conditions.append('p.id NOT IN (' + ','.join('?' for _ in locations) + ')')
                    params += [p['id'] for p in locations]
                removed = {row[0] for row in db.execute('SELECT id FROM map_places WHERE upstream_removed=1')}
                for place in locations:
                    lat, lon = extract_lat_lon(place)
                    if lat is None or lon is None or not _inside(lat, lon, box):
                        continue
                    feature = _feature(place)
                    feature['withdrawn'] |= place['id'] in removed
                    if ((wanted is None or wanted.intersection(feature['work_ids']))
                        and (filters.get('include_withdrawn', False) or not feature['withdrawn'])
                        and ('city' not in filters or feature['city'] == filters['city'])
                        and (destinations is None or feature['destination_id'] in destinations)
                        and ('content_levels' not in filters or feature['content_level'] in filters['content_levels'])
                        and ('access_statuses' not in filters or feature['access_status'] in filters['access_statuses'])):
                        overlay_points.append(feature)
            query = ' FROM map_bounds b JOIN map_places p ON p.row_id=b.row_id WHERE ' + ' AND '.join(conditions)
            total = db.execute('SELECT count(*)' + query, params).fetchone()[0] + len(overlay_points)
            if total > limit or (zoom < 8 and total > 1):
                # Aggregate in SQLite. Only bounded groups leave the DB, even for
                # a world view. Overlay facts join the same grid and filter rules.
                cell = max(0.01, 360 / 2 ** min(zoom + 2, 18))
                lon_expr = f'(CASE WHEN p.lon<{float(west)!r} THEN p.lon+360 ELSE p.lon END)' if west > east else 'p.lon'
                while True:
                    rows = db.execute(
                        f'SELECT CAST(({lon_expr}+180)/? AS INTEGER) x, CAST((p.lat+90)/? AS INTEGER) y, '
                        f'count(*) n,sum(p.lat) lat_sum,sum({lon_expr}) lon_sum, min(p.lat) south,max(p.lat) north,min({lon_expr}) west,max({lon_expr}) east' + query +
                        ' GROUP BY x,y LIMIT ?', [cell, cell, *params, limit + 1]).fetchall()
                    if len(rows) > limit:
                        cell *= 2
                        continue
                    cells = {(r['x'], r['y']): [r['n'], r['lat_sum'], r['lon_sum'], r['west'], r['south'], r['east'], r['north']] for r in rows}
                    for point in overlay_points:
                        lon = point['lon'] + (360 if west > east and point['lon'] < west else 0)
                        key = (math.floor((lon + 180) / cell), math.floor((point['lat'] + 90) / cell))
                        sums = cells.setdefault(key, [0, 0.0, 0.0, lon, point['lat'], lon, point['lat']])
                        sums[0] += 1
                        sums[1] += point['lat']
                        sums[2] += lon
                        sums[3] = min(sums[3], lon)
                        sums[4] = min(sums[4], point['lat'])
                        sums[5] = max(sums[5], lon)
                        sums[6] = max(sums[6], point['lat'])
                    if len(cells) <= limit:
                        break
                    cell *= 2
                clusters = [{'id': f'{cell:g}:{x}:{y}', 'count': values[0], 'lat': values[1] / values[0],
                             'lon': ((values[2] / values[0] + 180) % 360) - 180,
                             'extent': [{'lon': ((values[3]+180)%360)-180, 'lat': values[4]},
                                        {'lon': ((values[5]+180)%360)-180, 'lat': values[6]}]}
                            for (x, y), values in sorted(cells.items())]
                return {'mode': 'clusters', 'total': total, 'features': [], 'clusters': clusters,
                        'requires_zoom': True, 'limit': limit}
            rows = db.execute('SELECT p.id,p.name,p.lat,p.lon,p.city,p.destination,p.level,p.access,p.geography,p.withdrawn, '
                              '(SELECT group_concat(DISTINCT work_id) FROM map_scenes s WHERE s.location_id=p.id) works' +
                              query + ' ORDER BY p.id LIMIT ?', [*params, limit]).fetchall()
            points = [{'id': r['id'], 'name': r['name'], 'lat': r['lat'], 'lon': r['lon'], 'city': r['city'],
                       'destination_id': r['destination'], 'content_level': r['level'], 'access_status': r['access'],
                       'withdrawn': bool(r['withdrawn']), 'geography_status': r['geography'], 'work_ids': (r['works'] or '').split(',') if r['works'] else []}
                      for r in rows] + overlay_points
            for point in points:
                point['work_count'] = len(point['work_ids'])
            return {'mode': 'points', 'total': total, 'features': sorted(points, key=lambda p: p['id']),
                    'clusters': [], 'requires_zoom': False, 'limit': limit}

    def list_places(self, bbox, zoom, work_ids=None, filters=None, limit=500):
        """Same bounded result/filter semantics for text fallback and map."""
        return self.query_places(bbox, zoom, work_ids, filters, limit)

    def get_place(self, location_id: str):
        overlay = self._editorial()
        with self._connect() as db:
            row = db.execute('SELECT data,editorial FROM map_places WHERE id=?', (location_id,)).fetchone()
            if row is None:
                alias = db.execute('SELECT location_id FROM map_aliases WHERE id=?', (location_id,)).fetchone()
                if alias:
                    location_id = alias[0]
                    row = db.execute('SELECT data,editorial FROM map_places WHERE id=?', (location_id,)).fetchone()
            place = json.loads(row['data']) if row else None
            if overlay is not None:
                current = next((p for p in overlay.get('locations', []) if p['id'] == location_id), None)
                if current is not None:
                    removed = bool(place and place.get('upstream_removed'))
                    place = deepcopy(current)
                    place['withdrawn'] = bool(place.get('withdrawn')) or removed
                elif row and row['editorial']:
                    place['withdrawn'] = True
            if place is None:
                return None
            stored_scenes = db.execute('SELECT id,data,editorial FROM map_scenes WHERE location_id=?', (location_id,)).fetchall()
            removed_scene_ids = {r['id'] for r in stored_scenes if json.loads(r['data']).get('upstream_removed')}
            scenes = {r['id']: json.loads(r['data']) for r in stored_scenes if overlay is None or not r['editorial']}
            if overlay is not None:
                for scene in overlay.get('scenes', []):
                    if scene['location_id'] == location_id:
                        scenes[scene['id']] = deepcopy(scene)
                        if scene['id'] in removed_scene_ids:
                            scenes[scene['id']]['upstream_removed'] = True
            refs = [json.loads(r[0]) for r in db.execute('SELECT data FROM map_sources WHERE location_id=?', (location_id,))]
            source_ids = set(place.get('source_ids', []))
            for scene in scenes.values():
                source_ids.update(scene.get('source_ids', []))
                if place.get('withdrawn') or scene.get('upstream_removed'):
                    scene['media'] = {**scene.get('media', {}), 'url': '', 'display_allowed': False,
                                      'download_allowed': False, 'share_allowed': False}
            sources = {r['id']: json.loads(r['data']) for r in db.execute('SELECT id,data FROM map_editorial_sources') if r['id'] in source_ids}
            if overlay is not None:
                sources.update({s['id']: deepcopy(s) for s in overlay.get('sources', []) if s['id'] in source_ids})
            return {'place': place, 'scenes': list(scenes.values()), 'source_refs': refs, 'sources': list(sources.values())}

    def work_page(self, work_id, *, episode=None, region=None, level=None, offset=0, limit=24):
        """One work's grouped scenes; only a bounded page leaves the service."""
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError('Invalid scene pagination')
        work_id = str(work_id)
        overlay = self._editorial()
        with self._connect() as db:
            row = db.execute('SELECT data FROM map_works WHERE id=?', (work_id,)).fetchone()
            work = json.loads(row[0]) if row else None
            if overlay:
                edited = next((w for w in overlay.get('anime', []) if str(w['id']) == work_id), None)
                if edited:
                    work = {**(work or {}), **edited}
            if work is None:
                return None
            rows = db.execute('''SELECT s.id,s.data,s.editorial,p.editorial place_editorial,p.data place FROM map_scenes s
                                 JOIN map_places p ON p.id=s.location_id WHERE s.work_id=? ORDER BY s.id''', (work_id,)).fetchall()
        places = {p['id']: p for p in (overlay or {}).get('locations', [])}
        edits = {s['id']: s for s in (overlay or {}).get('scenes', [])}
        scenes = []
        for row in rows:
            scene, place = json.loads(row['data']), json.loads(row['place'])
            if overlay is not None and row['editorial']:
                if row['id'] not in edits:
                    continue
                removed = scene.get('upstream_removed')
                scene = {**scene, **deepcopy(edits[row['id']]), 'upstream_removed': removed}
            if overlay is not None and row['place_editorial'] and place['id'] not in places:
                continue
            removed = place.get('upstream_removed')
            place = places.get(place['id'], place)
            if removed or place.get('withdrawn') or scene.get('upstream_removed'):
                continue
            scenes.append({'id': scene['id'], 'location_id': place['id'], 'title': scene.get('title', place['name']),
                           'episode': str(scene['episode']) if scene.get('episode') is not None else None,
                           'timecode_seconds': scene.get('timecode_seconds'), 'group': scene.get('group'),
                           'place_name': place['name'], 'lat': place['lat'], 'lon': place['lon'],
                           'region': place.get('destination_id') or place.get('city') or None,
                           'content_level': place.get('content_level', 'basic')})
        episodes = sorted({s['episode'] for s in scenes}, key=lambda e: (e is None, str(e)))
        regions = sorted({s['region'] for s in scenes}, key=lambda r: (r is None, str(r)))
        filtered = [s for s in scenes if (episode is None or (s['episode'] or '__unknown__') == episode)
                    and (region is None or (s['region'] or '__unknown__') == region)
                    and (level is None or s['content_level'] == level)]
        from core.map_explore import fit_points
        return {'work': work, 'episodes': episodes, 'regions': regions, 'total': len(filtered),
                'scenes': filtered[offset:offset + limit], 'offset': offset, 'limit': limit,
                'bounds': fit_points(scenes)}
