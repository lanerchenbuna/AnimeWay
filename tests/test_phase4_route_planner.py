from core.route_planner import RoutePlanner
from utils import amap


def sample_points():
    return [
        {"name": "下北沢SHELTER", "lat": 35.6615, "lon": 139.6694, "_city": "东京都"},
        {"name": "京都站前", "lat": 34.9858, "lon": 135.7588, "_city": "京都府"},
    ]


def test_offline_route_preview_without_amap_key(tmp_path):
    planner = RoutePlanner(cache_path=str(tmp_path / "route_cache.json"))

    plan = planner.plan(sample_points(), amap_key="", enable_tsp=False)

    assert plan["routes"]
    assert plan["routes"][0]["type"] == "offline"
    assert plan["summary"]["offline_segments"] == 1
    assert any("离线预览" in warning for warning in plan["warnings"])


def test_cross_city_tsp_warning(tmp_path):
    planner = RoutePlanner(cache_path=str(tmp_path / "route_cache.json"))

    plan = planner.plan(sample_points(), amap_key="", enable_tsp=True)

    assert any("跨城市提醒" in warning for warning in plan["warnings"])


def test_online_route_is_cached(tmp_path, monkeypatch):
    planner = RoutePlanner(cache_path=str(tmp_path / "route_cache.json"))
    calls = {"transit": 0}

    def fake_transit(*args, **kwargs):
        calls["transit"] += 1
        return {
            "type": "transit",
            "distance_m": 1200,
            "duration_min": 15,
            "cost": 220,
            "steps": ["乘坐 [测试线] (2站)"],
        }

    monkeypatch.setattr("core.route_planner.amap.get_transit_route", fake_transit)
    monkeypatch.setattr("core.route_planner.amap.get_walking_route", lambda *args, **kwargs: None)
    monkeypatch.setattr("core.route_planner.amap.get_driving_route", lambda *args, **kwargs: None)
    monkeypatch.setattr("core.route_planner.amap.get_regeo_city", lambda *args, **kwargs: "010")

    first = planner.plan(sample_points(), amap_key="key", enable_tsp=False)
    second = planner.plan(sample_points(), amap_key="key", enable_tsp=False)

    assert calls["transit"] == 1
    assert first["summary"]["online_segments"] == 1
    assert second["routes"][0]["cached"] is True


def test_amap_geocode_uses_params(monkeypatch):
    captured = {}

    class Response:
        def json(self):
            return {"status": "1", "geocodes": [{"location": "139.1,35.1"}]}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(amap.requests, "get", fake_get)

    lon, lat = amap.get_location_coords("秋叶原站", "secret", city="东京")

    assert (lon, lat) == (139.1, 35.1)
    assert captured["url"].endswith("/v3/geocode/geo")
    assert captured["params"]["address"] == "秋叶原站"
    assert captured["params"]["key"] == "secret"
    assert captured["params"]["city"] == "东京"
