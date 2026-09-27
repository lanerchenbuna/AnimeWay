"""Persist the public catalog and an RTree inside an unpublished candidate DB."""
import json
import sqlite3
from contextlib import closing

from data_factory.normalization import extract_lat_lon

MAP_SCHEMA_VERSION = 1


def build_map_index(db_path: str, catalog: dict) -> dict:
    if catalog.get('schema_version') != 1:
        raise ValueError('Unsupported catalog schema')
    with closing(sqlite3.connect(db_path)) as db, db:
        db.executescript('''
            CREATE TABLE map_places (
                row_id INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL,
                lat REAL NOT NULL, lon REAL NOT NULL, name TEXT NOT NULL, city TEXT,
                destination TEXT, level TEXT, access TEXT, geography TEXT, withdrawn INTEGER NOT NULL,
                editorial INTEGER NOT NULL, upstream_removed INTEGER NOT NULL, data TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE map_bounds USING rtree(row_id, min_lon, max_lon, min_lat, max_lat);
            CREATE TABLE map_works (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE map_scenes (id TEXT PRIMARY KEY, location_id TEXT NOT NULL REFERENCES map_places(id),
                work_id TEXT NOT NULL REFERENCES map_works(id), editorial INTEGER NOT NULL, data TEXT NOT NULL);
            CREATE INDEX map_scenes_location ON map_scenes(location_id);
            CREATE INDEX map_scenes_work ON map_scenes(work_id, location_id);
            CREATE TABLE map_sources (id TEXT PRIMARY KEY, location_id TEXT NOT NULL REFERENCES map_places(id), data TEXT NOT NULL);
            CREATE INDEX map_sources_location ON map_sources(location_id);
            CREATE TABLE map_aliases (id TEXT PRIMARY KEY, location_id TEXT NOT NULL REFERENCES map_places(id));
            CREATE TABLE map_destinations (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE map_editorial_sources (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        ''')
        db.execute('PRAGMA foreign_keys=ON')
        for row_id, (key, place) in enumerate(catalog['places'].items(), 1):
            lat, lon = extract_lat_lon(place)
            if lat is None or lon is None:
                raise ValueError(f'Invalid map place coordinates: {key}')
            db.execute('INSERT INTO map_places VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
                row_id, key, lat, lon, place['name'], place.get('city'), place.get('destination_id'),
                place.get('content_level', 'basic'), place.get('access', {}).get('status', 'unknown'),
                place.get('geography', {}).get('status', 'unknown'),
                int(bool(place.get('withdrawn'))), int(key in catalog.get('editorial_place_ids', [])),
                int(bool(place.get('upstream_removed'))), json.dumps(place, ensure_ascii=False)))
            db.execute('INSERT INTO map_bounds VALUES (?,?,?,?,?)', (row_id, lon, lon, lat, lat))
        for key, work in catalog['works'].items():
            db.execute('INSERT INTO map_works VALUES (?,?)', (key, json.dumps(work, ensure_ascii=False)))
        for key, scene in catalog['scenes'].items():
            for ref_id in scene.get('source_ref_ids', []):
                ref = catalog['source_refs'].get(ref_id)
                if not ref or ref['location_id'] != scene['location_id'] or ref['work_id'] != scene['work_id']:
                    raise ValueError(f'Broken scene/source relationship: {key}')
            db.execute('INSERT INTO map_scenes VALUES (?,?,?,?,?)', (key, scene['location_id'], scene['work_id'],
                int(key in catalog.get('editorial_scene_ids', [])), json.dumps(scene, ensure_ascii=False)))
        for key, source in catalog['source_refs'].items():
            db.execute('INSERT INTO map_sources VALUES (?,?,?)', (key, source['location_id'], json.dumps(source, ensure_ascii=False)))
        for key, location_id in catalog['place_by_source'].items():
            db.execute('INSERT INTO map_aliases VALUES (?,?)', (key, location_id))
        for key, destination in catalog.get('destinations', {}).items():
            db.execute('INSERT INTO map_destinations VALUES (?,?)', (key, json.dumps(destination, ensure_ascii=False)))
        for key, source in catalog['editorial_sources'].items():
            db.execute('INSERT INTO map_editorial_sources VALUES (?,?)', (key, json.dumps(source, ensure_ascii=False)))
        db.execute('INSERT INTO metadata VALUES (?,?)', ('map_schema_version', json.dumps(MAP_SCHEMA_VERSION)))
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Broken map relationships')
    return {key: len(catalog[key]) for key in ('places', 'works', 'scenes', 'source_refs')}
