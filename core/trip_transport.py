"""One transport result contract for Tokyo Trip drafts and routebook previews.

No provider has passed the Tokyo transit acceptance set. A walking calculation
is an estimate, and a transit request never silently becomes a walk or drive.
"""
from __future__ import annotations

from datetime import date, datetime
import math
from zoneinfo import ZoneInfo

from geopy.distance import geodesic

POLICY_VERSION = "tokyo-trip-transport-v1"
WALK_DETOUR = 1.35
WALK_METERS_PER_MINUTE = 65
MAX_WALK_STRAIGHT_METERS = 5000


def resolve_anchor(anchor: dict, catalog: dict) -> dict | None:
    if not anchor.get("confirmed"):
        return None
    if anchor.get("location_id"):
        point = next((p for p in catalog["locations"] if p["id"] == anchor["location_id"]), None)
        return dict(point) if point and not point.get("withdrawn") and (point.get("access") or {}).get("status") not in {"closed", "prohibited", "forbidden", "no_entry"} else None
    if anchor.get("lat") is None or anchor.get("lon") is None:
        return None
    return {"id": "manual", "name": anchor["name"], "lat": anchor["lat"], "lon": anchor["lon"]}


def connection(origin: dict | None, destination: dict | None, mode: str, catalog: dict,
               *, day_date: str = "", departure_min: int | None = None,
               overridden: bool = False) -> dict:
    """Return the complete evidence for a single requested leg.

    ``None`` means unknown. Only an explicit no-fare mode may report zero fare.
    The date and departure are context, not a claim of timetable coverage.
    """
    if mode not in {"walk", "transit"}:
        raise ValueError("不支持的交通方式")
    result = {"mode": mode, "requested_mode": mode, "actual_mode": None,
              "overridden": overridden, "status": "unknown", "move_min": None,
              "wait_min": None, "walk_m": None, "fare_jpy": None,
              "fare_status": "unknown", "source_url": "", "checked_at": "",
              "provider": "none", "policy_version": POLICY_VERSION,
              "date": day_date, "departure_min": departure_min,
              "from_id": origin.get("id") if origin else None,
              "to_id": destination.get("id") if destination else None,
              "from_source_version": origin.get("source_version", "") if origin else "",
              "to_source_version": destination.get("source_version", "") if destination else "",
              "from_coord": [origin["lat"], origin["lon"]] if origin else None,
              "to_coord": [destination["lat"], destination["lon"]] if destination else None,
              "reason": "起点或终点尚未确认", "exact": False}
    if not origin or not destination:
        if mode == "walk":
            result.update(fare_jpy=0, fare_status="not_applicable")
        return result
    distance = geodesic((origin["lat"], origin["lon"]), (destination["lat"], destination["lon"])).meters
    result["straight_distance_m"] = math.ceil(distance)
    if distance < 1:
        return {**result, "status": "same_location", "actual_mode": "none",
                "move_min": 0, "wait_min": 0, "walk_m": 0, "fare_jpy": 0,
                "fare_status": "not_applicable", "exact": True, "reason": "同一位置，无站间移动"}
    if mode == "transit":
        return {**result, "reason": "日本公交／铁路尚未通过样本核验，请在外部地图确认；未改用驾车或步行"}
    result.update(fare_jpy=0, fare_status="not_applicable")
    if distance > MAX_WALK_STRAIGHT_METERS:
        return {**result, "reason": "直线距离超过 5 公里，超出短途步行草案范围；请减少跨片区或主动选择其他交通"}
    # Detour factor is explicitly a draft assumption, never street geometry.
    estimated_walk = math.ceil(distance * WALK_DETOUR)
    result.update(status="estimated", actual_mode="walk", provider="local_estimate",
                  move_min=max(1, math.ceil(estimated_walk / WALK_METERS_PER_MINUTE)), wait_min=0,
                  walk_m=estimated_walk,
                  reason="直线距离 × 1.35，按 65 米／分钟估算；不含台阶、信号灯和施工，不用于赶预约或末班车")
    for route in catalog.get("routes", []):
        for item in route.get("connections", []):
            if (item.get("from_location_id"), item.get("to_location_id"), item.get("status")) == (
                origin.get("id"), destination.get("id"), "official_reference"
            ):
                # A station-to-shrine reference cannot become exact pin-to-pin routing.
                result.update(source_url=item.get("source_url", ""), checked_at=item.get("checked_at", ""),
                              reference=f"官方接近参考 {item['duration_min']} 分钟。{item.get('scope', '')}")
    return result


def stale(value: str | None, *, today: date | None = None, max_days: int = 30) -> bool:
    try:
        checked = date.fromisoformat(str(value)[:10])
        delta = ((today or datetime.now(ZoneInfo("Asia/Tokyo")).date()) - checked).days
        return delta < 0 or delta > max_days
    except (ValueError, TypeError):
        return True
