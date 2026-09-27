"""End-to-end natural-language anime pilgrimage routebook orchestration."""
from __future__ import annotations

from copy import deepcopy

from core.trip import evaluate
from core.trip_ai import request_routebook


def generate_routebook(text, *, store, token, catalog, qwen_key, amap_key, route_planner, locale="zh_CN"):
    """Plan from a user request, ground stops in the catalog, then route each day."""
    draft = request_routebook(store, token, text, catalog, qwen_key)
    plan = draft["plan"]
    places = {point["id"]: point for point in catalog.get("locations", [])}
    works = {str(work["id"]): work for work in catalog.get("anime", [])}
    route_days, flat_routes, warnings = [], [], []
    for day in plan["days"]:
        points = []
        for stop in day["stops"]:
            point = places.get(stop["location_id"])
            if not point:
                raise ValueError("地点资料刚刚变化，请重新生成路书")
            item = deepcopy(point)
            matched = next((works[work_id] for work_id in item.get("anime_ids", []) if work_id in works), {})
            item["_anime_name"] = matched.get("cn") or matched.get("name") or "关联作品"
            item["_city"] = item.get("city") or item.get("region") or "东京"
            points.append(item)
        route = route_planner.plan(points, amap_key=amap_key, enable_tsp=True)
        optimized_ids = [point.get("id") for point in route.get("points", []) if point.get("id") in {item["id"] for item in points}]
        if len(optimized_ids) == len(points):
            day["stops"] = sorted(day["stops"], key=lambda stop: optimized_ids.index(stop["location_id"]))
            points = [places[location_id] | {
                "_anime_name": next((works[work_id].get("cn") or works[work_id].get("name") or "关联作品"
                                     for work_id in places[location_id].get("anime_ids", []) if work_id in works), "关联作品"),
                "_city": places[location_id].get("city") or places[location_id].get("region") or "东京",
            } for location_id in optimized_ids]
        clean_routes = []
        for segment in route.get("routes", []):
            segment = {key: value for key, value in segment.items() if key != "raw"}
            clean_routes.append(segment)
        day_route = {"summary": route.get("summary", {}), "segments": route.get("segments", []),
                     "routes": clean_routes, "warnings": route.get("warnings", [])}
        route_days.append({"date": day["date"], "start_min": day["start_min"], "end_min": day["end_min"],
                           "location_ids": optimized_ids if len(optimized_ids) == len(points) else [point["id"] for point in points], "route": day_route})
        flat_routes.extend(clean_routes)
        warnings.extend(route.get("warnings", []))
    if amap_key and any(route.get("type") == "offline" for route in flat_routes):
        warnings.append("东京路线未取得高德在线结果。请确认 Key 已开通海外 Web 服务权限；海外公交能力还取决于高德当前服务范围。已保留直线距离估算，不能作为导航路线。")
    return {"plan": plan, "evaluation": evaluate(plan, catalog), "days": route_days,
            "guide": "Qwen 根据你的作品、日期和节奏选择地点并分配日期；本地再按片区与近邻距离调整每日顺序。地点关联、场景图及路线步骤分别来自项目资料库与路线服务；访问状态和未验证项请按下方提醒现场复核。",
            "warnings": list(dict.fromkeys(warnings)),
            "route_provider": "AMap Web Service" if amap_key else "offline estimate"}
