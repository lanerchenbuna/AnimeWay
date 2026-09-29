"""Three-entry navigation and field-use Trip controls."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from streamlit.testing.v1 import AppTest

from core.trip import evaluate
from core.trip_navigation import directions_url
from core.trip_store import TripStore
from trip_fixtures import CATALOG, plan_for


class NavigationTests(unittest.TestCase):
    def test_three_top_level_entries_and_legacy_secondary_area(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"ANIMEWAY_DATA_DIR": temporary}):
            app = AppTest.from_file("app.py", default_timeout=30).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual([tab.label for tab in app.tabs], ["规划行程", "探索地点", "我的行程"])
            app.session_state["aw_active_tab"] = "探索地点"
            app.run()
            self.assertEqual(len(app.exception), 0)
            app.radio(key="aw_explore_view").set_value("临时背包").run()
            self.assertEqual(len(app.exception), 0)
            app.session_state["aw_pending_tab"] = "explore"
            app.session_state["aw_explore_view"] = "手册与地点"
            app.session_state["aw_page"] = "discover"
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertFalse(any(button.key and button.key.startswith("aw_nav_") for button in app.button))
            app.session_state["aw_pending_tab"] = "trips"
            app.session_state["aw_my_view"] = "legacy"
            app.session_state["aw_page"] = "trips"
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any(button.key == "aw_secondary_trips" for button in app.button))

    def test_map_disabled_keeps_text_exploration(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "ANIMEWAY_DATA_DIR": temporary, "ANIMEWAY_MAP_ENABLED": "0",
        }):
            app = AppTest.from_file("app.py", default_timeout=30).run()
            app.session_state["aw_active_tab"] = "探索地点"
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.radio(key="aw_explore_view").value, "手册与地点")


class TodayTests(unittest.TestCase):
    def test_directions_link_passes_selected_mode_without_visit(self):
        place = CATALOG["locations"][1]
        walking = parse_qs(urlparse(directions_url(place, "walk")).query)
        transit = parse_qs(urlparse(directions_url(place, "transit")).query)
        self.assertEqual(walking["travelmode"], ["walking"])
        self.assertEqual(transit["travelmode"], ["transit"])
        self.assertEqual(walking["destination"], ["35.661000,139.701000"])
        self.assertEqual(transit["dir_action"], ["navigate"])
        with self.assertRaises(ValueError):
            directions_url(place, "driving")

    def test_skip_and_closed_are_not_visits_and_recalculate_remaining_leg(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "private.sqlite3")
            store = TripStore(path)
            token = store.new_identity()
            saved = store.create_personal_trip(token, plan_for("transit"))
            begun = store.begin_personal_trip(token, saved["id"], saved["revision"], CATALOG)
            code = (
                "import streamlit as st\n"
                "from components.trip_planner import _detail\n"
                "from core.trip_store import TripStore\n"
                f"store=TripStore({path!r})\ntoken={token!r}\ncatalog={CATALOG!r}\n"
                f"st.session_state.setdefault('awp_selected',{saved['id']!r})\n"
                "_detail(store,token,catalog,'')\n"
            )
            app = AppTest.from_string(code, default_timeout=20).run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any(item.value == "现在" for item in app.subheader))
            self.assertTrue(any(item.value == "下一步" for item in app.subheader))
            self.assertFalse(any(item.label == "编辑需求卡：日期、住宿、每日时间、作品与体力" for item in app.expander))
            prefix = f"awp_today_{saved['id']}_{begun['revision']}_2026-10-01"
            app.checkbox(key=f"{prefix}_confirm").check().run()
            app.button(key=f"{prefix}_skip").click().run()
            self.assertEqual(len(app.exception), 0)
            after_skip = store.get_personal_trip(token, saved["id"])
            self.assertEqual(after_skip["events"][0]["kind"], "skip")
            check = evaluate(after_skip["plan"], CATALOG, after_skip["events"])["days"][0]
            self.assertEqual(check["next_id"], "c")
            self.assertEqual(next(row for row in check["rows"] if row["location_id"] == "c")["leg"]["from_id"], "a")
            prefix = f"awp_today_{saved['id']}_{after_skip['revision']}_2026-10-01"
            app.checkbox(key=f"{prefix}_confirm").check().run()
            app.button(key=f"{prefix}_closed").click().run()
            self.assertEqual(len(app.exception), 0)
            after_closed = store.get_personal_trip(token, saved["id"])
            self.assertEqual([event["kind"] for event in after_closed["events"]], ["skip", "closed"])
            self.assertIsNone(evaluate(after_closed["plan"], CATALOG, after_closed["events"])["days"][0]["next_id"])
            self.assertFalse(any(event["kind"] == "visit" for event in after_closed["events"]))

    def test_visit_requires_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "private.sqlite3")
            store = TripStore(path)
            token = store.new_identity()
            saved = store.create_personal_trip(token, plan_for())
            begun = store.begin_personal_trip(token, saved["id"], saved["revision"], CATALOG)
            code = (
                "import streamlit as st\n"
                "from components.trip_planner import _detail\n"
                "from core.trip_store import TripStore\n"
                f"store=TripStore({path!r})\ntoken={token!r}\ncatalog={CATALOG!r}\n"
                f"st.session_state.setdefault('awp_selected',{saved['id']!r})\n"
                "_detail(store,token,catalog,'')\n"
            )
            app = AppTest.from_string(code, default_timeout=20).run()
            prefix = f"awp_today_{saved['id']}_{begun['revision']}_2026-10-01"
            self.assertTrue(app.button(key=f"{prefix}_visit").disabled)
            self.assertEqual(store.get_personal_trip(token, saved["id"])["events"], [])
            app.checkbox(key=f"{prefix}_confirm").check().run()
            app.button(key=f"{prefix}_visit").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(store.get_personal_trip(token, saved["id"])["events"][0]["kind"], "visit")
