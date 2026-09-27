"""Candidate construction and atomic publication, with an exclusive writer lock."""
import fcntl
import json
import os
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from core.public_snapshot import REQUIRED_FILES, checksum, resolve_snapshot, validate_version
from data_factory.map_index import build_map_index
from data_factory.sqlite_index import SCHEMA_VERSION, _data_checksum, build_runtime_index


def _write_json(path: Path, value) -> None:
    with path.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def _writer(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.publish.lock').open('a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Another snapshot writer is active') from exc
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _activate(root: Path, versions: list[str]) -> None:
    temp = root / f'.pointer-{uuid.uuid4().hex}.json'
    try:
        _write_json(temp, {'pointer_version': 1, 'versions': versions[:2]})
        os.replace(temp, root / 'current.json')
        _sync_dir(root)
    finally:
        temp.unlink(missing_ok=True)


def publish_snapshot(root: str | Path, payload: dict, catalog: dict, *, raw: list,
                     state: dict, sync_report: dict, expected_version: str | None = None) -> dict:
    """Publish only complete, explicitly eligible offline or refreshed candidates.

    Failed/unreviewed refresh reports cannot enter the publication path. Files are
    immutable after publication; staging directories left by a crash are never read.
    """
    if sync_report.get('publishable') is not True or sync_report.get('failures'):
        raise ValueError('Sync candidate is incomplete or requires review')
    if str(payload.get('stats', {}).get('schema_version', SCHEMA_VERSION)) != SCHEMA_VERSION:
        raise ValueError('Candidate JSON schema does not match index builder')
    root = Path(root).resolve()
    with _writer(root):
        previous = resolve_snapshot(root)['version'] if (root / 'current.json').exists() else None
        if expected_version is not None and (previous or '') != expected_version:
            raise ValueError('Snapshot baseline changed during candidate build')
        from data_factory.sync import digest_json
        if sync_report.get('raw_checksum') != digest_json(raw):
            raise ValueError('Source snapshot checksum mismatch')
        version = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:12]
        versions = root / 'versions'
        versions.mkdir(exist_ok=True)
        stage = versions / f'.staging-{version}'
        stage.mkdir()
        db_path = stage / 'animeway.sqlite3'
        index = build_runtime_index(payload, str(db_path))
        counts = build_map_index(str(db_path), catalog)
        _write_json(stage / 'index.json', payload)
        _write_json(stage / 'catalog.json', catalog)
        _write_json(stage / 'raw.json', raw)
        _write_json(stage / 'state.json', state)
        _write_json(stage / 'sync-report.json', sync_report)
        with closing(sqlite3.connect(str(db_path))) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Invalid candidate database')
        if index['data_checksum'] != _data_checksum(payload['items']):
            raise ValueError('JSON/SQLite data checksum mismatch')
        expected = sum(len(item.get('spots', [])) for item in payload['items'])
        if index['spot_count'] != expected:
            raise ValueError('JSON/SQLite point counts differ')
        # SQLite was closed before fsync; no WAL or live database copy is involved.
        with db_path.open('rb') as handle:
            os.fsync(handle.fileno())
        manifest = {'manifest_version': 1, 'version': version,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'index_schema_version': SCHEMA_VERSION, 'map_schema_version': 1,
                    'data_checksum': index['data_checksum'], 'counts': counts,
                    'source_metadata': payload.get('stats', {}).get('source_metadata', {}),
                    'files': {name: checksum(stage / name) for name in sorted(REQUIRED_FILES)}}
        _write_json(stage / 'manifest.json', manifest)
        _sync_dir(stage)
        os.replace(stage, versions / version)
        _sync_dir(versions)
        result = validate_version(root, version)
        _activate(root, [version] + ([previous] if previous else []))
        return result


def rollback_snapshot(root: str | Path) -> dict:
    root = Path(root).resolve()
    with _writer(root):
        pointer = json.loads((root / 'current.json').read_text())
        if len(pointer.get('versions', [])) != 2:
            raise ValueError('No previous snapshot available')
        current, previous = pointer['versions']
        result = validate_version(root, previous)
        _activate(root, [previous, current])
        return result
