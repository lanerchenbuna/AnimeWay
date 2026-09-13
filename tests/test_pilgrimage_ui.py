"""User-task checks for the pilot: no LLM, browser identity supplied by app shell."""
from copy import deepcopy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from components.pilgrimage import export_checklist, filter_locations, navigation_url
from core.pilot import load_pilot
from core.private_store import PrivateStore


@pytest.fixture
def pilot_app(tmp_path):
    path = tmp_path / "private.sqlite3"
    store = PrivateStore(path)
    token = store.new_identity()
    script = f'''
import streamlit as st
from components.pilgrimage import render_pilgrimage
from core.private_store import PrivateStore
from core.pilot import load_pilot
render_pilgrimage(PrivateStore({str(path)!r}), st.session_state.get("test_token"), st.session_state.get("test_catalog", load_pilot()))
'''
    app = AppTest.from_string(script, default_timeout=30)
    app.session_state["test_token"] = token
    app.run()
    assert not app.exception
    return app, store, token


def click(app, key):
    app.button(key=key).click().run()
    assert not app.exception
    return app


def test_work_scene_route_save_reopen_and_checklist(pilot_app):
    app, store, token = pilot_app
    data = load_pilot()
    anime = data["anime"][0]
    route = next(route for route in data["routes"] if anime["id"] in route["anime_ids"])
    click(app, f"aw_work_{anime['id']}")
    assert app.session_state["aw_page"] == "anime"
    scene_location_button = next(button for button in app.button if button.key.startswith("aw_scene_location_"))
    scene_location_button.click().run()
    assert not app.exception
    location_id = app.session_state["aw_selected_location"]
    click(app, f"aw_wish_detail_{location_id}")
    assert store.list_wishlist(token)[0]["id"] == location_id
    click(app, "aw_back")
    click(app, f"aw_route_card_anime_{route['id']}")
    optional = next(stop for stop in route["stops"] if not stop["required"])
    key = f"aw_keep_{route['id']}_{route['version']}_{optional['location_id']}"
    app.checkbox(key=key).uncheck().run()
    click(app, f"aw_adopt_{route['id']}")
    assert app.session_state["aw_page"] == "trip"
    trip = store.list_trips(token)[0]
    assert optional["location_id"] not in {stop["id"] for stop in trip["stops"]}
    assert trip["connection_status"] == "needs_recheck"
    assert len(load_pilot()["routes"][0]["stops"]) == len(route["stops"])
    click(app, f"aw_begin_{trip['id']}")
    assert store.get_trip(token, trip["id"])["started_at"]
    assert len(app.get("download_button")) == 1
    # A new Streamlit session using the same private identity sees its saved copy.
    reopened = AppTest.from_string(Path(app._script_path).read_text(), default_timeout=30)
    reopened.session_state["test_token"] = token
    reopened.run()
    assert not reopened.exception
    click(reopened, "aw_continue_latest")
    assert reopened.session_state["aw_selected_trip"] == trip["id"]


def test_map_and_list_share_filter_selection_and_return_context(pilot_app):
    app, _, _ = pilot_app
    app.text_input(key="aw_discovery_query").set_value("須賀神社").run()
    visible = app.session_state["aw_visible_locations_discover"]
    assert visible
    app.radio(key="aw_view_mode_discover").set_value("map").run()
    assert not app.exception
    assert app.session_state["aw_visible_locations_discover"] == visible
    assert len(app.get("deck_gl_json_chart")) == 1
    selected = app.selectbox(key="aw_location_selector_discover").value
    click(app, "aw_open_selected_discover")
    assert app.session_state["aw_selected_location"] == selected
    click(app, "aw_back")
    assert app.text_input(key="aw_discovery_query").value == "須賀神社"
    assert app.selectbox(key="aw_location_selector_discover").value == selected
    assert app.session_state["aw_visible_locations_discover"] == visible


