"""External directions for a user-confirmed Trip leg, never an arrival event."""
from __future__ import annotations

import math
from urllib.parse import urlencode


def directions_url(place: dict, mode: str) -> str:
    if mode not in {"walk", "transit"}:
        raise ValueError("不支持的导航交通方式")
    try:
        lat, lon = float(place["lat"]), float(place["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("地点坐标无效，不能打开导航") from exc
    if not math.isfinite(lat) or not math.isfinite(lon) or not 35.4 <= lat <= 35.9 or not 139.3 <= lon <= 139.95:
        raise ValueError("地点不在东京试点范围，不能打开导航")
    return "https://www.google.com/maps/dir/?" + urlencode({
        "api": "1", "destination": f"{lat:.6f},{lon:.6f}",
        "travelmode": "walking" if mode == "walk" else "transit", "dir_action": "navigate",
    })
