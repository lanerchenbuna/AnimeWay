"""Validated immutable public snapshots. One pointer selects the whole pair."""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

VERSION_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$')
REQUIRED_FILES = {'index.json', 'animeway.sqlite3', 'catalog.json', 'raw.json', 'state.json', 'sync-report.json'}


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_version(root: str | Path, version: str) -> dict:
    root = Path(root).resolve()
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ValueError('Invalid snapshot version')
    directory = root / 'versions' / version
    if directory.resolve() != directory or not directory.is_dir():
        raise ValueError('Invalid snapshot directory')
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest.get('manifest_version') != 1 or manifest.get('version') != version:
        raise ValueError('Unsupported or mismatched manifest')
    if set(manifest.get('files', {})) != REQUIRED_FILES:
        raise ValueError('Incomplete snapshot file set')
    for name, digest in manifest['files'].items():
        path = directory / name
        if path.is_symlink() or checksum(path) != digest:
            raise ValueError(f'Snapshot checksum mismatch: {name}')
    from data_factory.sqlite_index import SUPPORTED_SCHEMA_VERSIONS

    with closing(sqlite3.connect((directory / 'animeway.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        metadata = {key: json.loads(value) for key, value in db.execute('SELECT key,value FROM metadata')}
        if str(metadata.get('schema_version')) not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError('Unsupported snapshot database schema')
        if metadata.get('schema_version') != manifest.get('index_schema_version'):
            raise ValueError('Snapshot schema mismatch')
        if metadata.get('data_checksum') != manifest.get('data_checksum') or metadata.get('map_schema_version') != 1:
            raise ValueError('Snapshot data or map schema mismatch')
    return {'version': version, 'directory': str(directory), 'manifest': manifest,
            'db_path': str(directory / 'animeway.sqlite3'), 'json_path': str(directory / 'index.json')}


def resolve_snapshot(root: str | Path) -> dict:
    """Pin one valid version; a bad current version falls back as a whole.

    No fallback to unrelated legacy files if both snapshots are invalid. Existing
    readers stay pinned; constructing a new reader observes a new publication.
    """
    pointer = json.loads((Path(root) / 'current.json').read_text())
    if pointer.get('pointer_version') != 1 or not isinstance(pointer.get('versions'), list):
        raise ValueError('Invalid snapshot pointer')
    failures = []
    for version in pointer['versions'][:2]:
        try:
            result = validate_version(root, version)
            result['fallback_reasons'] = failures
            return result
        except (ValueError, OSError, sqlite3.Error, TypeError, KeyError) as exc:
            failures.append(f'{version}: {exc}')
    raise ValueError(f'No valid public snapshot: {failures}')
