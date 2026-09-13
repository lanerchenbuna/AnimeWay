from streamlit.testing.v1 import AppTest
import pytest
import requests

from utils import amap


@pytest.fixture(autouse=True)
def isolated_private_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIMEWAY_DATA_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    monkeypatch.setenv("AMAP_API_KEY", "")


def test_legacy_anime_expansion_deduplicates_pilot_locations():
    app = AppTest.from_file("app.py", default_timeout=30).run()
    app.chat_input[0].set_value("孤独摇滚").run()
    assert not app.exception
    selected = next(button for button in app.button if button.key and button.key.startswith("sel_328609_"))
    selected.click().run()
    assert not app.exception
    results = app.session_state["search_results"]
    assert results
    assert len({point["id"] for point in results}) == len(results)
    merged = next(point for point in results if point["id"] == "loc-tokyo-village-vanguard")
    assert len(merged["scene_ids"]) == 2
    assert merged["image"] is None
    assert len({button.key for button in app.button if button.key and button.key.startswith("add_")}) > 1


def test_unreadable_private_database_preserves_file_and_public_browsing(tmp_path, monkeypatch):
    directory = tmp_path / "corrupt-private"
    directory.mkdir()
    database = directory / "private.sqlite3"
    original = b"preserve unreadable private data"
    database.write_bytes(original)
    monkeypatch.setenv("ANIMEWAY_DATA_DIR", str(directory))
    app = AppTest.from_file("app.py", default_timeout=30).run()
    assert not app.exception
    assert any("原数据不会被重建或清空" in item.value for item in app.error)
    app.button(key="aw_work_160209").click().run()
    assert not app.exception
    assert app.session_state["aw_page"] == "anime"
    assert database.read_bytes() == original


def test_interface_switches_between_chinese_english_and_japanese():
    app = AppTest.from_file("app.py", default_timeout=20).run()

    assert app.selectbox(key="locale").options == ["简体中文", "English", "日本語"]

    app.selectbox(key="locale").set_value("en_US").run()
    assert [tab.label for tab in app.tabs][:3] == ["Pilgrimage handbooks", "✦ Discover", "✦ Route Log"]

    app.selectbox(key="locale").set_value("ja_JP").run()
    assert [tab.label for tab in app.tabs][:3] == ["巡礼ハンドブック", "✦ 聖地を探す", "✦ 冒険の書"]


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
    app.text_input(key="amap_key").set_value("fake-amap-key").run()
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
