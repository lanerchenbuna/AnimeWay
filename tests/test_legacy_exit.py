"""Historical review, legacy exit and one Trip lifecycle."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from streamlit.testing.v1 import AppTest

from core.private_store import _location, _now, _trip
from core.trip import evaluate
from core.trip_adoption import audit_legacy_conversion, draft_from_legacy
from core.trip_store import TripStore
from scripts.audit_legacy_trips import audit_database
from trip_fixtures import CATALOG, plan_for


class LegacyExitTests(unittest.TestCase):
    def test_conversion_audit_catches_omissions_current_fact_changes_and_tampering(self):
        catalog = deepcopy(CATALOG)
        catalog["locations"].append({"id": "closed", "name": "Closed", "lat": 35.67,
                                     "lon": 139.71, "anime_ids": ["work"],
                                     "destination_id": "tokyo", "access": {"status": "closed"}})
        original = [{"id": "b", "name": "Old B", "lat": 35.0, "lon": 139.701,
                     "access": {"status": "unknown"}, "required": True, "stay_max": 45},
                    {"id": "b", "name": "Duplicate B"},
                    {"id": "missing", "name": "Lost"}, {"id": "closed"},
                    {"id": "a", "required": False, "stay_min": 30}]
        before = deepcopy(original)
        plan = draft_from_legacy(original, catalog, selected_ids=["a", "b"],
                                 start_date="2026-10-01", day_count=1,
                                 title="Historical", mode="transit")
        audit = audit_legacy_conversion(original, catalog, plan, ["a", "b"])
        self.assertEqual(original, before)
        self.assertTrue(audit["matches"])
        self.assertEqual((audit["source_count"], audit["selected_count"], len(audit["omitted"])), (5, 2, 3))
        self.assertEqual([entry["reason"] for entry in audit["omitted"]],
                         ["同一现实地点重复出现；个人 Trip 只安排一次",
                          "不在东京试点地点目录中，暂不能安排",
                          "地点已关闭、撤下或不在东京试点范围，需先核查"])
        self.assertEqual(audit["changed_facts"][0]["fields"], ["名称", "坐标", "访问状态"])
        self.assertEqual([s["location_id"] for s in plan["days"][0]["stops"]], ["b", "a"])
        self.assertEqual(plan["requirements"]["mode"], "transit")
        self.assertIsNone(evaluate(plan, catalog)["days"][0]["totals"]["fare_jpy"])
        changed = deepcopy(plan)
        changed["days"][0]["stops"][0]["stay_min"] = 10
        self.assertIn("停留时长不一致", audit_legacy_conversion(original, catalog, changed,
                                                        ["a", "b"])["differences"])
        with self.assertRaisesRegex(ValueError, "旧停留时长无效"):
            draft_from_legacy([{"id": "a", "stay_min": 0}], catalog, selected_ids=["a"],
                              start_date="2026-10-01", day_count=1, title="Bad")

    def test_legacy_creation_is_blocked_but_historical_backup_still_reads_and_audits(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private.sqlite3"
            store = TripStore(path)
            token = store.new_identity()
            with self.assertRaisesRegex(ValueError, "已停止新增"):
                store.create_trip(token, {"title": "new"}, CATALOG["locations"][:1])
            self.assertEqual(store.list_trips(token), [])
            catalog = deepcopy(CATALOG)
            catalog["locations"][0]["access"]["status"] = "public_exterior"
            historical = _trip({"id": "old", "title": "Historical", "template_id": "source",
                                "created_at": _now(), "updated_at": _now(),
                                "stops": [{**_location(catalog["locations"][0]), "required": True}]})
            store.import_backup(token, json.dumps({"schema_version": 1, "wishlist": [],
                                                   "trips": [historical]}))
            saved = store.list_trips(token)
            self.assertEqual(len(saved), 1)
            self.assertEqual(store.get_trip(token, saved[0]["id"])["title"], "Historical")
            with self.assertRaisesRegex(ValueError, "只读"):
                store.update_trip(token, saved[0]["id"], saved[0]["revision"], title="Changed")
            with self.assertRaisesRegex(ValueError, "只读"):
                store.start_trip(token, saved[0]["id"])
            self.assertEqual(audit_database(path, catalog), {
                "legacy_trips": 1, "legacy_stops": 1, "eligible_stops": 1,
                "ineligible_stops": 0, "changed_facts": 0, "invalid_trips": 0,
                "personal_trips": 0, "personal_drafts": 0})

    def test_backpack_only_offers_reviewed_trip_draft_and_keeps_source_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private.sqlite3"
            store = TripStore(path)
            token = store.new_identity()
            bag = [{"id": "a", "name": "Old name", "lat": 35.0, "lon": 139.7},
                   {"id": "a", "name": "Repeated name"}]
            code = (
                "import streamlit as st\n"
                "from components.backpack import render_backpack\n"
                "from core.trip_store import TripStore\n"
                f"store=TripStore({str(path)!r})\ntoken={token!r}\ncatalog={CATALOG!r}\n"
                f"st.session_state.setdefault('itinerary',{bag!r})\n"
                "render_backpack(catalog,store=store,token=token)\n"
            )
            app = AppTest.from_string(code, default_timeout=20).run()
            self.assertEqual(len(app.exception), 0)
            self.assertFalse(any("生成路线" in button.label for button in app.button))
            self.assertEqual(app.session_state["itinerary"], bag)
            self.assertTrue(any("重复" in warning.value for warning in app.warning))
            self.assertEqual(store.list_trips(token), [])


class TripLifecycleTests(unittest.TestCase):
    def test_create_edit_commit_reopen_begin_and_skip_keeps_one_trip_and_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private.sqlite3"
            store = TripStore(path)
            token = store.new_identity()
            draft = store.create_personal_draft(token, plan_for("transit"), "manual")
            preview = evaluate(draft["plan"], CATALOG)["days"][0]
            self.assertTrue(all(leg["mode"] == "transit" for leg in preview["legs"]))
            self.assertIsNone(preview["totals"]["moving_min"])
            edited = store.edit_personal_draft(token, draft["id"], draft["revision"],
                {"kind": "leg_mode", "date": "2026-10-01", "location_id": "b", "value": "walk"}, CATALOG)
            saved = store.commit_personal_draft(token, draft["id"], edited["revision"])
            reopened = TripStore(path).get_personal_trip(token, saved["id"])
            self.assertEqual(saved["id"], draft["id"])
            self.assertEqual(reopened["plan"], edited["plan"])
            after = evaluate(reopened["plan"], CATALOG)["days"][0]
            self.assertEqual([leg["mode"] for leg in after["legs"]], ["walk", "transit", "transit"])
            self.assertIsNone(after["totals"]["fare_jpy"])
            begun = store.begin_personal_trip(token, saved["id"], reopened["revision"], CATALOG)
            skipped = store.record_personal_event(token, saved["id"], begun["revision"],
                                                  "2026-10-01", "skip", 600, CATALOG)
            result = evaluate(skipped["plan"], CATALOG, skipped["events"])["days"][0]
            self.assertEqual(result["next_id"], "c")
            self.assertEqual(result["rows"][0]["outcome"], "skip")
            self.assertEqual(next(row for row in result["rows"] if row["location_id"] == "c")["leg"]["mode"], "transit")
            self.assertEqual(len(store.list_personal_trips(token)), 1)
            self.assertEqual(store.list_personal_drafts(token), [])
            self.assertEqual(store.list_trips(token), [])


if __name__ == "__main__":
    unittest.main()
