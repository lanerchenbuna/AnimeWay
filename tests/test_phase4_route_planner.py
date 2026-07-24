import sqlite3
from contextlib import closing

import requests

from components.plan import build_map_paths, calculate_map_view
from core.route_planner import RoutePlanner
from utils import amap, optimization


def sample_points():
    return [
        {"name": "下北沢SHELTER", "lat": 35.6615, "lon": 139.6694, "_city": "东京都"},
        {"name": "京都站前", "lat": 34.9858, "lon": 135.7588, "_city": "京都府"},
    ]


def test_offline_route_preview_without_amap_key(tmp_path):
    planner = RoutePlanner(cache_path=str(tmp_path / "route_cache.sqlite3"))

    plan = planner.plan(sample_points(), amap_key="", enable_tsp=False)

    assert plan["routes"]
    assert plan["routes"][0]["type"] == "offline"
    assert plan["summary"]["offline_segments"] == 1
    assert any("离线预览" in warning for warning in plan["warnings"])


def test_cross_city_tsp_warning(tmp_path):
    planner = RoutePlanner(cache_path=str(tmp_path / "route_cache.sqlite3"))

    plan = planner.plan(sample_points(), amap_key="", enable_tsp=True)

    assert any("按城市聚类" in warning for warning in plan["warnings"])


def test_online_route_is_cached(tmp_path, monkeypatch):
    planner = RoutePlanner(cache_path=str(tmp_path / "route_cache.sqlite3"))
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
    second_planner = RoutePlanner(cache_path=str(tmp_path / "route_cache.sqlite3"))
    second = second_planner.plan(sample_points(), amap_key="key", enable_tsp=False)

    assert calls["transit"] == 1
    assert first["summary"]["online_segments"] == 1
    assert second["routes"][0]["cached"] is True


def test_japan_online_plan_discloses_provider_coverage_limit(tmp_path, monkeypatch):
    planner = RoutePlanner(cache_path=str(tmp_path / "route_cache.sqlite3"))
    monkeypatch.setattr(
        amap,
        "get_transit_route",
        lambda *args, **kwargs: {
            "type": "rail",
            "distance_m": 450000,
            "duration_min": 150,
            "cost": 0,
            "steps": ["测试铁路"],
            "polyline": [],
        },
    )

    plan = planner.plan(sample_points(), amap_key="key", enable_tsp=False)

    assert any("未公开承诺日本" in warning for warning in plan["warnings"])


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


def test_geocode_cache_hashes_user_address(tmp_path, monkeypatch):
    cache_path = tmp_path / "route_cache.sqlite3"
    planner = RoutePlanner(cache_path=str(cache_path))
    monkeypatch.setattr("core.route_planner.amap.get_location_coords", lambda *args, **kwargs: (139.7, 35.6))
    monkeypatch.setattr("core.route_planner.amap.get_regeo_city", lambda *args, **kwargs: "010")
    monkeypatch.setattr(
        "core.route_planner.amap.get_transit_route",
        lambda *args, **kwargs: {
            "type": "transit",
            "distance_m": 1000,
            "duration_min": 10,
            "cost": 100,
            "steps": ["测试线路"],
        },
    )

    planner.plan(
        [sample_points()[0]],
        start_addr="我的私人出发地址",
        amap_key="key",
        enable_tsp=False,
    )

    assert "我的私人出发地址".encode("utf-8") not in cache_path.read_bytes()


def test_route_cache_expires_stale_entries(tmp_path):
    planner = RoutePlanner(
        cache_path=str(tmp_path / "route_cache.sqlite3"),
        cache_ttl_seconds=60,
    )
    planner._cache_set("route", "stale-key", {"type": "walking"})
    with planner._connect() as connection:
        connection.execute(
            "UPDATE cache_entries SET expires_at = 0 WHERE namespace = ? AND cache_key = ?",
            ("route", "stale-key"),
        )

    assert planner._cache_get("route", "stale-key") is None