def test_destination_entry_uses_same_filter_without_widget_mutation(pilot_app):
    app, _, _ = pilot_app
    destination = load_pilot()["destinations"][1]["id"]
    click(app, f"aw_dest_{destination}")
    assert app.selectbox(key="aw_destination_filter").value == destination
    expected = filter_locations(load_pilot(), destination_id=destination)
    assert app.session_state["aw_visible_locations_discover"] == [item["id"] for item in expected]


def test_correction_is_separate_from_ai_feedback_and_private(pilot_app):
    app, store, token = pilot_app
    location = load_pilot()["locations"][0]
    app.session_state["aw_page"] = "location"
    app.session_state["aw_selected_location"] = location["id"]
    app.run()
    app.text_area[0].set_value("入口标识变化，需核实公共区域的到访说明")
    next(button for button in app.button if button.label == "提交地点纠错").click().run()
    assert not app.exception
    report = store.list_corrections(token)[0]
    assert report["location_id"] == location["id"]
    assert report["status"] == "pending"
    click(app, "aw_nav_settings")
    assert any("入口标识变化" in element.value for element in app.markdown)
    other = store.new_identity()
    app.session_state["test_token"] = other
    app.run()
    assert not app.exception
    assert not any("入口标识变化" in element.value for element in app.markdown)


def test_identity_unavailable_allows_browsing_but_no_saving(pilot_app):
    app, store, token = pilot_app
    app.session_state["test_token"] = None
    app.run()
    assert app.button(key=f"aw_wish_discover_{app.session_state['aw_location_selector_discover']}").disabled
    route = load_pilot()["routes"][0]
    click(app, f"aw_route_card_discover_{route['id']}")
    assert app.button(key=f"aw_adopt_{route['id']}").disabled
    assert store.list_trips(token) == []


def test_locale_switch_preserves_trip_identity_and_localizes_actions(pilot_app):
    app, store, token = pilot_app
    data = load_pilot()
    trip = store.create_trip(token, data["routes"][0], data["locations"])
    app.session_state["aw_page"] = "trip"
    app.session_state["aw_selected_trip"] = trip["id"]
    for locale, title in [("en_US", "Trip name"), ("ja_JP", "旅の名前"), ("zh_CN", "行程名称")]:
        app.session_state["locale"] = locale
        app.run()
        assert not app.exception
        assert app.text_input[0].label == title
        assert app.session_state["aw_selected_trip"] == trip["id"]
        assert len(store.list_trips(token)) == 1


def test_template_update_does_not_overwrite_personal_stops(pilot_app):
    app, store, token = pilot_app
    data = load_pilot()
    route = data["routes"][0]
    trip = store.create_trip(token, route, data["locations"])
    optional = next(stop for stop in trip["stops"] if not stop["required"])
    store.update_trip(token, trip["id"], trip["revision"], remove_location_id=optional["id"])
    changed = deepcopy(data)
    changed["routes"][0]["version"] = "new-version"
    app.session_state["test_catalog"] = changed
    app.session_state["aw_page"] = "trip"
    app.session_state["aw_selected_trip"] = trip["id"]
    app.run()
    assert not app.exception
    assert any("原模板已有新版" in element.value for element in app.info)
    assert optional["id"] not in {stop["id"] for stop in store.get_trip(token, trip["id"])["stops"]}


def test_no_media_is_embedded_without_display_permission(pilot_app):
    app, _, _ = pilot_app
    data = load_pilot()
    location = data["locations"][0]
    app.session_state["aw_page"] = "location"
    app.session_state["aw_selected_location"] = location["id"]
    app.run()
    assert not app.exception
    assert not app.get("imgs")
    assert any("展示 / 下载范围确认" in element.value for element in app.caption)


def test_restricted_access_never_becomes_enterable_route(pilot_app):
    app, store, token = pilot_app
    data = deepcopy(load_pilot())
    route = data["routes"][0]
    required = next(stop for stop in route["stops"] if stop["required"])
    location = next(place for place in data["locations"] if place["id"] == required["location_id"])
    location["access"]["status"] = "prohibited"
    app.session_state["test_catalog"] = data
    app.session_state["aw_page"] = "route"
    app.session_state["aw_selected_route"] = route["id"]
    app.run()
    assert not app.exception
    assert app.button(key=f"aw_adopt_{route['id']}").disabled
    assert not store.list_trips(token)


