"""Inventory source records near the Tokyo pilot without promoting them to Trips.

Run from the repository root. The output is a candidate inventory, not an
administrative Tokyo boundary or a list of safe, reviewed destinations.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "knowledge_base" / "animeway.sqlite3"
PILOT = ROOT / "knowledge_base" / "pilot" / "tokyo.json"
CRAWL_STATE = ROOT / "knowledge_base" / "raw" / "crawl_state.json"
INVENTORY = ROOT / "knowledge_base" / "pilot" / "candidates" / "tokyo_bbox_works.json"
BBOX = (139.3, 35.4, 139.95, 35.9)  # west, south, east, north; screening only


def audit(index: Path = INDEX, pilot_path: Path = PILOT, state_path: Path = CRAWL_STATE) -> dict:
    pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    editorial_works = {str(work["id"]) for work in pilot["anime"]}
    editorial_sources = {
        (str(upstream["anime_id"]), str(upstream["record_id"]))
        for place in pilot["locations"]
        for upstream in place.get("upstream", [])
    }

    digest = hashlib.sha256()
    with index.open("rb") as index_file:
        for chunk in iter(lambda: index_file.read(1024 * 1024), b""):
            digest.update(chunk)
    index_sha256 = digest.hexdigest()

    with sqlite3.connect(f"file:{index.resolve()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        generated_row = db.execute("SELECT value FROM metadata WHERE key='generated_at'").fetchone()
        index_generated_at = json.loads(generated_row[0]) if generated_row else None
        anime_total = db.execute("SELECT count(*) FROM anime").fetchone()[0]
        spots_total = db.execute("SELECT count(*) FROM spots").fetchone()[0]
        works_with_spots = db.execute("SELECT count(DISTINCT anime_id) FROM spots").fetchone()[0]
        records = db.execute(
            "SELECT s.anime_id, s.spot_id, s.lat, s.lon, s.city, s.source_url, "
            "s.verified_at, a.cn, a.jp FROM spots s JOIN anime a USING (anime_id) "
            "WHERE s.lon BETWEEN ? AND ? AND s.lat BETWEEN ? AND ? "
            "ORDER BY s.anime_id, s.spot_id",
            (BBOX[0], BBOX[2], BBOX[1], BBOX[3]),
        ).fetchall()

    by_work: dict[str, list[sqlite3.Row]] = defaultdict(list)
    coordinate_cells: Counter[tuple[float, float]] = Counter()
    for record in records:
        by_work[str(record["anime_id"])].append(record)
        coordinate_cells[(round(record["lat"], 4), round(record["lon"], 4))] += 1

    works = []
    for work_id, points in by_work.items():
        crawl = state.get(work_id, {})
        works.append({
            "work_id": work_id,
            "title": points[0]["cn"] or points[0]["jp"] or work_id,
            "bbox_record_count": len(points),
            "bbox_coordinate_cells_4dp": len({
                (round(point["lat"], 4), round(point["lon"], 4)) for point in points
            }),
            "editorial_work": work_id in editorial_works,
            "editorial_source_matches": sum(
                (work_id, str(point["spot_id"])) in editorial_sources for point in points
            ),
            "crawl_status": crawl.get("status", "missing"),
            "crawl_updated_at": crawl.get("updated_at"),
            "review_state": "partially_curated" if work_id in editorial_works else "candidate_only",
        })
    works.sort(key=lambda work: (-work["bbox_record_count"], int(work["work_id"])))

    return {
        "definition": {
            "grain": "indexed source point record by work; physical places require editorial merging",
            "bbox_west_south_east_north": list(BBOX),
            "bbox_is_administrative_boundary": False,
            "index_sha256": index_sha256,
            "index_generated_at": index_generated_at,
        },
        "summary": {
            "anime_metadata_rows": anime_total,
            "works_with_any_indexed_spots": works_with_spots,
            "indexed_spot_records": spots_total,
            "bbox_spot_records": len(records),
            "bbox_works": len(works),
            "bbox_works_with_at_least_10_records": sum(w["bbox_record_count"] >= 10 for w in works),
            "bbox_records_in_works_with_at_least_10": sum(
                w["bbox_record_count"] for w in works if w["bbox_record_count"] >= 10
            ),
            "bbox_distinct_coordinate_cells_4dp": len(coordinate_cells),
            "bbox_shared_coordinate_cells_4dp": sum(n > 1 for n in coordinate_cells.values()),
            "bbox_records_without_indexed_source_url": sum(not r["source_url"] for r in records),
            "bbox_records_without_indexed_verified_at": sum(not r["verified_at"] for r in records),
            "pilot_works": len(pilot["anime"]),
            "pilot_locations": len(pilot["locations"]),
            "pilot_scenes": len(pilot["scenes"]),
            "pilot_routes": len(pilot["routes"]),
            "pilot_source_links": len(editorial_sources),
            "bbox_source_records_mapped_to_pilot": sum(
                (str(r["anime_id"]), str(r["spot_id"])) in editorial_sources for r in records
            ),
        },
        "works": works,
    }


def work_records(work_id: str, index: Path = INDEX, pilot_path: Path = PILOT) -> list[dict]:
    """Expose one work's screening rows for manual review, without promotion."""
    if not work_id.isdecimal():
        raise ValueError("work_id must be a numeric source ID")
    pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
    pilot_places = {
        (str(upstream["anime_id"]), str(upstream["record_id"])): place["id"]
        for place in pilot["locations"]
        for upstream in place.get("upstream", [])
    }
    with sqlite3.connect(f"file:{index.resolve()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT spot_id, name, lat, lon, city, source_url, verified_at "
            "FROM spots WHERE anime_id=? AND lon BETWEEN ? AND ? AND lat BETWEEN ? AND ? "
            "ORDER BY spot_id",
            (int(work_id), BBOX[0], BBOX[2], BBOX[1], BBOX[3]),
        ).fetchall()
    return [{
        "source_point_id": row["spot_id"],
        "name": row["name"],
        "lat": row["lat"],
        "lon": row["lon"],
        "source_city_label": row["city"],
        "indexed_source_url": row["source_url"],
        "indexed_verified_at": row["verified_at"],
        "pilot_location_id": pilot_places.get((work_id, str(row["spot_id"]))),
    } for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write-inventory", action="store_true", help=f"write {INVENTORY}")
    mode.add_argument("--work-id", help="show the unreviewed source rows for one work ID")
    args = parser.parse_args()
    if args.work_id:
        print(json.dumps(work_records(args.work_id), ensure_ascii=False, indent=2))
        return
    result = audit()
    if args.write_inventory:
        INVENTORY.parent.mkdir(parents=True, exist_ok=True)
        INVENTORY.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(INVENTORY)
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
