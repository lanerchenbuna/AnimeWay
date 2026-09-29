"""Reviewed legacy inputs and the persisted Trip draft flow."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from core.trip import evaluate
from core.trip_adoption import draft_from_legacy, review_legacy_places
from core.trip_store import TripStore
from core.private_store import _location, _now, _trip
from trip_fixtures import CATALOG, plan_for


class LegacyAdoptionTests(unittest.TestCase):
    def test_review_reports_every_original_point_and_does_not_change_source(self):
        catalog = deepcopy(CATALOG)
        catalog["locations"].append({"id": "closed", "name": "Closed", "lat": 35.66,
                                     "lon": 139.7, "anime_ids": ["work"], "destination_id": "tokyo",
                                     "access": {"status": "closed"}})
        original = [{"id": "a", "required": True, "stay_max": 40}, {"id": "a"},
                    {"id": "missing", "name": "Historical point"}, {"id": "closed"}]
        before = deepcopy(original)
        rows = review_legacy_places(original, catalog)
        self.assertEqual([row["eligible"] for row in rows], [True, False, False, False])
        self.assertIn("重复", rows[1]["reason"])
        self.assertIn("不在东京", rows[2]["reason"])
        self.assertIn("关闭", rows[3]["reason"])
        self.assertEqual(original, before)

    def test_conversion_preserves_order_required_stay_mode_and_days(self):
        original = [{"id": "c", "required": False, "stay_min": 35},
                    {"id": "a", "required": True, "stay_max": 45},
                    {"id": "b", "required": False, "stay_max": 20}]
        plan = draft_from_legacy(original, CATALOG, selected_ids=["b", "c", "a"],
                                 start_date="2026-10-01", day_count=2, title="旧手册转换", mode="transit")
        self.assertEqual(plan["requirements"]["mode"], "transit")
        self.assertEqual(plan["requirements"]["must_ids"], ["a"])
        self.assertEqual([[s["location_id"] for s in day["stops"]] for day in plan["days"]],
                         [["c", "a"], ["b"]])
        self.assertEqual([s["stay_min"] for day in plan["days"] for s in day["stops"]], [35, 45, 20])
        self.assertIsNone(evaluate(plan, CATALOG)["days"][0]["totals"]["fare_jpy"])

    def test_conversion_rejects_implicit_or_ineligible_selection(self):
        original = [{"id": "a"}, {"id": "a"}, {"id": "missing", "name": "Gone"}]
        common = dict(start_date="2026-10-01", day_count=1, title="背包")
        for selected in ([], ["a", "a"], ["missing"]):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                draft_from_legacy(original, CATALOG, selected_ids=selected, **common)
        chosen = draft_from_legacy(original, CATALOG, selected_ids=["a"], **common)
        self.assertEqual([s["location_id"] for s in chosen["days"][0]["stops"]], ["a"])


class DraftStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "private.sqlite3"
        self.store = TripStore(self.path)
        self.token = self.store.new_identity()

    def test_draft_autosave_reopen_edit_commit_and_same_saved_editor_data(self):
        draft = self.store.create_personal_draft(self.token, plan_for("transit"), "manual")
        reopened_store = TripStore(self.path)
        self.assertEqual(reopened_store.get_personal_draft(self.token, draft["id"])["plan"], draft["plan"])
        changed = reopened_store.edit_personal_draft(self.token, draft["id"], 1,
                    {"kind": "leg_mode", "date": "2026-10-01", "location_id": "b", "value": "walk"}, CATALOG)
        self.assertEqual(changed["revision"], 2)
        self.assertEqual(self.store.get_personal_draft(self.token, draft["id"])["plan"], changed["plan"])
        with self.assertRaises(ValueError):
            self.store.commit_personal_draft(self.token, draft["id"], 1)
        saved = self.store.commit_personal_draft(self.token, draft["id"], 2)
        self.assertEqual(saved["id"], draft["id"])
        self.assertIsNone(self.store.get_personal_draft(self.token, draft["id"]))
        self.assertEqual(self.store.get_personal_trip(self.token, saved["id"])["plan"], changed["plan"])
        modes = [leg["mode"] for leg in evaluate(saved["plan"], CATALOG)["days"][0]["legs"]]
        self.assertEqual(modes, ["walk", "transit", "transit"])
        with self.assertRaises(ValueError):
            self.store.commit_personal_draft(self.token, draft["id"], 2)

    def test_draft_is_owner_scoped_and_conflicting_edits_do_not_overwrite(self):
        draft = self.store.create_personal_draft(self.token, plan_for(), "map")
        other = self.store.new_identity()
        self.assertEqual(self.store.list_personal_drafts(other), [])
        self.assertIsNone(self.store.get_personal_draft(other, draft["id"]))
        with self.assertRaises(ValueError):
            self.store.edit_personal_draft(other, draft["id"], 1,
                                           {"kind": "return_mode", "date": "2026-10-01", "value": "transit"}, CATALOG)
        changed = self.store.edit_personal_draft(self.token, draft["id"], 1,
                      {"kind": "return_mode", "date": "2026-10-01", "value": "transit"}, CATALOG)
        with self.assertRaises(ValueError):
            self.store.edit_personal_draft(self.token, draft["id"], 1,
                                           {"kind": "return_mode", "date": "2026-10-01", "value": "walk"}, CATALOG)
        self.assertEqual(self.store.get_personal_draft(self.token, draft["id"])["plan"], changed["plan"])

    def test_failed_save_keeps_draft_and_creates_no_trip(self):
        draft = self.store.create_personal_draft(self.token, plan_for(), "manual")
        with patch.object(TripStore, "_check_portable_size", side_effect=ValueError("backup limit")):
            with self.assertRaises(ValueError):
                self.store.commit_personal_draft(self.token, draft["id"], 1)
        self.assertIsNotNone(self.store.get_personal_draft(self.token, draft["id"]))
        self.assertEqual(self.store.list_personal_trips(self.token), [])

    def test_ai_changes_use_same_plan_rules_and_are_atomic(self):
        draft = self.store.create_personal_draft(self.token, plan_for(), "routebook")
        valid = {"kind": "end_time", "date": "2026-10-01", "value": 19 * 60}
        invalid = {"kind": "leg_mode", "date": "2026-10-01", "location_id": "b", "value": "transit"}
        with self.assertRaises(ValueError):
            self.store.apply_draft_ai_operations(self.token, draft["id"], 1, [valid, invalid], CATALOG)
        self.assertEqual(self.store.get_personal_draft(self.token, draft["id"])["revision"], 1)
        changed = self.store.apply_draft_ai_operations(self.token, draft["id"], 1, [valid], CATALOG)
        self.assertEqual(changed["plan"]["days"][0]["end_min"], 19 * 60)
        self.assertEqual(changed["revision"], 2)

    def test_legacy_draft_commit_supports_saved_edit_and_day_usage(self):
        plan = draft_from_legacy([{"id": "b", "required": True}], CATALOG,
                                 selected_ids=["b"], start_date="2026-10-01", day_count=1,
                                 title="手册", mode="walk")
        draft = self.store.create_personal_draft(self.token, plan, "handbook")
        saved = self.store.commit_personal_draft(self.token, draft["id"], draft["revision"])
        unlocked = self.store.edit_personal_trip(self.token, saved["id"], saved["revision"],
                    {"kind": "lock", "date": "2026-10-01", "location_id": "b", "value": False}, CATALOG)
        changed = self.store.edit_personal_trip(self.token, saved["id"], unlocked["revision"],
                    {"kind": "stay", "date": "2026-10-01", "location_id": "b", "value": 50}, CATALOG)
        self.assertEqual(changed["plan"]["days"][0]["stops"][0]["stay_min"], 50)
        begun = self.store.begin_personal_trip(self.token, saved["id"], changed["revision"], CATALOG)
        self.assertEqual(begun["state"], "on_trip")
        visited = self.store.record_personal_event(self.token, saved["id"], begun["revision"],
                                                   "2026-10-01", "visit", 600, CATALOG)
        self.assertEqual(visited["events"][0]["kind"], "visit")


class DraftUiTests(unittest.TestCase):
    def test_same_draft_editor_can_save_and_reopen(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "private.sqlite3")
            store = TripStore(path)
            token = store.new_identity()
            draft = store.create_personal_draft(token, plan_for("transit"), "backpack")
            code = (
                "import streamlit as st\n"
                "from components.trip_planner import render_personal_trips\n"
                "from core.trip_store import TripStore\n"
                f"store=TripStore({path!r})\ntoken={token!r}\ncatalog={CATALOG!r}\n"
                f"st.session_state.setdefault('awp_mode','draft')\n"
                f"st.session_state.setdefault('awp_draft_id',{draft['id']!r})\n"
                "render_personal_trips(store,token,catalog,'')\n"
            )
            app = AppTest.from_string(code, default_timeout=20).run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("未保存草案" in item.value for item in app.caption))
            prefix = f"awp_edit_{draft['id']}_1_b"
            app.selectbox(key=f"{prefix}_kind").select("leg_mode").run()
            app.selectbox(key=f"{prefix}_leg_mode").select("walk").run()
            app.button(key=f"{prefix}_apply").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(store.get_personal_draft(token, draft["id"])["revision"], 2)
            app.button(key=f"awp_commit_{draft['id']}_2").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(store.list_personal_drafts(token), [])
            saved = store.list_personal_trips(token)
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["plan"]["days"][0]["stops"][0]["leg_mode"], "walk")
            self.assertEqual(app.session_state["awp_mode"], "detail")
            self.assertEqual(app.session_state["awp_selected"], saved[0]["id"])

    def test_routebook_entry_creates_unsaved_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "private.sqlite3")
            store = TripStore(path)
            token = store.new_identity()
            code = (
                "from components.discover import _render_routebook\n"
                "from core.trip_store import TripStore\n"
                f"store=TripStore({path!r})\ntoken={token!r}\ncatalog={CATALOG!r}\n"
                f"_render_routebook({{'plan': {plan_for('transit')!r}, 'guide': ''}},"
                "'routebook_test', store=store, token=token, catalog=catalog)\n"
            )
            app = AppTest.from_string(code, default_timeout=20).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(store.list_personal_trips(token), [])
            app.button(key="aw_agent_draft_button_routebook_test").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(store.list_personal_drafts(token)), 1)
            self.assertEqual(store.list_personal_drafts(token)[0]["source"], "routebook")
            self.assertEqual(store.list_personal_trips(token), [])

    def test_legacy_conversion_requires_review_before_creating_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "private.sqlite3")
            store = TripStore(path)
            token = store.new_identity()
            items = [{"id": "a", "required": True, "stay_max": 35},
                     {"id": "missing", "name": "Historical point"}]
            code = (
                "from components.legacy_trip_adoption import render_legacy_conversion\n"
                "from core.trip_store import TripStore\n"
                f"store=TripStore({path!r})\ntoken={token!r}\ncatalog={CATALOG!r}\n"
                f"items={items!r}\n"
                "render_legacy_conversion(items,catalog,store,token,source='handbook',key='accept',title='Old')\n"
            )
            app = AppTest.from_string(code, default_timeout=20).run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(app.button(key="accept_create").disabled)
            self.assertTrue(any("未进入" in item.value for item in app.warning))
            app.checkbox(key="accept_reviewed").check().run()
            self.assertFalse(app.button(key="accept_create").disabled)
            app.button(key="accept_create").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(store.list_personal_trips(token), [])
            self.assertEqual(store.list_personal_drafts(token)[0]["source"], "handbook")

    def test_map_selection_creates_draft_before_save(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "private.sqlite3")
            store = TripStore(path)
            token = store.new_identity()
            code = (
                "from components.map_trip import render_place_actions\n"
                "from core.journal_store import JournalStore\n"
                "from core.pilot import load_pilot\n"
                "from core.place_links import trip_eligible\n"
                f"store=JournalStore({path!r})\ntoken={token!r}\ncatalog=load_pilot()\n"
                "place=next(p for p in catalog['locations'] if trip_eligible(p,catalog))\n"
                "render_place_actions(store,token,{'place':place,'scenes':[]},catalog)\n"
            )
            app = AppTest.from_string(code, default_timeout=20).run()
            self.assertEqual(len(app.exception), 0)
            app.button(key="awmap_trip_create").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(store.list_personal_drafts(token)[0]["source"], "map")
            self.assertEqual(store.list_personal_trips(token), [])

    def test_backpack_entry_reviews_points_before_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "private.sqlite3")
            store = TripStore(path)
            token = store.new_identity()
            code = (
                "import streamlit as st\n"
                "from components.backpack import render_backpack\n"
                "from core.trip_store import TripStore\n"
                "from core.pilot import load_pilot\n"
                "from core.place_links import trip_eligible\n"
                f"store=TripStore({path!r})\ntoken={token!r}\ncatalog=load_pilot()\n"
                "point=next(p for p in catalog['locations'] if trip_eligible(p,catalog))\n"
                "st.session_state.setdefault('itinerary',[point])\n"
                "render_backpack(catalog,store=store,token=token)\n"
            )
            app = AppTest.from_string(code, default_timeout=20).run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(app.button(key="aw_bag_convert_create").disabled)
            app.checkbox(key="aw_bag_convert_reviewed").check().run()
            app.button(key="aw_bag_convert_create").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(store.list_personal_drafts(token)[0]["source"], "backpack")
            self.assertEqual(store.list_personal_trips(token), [])

    def test_form_entry_opens_same_unsaved_editor(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "private.sqlite3")
            store = TripStore(path)
            token = store.new_identity()
            code = (
                "import streamlit as st\n"
                "from components.trip_planner import render_personal_trips\n"
                "from core.trip_store import TripStore\n"
                "from core.pilot import load_pilot\n"
                f"store=TripStore({path!r})\ntoken={token!r}\ncatalog=load_pilot()\n"
                "st.session_state.setdefault('awp_mode','new')\n"
                "render_personal_trips(store,token,catalog,'')\n"
            )
            app = AppTest.from_string(code, default_timeout=20).run()
            self.assertEqual(len(app.exception), 0)
            next(button for button in app.button if button.label == "确认条件并检查草案").click().run()
            self.assertEqual(len(app.exception), 0)
            app.button(key="awp_adopt_0").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state["awp_mode"], "draft")
            self.assertEqual(store.list_personal_drafts(token)[0]["source"], "manual")
            self.assertEqual(store.list_personal_trips(token), [])

    def test_saved_legacy_handbook_page_opens_reviewed_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "private.sqlite3")
            store = TripStore(path)
            token = store.new_identity()
            from core.pilot import load_pilot
            from core.place_links import trip_eligible
            catalog = load_pilot()
            point = next(p for p in catalog["locations"] if trip_eligible(p, catalog))
            historical = _trip({"id": "historical", "title": "旧手册", "template_id": "test-route",
                                "template_version": "1", "created_at": _now(), "updated_at": _now(),
                                "stops": [{**_location(point), "required": True}]})
            store.import_backup(token, json.dumps({"schema_version": 1, "wishlist": [],
                                                   "trips": [historical]}))
            old = store.list_trips(token)[0]
            code = (
                "from components.pilgrimage import _trip_page\n"
                "from core.trip_store import TripStore\n"
                "from core.pilot import load_pilot\n"
                f"store=TripStore({path!r})\ntoken={token!r}\ncatalog=load_pilot()\n"
                f"_trip_page(catalog,store,token,{old['id']!r})\n"
            )
            app = AppTest.from_string(code, default_timeout=20).run()
            self.assertEqual(len(app.exception), 0)
            prefix = f"aw_convert_{old['id']}_1"
            self.assertFalse(any(button.key in {f"aw_begin_{old['id']}", f"aw_rename_{old['id']}"}
                                 for button in app.button))
            self.assertTrue(app.button(key=f"{prefix}_create").disabled)
            app.checkbox(key=f"{prefix}_reviewed").check().run()
            app.button(key=f"{prefix}_create").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(store.get_trip(token, old["id"])["stops"], old["stops"])
            self.assertEqual(store.list_personal_drafts(token)[0]["source"], "handbook")
            self.assertEqual(store.list_personal_trips(token), [])

    def test_handbook_template_can_open_trip_draft_without_old_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "private.sqlite3")
            store = TripStore(path)
            token = store.new_identity()
            from core.pilot import load_pilot
            route = load_pilot()["routes"][0]
            code = (
                "from components.pilgrimage import _route_page\n"
                "from core.trip_store import TripStore\n"
                "from core.pilot import load_pilot\n"
                f"store=TripStore({path!r})\ntoken={token!r}\ncatalog=load_pilot()\n"
                f"_route_page(catalog,store,token,{route['id']!r})\n"
            )
            app = AppTest.from_string(code, default_timeout=20).run()
            self.assertEqual(len(app.exception), 0)
            prefix = f"aw_route_convert_{route['id']}_{route['version']}"
            app.checkbox(key=f"{prefix}_reviewed").check().run()
            self.assertFalse(app.button(key=f"{prefix}_create").disabled)
            app.button(key=f"{prefix}_create").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(store.list_trips(token), [])
            self.assertEqual(store.list_personal_trips(token), [])
            self.assertEqual(store.list_personal_drafts(token)[0]["source"], "handbook")