def test_route_mode_profile_depends_on_distance_and_city(tmp_path):
    planner = RoutePlanner(cache_path=str(tmp_path / "route_cache.sqlite3"))
    tokyo_a = {"lat": 35.6812, "lon": 139.7671, "_city": "东京都"}
    tokyo_near = {"lat": 35.6840, "lon": 139.7570, "_city": "东京都"}
    tokyo_far = {"lat": 35.4437, "lon": 139.6380, "_city": "东京都"}
    kyoto = {"lat": 34.9858, "lon": 135.7588, "_city": "京都府"}

    short_profile, short_modes, _ = planner._route_profile(tokyo_a, tokyo_near)
    urban_profile, urban_modes, _ = planner._route_profile(tokyo_a, tokyo_far)
    intercity_profile, intercity_modes, _ = planner._route_profile(tokyo_a, kyoto)

    assert short_profile == "short_walk"
    assert short_modes[0] == "walking"
    assert urban_profile == "urban_transit"
    assert urban_modes[0] == "transit"
    assert intercity_profile == "intercity_rail"
    assert intercity_modes[0] == "transit"


def test_short_online_segment_attempts_walking_before_transit(tmp_path, monkeypatch):
    planner = RoutePlanner(cache_path=str(tmp_path / "route_cache.sqlite3"))
    calls = []
    points = [
        {"name": "A", "lat": 35.6812, "lon": 139.7671, "_city": "东京都"},
        {"name": "B", "lat": 35.6840, "lon": 139.7570, "_city": "东京都"},
    ]

    def fake_walking(*args, **kwargs):
        calls.append("walking")
        return {
            "type": "walking",
            "distance_m": 1000,
            "duration_min": 12,
            "steps": ["步行"],
            "polyline": [[139.7671, 35.6812], [139.7570, 35.6840]],
        }

    monkeypatch.setattr(amap, "get_walking_route", fake_walking)
    monkeypatch.setattr(amap, "get_transit_route", lambda *args, **kwargs: calls.append("transit"))
    monkeypatch.setattr(amap, "get_driving_route", lambda *args, **kwargs: calls.append("driving"))

    plan = planner.plan(points, amap_key="key", enable_tsp=False)

    assert calls == ["walking"]
    assert plan["routes"][0]["type"] == "walking"
    assert plan["routes"][0]["estimated"] is False


def test_tsp_clusters_by_city_without_cross_city_greedy():
    points = [
        {"name": "东京 A", "lat": 35.68, "lon": 139.76, "_city": "东京都"},
        {"name": "京都 A", "lat": 34.98, "lon": 135.75, "_city": "京都府"},
        {"name": "东京 B", "lat": 35.69, "lon": 139.77, "_city": "东京都"},
    ]

    optimized = optimization.solve_tsp_by_city(points)

    assert [point["name"] for point in optimized] == ["东京 A", "东京 B", "京都 A"]


def test_distance_matrix_calculates_each_symmetric_pair_once(monkeypatch):
    calls = []

    class Distance:
        km = 1.0

    def fake_geodesic(start, end):
        calls.append((start, end))
        return Distance()

    monkeypatch.setattr(optimization, "geodesic", fake_geodesic)
    points = [
        {"lat": 35.0, "lon": 139.0},
        {"lat": 35.1, "lon": 139.1},
        {"lat": 35.2, "lon": 139.2},
        {"lat": 35.3, "lon": 139.3},
    ]

    matrix = optimization.calculate_distance_matrix(points)

    assert len(calls) == 6
    assert matrix[0][3] == matrix[3][0] == 1.0


def test_cache_records_provider_version_mode_and_expiry(tmp_path):
    cache_path = tmp_path / "route_cache.sqlite3"
    planner = RoutePlanner(cache_path=str(cache_path))

    planner._cache_set("route", "scoped", {"type": "walking"}, mode="short_walk")

    with closing(sqlite3.connect(cache_path)) as connection:
        row = connection.execute(
            """
            SELECT provider, api_version, mode, expires_at, updated_at
            FROM cache_entries
            WHERE cache_key = ?
            """,
            ("scoped",),
        ).fetchone()
    assert row is not None
    assert row[0] == "amap"
    assert row[1] == "v3"
    assert row[2] == "short_walk"
    assert row[3] > row[4]


