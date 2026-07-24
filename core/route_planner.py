import hashlib
import json
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from copy import deepcopy
from collections.abc import Iterator
from typing import Any, Dict, List

from geopy.distance import geodesic

from utils import amap, optimization


class RoutePlanner:
    PROVIDER = amap.PROVIDER
    PROVIDER_API_VERSION = amap.API_VERSION
    POLICY_VERSION = "2"
    MAX_ITINERARY_POINTS = 12
    WALK_FIRST_MAX_KM = 2.0
    WALK_FALLBACK_MAX_KM = 5.0
    JAPAN_BOUNDS = (20.0, 46.5, 122.0, 154.0)

    def __init__(self, cache_path: str | None = None, cache_ttl_seconds: int = 24 * 60 * 60):
        self.cache_path = cache_path or self._default_cache_path()
        self.cache_ttl_seconds = max(60, int(cache_ttl_seconds))
        self._init_cache()

    @staticmethod
    def _default_cache_path() -> str:
        configured = os.getenv("ANIMEWAY_ROUTE_CACHE_PATH")
        if configured:
            return configured
        data_dir = os.getenv("ANIMEWAY_DATA_DIR") or os.path.join(tempfile.gettempdir(), "animeway")
        return os.path.join(data_dir, "route_cache.sqlite3")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.cache_path, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_cache(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.cache_path)), exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL,
                    provider TEXT NOT NULL DEFAULT '',
                    api_version TEXT NOT NULL DEFAULT '',
                    mode TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (namespace, cache_key)
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(cache_entries)")
            }
            migrations = {
                "expires_at": "ALTER TABLE cache_entries ADD COLUMN expires_at REAL",
                "provider": "ALTER TABLE cache_entries ADD COLUMN provider TEXT NOT NULL DEFAULT ''",
                "api_version": "ALTER TABLE cache_entries ADD COLUMN api_version TEXT NOT NULL DEFAULT ''",
                "mode": "ALTER TABLE cache_entries ADD COLUMN mode TEXT NOT NULL DEFAULT ''",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    connection.execute(statement)
            connection.execute(
                """
                DELETE FROM cache_entries
                WHERE COALESCE(expires_at, updated_at + ?) < ?
                """,
                (self.cache_ttl_seconds, time.time()),
            )

    def _cache_get(
        self,
        namespace: str,
        cache_key: str,
        mode: str = "",
        provider: str | None = None,
        api_version: str | None = None,
    ) -> Dict[str, Any] | None:
        provider = provider or self.PROVIDER
        api_version = api_version or self.PROVIDER_API_VERSION
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload, updated_at, expires_at
                FROM cache_entries
                WHERE namespace = ? AND cache_key = ?
                  AND provider = ? AND api_version = ? AND mode = ?
                """,
                (namespace, cache_key, provider, api_version, mode),
            ).fetchone()
            if not row:
                return None
            expires_at = (
                float(row[2])
                if row[2] is not None
                else float(row[1]) + self.cache_ttl_seconds
            )
            if expires_at < time.time():
                connection.execute(
                    "DELETE FROM cache_entries WHERE namespace = ? AND cache_key = ?",
                    (namespace, cache_key),
                )
                return None
        try:
            payload = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _cache_set(
        self,
        namespace: str,
        cache_key: str,
        payload: Dict[str, Any],
        mode: str = "",
        provider: str | None = None,
        api_version: str | None = None,
    ) -> None:
        provider = provider or self.PROVIDER
        api_version = api_version or self.PROVIDER_API_VERSION
        updated_at = time.time()
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cache_entries(
                    namespace, cache_key, payload, updated_at, expires_at,
                    provider, api_version, mode
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(namespace, cache_key)
                DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at,
                    provider = excluded.provider,
                    api_version = excluded.api_version,
                    mode = excluded.mode
                """,
                (
                    namespace,
                    cache_key,
                    serialized,
                    updated_at,
                    updated_at + self.cache_ttl_seconds,
                    provider,
                    api_version,
                    mode,
                ),
            )

    @staticmethod
    def _address_cache_key(address: str) -> str:
        normalized = " ".join(address.strip().lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _point_name(point: Dict[str, Any]) -> str:
        return point.get("cn") or point.get("name") or "未知地点"

    @staticmethod
    def _point_city(point: Dict[str, Any]) -> str:
        return point.get("_city") or point.get("city") or ""

    @staticmethod
    def _coords(point: Dict[str, Any]) -> tuple[float, float]:
        return float(point["lat"]), float(point["lon"])

    @staticmethod
    def _coord_key(lon: float, lat: float) -> str:
        return f"{float(lon):.6f},{float(lat):.6f}"

    @staticmethod
    def _distance_km(start: Dict[str, Any], end: Dict[str, Any]) -> float:
        try:
            return float(geodesic(RoutePlanner._coords(start), RoutePlanner._coords(end)).km)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _normalized_city(point: Dict[str, Any]) -> str:
        return optimization.normalize_city(point)

    @classmethod
    def _same_city(cls, start: Dict[str, Any], end: Dict[str, Any]) -> bool:
        start_city = cls._normalized_city(start)
        end_city = cls._normalized_city(end)
        return bool(
            start_city
            and end_city
            and start_city not in optimization.UNKNOWN_CITIES
            and end_city not in optimization.UNKNOWN_CITIES
            and start_city == end_city
        )

    @classmethod
    def _is_japan_point(cls, point: Dict[str, Any]) -> bool:
        try:
            lat = float(point["lat"])
            lon = float(point["lon"])
        except (KeyError, TypeError, ValueError):
            return False
        min_lat, max_lat, min_lon, max_lon = cls.JAPAN_BOUNDS
        return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon

    def _route_profile(
        self,
        start: Dict[str, Any],
        end: Dict[str, Any],
    ) -> tuple[str, list[str], float]:
        distance_km = self._distance_km(start, end)
        if distance_km <= self.WALK_FIRST_MAX_KM:
            return "short_walk", ["walking", "transit", "driving"], distance_km
        if self._same_city(start, end):
            modes = ["transit"]
            if distance_km <= self.WALK_FALLBACK_MAX_KM:
                modes.append("walking")
            modes.append("driving")
            return "urban_transit", modes, distance_km
        return "intercity_rail", ["transit", "driving"], distance_km

    def _geocode_start(self, address: str, amap_key: str, warnings: List[str]) -> Dict[str, Any] | None:
        if not address:
            return None
        if not amap_key:
            warnings.append("未设置 Amap Key，已跳过出发地解析，仅使用已收藏地点生成离线预览。")
            return None

        cache_key = self._address_cache_key(address)
        cached = self._cache_get("geocode", cache_key, mode="geocode")
        if cached:
            return {
                "name": f"出发地: {address}",
                "cn": f"出发地: {address}",
                "_anime_name": "起点",
                "lat": cached["lat"],
                "lon": cached["lon"],
                "_city": cached.get("city", ""),
            }

        lon, lat = amap.get_location_coords(address, amap_key)
        if lon is None or lat is None:
            warnings.append(f"未能解析出发地“{address}”，已从第一个收藏地点开始规划。")
            return None

        city = amap.get_regeo_city(lon, lat, amap_key)
        self._cache_set(
            "geocode",
            cache_key,
            {
                "lon": lon,
                "lat": lat,
                "city": city,
            },
            mode="geocode",
        )
        return {
            "name": f"出发地: {address}",
            "cn": f"出发地: {address}",
            "_anime_name": "起点",
            "lat": lat,
            "lon": lon,
            "_city": city,
        }

    def _route_cache_key(
        self,
        start: Dict[str, Any],
        end: Dict[str, Any],
        profile: str,
        strategy: int,
    ) -> str:
        source = "|".join(
            [
                self.PROVIDER,
                self.PROVIDER_API_VERSION,
                self.POLICY_VERSION,
                profile,
                self._coord_key(start["lon"], start["lat"]),
                self._coord_key(end["lon"], end["lat"]),
                self._point_city(start),
                self._point_city(end),
                str(strategy),
            ]
        )
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    def _offline_route(
        self,
        start: Dict[str, Any],
        end: Dict[str, Any],
        profile: str,
        reason: str = "offline",
    ) -> Dict[str, Any]:
        dist_km = self._distance_km(start, end)
        dist_m = int(dist_km * 1000)
        speed_kmh = {
            "short_walk": 5,
            "urban_transit": 25,
            "intercity_rail": 80,
        }.get(profile, 40)
        duration_min = max(1, int(dist_km / speed_kmh * 60)) if dist_km else 0
        return {
            "type": "offline",
            "source": "offline_estimate",
            "fallback_reason": reason,
            "recommended_mode": profile,
            "distance_m": dist_m,
            "duration_min": duration_min,
            "cost": 0.0,
            "steps": [
                f"离线估算：直线距离约 {dist_km:.1f}km，"
                "不是道路或铁路路径，请以当地地图服务为准。"
            ],
            "polyline": [
                [float(start["lon"]), float(start["lat"])],
                [float(end["lon"]), float(end["lat"])],
            ],
            "estimated": True,
            "provider": "offline",
            "provider_version": self.POLICY_VERSION,
        }

    def _online_route(
        self,
        start: Dict[str, Any],
        end: Dict[str, Any],
        amap_key: str,
        strategy: int,
        profile: str,
        modes: List[str],
    ) -> Dict[str, Any] | None:
        start_city = self._point_city(start)
        end_city = self._point_city(end)
        if not start_city:
            start_city = amap.get_regeo_city(start["lon"], start["lat"], amap_key)
        if not end_city:
            end_city = amap.get_regeo_city(end["lon"], end["lat"], amap_key)

        cache_mode = f"{profile}:{','.join(modes)}"
        cache_key = self._route_cache_key(start, end, cache_mode, strategy)
        cached = self._cache_get("route", cache_key, mode=cache_mode)
        if cached:
            cached_route = dict(cached)
            cached_route["cached"] = True
            return cached_route

        route = None
        for mode in modes:
            if mode == "walking":
                route = amap.get_walking_route(
                    start["lon"],
                    start["lat"],
                    end["lon"],
                    end["lat"],
                    amap_key,
                )
            elif mode == "transit" and start_city:
                route = amap.get_transit_route(
                    start["lon"],
                    start["lat"],
                    end["lon"],
                    end["lat"],
                    start_city,
                    amap_key,
                    strategy=strategy,
                    destination_city=end_city,
                )
            elif mode == "driving":
                route = amap.get_driving_route(
                    start["lon"],
                    start["lat"],
                    end["lon"],
                    end["lat"],
                    amap_key,
                )
            if route:
                break

        if route:
            route = dict(route)
            route["cached"] = False
            route["estimated"] = False
            route["requested_profile"] = profile
            route["provider"] = self.PROVIDER
            route["provider_version"] = self.PROVIDER_API_VERSION
            cached_route = {key: value for key, value in route.items() if key != "raw"}
            self._cache_set(
                "route",
                cache_key,
                cached_route,
                mode=cache_mode,
            )
        return route

    def _plan_segment(self, start: Dict[str, Any], end: Dict[str, Any], amap_key: str, strategy: int) -> Dict[str, Any]:
        profile, modes, _ = self._route_profile(start, end)
        route = (
            self._online_route(start, end, amap_key, strategy, profile, modes)
            if amap_key
            else None
        )
        if not route:
            route = self._offline_route(
                start,
                end,
                profile=profile,
                reason="no_api_key" if not amap_key else "provider_unavailable",
            )
        return route

    def _warnings_for_points(self, points: List[Dict[str, Any]], enable_tsp: bool, amap_key: str) -> List[str]:
        warnings: List[str] = []
        cities = {self._point_city(point) for point in points if self._point_city(point)}
        if enable_tsp and len(cities) > 1:
            warnings.append(
                "跨城市路线已按城市聚类，只在城市内部执行 TSP；"
                "城市间顺序保留首次加入顺序。"
            )
        if not amap_key:
            warnings.append("当前为离线预览路线：耗时按直线距离估算，不包含真实换乘、拥堵和票价。")
        elif any(self._is_japan_point(point) for point in points):
            warnings.append(
                "地图服务提示：高德未公开承诺日本公交/铁路路线覆盖；"
                "海外逆地理编码可能需要单独权限且不返回 cityCode。"
                "在线结果仅在接口实际返回路径时采用。"
            )
        if len(cities) > 1:
            warnings.append("跨城段会优先请求公共交通/铁路方案，失败时显示明确的离线估算直线。")
        return warnings

    @staticmethod
    def _summarize(points: List[Dict[str, Any]], routes: List[Dict[str, Any]], warnings: List[str]) -> Dict[str, Any]:
        total_distance_m = sum(int(float(route.get("distance_m", 0) or 0)) for route in routes)
        total_duration_min = sum(int(float(route.get("duration_min", 0) or 0)) for route in routes)
        total_cost = sum(float(route.get("cost", 0) or 0) for route in routes)
        online_count = sum(1 for route in routes if route.get("type") != "offline")
        offline_count = len(routes) - online_count
        estimated_count = sum(1 for route in routes if route.get("estimated"))
        return {
            "stop_count": len(points),
            "segment_count": len(routes),
            "total_distance_km": round(total_distance_m / 1000, 1),
            "total_duration_min": total_duration_min,
            "total_cost": round(total_cost, 1),
            "online_segments": online_count,
            "offline_segments": offline_count,
            "estimated_segments": estimated_count,
            "warnings": warnings,
        }

    @staticmethod
    def _segments(points: List[Dict[str, Any]], routes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        segments = []
        for idx, route in enumerate(routes):
            start = points[idx]
            end = points[idx + 1]
            segments.append(
                {
                    "index": idx + 1,
                    "from": RoutePlanner._point_name(start),
                    "to": RoutePlanner._point_name(end),
                    "mode": route.get("type", "unknown"),
                    "distance_km": round(float(route.get("distance_m", 0) or 0) / 1000, 1),
                    "duration_min": int(float(route.get("duration_min", 0) or 0)),
                    "cost": route.get("cost", 0),
                    "steps": route.get("steps", []),
                    "cached": bool(route.get("cached")),
                    "estimated": bool(route.get("estimated")),
                    "provider": route.get("provider", "unknown"),
                    "provider_version": route.get("provider_version", ""),
                    "recommended_mode": route.get("recommended_mode")
                    or route.get("requested_profile"),
                    "polyline": route.get("polyline", []),
                }
            )
        return segments

    def plan(
        self,
        points: List[Dict[str, Any]],
        start_addr: str = "",
        amap_key: str = "",
        enable_tsp: bool = True,
        strategy: int = 0,
    ) -> Dict[str, Any]:
        if len(points) > self.MAX_ITINERARY_POINTS:
            raise ValueError(
                f"Route planning supports at most {self.MAX_ITINERARY_POINTS} itinerary points."
            )
        warnings: List[str] = []
        route_points = deepcopy(points)
        start_point = self._geocode_start(start_addr, amap_key, warnings)
        if start_point:
            route_points.insert(0, start_point)

        if enable_tsp:
            route_points = optimization.solve_tsp_by_city(route_points)

        warnings.extend(self._warnings_for_points(route_points, enable_tsp, amap_key))
        routes = []
        for idx in range(max(0, len(route_points) - 1)):
            routes.append(self._plan_segment(route_points[idx], route_points[idx + 1], amap_key, strategy))

        summary = self._summarize(route_points, routes, warnings)
        return {
            "points": route_points,
            "routes": routes,
            "segments": self._segments(route_points, routes),
            "summary": summary,
            "warnings": warnings,
            "provider": {
                "name": self.PROVIDER if amap_key else "offline",
                "api_version": self.PROVIDER_API_VERSION if amap_key else self.POLICY_VERSION,
                "policy_version": self.POLICY_VERSION,
            },
        }
