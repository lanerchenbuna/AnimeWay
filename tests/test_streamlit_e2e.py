from streamlit.testing.v1 import AppTest
import requests

from utils import amap


def test_interface_switches_between_chinese_english_and_japanese():
    app = AppTest.from_file("app.py", default_timeout=20).run()

    assert app.selectbox[0].options == ["简体中文", "English", "日本語"]

    app.selectbox[0].set_value("en_US").run()
    assert [tab.label for tab in app.tabs] == ["✦ Discover", "✦ Route Log"]

    app.selectbox[0].set_value("ja_JP").run()
    assert [tab.label for tab in app.tabs] == ["✦ 聖地を探す", "✦ 冒険の書"]


def test_offline_empty_result_and_messages_survive_rerun():
    app = AppTest.from_file("app.py", default_timeout=20).run()

    assert not app.exception
    app.chat_input[0].set_value("量子香蕉飞船").run()

    assert not app.exception
    assert len(app.session_state["messages"]) == 2
    assert app.session_state["messages"][-1]["structured_result"]["mode"] == "empty"

    app.run()

    assert not app.exception
    assert len(app.session_state["messages"]) == 2
    assert app.session_state["messages"][-1]["content"].startswith("知识库里暂时没有")


def test_offline_route_and_map_survive_rerun():
    app = AppTest.from_file("app.py", default_timeout=60).run()
    app.session_state["itinerary"] = [
        {
            "id": "a",
            "name": "东京 A",
            "lat": 35.6812,
            "lon": 139.7671,
            "_city": "东京都",
            "_anime_name": "测试作品",
        },
        {
            "id": "b",
            "name": "东京 B",
            "lat": 35.6840,
            "lon": 139.7570,
            "_city": "东京都",
            "_anime_name": "测试作品",
        },
    ]
    app.run()

    next(
        button
        for button in app.button
        if button.label == "生成路线预览与路书"
    ).click().run()

    assert not app.exception
    assert app.session_state["planned_routes"]["routes"][0]["estimated"] is True
    assert app.session_state["planned_routes"]["routes"][0]["recommended_mode"] == "short_walk"

    app.run()

    assert not app.exception
    assert app.session_state["planned_routes"]["summary"]["segment_count"] == 1


def test_map_api_timeout_falls_back_to_disclosed_estimate(monkeypatch):
    monkeypatch.setattr(
        amap.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout()),
    )
    app = AppTest.from_file("app.py", default_timeout=60).run()
    app.text_input[0].set_value("fake-amap-key").run()
    app.session_state["itinerary"] = [
        {
            "id": "a",
            "name": "东京 A",
            "lat": 35.6812,
            "lon": 139.7671,
            "_city": "东京都",
            "_anime_name": "测试作品",
        },
        {
            "id": "b",
            "name": "东京 B",
            "lat": 35.6840,
            "lon": 139.7570,
            "_city": "东京都",
            "_anime_name": "测试作品",
        },
    ]
    app.run()

    next(
        button
        for button in app.button
        if button.label == "生成路线预览与路书"
    ).click().run()

    route = app.session_state["planned_routes"]["routes"][0]
    assert not app.exception
    assert route["type"] == "offline"
    assert route["fallback_reason"] == "provider_unavailable"
    assert route["estimated"] is True
