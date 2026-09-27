"""Build/publish offline or reviewed refresh bundles through the same manifest gate."""
import argparse
import json
from pathlib import Path

from core.map_catalog import build_map_catalog
from core.pilot import load_pilot
from core.public_snapshot import resolve_snapshot
from data_factory.build_kb import build_knowledge_base, load_json, ANITABI_FILE
from data_factory.map_reconcile import reconcile_catalog
from data_factory.snapshot import publish_snapshot, rollback_snapshot
from data_factory.sync import digest_json

DEFAULT_ROOT = 'knowledge_base/releases'


def _previous(root):
    if not (Path(root) / 'current.json').exists():
        return None
    selected = resolve_snapshot(root)
    directory = Path(selected['directory'])
    return {'version': selected['version'], **{key: json.loads((directory / f'{key}.json').read_text()) for key in ('raw', 'catalog', 'state')}}


def publish_offline(root=DEFAULT_ROOT, *, payload=None, raw=None, editorial=None):
    """Bootstrap from the saved source snapshot; never claims a content refresh."""
    previous = _previous(root)
    raw = (previous['raw'] if previous else load_json(ANITABI_FILE, [])) if raw is None else raw
    payload = build_knowledge_base(write=False, raw_spots=raw) if payload is None else payload
    if previous and digest_json(previous['raw']) != digest_json(raw):
        raise ValueError('Offline rebuild cannot bypass review of changed source data; use a refresh bundle')
    payload.setdefault('stats', {}).setdefault('source_metadata', {}).setdefault('anitabi', {})['snapshot_checksum'] = digest_json(raw)
    if previous:
        payload['stats']['source_metadata']['anitabi'].pop('checksum_sha256', None)
        payload['stats']['source_metadata']['anitabi']['path'] = 'raw.json'
    catalog = build_map_catalog(payload, load_pilot() if editorial is None else editorial)
    catalog = reconcile_catalog(catalog, previous['catalog'] if previous else None)
    report = {'schema_version': 1, 'mode': 'offline_rebuild', 'publishable': True, 'failures': [],
              'raw_checksum': digest_json(raw), 'content_refreshed': False}
    return publish_snapshot(root, payload, catalog, raw=raw, state=previous['state'] if previous else load_json('knowledge_base/raw/crawl_state.json', {}), sync_report=report,
                            expected_version=previous['version'] if previous else '')


def publish_bundle(root, bundle, *, editorial=None):
    if bundle.get('bundle_version') != 1:
        raise ValueError('Unsupported refresh bundle')
    report = bundle['report']
    if not report.get('publishable') or report.get('failures'):
        raise ValueError('Refresh has failed or unreviewed subjects')
    if digest_json(bundle['raw']) != report.get('raw_checksum'):
        raise ValueError('Refresh bundle raw checksum mismatch')
    previous = _previous(root)
    if not previous or digest_json(previous['raw']) != report.get('base_raw_checksum'):
        raise ValueError('Refresh baseline changed or missing; rebuild candidate against current snapshot')
    payload = build_knowledge_base(write=False, raw_spots=bundle['raw'])
    payload['stats']['source_metadata']['anitabi'] = {
        'source_url': 'https://api.anitabi.cn', 'license': 'upstream-terms-see-source',
        'snapshot_checksum': report['raw_checksum'], 'refresh_report': 'sync-report.json'}
    catalog = build_map_catalog(payload, load_pilot() if editorial is None else editorial)
    catalog = reconcile_catalog(catalog, previous['catalog'], report.get('review'))
    for source in catalog['source_refs'].values():
        state = bundle['state'].get(source['work_id'], {})
        source['upstream_updated_at'] = state.get('upstream_modified')
        source['fetched_at'] = state.get('last_success_at')
    return publish_snapshot(root, payload, catalog, raw=bundle['raw'], state=bundle['state'], sync_report=report, expected_version=previous['version'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=DEFAULT_ROOT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--offline', action='store_true')
    mode.add_argument('--bundle', type=Path)
    mode.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    if args.offline:
        selected = publish_offline(args.root)
    elif args.bundle:
        selected = publish_bundle(args.root, json.loads(args.bundle.read_text()))
    else:
        selected = rollback_snapshot(args.root)
    print(json.dumps({'version': selected['version'], 'db_path': selected['db_path']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
