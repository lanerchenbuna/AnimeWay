"""User task regression checks for the personal Trip form and edit flow."""
from copy import deepcopy

import pytest
from streamlit.testing.v1 import AppTest

from core.pilot import load_pilot
from core.trip import empty_plan, new_requirements, propose
from core.trip_store import TripStore


@pytest.fixture
def personal_app(tmp_path):
    path = tmp_path / "private.sqlite3"
    store = TripStore(path)
    token = store.new_identity()
    script = f'''
import streamlit as st
from components.trip_planner import render_personal_trips
from core.trip_store import TripStore
from core.pilot import load_pilot
render_personal_trips(TripStore({str(path)!r}), st.session_state.get("test_token"), load_pilot())
'''
    app = AppTest.from_string(script, default_timeout=30)
    app.session_state["test_token"] = token
    app.run()
    assert not app.exception
    return app, store, token


def click(app, key):
    app.button(key=key).click().run()
    assert not app.exception


def test_requirement_form_proposes_saves_and_edits_without_llm(personal_app):
    app, store, token = personal_app
    click(app, "awp_new")
    assert not app.exception
    app.text_area(key="awp_free_text").set_value("后天下午到东京，住新宿，两天，孤独摇滚和你的名字，不想太赶")
    click(app, "awp_parse")
    assert app.session_state["awp_seed"]["days"][0]["day_type"] == "arrival"
    form = next(b for b in app.button if b.label == "确认条件并检查草案")
    form.click().run()
    assert not app.exception
    assert 1 <= len(app.session_state["awp_options"]) <= 2
    click(app, "awp_adopt_0")
    trip = store.list_personal_trips(token)[0]
    assert app.session_state["awp_selected"] == trip["id"]
    assert len(trip["plan"]["days"]) == 2
    day = trip["plan"]["days"][1]
    prefix = f"awp_{trip['id']}_{trip['revision']}_{day['date']}"
    app.text_input(key=f"{prefix}_end_text").set_value("17:00")
    click(app, f"{prefix}_end")
    changed = store.get_personal_trip(token, trip["id"])
    assert changed["plan"]["days"][1]["end_min"] == 1020
    assert changed["plan"]["days"][0] == trip["plan"]["days"][0]
    click(app, f"awp_{trip['id']}_{changed['revision']}_undo")
    assert store.get_personal_trip(token, trip["id"])["plan"] == trip["plan"]


def test_detail_local_edit_and_language_switch_preserve_private_trip(personal_app):
    app, store, token = personal_app
    plan = propose(empty_plan(new_requirements("2026-10-10", 1, anime_ids=["328609"])), load_pilot())[0]["plan"]
    trip = store.create_personal_trip(token, plan)
    app.session_state["awp_selected"] = trip["id"]
    app.session_state["awp_mode"] = "detail"
    app.run()
    assert not app.exception
    stop = plan["days"][0]["stops"][0]
    prefix = f"awp_edit_{trip['id']}_1_{stop['location_id']}"
    app.number_input(key=f"{prefix}_stay").set_value(10).run()
    click(app, f"{prefix}_apply")
    current = store.get_personal_trip(token, trip["id"])
    assert current["plan"]["days"][0]["stops"][0]["stay_min"] == 10
    for language in ("en_US", "ja_JP", "zh_CN"):
        app.session_state["locale"] = language
        app.run()
        assert not app.exception
        assert store.get_personal_trip(token, trip["id"]) == current
    assert len(app.get("download_button")) == 1


def test_today_skip_is_not_visit_and_other_identity_cannot_read(personal_app):
    app, store, token = personal_app
    plan = propose(empty_plan(new_requirements("2026-10-10", 1, anime_ids=["328609"])), load_pilot())[0]["plan"]
    trip = store.create_personal_trip(token, plan)
    app.session_state["awp_selected"] = trip["id"]
    app.session_state["awp_mode"] = "detail"
    app.run()
    app.checkbox(key=f"awp_{trip['id']}_1_ack").check().run()
    click(app, f"awp_{trip['id']}_1_begin")
    active = store.get_personal_trip(token, trip["id"])
    prefix = f"awp_today_{trip['id']}_{active['revision']}_2026-10-10"
    app.text_input(key=f"{prefix}_time").set_value("10:00")
    app.selectbox(key=f"{prefix}_kind").set_value("skip")
    app.checkbox(key=f"{prefix}_confirm").check()
    click(app, f"{prefix}_record")
    assert store.get_personal_trip(token, trip["id"])["events"][0]["kind"] == "skip"
    app.session_state["test_token"] = store.new_identity()
    app.run()
    assert not app.exception
    assert any("未找到此浏览器" in x.value for x in app.warning)


def test_ai_preview_needs_current_revision_and_explicit_confirmation(personal_app):
    from core.trip_ai import preview_operations
    app, store, token = personal_app
    catalog = load_pilot()
    plan = propose(empty_plan(new_requirements("2026-10-10", 1, anime_ids=["328609"])), catalog)[0]["plan"]
    trip = store.create_personal_trip(token, plan)
    app.session_state["awp_selected"] = trip["id"]
    app.session_state["awp_mode"] = "detail"
    preview = preview_operations(trip, {"operations": [{"kind": "end_time", "date": "2026-10-10", "value": 1020}]}, catalog)
    app.session_state["awp_ai_preview"] = {"trip_id": trip["id"], **deepcopy(preview)}
    app.run()
    assert not app.exception
    assert store.get_personal_trip(token, trip["id"])["revision"] == 1
    click(app, f"awp_ai_apply_{trip['id']}")
    assert store.get_personal_trip(token, trip["id"])["revision"] == 2
    app.session_state["awp_ai_preview"] = {"trip_id": trip["id"], **preview}
    app.run()
    assert not app.exception
    assert any("旧 AI 预览已失效" in x.value for x in app.info)



def test_saved_handbook_converts_to_independent_personal_trip(tmp_path):
    path = tmp_path / "private.db"
    store, catalog = TripStore(path), load_pilot()
    token = store.new_identity()
    handbook = store.create_trip(token, catalog["routes"][0], catalog["locations"])
    script = f'''
import streamlit as st
from components.pilgrimage import render_pilgrimage
from core.trip_store import TripStore
from core.pilot import load_pilot
render_pilgrimage(TripStore({str(path)!r}), st.session_state.get("test_token"), load_pilot())
'''
    app = AppTest.from_string(script, default_timeout=30)
    app.session_state["test_token"] = token
    app.session_state["aw_page"] = "trip"
    app.session_state["aw_selected_trip"] = handbook["id"]
    app.run()
    click(app, f"aw_convert_{handbook['id']}")
    assert app.session_state["aw_page"] == "personal"
    trip = store.list_personal_trips(token)[0]
    assert trip["id"] != handbook["id"]
    assert len(trip["plan"]["days"]) == 1
    assert [s["location_id"] for s in trip["plan"]["days"][0]["stops"]] == [s["id"] for s in handbook["stops"]]
    assert store.get_trip(token, handbook["id"]) == handbook
    assert trip["plan"]["days"][0]["start"]["confirmed"] is False
