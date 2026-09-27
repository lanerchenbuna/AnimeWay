"""Reviewable, all-or-nothing Anitabi refresh candidates; never edits source files.

Two upstream shapes are supported. When ``/points/detail`` returns coordinates the row
replaces its record as before. Since 2026-09 the endpoint returns point ID, episode,
timecode, origin and image but no coordinates, so those rows enrich existing records
(matched by upstream ID) while identity and geography stay with the audited snapshot.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time

from data_factory.normalization import (
    extract_lat_lon, image_point_id, normalize_point_metadata, normalize_spot,
)

# Marks an upstream throttle (Cloudflare 403) so a run can stop instead of grinding.
BLOCKED_ERROR_PREFIX = 'http_403'


def digest_json(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def fetch_json(url):
    from data_factory.crawler import request_with_backoff
    response, error = request_with_backoff(url)
    if response is None:
        return 0, None, error
    if response.status_code != 200:
        return response.status_code, None, error or f'HTTP {response.status_code}'
    try:
        return 200, response.json(), ''
    except ValueError:
        return 200, None, 'Invalid JSON'


def _review(review):
    review = deepcopy(review or {})
    if not review:
        return {'migrations': [], 'deletions': [], 'allow_large_drop_work_ids': []}
    if review.get('schema_version') != 1 or not review.get('reviewed_by') or not review.get('reason'):
        raise ValueError('Review requires schema_version=1, reviewed_by and reason')
    for key in ('migrations', 'deletions', 'allow_large_drop_work_ids'):
        if not isinstance(review.get(key, []), list):
            raise ValueError(f'Invalid review {key}')
        review.setdefault(key, [])
    old_keys, new_keys = set(), set()
    for row in review['migrations']:
        old = (str(row['work_id']), str(row['old_id']))
        new = (str(row['work_id']), str(row['new_id']))
        if old in old_keys or new in new_keys or old == new:
            raise ValueError('Migration must be explicit and one-to-one')
        old_keys.add(old)
        new_keys.add(new)
    deletion_keys = {(str(row['work_id']), str(row['point_id'])) for row in review['deletions']}
    if old_keys & deletion_keys:
        raise ValueError('A source cannot be both deleted and migrated')
    return review


def _records(rows, work_id):
    result = {}
    for raw in rows:
        spot = normalize_spot(raw, int(work_id))
        if spot is None:
            continue
        record = spot.model_dump(mode='json', exclude_none=True)
        result.setdefault(spot.id, []).append(record)
    return result


def has_coordinates(row: dict) -> bool:
    lat, lon = extract_lat_lon(row)
    return lat is not None and lon is not None


def declares_coordinates(row: dict) -> bool:
    """True when a row claims a position, even an unusable one such as [0, 0]."""
    return any(row.get(key) is not None for key in ('geo', 'lat', 'lon'))


def stored_upstream_id(record: dict) -> str | None:
    """Upstream point ID of a stored record: explicit source ID, else its image URL.

    The saved 2026-02 snapshot carries no point IDs, but Anitabi's own image URLs embed
    them: a live 2026-09 response for work 265 returned the same ID *and* name for every
    matched row. That makes this upstream evidence rather than a name or distance guess.
    Records with no recoverable ID stay unverified instead of being guessed at.
    """
    explicit = record.get('source_point_id')
    if record.get('identity_kind') == 'upstream' and explicit:
        return str(explicit)
    return image_point_id(record.get('image'))


ENRICHABLE = ('episode', 'timecode_seconds', 'origin', 'origin_url')


def enrich_record(record: dict, metadata: dict) -> list:
    """Fill upstream metadata facts only; identity and coordinates are never touched."""
    changed = []
    for key in ENRICHABLE:
        value = metadata.get(key)
        if value is not None and record.get(key) != value:
            record[key] = value
            changed.append(key)
    for key in ('image', 'description'):
        if not record.get(key) and metadata.get(key):
            record[key] = metadata[key]
            changed.append(key)
    observed = metadata.get('source_raw')
    if isinstance(observed, dict) and observed:
        evidence = record.get('source_raw')
        evidence = dict(evidence) if isinstance(evidence, dict) else {}
        for key, value in observed.items():
            evidence.setdefault(key, value)
        if evidence != record.get('source_raw'):
            record['source_raw'] = evidence
            changed.append('source_raw')
    issues = sorted(set(record.get('normalization_issues') or [])
                    | set(metadata.get('normalization_issues') or []))
    if issues and issues != list(record.get('normalization_issues') or []):
        record['normalization_issues'] = issues
        changed.append('normalization_issues')
    return changed


def merge_metadata(records: dict, fetched: dict) -> dict:
    """Match refreshed metadata rows onto stored records by upstream ID.

    Unmatched rows leave the snapshot untouched: a point without coordinates cannot be
    added to a map, and missing evidence is never turned into a deletion. Only a stored
    record whose own upstream ID is absent from the response counts as deleted.
    """
    by_id, ambiguous = {}, set()
    for key, rows in records.items():
        upstream_id = stored_upstream_id(rows[0])
        if not upstream_id:
            continue
        if upstream_id in by_id:
            ambiguous.add(upstream_id)
        by_id[upstream_id] = key
    enriched, unmatched = [], []
    for upstream_id, metadata in fetched.items():
        if upstream_id in ambiguous:
            continue
        key = by_id.get(upstream_id)
        if key is None:
            unmatched.append(upstream_id)
            continue
        changed = enrich_record(records[key][0], metadata)
        if changed:
            enriched.append({'id': key, 'upstream_id': upstream_id, 'fields': changed})
    matched = {upstream_id for upstream_id in fetched
               if upstream_id in by_id and upstream_id not in ambiguous}
    removed = sorted(({'id': key, 'upstream_id': upstream_id}
                      for upstream_id, key in by_id.items()
                      if upstream_id not in fetched and upstream_id not in ambiguous),
                     key=lambda row: row['upstream_id'])
    return {
        'enriched': enriched, 'unmatched_upstream_ids': sorted(unmatched),
        'ambiguous_upstream_ids': sorted(ambiguous),
        'unverified_stored_ids': sorted(key for key, rows in records.items()
                                        if not stored_upstream_id(rows[0])),
        'deleted': [row['id'] for row in removed], 'deleted_rows': removed,
        'matched_count': len(matched),
        'modified': sorted({item['id'] for item in enriched}),
    }


def refresh_subjects(subjects: list, raw: list, state: dict, *, refresh_ids=None,
                     fetch=fetch_json, review=None, delay=2.0, force=False) -> dict:
    """Default: pending/retryable works. refresh_ids explicitly rechecks completed ones.

    Any failure/review gate makes the whole bundle unpublishable. Proposed successes
    remain inspectable; failed works retain their original records and last success.
    """
    from data_factory.crawler import ANITABI_BASE_URL, ANITABI_LITE_URL
    review = _review(review)
    by_work = {}
    for subject in subjects:
        work_id = str(int(subject.get('subject') or subject.get('id')))
        by_work[work_id] = subject
    selected = set(map(str, refresh_ids)) if refresh_ids is not None else {
        work_id for work_id in by_work
        if state.get(work_id, {}).get('status') not in {'success', 'no_spots', 'not_found'}
        and int(state.get(work_id, {}).get('retries', 0)) < 3
    }
    if selected - set(by_work):
        raise ValueError('Refresh IDs must exist in work metadata')
    original = defaultdict_rows(raw)
    proposed = deepcopy(original)
    next_state = deepcopy(state)
    reports, failures, shape_limited = {}, [], []
    for work_id in sorted(selected, key=int):
        previous = state.get(work_id, {})
        attempted_at = datetime.now(timezone.utc).isoformat()
        old_records = _records(original.get(work_id, []), work_id)
        result = {'work_id': work_id, 'attempted_at': attempted_at, 'old_count': len(old_records),
                  'added': [], 'modified': [], 'deleted': [], 'migrations': [], 'failures': []}
        try:
            code, lite, error = fetch(ANITABI_LITE_URL.format(work_id))
            result['lite_http_status'] = code
            if error and code != 404:
                raise ValueError(error)
            if code not in {200, 404} or (code == 200 and not isinstance(lite, dict)):
                raise ValueError('Invalid lite metadata response')
            unchanged = (not force and code == 200 and previous.get('status') == 'success'
                         and previous.get('upstream_modified') is not None
                         and lite.get('modified') == previous.get('upstream_modified')
                         and original.get(work_id))
            if unchanged:
                # Upstream reports no change since the last success, so the detail request
                # is skipped. This halves the request count, and staying under the rate
                # limit is what keeps the API from answering with a Cloudflare 403.
                result.update(status='unchanged', skipped_detail=True, new_count=len(old_records),
                              upstream_modified=lite.get('modified'),
                              upstream_points_length=lite.get('pointsLength'))
                next_state[work_id] = {**previous, 'attempted_at': attempted_at, 'retries': 0}
                reports[work_id] = result
                if delay:
                    time.sleep(delay)
                continue
            if delay:
                time.sleep(delay)
            detail_code, detail, detail_error = fetch(ANITABI_BASE_URL.format(work_id))
            result['detail_http_status'] = detail_code
            if detail_error and detail_code != 404:
                raise ValueError(detail_error)
            if code == detail_code == 404:
                detail, lite = [], {}
            elif code != 200 or detail_code != 200 or not isinstance(detail, list):
                raise ValueError('Incomplete/inconsistent detail response')
            expected = lite.get('pointsLength')
            result['upstream_points_length'] = expected
            result['upstream_detail_rows'] = len(detail)
            # pointsLength does not equal the detail row count in practice: on 2026-09-27
            # work 265 reported 7 with 6 rows and work 328609 reported 414 with 82. It is
            # recorded for review instead of gating on equality, which rejected every
            # healthy response. Genuine truncation is still caught by the deletion review
            # gate and the large-drop rule below.
            coordinate_rows, metadata_rows, groups, unplaceable = {}, {}, 0, []
            for row in detail:
                if not isinstance(row, dict):
                    raise ValueError('Malformed detail record')
                if has_coordinates(row):
                    normalized = normalize_spot(row, int(work_id))
                    if normalized is None or normalized.identity_kind != 'upstream':
                        raise ValueError('Refreshed points require explicit upstream IDs')
                    if normalized.id in coordinate_rows:
                        raise ValueError('Duplicate source ID in detail response')
                    record = normalized.model_dump(mode='json', exclude_none=True)
                    record['anime_id'] = int(work_id)
                    coordinate_rows[normalized.id] = record
                    continue
                if declares_coordinates(row):
                    # A row that claims a position but cannot be used is malformed. Rows
                    # that omit coordinates entirely are the current upstream shape.
                    raise ValueError('Invalid point coordinates in detail')
                if row.get('type') in {'folder', 'group'}:
                    groups += 1
                    continue
                metadata = normalize_point_metadata(row)
                point_id = metadata.get('point_id') if metadata else None
                if metadata is None or not point_id:
                    # Neither placeable nor identifiable: a grouping or placeholder node.
                    # It never becomes a point; it is counted and reported for review.
                    unplaceable.append({'name': row.get('name'), 'id': row.get('id'),
                                        'keys': sorted(row)})
                    continue
                if point_id in metadata_rows or point_id in coordinate_rows:
                    raise ValueError('Duplicate source ID in detail response')
                metadata_rows[point_id] = metadata
            if unplaceable:
                result['unplaceable_rows'] = unplaceable[:20]
                result['unplaceable_count'] = len(unplaceable)
            mode = 'metadata_only' if metadata_rows and not coordinate_rows else (
                'mixed' if metadata_rows else 'full')
            result.update(mode=mode, metadata_rows=len(metadata_rows),
                          coordinate_rows=len(coordinate_rows))
            mappings = [r for r in review['migrations'] if str(r['work_id']) == work_id]
            approved = {str(r['point_id']) for r in review['deletions'] if str(r['work_id']) == work_id}
            deleted_aliases = {}
            merged = {}
            if mode == 'full':
                new_records = coordinate_rows
                added = set(new_records) - set(old_records)
                deleted = set(old_records) - set(new_records)
                modified = [key for key in set(old_records) & set(new_records)
                            if old_records[key][0] != {k: v for k, v in new_records[key].items() if k != 'anime_id'}]
            else:
                # Identity and coordinates stay with the audited snapshot; only the facts
                # upstream now supplies (episode, timecode, origin, image) are refreshed.
                # Records are matched by upstream ID, never by name or distance.
                records = {key: [deepcopy(rows[0])] for key, rows in old_records.items()}
                merged = merge_metadata(records, metadata_rows)
                by_id = {}
                for key, rows in records.items():
                    upstream_id = stored_upstream_id(rows[0])
                    if upstream_id and upstream_id not in by_id:
                        by_id[upstream_id] = key
                added = set()
                for upstream_id, record in coordinate_rows.items():
                    key = by_id.get(upstream_id)
                    if key is None:
                        records[upstream_id] = [record]
                        added.add(upstream_id)
                    else:
                        records[key] = [record]
                    if upstream_id in merged['unmatched_upstream_ids']:
                        merged['unmatched_upstream_ids'].remove(upstream_id)
                new_records = {key: rows[0] for key, rows in records.items()}
                deleted = set(merged['deleted'])
                deleted_aliases = {row['id']: row['upstream_id'] for row in merged['deleted_rows']}
                modified = merged['modified']
            # A reviewer may name a deletion by its local ID or its upstream point ID; the
            # upstream ID stays stable across rebuilds, the derived one does not.
            upstream_to_local = {upstream_id: local_id
                                 for local_id, upstream_id in deleted_aliases.items()}
            resolved = {upstream_to_local.get(token, token) for token in approved}
            for mapping in mappings:
                if str(mapping['old_id']) not in deleted or str(mapping['new_id']) not in added:
                    raise ValueError('Migration must map a removed old ID to an added new ID')
            if resolved - deleted:
                raise ValueError('Deletion review contains non-deleted IDs')
            unresolved = deleted - resolved - {str(r['old_id']) for r in mappings}
            result.update(new_count=len(new_records), added=sorted(added), modified=sorted(modified),
                          deleted=sorted(deleted), migrations=mappings, unresolved_deleted=sorted(unresolved),
                          group_nodes=groups, upstream_modified=lite.get('modified'),
                          legacy_conflicts=[key for key, rows in old_records.items() if len(rows) > 1 or rows[0].get('legacy_variants')])
            for key in ('enriched', 'matched_count', 'unmatched_upstream_ids',
                        'ambiguous_upstream_ids', 'unverified_stored_ids', 'deleted_rows'):
                if key in merged:
                    result[key] = merged[key]
            if unresolved:
                raise ValueError('Removed/changed source IDs require explicit review')
            if (mode == 'full' and old_records and len(new_records) < len(old_records) * 0.8
                    and work_id not in set(map(str, review['allow_large_drop_work_ids']))):
                raise ValueError('Point count dropped by more than 20%; explicit review required')
            proposed[work_id] = list(new_records.values())
            if not new_records and (metadata_rows or unplaceable) and not old_records:
                # Upstream describes points but no longer ships coordinates, so a work
                # with no audited baseline cannot be imported. Nothing is invented and
                # nothing is written; the work is reported instead of silently skipped.
                status = 'shape_limited'
                shape_limited.append(work_id)
            elif detail_code == 404:
                status = 'not_found'
            else:
                status = 'success' if new_records else 'no_spots'
            next_state[work_id] = {**previous, 'anime_id': int(work_id), 'status': status,
                'point_count': len(new_records), 'error': '',
                'attempted_at': attempted_at, 'upstream_modified': lite.get('modified'),
                'snapshot_checksum': digest_json(proposed[work_id])}
            if status == 'shape_limited':
                next_state[work_id]['retries'] = int(previous.get('retries', 0))
                next_state[work_id]['last_success_at'] = previous.get('last_success_at', '')
            else:
                next_state[work_id]['retries'] = 0
                next_state[work_id]['last_success_at'] = attempted_at
            result['status'] = status
        except (ValueError, TypeError, KeyError, OSError) as exc:
            result['status'] = 'failed'
            result['failures'].append(str(exc))
            failures.append({'work_id': work_id, 'error': str(exc)})
            next_state[work_id] = {**previous, 'status': 'failed', 'attempted_at': attempted_at,
                                   'error': str(exc), 'retries': int(previous.get('retries', 0)) + 1}
        reports[work_id] = result
        if any(str(error).startswith(BLOCKED_ERROR_PREFIX) for error in result.get('failures', [])):
            # Waiting out the throttle once per remaining work would multiply the wait
            # without adding evidence, so the run stops and reports what it never tried.
            for key in sorted(selected - set(reports), key=int):
                reports[key] = {'work_id': key, 'status': 'not_attempted',
                                'reason': 'throttled_by_upstream'}
            break
        if delay:
            time.sleep(delay)
    candidate_raw = [row for key in sorted(proposed, key=int) for row in proposed[key]]
    refreshed = [row for row in reports.values() if row.get('status') == 'success']
    throttled = sorted((row['work_id'] for row in reports.values()
                        if row.get('status') == 'not_attempted'), key=int)
    report = {'schema_version': 1, 'mode': 'refresh', 'publishable': bool(selected) and not failures,
              'selected_work_ids': sorted(selected, key=int), 'works': reports, 'failures': failures,
              'shape_limited_work_ids': sorted(shape_limited, key=int), 'review': review,
              'throttled_work_ids': throttled,
              'content_dimensions': {
                  # Counted over works that actually made it into the candidate: a work that
                  # fails a gate keeps its original records, so its computed enrichment is
                  # discarded and must not be advertised here.
                  'metadata_refreshed': any(row.get('metadata_rows') for row in refreshed),
                  'coordinates_refreshed': any(row.get('coordinate_rows') for row in refreshed),
                  'enriched_records': sum(len(row.get('enriched') or []) for row in refreshed),
                  'unmatched_upstream_ids': sum(len(row.get('unmatched_upstream_ids') or [])
                                                for row in refreshed),
                  'unverified_stored_ids': sum(len(row.get('unverified_stored_ids') or [])
                                               for row in refreshed),
              },
              'base_raw_checksum': digest_json(raw), 'raw_checksum': digest_json(candidate_raw)}
    return {'bundle_version': 1, 'raw': candidate_raw, 'state': next_state, 'report': report}


def defaultdict_rows(raw):
    result = {}
    for row in raw:
        result.setdefault(str(int(row['anime_id'])), []).append(row)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, default=Path('knowledge_base/raw/anitabi_crawl.json'))
    parser.add_argument('--state', type=Path, default=Path('knowledge_base/raw/crawl_state.json'))
    parser.add_argument('--subjects', type=Path, default=Path('knowledge_base/raw/bangumi_knowledge.json'))
    parser.add_argument('--snapshot-root', type=Path, help='Use raw/state from a validated current snapshot')
    parser.add_argument('--refresh', action='store_true', help='Recheck completed works; requires explicit --subject IDs')
    parser.add_argument('--subject', action='append', type=int)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--force', action='store_true',
                        help='Re-fetch details even when upstream reports no change')
    parser.add_argument('--candidate', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.snapshot_root:
        from core.public_snapshot import resolve_snapshot
        selected = resolve_snapshot(args.snapshot_root)
        args.raw = Path(selected['directory']) / 'raw.json'
        args.state = Path(selected['directory']) / 'state.json'
    if args.refresh and not args.subject:
        parser.error('--refresh requires one or more --subject IDs')
    if args.subject and not args.refresh:
        parser.error('--subject requires --refresh')
    if args.candidate.resolve() in {p.resolve() for p in (args.raw, args.state, args.subjects)}:
        parser.error('Candidate must not overwrite source inputs')
    if args.candidate.exists():
        parser.error('Candidate output already exists; choose a new path')
    raw = json.loads(args.raw.read_text())
    state = json.loads(args.state.read_text()) if args.state.exists() else {}
    subjects = json.loads(args.subjects.read_text())
    review = json.loads(args.review.read_text()) if args.review else None
    bundle = refresh_subjects(subjects, raw, state, refresh_ids=args.subject,
                              review=review, force=args.force)
    args.candidate.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive output prevents accidentally overwriting another review artifact.
    with args.candidate.open('x', encoding='utf-8') as output:
        json.dump(bundle, output, ensure_ascii=False, allow_nan=False)
        output.flush()
        os.fsync(output.fileno())
    print(json.dumps({'candidate': str(args.candidate), 'publishable': bundle['report']['publishable'],
                      'failures': bundle['report']['failures']}, ensure_ascii=False))
    raise SystemExit(0 if bundle['report']['publishable'] else 1)


if __name__ == '__main__':
    main()