def test_map_view_fits_local_and_cross_city_bounds():
    local = calculate_map_view(
        [
            {"lat": 35.6812, "lon": 139.7671},
            {"lat": 35.6895, "lon": 139.6917},
        ]
    )
    cross_city = calculate_map_view(sample_points())

    assert local["zoom"] > cross_city["zoom"]
    assert 135 < cross_city["longitude"] < 140


def test_map_paths_use_provider_polyline_and_mark_offline_estimate():
    points = sample_points()
    online = {
        "type": "rail",
        "polyline": [[139.6694, 35.6615], [138.0, 35.2], [135.7588, 34.9858]],
    }
    offline = {
        "type": "offline",
        "polyline": [[139.6694, 35.6615], [135.7588, 34.9858]],
    }

    online_path = build_map_paths(points, [online])[0]
    offline_path = build_map_paths(points, [offline])[0]

    assert online_path["geometry"] == "provider_polyline"
    assert len(online_path["path"]) == 3
    assert offline_path["geometry"] == "estimated"
    assert offline_path["label"] == "离线估算直线"


def test_route_planner_rejects_unbounded_itinerary(tmp_path):
    planner = RoutePlanner(cache_path=str(tmp_path / "route_cache.sqlite3"))
    points = [
        {"name": str(index), "lat": 35 + index / 1000, "lon": 139, "_city": "东京都"}
        for index in range(RoutePlanner.MAX_ITINERARY_POINTS + 1)
    ]

    try:
        planner.plan(points)
    except ValueError as error:
        assert "at most" in str(error)
    else:
        raise AssertionError("Expected route planner to reject an oversized itinerary")


def test_amap_timeout_returns_no_route(monkeypatch):
    monkeypatch.setattr(
        amap.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout()),
    )

    assert amap.get_walking_route(139.0, 35.0, 139.1, 35.1, "key") is None


def test_amap_walking_route_preserves_polyline(monkeypatch):
    class Response:
        def json(self):
            return {
                "status": "1",
                "route": {
                    "paths": [
                        {
                            "distance": "1200",
                            "duration": "900",
                            "steps": [
                                {
                                    "instruction": "向前步行",
                                    "polyline": "139.0,35.0;139.05,35.05;139.1,35.1",
                                }
                            ],
                        }
                    ]
                },
            }

    monkeypatch.setattr(amap.requests, "get", lambda *args, **kwargs: Response())

    route = amap.get_walking_route(139.0, 35.0, 139.1, 35.1, "key")

    assert route["polyline"] == [
        [139.0, 35.0],
        [139.05, 35.05],
        [139.1, 35.1],
    ]


def test_amap_cross_city_transit_sends_destination_city(monkeypatch):
    captured = {}

    class Response:
        def json(self):
            return {"status": "1", "route": {"transits": []}}

    def fake_get(url, params=None, timeout=None):
        captured["params"] = params
        return Response()

    monkeypatch.setattr(amap.requests, "get", fake_get)

    route = amap.get_transit_route(
        139.0,
        35.0,
        135.0,
        34.0,
        "东京都",
        "key",
        destination_city="京都府",
    )

    assert route is None
    assert captured["params"]["city"] == "东京都"
    assert captured["params"]["cityd"] == "京都府"


def test_amap_overseas_reverse_geocode_falls_back_to_city_name(monkeypatch):
    class Response:
        def json(self):
            return {
                "status": "1",
                "regeocode": {
                    "addressComponent": {
                        "citycode": "",
                        "adcode": "",
                        "city": "Tokyo",
                    }
                },
            }

    monkeypatch.setattr(amap.requests, "get", lambda *args, **kwargs: Response())

    assert amap.get_regeo_city(139.7, 35.6, "key") == "Tokyo"
