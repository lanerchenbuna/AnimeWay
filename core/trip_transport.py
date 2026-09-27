"""Tokyo transport evidence for Trip drafts. No silent mode substitution.

No paid provider has passed the Tokyo acceptance set yet. Walking estimates
remain estimates; transit has no invented timetable or fare. This boundary is
independent of the older best-effort route-preview feature.
"""
from __future__ import annotations

from datetime import date, datetime
import math
from zoneinfo import ZoneInfo

from geopy.distance import geodesic


def resolve_anchor(anchor: dict, catalog: dict) -> dict | None:
    if not anchor.get("confirmed"):
        return None
    if anchor.get("location_id"):
        point = next((p for p in catalog["locations"] if p["id"] == anchor["location_id"]), None)
        return dict(point) if point and not point.get("withdrawn") and (point.get("access") or {}).get("status") not in {"closed", "prohibited", "forbidden", "no_entry"} else None
    if anchor.get("lat") is None or anchor.get("lon") is None:
        return None
    return {"id": "manual", "name": anchor["name"], "lat": anchor["lat"], "lon": anchor["lon"]}


def connection(origin: dict | None, destination: dict | None, mode: str, catalog: dict) -> dict:
    result = {"mode": mode, "status": "unknown", "move_min": None, "wait_min": None,
              "walk_m": None, "fare_jpy": None, "fare_status": "unknown", "source_url": "", "checked_at": "",
              "reason": "起点或终点尚未确认", "exact": False}
    if not origin or not destination:
        return result
    distance = geodesic((origin["lat"], origin["lon"]), (destination["lat"], destination["lon"])).meters
    if distance < 1:
        return {**result, "status": "same_location", "move_min": 0, "wait_min": 0,
                "walk_m": 0, "fare_jpy": 0, "fare_status": "not_applicable", "exact": True, "reason": "同一位置，无站间移动"}
    if mode == "transit":
        return {**result, "reason": "日本公交／铁路尚未通过样本核验，请在外部地图确认；未改用驾车或步行"}
    if distance > 5000:
        return {**result, "reason": "直线距离超过 5 公里，超出短途步行草案范围；请减少跨片区或主动选择其他交通"}
    # Detour factor is explicitly a draft assumption, never street geometry.
    estimated_walk = math.ceil(distance * 1.35)
    result.update(status="estimated", move_min=max(1, math.ceil(estimated_walk / 65)), wait_min=0,
                  walk_m=estimated_walk, fare_jpy=0, fare_status="not_applicable",
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
