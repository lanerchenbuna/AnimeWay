#!/usr/bin/env python3
"""Local operator workflow. Never expose as an unauthenticated web endpoint."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import contributions as c
from core.journal_store import JournalStore
from core.pilot import load_pilot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("queue")
    commands.add_parser("stats")
    invite = commands.add_parser("invite")
    invite.add_argument("--reviewer", required=True)
    invite.add_argument("--days", type=int, default=14)
    review = commands.add_parser("review")
    review.add_argument("id")
    review.add_argument("--status", choices=["needs_info", "accepted", "rejected"], required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--note", required=True)
    review.add_argument("--minutes", type=int, required=True)
    review.add_argument("--patch", type=Path)
    withdraw = commands.add_parser("withdraw")
    withdraw.add_argument("id")
    withdraw.add_argument("--reviewer", required=True)
    withdraw.add_argument("--note", required=True)
    activity = commands.add_parser("activity")
    activity.add_argument("--file", type=Path, required=True)
    activity.add_argument("--reviewer", required=True)
    activity.add_argument("--minutes", type=int, required=True)
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error("请指定已有服务数据库，避免误建空库")
    store = JournalStore(args.db)
    try:
        if args.command == "invite":
            output = {"invitation": c.issue_invite(store, args.reviewer, days=args.days), "note": "仅交给受邀贡献者，不公开；默认单次兑换。"}
        elif args.command == "queue":
            output = c.queue(store)
        elif args.command == "stats":
            output = c.maintenance_report(store)
        elif args.command == "withdraw":
            c.withdraw_edit(store, args.id, args.reviewer, args.note)
            output = {"withdrawn": args.id}
        elif args.command == "activity":
            output = {"edit_id": c.publish_activity(store, json.loads(args.file.read_text()), args.reviewer, args.minutes, load_pilot())}
        else:
            output = c.review(store, args.id, status=args.status, reviewer=args.reviewer, note=args.note, minutes=args.minutes,
                              patch=json.loads(args.patch.read_text()) if args.patch else None, catalog=load_pilot())
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
