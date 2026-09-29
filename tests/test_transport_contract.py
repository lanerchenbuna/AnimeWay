"""One transport contract across Trip entry points and saved states."""
from __future__ import annotations

from copy import deepcopy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from core.pilgrimage_agent import generate_routebook
from core.trip import edit_plan, evaluate, validate_plan
from core.trip_store import TripStore
from core.trip_transport import POLICY_VERSION, connection
from trip_fixtures import CATALOG, plan_for


class TransportContractTests(unittest.TestCase):
    def test_walk_estimate_has_provenance_and_zero_fare(self):
        a, b = CATALOG["locations"][:2]
        leg = connection(a, b, "walk", CATALOG, day_date="2026-10-01", departure_min=540)
        self.assertEqual(leg["mode"], "walk")
        self.assertEqual(leg["status"], "estimated")
        self.assertEqual(leg["actual_mode"], "walk")
        self.assertEqual(leg["fare_jpy"], 0)
        self.assertEqual(leg["fare_status"], "not_applicable")
        self.assertEqual(leg["policy_version"], POLICY_VERSION)
        self.assertEqual(leg["date"], "2026-10-01")
        self.assertEqual(leg["departure_min"], 540)
        self.assertGreater(leg["move_min"], 0)

    def test_transit_remains_unknown_and_never_substitutes_mode(self):
        a, b = CATALOG["locations"][:2]
        leg = connection(a, b, "transit", CATALOG)
        self.assertEqual(leg["status"], "unknown")
        self.assertEqual(leg["mode"], "transit")
        self.assertIsNone(leg["actual_mode"])
        self.assertIsNone(leg["move_min"])
        self.assertIsNone(leg["fare_jpy"])
        self.assertEqual(leg["fare_status"], "unknown")

    def test_unknown_leg_keeps_known_subtotal_but_invalidates_later_eta(self):
        plan = plan_for()
        plan["days"][0]["start"]["confirmed"] = False
        result = evaluate(plan, CATALOG)["days"][0]
        self.assertEqual(result["totals"]["unknown_legs"], 1)
        self.assertGreater(result["totals"]["known_moving_min"], 0)
        self.assertIsNone(result["totals"]["moving_min"])
        self.assertIsNone(result["rows"][0]["arrival_min"])
        self.assertIsNone(result["rows"][1]["arrival_min"])
        self.assertIsNone(result["finish_min"])

    def test_transit_totals_keep_time_and_fare_unknown(self):
        result = evaluate(plan_for("transit"), CATALOG)["days"][0]
        self.assertEqual(result["totals"]["unknown_legs"], 3)
        self.assertEqual(result["totals"]["known_moving_min"], 0)
        self.assertIsNone(result["totals"]["moving_min"])
        self.assertIsNone(result["totals"]["fare_jpy"])
        self.assertIsNone(result["finish_min"])
        self.assertTrue(all(row["leg"]["mode"] == "transit" for row in result["rows"]))

    def test_single_leg_override_survives_default_change_and_reopen(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = TripStore(Path(temporary) / "private.sqlite3")
            token = store.new_identity()
            saved = store.create_personal_trip(token, plan_for("transit"))
            changed = store.edit_personal_trip(token, saved["id"], saved["revision"],
                                               {"kind": "leg_mode", "date": "2026-10-01", "location_id": "b", "value": "walk"}, CATALOG)
            plan = deepcopy(changed["plan"])
            plan["requirements"]["mode"] = "walk"
            changed = store.edit_personal_trip(token, saved["id"], changed["revision"],
                                               {"kind": "requirements", "plan": plan}, CATALOG)
            plan = deepcopy(changed["plan"])
            plan["requirements"]["mode"] = "transit"
            changed = store.edit_personal_trip(token, saved["id"], changed["revision"],
                                               {"kind": "requirements", "plan": plan}, CATALOG)
            reopened = store.get_personal_trip(token, saved["id"])
            self.assertEqual(reopened["plan"]["days"][0]["stops"][0]["leg_mode"], "walk")
            checked = evaluate(reopened["plan"], CATALOG)["days"][0]
            self.assertEqual([leg["mode"] for leg in checked["legs"]], ["walk", "transit", "transit"])
            self.assertTrue(checked["legs"][0]["overridden"])
            self.assertIsNone(checked["totals"]["fare_jpy"])

    def test_return_override_and_legacy_plan_validation(self):
        plan = plan_for("transit")
        self.assertNotIn("leg_mode", plan["days"][0]["stops"][0])
        self.assertEqual(validate_plan(plan), plan)
        archive = {"plan": plan, "state": "draft", "events": []}
        changed, _ = edit_plan(archive, {"kind": "return_mode", "date": "2026-10-01", "value": "walk"}, CATALOG)
        checked = evaluate(changed, CATALOG)["days"][0]
        self.assertEqual(checked["return_leg"]["mode"], "walk")
        self.assertTrue(checked["return_leg"]["overridden"])

    def test_reorder_recalculates_affected_legs_without_changing_mode(self):
        plan = plan_for("walk")
        archive = {"plan": plan, "state": "draft", "events": []}
        before = evaluate(plan, CATALOG)["days"][0]
        changed, _ = edit_plan(archive, {"kind": "move", "date": "2026-10-01",
                                         "location_id": "c", "position": 0}, CATALOG)
        after = evaluate(changed, CATALOG)["days"][0]
        self.assertEqual([leg["to_id"] for leg in before["legs"]], ["b", "c", "a"])
        self.assertEqual([leg["to_id"] for leg in after["legs"]], ["c", "b", "a"])
        self.assertTrue(all(leg["mode"] == "walk" for leg in after["legs"]))

    def test_backup_restores_mode_overrides_and_recalculates_dates(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = TripStore(Path(temporary) / "source.sqlite3")
            token = source.new_identity()
            saved = source.create_personal_trip(token, plan_for("transit"))
            changed = source.edit_personal_trip(token, saved["id"], saved["revision"],
                                                {"kind": "leg_mode", "date": "2026-10-01",
                                                 "location_id": "b", "value": "walk"}, CATALOG)
            backup = source.export_backup(token)
            target = TripStore(Path(temporary) / "target.sqlite3")
            target_token = target.new_identity()
            target.import_backup(target_token, backup)
            restored = target.list_personal_trips(target_token)[0]
            self.assertNotEqual(restored["id"], changed["id"])
            self.assertEqual(restored["plan"]["days"][0]["stops"][0]["leg_mode"], "walk")
            plan = deepcopy(restored["plan"])
            plan["requirements"]["start_date"] = "2026-10-02"
            plan["days"][0]["date"] = "2026-10-02"
            updated = target.edit_personal_trip(target_token, restored["id"], restored["revision"],
                                                {"kind": "requirements", "plan": plan}, CATALOG)
            checked = evaluate(updated["plan"], CATALOG)["days"][0]
            self.assertEqual([leg["date"] for leg in checked["legs"]], ["2026-10-02"] * 3)

    def test_today_uses_saved_mode_after_visit_event(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = TripStore(Path(temporary) / "private.sqlite3")
            token = store.new_identity()
            saved = store.create_personal_trip(token, plan_for("transit"))
            started = store.begin_personal_trip(token, saved["id"], saved["revision"], CATALOG)
            recorded = store.record_personal_event(token, saved["id"], started["revision"],
                                                   "2026-10-01", "visit", 600, CATALOG)
            checked = evaluate(recorded["plan"], CATALOG, recorded["events"])["days"][0]
            self.assertEqual(checked["rows"][0]["outcome"], "visit")
            self.assertEqual(checked["rows"][1]["leg"]["mode"], "transit")
            self.assertIsNone(checked["rows"][1]["arrival_min"])
            self.assertIsNone(checked["totals"]["fare_jpy"])

    def test_ai_cannot_change_transport_override_as_a_fact(self):
        archive = {"plan": plan_for("transit"), "state": "draft", "events": []}
        with self.assertRaises(ValueError):
            edit_plan(archive, {"kind": "leg_mode", "date": "2026-10-01",
                                "location_id": "b", "value": "walk"}, CATALOG, ai=True)

    def test_routebook_preview_matches_saved_trip_evaluation(self):
        plan = plan_for("transit")
        with tempfile.TemporaryDirectory() as temporary:
            store = TripStore(Path(temporary) / "private.sqlite3")
            token = store.new_identity()
            with patch("core.pilgrimage_agent.request_routebook", return_value={"plan": plan}):
                preview = generate_routebook("test", store=store, token=token,
                                             catalog=CATALOG, qwen_key="unused")
            saved = store.create_personal_trip(token, preview["plan"])
            reopened = store.get_personal_trip(token, saved["id"])
            actual = evaluate(reopened["plan"], CATALOG)
            self.assertEqual(preview["evaluation"], actual)
            self.assertEqual(preview["plan"], reopened["plan"])

    def test_routebook_and_saved_detail_render_same_unknown_transport(self):
        plan = plan_for("transit", anchored=False)
        routebook_code = (
            "from components.discover import _render_routebook\n"
            f"_render_routebook({{'plan': {plan!r}, 'guide': ''}}, 'acceptance', "
            f"catalog={CATALOG!r})\n"
        )
        routebook_ui = AppTest.from_string(routebook_code, default_timeout=20).run()
        self.assertEqual(len(routebook_ui.exception), 0)
        routebook_captions = [item.value for item in routebook_ui.caption]
        self.assertTrue(any("待核查交通 3 段" in item for item in routebook_captions))
        self.assertTrue(any("交通费用：待核查" in item for item in routebook_captions))
        with tempfile.TemporaryDirectory() as temporary:
            detail_code = (
                "import streamlit as st\n"
                "from components.trip_planner import _detail\n"
                "from core.trip_store import TripStore\n"
                f"catalog={CATALOG!r}\nplan={plan!r}\n"
                f"store=TripStore({str(Path(temporary) / 'private.sqlite3')!r})\n"
                "token=store.new_identity()\n"
                "saved=store.create_personal_trip(token,plan)\n"
                "st.session_state['awp_selected']=saved['id']\n"
                "_detail(store,token,catalog,'')\n"
            )
            detail_ui = AppTest.from_string(detail_code, default_timeout=20).run()
            self.assertEqual(len(detail_ui.exception), 0)
            detail_captions = [item.value for item in detail_ui.caption]
            self.assertTrue(any("待核查交通 3 段" in item for item in detail_captions))
            self.assertTrue(any("交通费用 待核查" in item for item in detail_captions))

    def test_detail_editor_saves_single_leg_mode_from_ui(self):
        plan = plan_for("transit", anchored=False)
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "private.sqlite3")
            code = (
                "import streamlit as st\n"
                "from components.trip_planner import _detail\n"
                "from core.trip_store import TripStore\n"
                f"catalog={CATALOG!r}\nplan={plan!r}\nstore=TripStore({path!r})\n"
                "if 'test_token' not in st.session_state:\n"
                "    st.session_state['test_token']=store.new_identity()\n"
                "    saved=store.create_personal_trip(st.session_state['test_token'],plan)\n"
                "    st.session_state['awp_selected']=saved['id']\n"
                "_detail(store,st.session_state['test_token'],catalog,'')\n"
            )
            app = AppTest.from_string(code, default_timeout=20).run()
            self.assertEqual(len(app.exception), 0)
            next(item for item in app.selectbox if item.label == "操作").set_value("leg_mode").run()
            next(item for item in app.selectbox if item.label == "到此站的交通方式").set_value("walk").run()
            next(item for item in app.button if item.label == "应用此项人工修改").click().run()
            self.assertEqual(len(app.exception), 0)
            reopened = TripStore(path).get_personal_trip(app.session_state["test_token"],
                                                           app.session_state["awp_selected"])
            self.assertEqual(reopened["plan"]["days"][0]["stops"][0]["leg_mode"], "walk")
            self.assertEqual(evaluate(reopened["plan"], CATALOG)["days"][0]["rows"][0]["leg"]["mode"], "walk")

    def test_trip_transit_does_not_invent_time_or_cost(self):
        result = evaluate(plan_for("transit"), CATALOG)["days"][0]
        self.assertIsNone(result["totals"]["moving_min"])
        self.assertIsNone(result["totals"]["fare_jpy"])
        self.assertGreater(result["totals"]["unknown_legs"], 0)
        self.assertTrue(all(leg["mode"] == "transit" for leg in result["legs"]))

    def test_trip_evaluation_never_queries_unverified_provider(self):
        with patch("requests.get", side_effect=AssertionError("provider must not be queried")) as request:
            result = evaluate(plan_for("transit"), CATALOG)
        request.assert_not_called()
        self.assertIsNone(result["days"][0]["totals"]["fare_jpy"])


if __name__ == "__main__":
    unittest.main()
