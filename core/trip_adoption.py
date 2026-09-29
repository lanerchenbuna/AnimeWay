"""Review old handbook/backpack points before creating a personal Trip draft."""
from __future__ import annotations

from core.place_links import trip_eligible
from core.trip import MAX_DAILY_STOPS, empty_plan, new_requirements, stop_spec, validate_plan


def review_legacy_places(items: list[dict], catalog: dict) -> list[dict]:
    """Preserve source order and report every point, including duplicates/lost IDs."""
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError("旧清单数量无效")
    places = {point["id"]: point for point in catalog["locations"]}
    seen = set()
    rows = []
    for item in items:
        location_id = str(item.get("id") or "")
        current = places.get(location_id)
        source_name = item.get("name") or item.get("spot_name") or item.get("cn") or location_id
        if not location_id:
            reason = "缺少地点编号"
        elif location_id in seen:
            reason = "同一现实地点重复出现；个人 Trip 只安排一次"
        elif not current:
            reason = "不在东京试点地点目录中，暂不能安排"
        elif not trip_eligible(current, catalog):
            reason = "地点已关闭、撤下或不在东京试点范围，需先核查"
        else:
            reason = ""
        seen.add(location_id)
        changed_facts = []
        if current:
            if source_name and source_name != location_id and source_name != current.get("name"):
                changed_facts.append("名称")
            if any(item.get(field) is not None and item[field] != current.get(field)
                   for field in ("lat", "lon")):
                changed_facts.append("坐标")
            if (item.get("access") or {}).get("status") and (item["access"]["status"] !=
                                                          (current.get("access") or {}).get("status")):
                changed_facts.append("访问状态")
        rows.append({"id": location_id, "name": current.get("name") if current else source_name,
                     "source_name": source_name, "changed_facts": changed_facts,
                     "eligible": not reason, "reason": reason,
                     "required": bool(item.get("required", False)),
                     "stay_min": (item["stay_max"] if item.get("stay_max") is not None else
                                  item["stay_min"] if item.get("stay_min") is not None else 25),
                     "stay_defaulted": item.get("stay_max") is None and item.get("stay_min") is None,
                     "anime_ids": list(map(str, current.get("anime_ids", []))) if current else []})
    return rows


def draft_from_legacy(items: list[dict], catalog: dict, *, selected_ids: list[str],
                      start_date: str, day_count: int, title: str, mode: str = "walk") -> dict:
    """Adopt only IDs the user explicitly selected from the reviewed source."""
    review = review_legacy_places(items, catalog)
    if not isinstance(selected_ids, list) or not selected_ids or len(set(selected_ids)) != len(selected_ids):
        raise ValueError("请明确选择至少一个不重复的东京地点")
    eligible = {row["id"]: row for row in review if row["eligible"]}
    if not set(selected_ids) <= set(eligible):
        raise ValueError("选择中包含缺失、重复或不可用于东京 Trip 的地点")
    if type(day_count) is not int or not 1 <= day_count <= 3 or len(selected_ids) > day_count * MAX_DAILY_STOPS:
        raise ValueError("每天最多安排 10 个地点；请增加天数或减少选择")
    if mode not in {"walk", "transit"}:
        raise ValueError("不支持的交通方式")
    ordered = [row for row in review if row["eligible"] and row["id"] in selected_ids]
    anime_ids = list(dict.fromkeys(work for row in ordered for work in row["anime_ids"]))
    if not 1 <= len(anime_ids) <= 3:
        raise ValueError("当前选择需要关联 1—3 部作品；请缩小选择")
    req = new_requirements(start_date, day_count, anime_ids=anime_ids, title=title)
    req["mode"] = mode
    req["must_ids"] = [row["id"] for row in ordered if row["required"]]
    plan = empty_plan(req)
    per_day = (len(ordered) + day_count - 1) // day_count
    for index, row in enumerate(ordered):
        stay = row["stay_min"]
        if type(stay) is not int or not 1 <= stay <= 240:
            raise ValueError(f"{row['name']} 的旧停留时长无效，请先核查原清单")
        stop = stop_spec(row["id"], required=row["required"])
        stop["stay_min"] = stay
        plan["days"][index // per_day]["stops"].append(stop)
    return validate_plan(plan)


def audit_legacy_conversion(items: list[dict], catalog: dict, plan: dict,
                            selected_ids: list[str]) -> dict:
    """Compare every source item with a proposed Trip before allowing a draft write."""
    rows = review_legacy_places(items, catalog)
    clean = validate_plan(plan)
    ordered = [row for row in rows if row["eligible"] and row["id"] in selected_ids]
    stops = [stop for day in clean["days"] for stop in day["stops"]]
    differences = []
    if len(selected_ids) != len(set(selected_ids)) or set(selected_ids) != {r["id"] for r in ordered}:
        differences.append("所选地点与原清单不一致")
    if [stop["location_id"] for stop in stops] != [row["id"] for row in ordered]:
        differences.append("站点数量或原清单顺序不一致")
    if [stop["stay_min"] for stop in stops] != [row["stay_min"] for row in ordered]:
        differences.append("停留时长不一致")
    if [(stop["priority"] == "required" and stop["locked"]) for stop in stops] != [row["required"] for row in ordered]:
        differences.append("必去属性不一致")
    if clean["requirements"]["must_ids"] != [row["id"] for row in ordered if row["required"]]:
        differences.append("必去清单不一致")
    omitted = [{"index": index, "name": row["source_name"],
                "reason": row["reason"] or "用户未选"}
               for index, row in enumerate(rows, 1) if not row["eligible"] or row["id"] not in selected_ids]
    return {"source_count": len(rows), "selected_count": len(ordered),
            "omitted": omitted, "changed_facts": [
                {"index": index, "source_name": row["source_name"], "current_name": row["name"],
                 "fields": row["changed_facts"]}
                for index, row in enumerate(rows, 1) if row["changed_facts"]],
            "differences": differences, "matches": not differences}
