#!/usr/bin/env python3
"""Local-only correction queue review; never expose this command as a web route."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.private_store import CORRECTION_STATUSES, SCHEMA_VERSION  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    directory = Path(os.environ.get("ANIMEWAY_DATA_DIR") or Path(__file__).resolve().parents[1] / ".animeway")
    parser.add_argument("--db", type=Path, default=directory / "private.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="List submitted corrections without browser identity hashes")
    listing.add_argument("--status", choices=sorted(CORRECTION_STATUSES))
    listing.add_argument("--limit", type=int, default=100)
    review = commands.add_parser("set", help="Record a review decision; this does not edit public content")
    review.add_argument("correction_id")
    review.add_argument("--status", required=True, choices=sorted(CORRECTION_STATUSES))
    review.add_argument("--note", required=True)
    commands.add_parser("stats", help="Aggregate event counts; start is not completion")
    args = parser.parse_args(argv)
    if not args.db.is_file():
        parser.error("Private database does not exist; check --db / ANIMEWAY_DATA_DIR")
    if args.command == "list" and not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")
    if args.command == "set" and (not args.note.strip() or len(args.note) > 3000):
        parser.error("--note must contain 1–3000 characters")
    try:
        conn = sqlite3.connect(str(args.db.resolve()), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise ValueError("Unsupported private database version")
            if args.command == "list":
                query = "SELECT id,location_id,kind,description,source_url,status,review_note,created_at,updated_at FROM corrections"
                params: list = []
                if args.status:
                    query += " WHERE status=?"
                    params.append(args.status)
                query += " ORDER BY created_at LIMIT ?"
                params.append(args.limit)
                output = [dict(row) for row in conn.execute(query, params)]
            elif args.command == "set":
                cursor = conn.execute("UPDATE corrections SET status=?,review_note=?,updated_at=? WHERE id=?", (args.status, args.note.strip(), datetime.now(timezone.utc).isoformat(), args.correction_id))
                if cursor.rowcount != 1:
                    raise ValueError("Correction not found")
                conn.commit()
                output = {"id": args.correction_id, "status": args.status, "content_updated": False}
            else:
                output = {"events": [dict(row) for row in conn.execute("SELECT event,count(*) AS events,count(DISTINCT owner) AS anonymous_browsers FROM events GROUP BY event ORDER BY event")], "note": "匿名浏览器不是人数；保存、采用、开始是不同事件，没有完成或到访推断。"}
            print(json.dumps(output, ensure_ascii=False, indent=2))
        finally:
            conn.close()
    except (sqlite3.Error, ValueError) as exc:
        print(f"Review failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
