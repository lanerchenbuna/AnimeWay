"""Read-only, aggregate audit of historical handbook copies in a private database.

Prints counts only. It never emits owner tokens, Trip IDs, titles, or place names.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from core.pilot import load_pilot
from core.trip_adoption import review_legacy_places


def audit_database(path: Path, catalog: dict) -> dict[str, int]:
    if not path.is_file():
        raise FileNotFoundError(path)
    summary = {"legacy_trips": 0, "legacy_stops": 0, "eligible_stops": 0,
               "ineligible_stops": 0, "changed_facts": 0, "invalid_trips": 0,
               "personal_trips": 0, "personal_drafts": 0}
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, field in (("personal_trips", "personal_trips"),
                             ("personal_trip_drafts", "personal_drafts")):
            if table in tables:
                summary[field] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if "trips" not in tables:
            return summary
        for (body,) in conn.execute("SELECT body FROM trips"):
            summary["legacy_trips"] += 1
            try:
                rows = review_legacy_places(json.loads(body)["stops"], catalog)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                summary["invalid_trips"] += 1
                continue
            summary["legacy_stops"] += len(rows)
            summary["eligible_stops"] += sum(row["eligible"] for row in rows)
            summary["ineligible_stops"] += sum(not row["eligible"] for row in rows)
            summary["changed_facts"] += sum(bool(row["changed_facts"]) for row in rows)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="现有 private.sqlite3 的绝对路径")
    args = parser.parse_args()
    print(json.dumps(audit_database(args.db, load_pilot()), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
