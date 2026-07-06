import json
import os
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List

from geopy.distance import geodesic

from utils import amap, optimization


class RoutePlanner:
    def __init__(self, cache_path: str = "knowledge_base/route_cache.json"):
        self.cache_path = cache_path
        self.cache = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        if not os.path.exists(self.cache_path):
            return {"geocode": {}, "routes": {}}
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("geocode", {})
                data.setdefault("routes", {})
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"geocode": {}, "routes": {}}

    def _save_cache(self) -> None:
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        tmp_path = f"{self.cache_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.cache_path)

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

    def _geocode_start(self, address: str, amap_key: str, warnings: List[str]) -> Dict[str, Any] | None:
        if not address:
            return None
        if not amap_key:
            warnings.append("未设置 Amap Key，已跳过出发地解析，仅使用已收藏地点生成离线预览。")
            return None

        cache_key = address.strip()
        cached = self.cache["geocode"].get(cache_key)
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
        self.cache["geocode"][cache_key] = {
            "lon": lon,
            "lat": lat,
            "city": city,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._save_cache()
        return {
            "name": f"出发地: {address}",
            "cn": f"出发地: {address}",
            "_anime_name": "起点",
            "lat": lat,
            "lon": lon,
            "_city": city,
        }

    def _route_cache_key(self, start: Dict[str, Any], end: Dict[str, Any], city: str, strategy: int) -> str:
        return "|".join(
            [
                self._coord_key(start["lon"], start["lat"]),
                self._coord_key(end["lon"], end["lat"]),
                city or "",
                str(strategy),
            ]
        )

    def _offline_route(self, start: Dict[str, Any], end: Dict[str, Any], reason: str = "offline") -> Dict[str, Any]:
        try:
            dist_km = geodesic(self._coords(start), self._coords(end)).km
        except Exception:
            dist_km = 0.0
        dist_m = int(dist_km * 1000)
        duration_min = max(1, int(dist_km / 40 * 60)) if dist_km else 0
        return {
            "type": "offline",
            "source": reason,
            "distance_m": dist_m,
            "duration_min": duration_min,
            "cost": 0.0,
            "steps": [f"离线预览：直线距离约 {dist_km:.1f}km，实际交通请以地图为准。"],
        }

    def _online_route(self, start: Dict[str, Any], end: Dict[str, Any], amap_key: str, strategy: int) -> Dict[str, Any] | None:
        city = self._point_city(start) or self._point_city(end)
        if not city:
            city = amap.get_regeo_city(start["lon"], start["lat"], amap_key)

        cache_key = self._route_cache_key(start, end, city, strategy)
        cached = self.cache["routes"].get(cache_key)
        if cached:
            cached_route = dict(cached["route"])
            cached_route["cached"] = True
            return cached_route

        route = amap.get_transit_route(start["lon"], start["lat"], end["lon"], end["lat"], city, amap_key, strategy=strategy)
        if not route:
            route = amap.get_walking_route(start["lon"], start["lat"], end["lon"], end["lat"], amap_key)
        if not route:
            route = amap.get_driving_route(start["lon"], start["lat"], end["lon"], end["lat"], amap_key)

        if route:
            route = dict(route)
            route["cached"] = False
            self.cache["routes"][cache_key] = {
                "route": route,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            self._save_cache()
        return route

    def _plan_segment(self, start: Dict[str, Any], end: Dict[str, Any], amap_key: str, strategy: int) -> Dict[str, Any]:
        route = self._online_route(start, end, amap_key, strategy) if amap_key else None
        if not route:
            route = self._offline_route(start, end, reason="offline" if not amap_key else "fallback")
        return route

    def _warnings_for_points(self, points: List[Dict[str, Any]], enable_tsp: bool, amap_key: str) -> List[str]:
        warnings = []
        cities = {self._point_city(point) for point in points if self._point_city(point)}
        if enable_tsp and len(cities) > 1:
            warnings.append("跨城市提醒：TSP 仅按直线距离排序，不代表真实公共交通最优路线。")
        if not amap_key:
            warnings.append("当前为离线预览路线：耗时按直线距离估算，不包含真实换乘、拥堵和票价。")
        return warnings

    @staticmethod
    def _summarize(points: List[Dict[str, Any]], routes: List[Dict[str, Any]], warnings: List[str]) -> Dict[str, Any]:
        total_distance_m = sum(int(float(route.get("distance_m", 0) or 0)) for route in routes)
        total_duration_min = sum(int(float(route.get("duration_min", 0) or 0)) for route in routes)
        total_cost = sum(float(route.get("cost", 0) or 0) for route in routes)
        online_count = sum(1 for route in routes if route.get("type") != "offline")
        offline_count = len(routes) - online_count
        return {
            "stop_count": len(points),
            "segment_count": len(routes),
            "total_distance_km": round(total_distance_m / 1000, 1),
            "total_duration_min": total_duration_min,
            "total_cost": round(total_cost, 1),
            "online_segments": online_count,
            "offline_segments": offline_count,
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
        warnings = []
        route_points = deepcopy(points)
        start_point = self._geocode_start(start_addr, amap_key, warnings)
        if start_point:
            route_points.insert(0, start_point)

        if enable_tsp:
            route_points = optimization.solve_tsp_greedy(route_points)

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
        }