def test_checklist_projection_contains_navigation_but_no_private_metadata(tmp_path):
    data = load_pilot()
    store = PrivateStore(tmp_path / "private.db")
    token = store.new_identity()
    trip = store.create_trip(token, data["routes"][0], data["locations"])
    trip["browser_token"] = token
    trip["api_key"] = "must-not-appear"
    trip["image"] = "https://image.example.test/unauthorized.jpg"
    checklist = export_checklist(trip, data, locale="en_US")
    assert navigation_url(trip["stops"][0]) in checklist
    assert token not in checklist
    assert "must-not-appear" not in checklist
    assert "unauthorized.jpg" not in checklist
    assert "Opening hours" not in checklist or "unverified" in checklist
    assert "No images or offline map" in checklist


def test_search_tokyo_aliases_do_not_confuse_kyoto():
    data = load_pilot()
    assert filter_locations(data, "Tokyo") == filter_locations(data, "东京")
    assert filter_locations(data, "京都") == []
    assert filter_locations(data, destination_id="unknown-destination") == []


def test_official_approach_reference_survives_save_restore_and_content_removal(pilot_app):
    app, store, token = pilot_app
    data = load_pilot()
    route = next(item for item in data["routes"] if item["id"] == "route-yotsuya-stairs")
    click(app, f"aw_route_card_discover_{route['id']}")
    assert any("已做资料核查" in element.value for element in app.info)
    assert any("sugajinjya.or.jp/access" in element.value for element in app.markdown)
    click(app, f"aw_adopt_{route['id']}")
    trip = store.list_trips(token)[0]
    assert trip["connection_status"] == "reference_only"
    other = store.new_identity()
    store.import_backup(other, store.export_backup(token))
    restored = store.list_trips(other)[0]
    checklist = export_checklist(restored, {"locations": [], "scenes": []}, locale="zh_CN")
    assert "sugajinjya.or.jp/access" in checklist
    assert "不是来源标点到男坂精确机位" in checklist
    for stop in trip["stops"]:
        assert stop["name"] in checklist
        assert stop["access"]["summary"] in checklist
        assert stop["entry"] in checklist


def test_current_access_withdrawal_warns_without_erasing_personal_choices(pilot_app):
    app, store, token = pilot_app
    data = load_pilot()
    trip = store.create_trip(token, data["routes"][0], data["locations"])
    first = trip["stops"][0]
    location = next(item for item in data["locations"] if item["id"] == first["id"])
    location.update(withdrawn=True, source_version=2)
    location["access"].update(status="closed", summary="测试：临时关闭，请勿进入")
    app.session_state["test_catalog"] = data
    app.session_state["aw_page"] = "trip"
    app.session_state["aw_selected_trip"] = trip["id"]
    app.run()
    assert not app.exception
    assert any("资料有更新" in item.value for item in app.info)
    assert any("临时关闭" in item.value for item in app.markdown)
    assert store.get_trip(token, trip["id"])["stops"] == trip["stops"]
    assert "临时关闭" in export_checklist(trip, data, locale="zh_CN")
    assert navigation_url(first) not in export_checklist(trip, data, locale="zh_CN")
    assert any("暂停提供到访导航" in item.value for item in app.caption)


def test_map_selection_uses_only_visible_location_ids(pilot_app):
    from components import pilgrimage

    app, _, _ = pilot_app
    state = {"map": {"selection": {"objects": {"pilot-points": [{"id": "visible"}]}}}}
    from unittest.mock import patch

    with patch.object(pilgrimage.st, "session_state", state):
        pilgrimage._map_selection("map", "selector", {"visible"})
        assert state["selector"] == "visible"
        state["map"]["selection"]["objects"]["pilot-points"] = [{"id": "hidden"}]
        pilgrimage._map_selection("map", "selector", {"visible"})
        assert state["selector"] == "visible"
