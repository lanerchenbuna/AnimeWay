"""Deterministic 1–3 day Tokyo Trip requirements, edits and feasibility checks.

The portable document contains user choices, never authoritative map or LLM
facts. Schedules are recomputed against current catalog data. Execution events
are separate from planning history so undo cannot erase a visit or a skip.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json
import math
import re
from zoneinfo import ZoneInfo

from core.trip_transport import POLICY_VERSION, connection, resolve_anchor, stale
from core.place_links import trip_eligible


TOKYO = ZoneInfo("Asia/Tokyo")
MAX_HISTORY = 20
MAX_DAILY_STOPS = 10


def _keys(raw, allowed, required=()):
    if not isinstance(raw, dict) or set(raw) - set(allowed) or not set(required) <= set(raw):
        raise ValueError("字段不完整或包含不允许的扩展字段")


def _text(value, limit=300):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError("文字字段无效")
    return value.strip()


def _int(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"数值应在 {low} 至 {high} 之间")
    return value


def _ids(value, limit=100):
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(v, str) or not re.fullmatch(r'[\w.:-]{1,200}', v) for v in value):
        raise ValueError("地点或作品编号无效")
    if len(set(value)) != len(value):
        raise ValueError("不能重复选择同一对象")
    return list(value)


def resolve_date(value: str, *, now: datetime | None = None) -> str:
    now = now or datetime.now(TOKYO)
    if now.tzinfo is None:
        raise ValueError("日期解析需要明确时区")
    local = now.astimezone(TOKYO).date()
    value = value.strip()
    if value in {"今天", "明天", "后天"}:
        return (local + timedelta(days={"今天": 0, "明天": 1, "后天": 2}[value])).isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("请使用 YYYY-MM-DD，或今天／明天／后天；所有日期按日本时间") from exc


def minutes(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r'\d{2}:\d{2}', value):
        raise ValueError("时间请用 HH:MM")
    hour, minute = map(int, value.split(':'))
    return _int(hour, 0, 23) * 60 + _int(minute, 0, 59)


def clock(value: int | None) -> str:
    if value is None:
        return "待核查"
    return ("次日 " if value >= 1440 else "") + f"{value // 60 % 24:02d}:{value % 60:02d}"


def validate_anchor(raw: dict) -> dict:
    _keys(raw, {"name", "location_id", "lat", "lon", "confirmed"})
    result = {"name": _text(raw.get("name", "住宿／起终点待确认")), "location_id": _text(raw.get("location_id", "")),
              "lat": raw.get("lat"), "lon": raw.get("lon"), "confirmed": raw.get("confirmed", False)}
    if type(result["confirmed"]) is not bool:
        raise ValueError("需明确确认起终点")
    if result["location_id"]:
        _ids([result["location_id"]])
        if result["lat"] is not None or result["lon"] is not None:
            raise ValueError("已知地点的坐标由资料库提供")
    elif result["lat"] is not None or result["lon"] is not None:
        for key, low, high in (("lat", 35.4, 35.9), ("lon", 139.3, 139.95)):
            val = result[key]
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or not low <= val <= high:
                raise ValueError("自定义起终点需提供东京试点范围内的有效坐标")
    elif result["confirmed"]:
        raise ValueError("只有名称还不能确认起终点，请选择地点或提供坐标")
    return result


def new_requirements(start_date: str, day_count=2, *, anime_ids=None, title="我的东京巡礼") -> dict:
    return {"title": title, "destination_id": "tokyo", "timezone": "Asia/Tokyo", "start_date": resolve_date(start_date),
            "day_count": _int(day_count, 1, 3), "anime_ids": anime_ids if anime_ids is not None else ["328609", "160209"], "must_ids": [], "excluded_ids": [],
            "pace": "relaxed", "mode": "walk", "max_walk_m": 6000}


def new_day(day_date: str, *, arrival=False) -> dict:
    anchor = {"name": "住宿／起终点待确认", "location_id": "", "lat": None, "lon": None, "confirmed": False}
    return {"date": day_date, "start_min": 14 * 60 if arrival else 9 * 60, "end_min": 18 * 60,
            "day_type": "arrival" if arrival else "full", "start": dict(anchor), "end": dict(anchor),
            "meal_min": 30 if arrival else 60, "break_min": 30, "buffer_min": 30, "stops": []}


def empty_plan(requirements: dict) -> dict:
    start = date.fromisoformat(requirements["start_date"])
    return validate_plan({"requirements": requirements, "days": [new_day((start + timedelta(days=i)).isoformat()) for i in range(requirements["day_count"])]})


def validate_plan(raw: dict) -> dict:
    try:
        return _validate_plan(raw)
    except (KeyError, TypeError, AttributeError, OverflowError, RecursionError) as exc:
        raise ValueError("Trip 条件字段缺失或格式无效") from exc


def _validate_plan(raw: dict) -> dict:
    _keys(raw, {"requirements", "days"}, {"requirements", "days"})
    req = raw["requirements"]
    _keys(req, {"title", "destination_id", "timezone", "start_date", "day_count", "anime_ids", "must_ids", "excluded_ids", "pace", "mode", "max_walk_m"})
    if req.get("destination_id") != "tokyo" or req.get("timezone") != "Asia/Tokyo":
        raise ValueError("当前支持东京同一目的地，时区为 Asia/Tokyo")
    if req.get("pace") not in {"relaxed", "normal"} or req.get("mode") not in {"walk", "transit"}:
        raise ValueError("不支持的节奏或交通方式")
    clean = {**req, "title": _text(req.get("title", "")), "day_count": _int(req.get("day_count"), 1, 3),
             "start_date": date.fromisoformat(req["start_date"]).isoformat(), "anime_ids": _ids(req.get("anime_ids"), 3),
             "must_ids": _ids(req.get("must_ids", []), 30), "excluded_ids": _ids(req.get("excluded_ids", [])),
             "max_walk_m": _int(req.get("max_walk_m"), 500, 20000)}
    if not clean["title"] or not clean["anime_ids"] or set(clean["must_ids"]) & set(clean["excluded_ids"]):
        raise ValueError("请填写标题、作品，并避免把必去同时设为不感兴趣")
    days = raw["days"]
    if not isinstance(days, list) or len(days) != clean["day_count"]:
        raise ValueError("天数与每日条件不一致")
    result, seen = [], set()
    for index, raw_day in enumerate(days):
        _keys(raw_day, {"date", "start_min", "end_min", "day_type", "start", "end", "meal_min", "break_min", "buffer_min", "return_mode", "stops"})
        day = dict(raw_day)
        if day.get("return_mode") not in {None, "walk", "transit"}:
            raise ValueError("回程交通方式无效")
        expected_date = (date.fromisoformat(clean["start_date"]) + timedelta(days=index)).isoformat()
        if day.get("date") != expected_date or day.get("day_type") not in {"arrival", "full"}:
            raise ValueError("每天日期必须连续，抵达日类型须明确")
        for key in ("start_min", "end_min"):
            day[key] = _int(day.get(key), 0, 1439)
        if day["start_min"] >= day["end_min"]:
            raise ValueError("当天结束时间必须晚于开始时间；首版不跨午夜")
        for key in ("meal_min", "break_min", "buffer_min"):
            day[key] = _int(day.get(key), 0, 180)
        day["start"], day["end"] = validate_anchor(day.get("start")), validate_anchor(day.get("end"))
        stops = day.get("stops")
        if not isinstance(stops, list) or len(stops) > MAX_DAILY_STOPS:
            raise ValueError("每一天最多 10 个停靠地点")
        clean_stops = []
        for stop in stops:
            _keys(stop, {"location_id", "stay_min", "locked", "priority", "visit_mode", "appointment_min", "leg_mode"}, {"location_id", "stay_min", "locked", "priority", "visit_mode"})
            if stop.get("leg_mode") not in {None, "walk", "transit"}:
                raise ValueError("到站交通方式无效")
            _ids([stop["location_id"]])
            if stop["location_id"] in seen:
                raise ValueError("同一现实地点只安排一次停靠，多个场景在站内查看")
            seen.add(stop["location_id"])
            if type(stop["locked"]) is not bool or stop["priority"] not in {"required", "optional"} or stop["visit_mode"] not in {"exterior", "entry"}:
                raise ValueError("站点的锁定、兴趣或到访方式无效")
            appointment = stop.get("appointment_min")
            clean_stops.append({**stop, "stay_min": _int(stop["stay_min"], 1, 240),
                                "appointment_min": None if appointment is None else _int(appointment, 0, 1439)})
        day["stops"] = clean_stops
        result.append(day)
    return {"requirements": clean, "days": result}


def candidates(plan: dict, catalog: dict) -> list[dict]:
    req = plan["requirements"]
    wanted, excluded = set(req["anime_ids"]), set(req["excluded_ids"])
    scenes = {scene["id"]: scene for scene in catalog["scenes"]}
    def score(place):
        value = sum(2 if scenes.get(sid, {}).get("featured") else 1 for sid in place.get("scene_ids", []))
        return (place["id"] not in req["must_ids"], place.get("content_level") == "basic", -value, place["id"])
    return sorted([p for p in catalog["locations"] if p["id"] not in excluded and wanted.intersection(p["anime_ids"])
                   and trip_eligible(p, catalog) and not p.get("withdrawn") and (p.get("access") or {}).get("status") not in {"prohibited", "closed", "forbidden", "no_entry"}], key=score)


def stop_spec(location_id, *, required=False, pace="relaxed") -> dict:
    return {"location_id": location_id, "stay_min": 25 if pace == "relaxed" else 15, "locked": required,
            "priority": "required" if required else "optional", "visit_mode": "exterior", "appointment_min": None}


def propose(plan: dict, catalog: dict) -> list[dict]:
    """At most two interest-led, district-grouped drafts, never popularity fill."""
    plan = validate_plan(plan)
    pool = candidates(plan, catalog)
    must = plan["requirements"]["must_ids"]
    alternatives = []
    for label, target in (("核心少走", 2), ("同片区多看", 3 if plan["requirements"]["pace"] == "relaxed" else 5)):
        option = deepcopy(plan)
        for day in option["days"]:
            day["stops"] = []
        groups = {}
        for point in pool:
            groups.setdefault(point["destination_id"], []).append(point)
        ordered_groups = sorted(groups.values(), key=lambda items: (-sum(p["id"] in must for p in items), pool.index(items[0])))
        for group_index, group in enumerate(ordered_groups):
            # Keep each district on one day; required overflow remains visible as a conflict.
            day = option["days"][group_index % len(option["days"]) ]
            required = [p for p in group if p["id"] in must]
            optional = [p for p in group if p["id"] not in must]
            slots = max(0, target - len(day["stops"]) - len(required))
            chosen = required + optional[:slots]
            for point in chosen:
                if len(day["stops"]) < MAX_DAILY_STOPS:
                    day["stops"].append(stop_spec(point["id"], required=point["id"] in must, pace=plan["requirements"]["pace"]))
        option = validate_plan(option)
        # Remove low-priority optional stops when even the draft cannot fit.
        # Unknown travel remains unknown; it never becomes proof of feasibility.
        trimmed = 0
        for day in option["days"]:
            while day["stops"]:
                check = _evaluate_day(day, option["requirements"], catalog, [])
                tight = any(issue["code"] in {"fixed_time_conflict", "estimated_overrun", "walking_budget"} for issue in check["issues"])
                removable = next((stop for stop in reversed(day["stops"]) if stop["priority"] == "optional"), None)
                if not tight or removable is None:
                    break
                day["stops"].remove(removable)
                trimmed += 1
        if not any(item["plan"]["days"] == option["days"] for item in alternatives):
            reason = "按所选作品与场景依据筛选，同一片区集中安排；必去缺失或时间不足会列为冲突。"
            if trimmed:
                reason += f" 为适应时间或步行预算，已删减 {trimmed} 个可选站；未知交通仍需外部核查。"
            alternatives.append({"label": label, "plan": option, "reason": reason})
    return alternatives


def _issue(code, message, *, severity="review", day="", location_id=""):
    return {"code": code, "message": message, "severity": severity, "date": day, "location_id": location_id}


def _evaluate_day(day, req, catalog, events):
    places = {p["id"]: p for p in catalog["locations"]}
    issues, rows = [], []
    day_events = [e for e in events if e["date"] == day["date"]]
    terminal = {e["location_id"]: e for e in day_events if e["kind"] in {"visit", "skip", "closed"}}
    ended = any(e["kind"] == "end_day" for e in day_events) or any(e["kind"] == "end_trip" for e in events)
    start, end = resolve_anchor(day["start"], catalog), resolve_anchor(day["end"], catalog)
    for label, anchor in (("起点", start), ("终点", end)):
        if not anchor:
            issues.append(_issue("anchor_unknown", f"{label}未确认，不能声称从住宿出发或按时回到终点", day=day["date"]))
    elapsed, provisional, cursor = day["start_min"], False, start
    moving, waiting, staying, walking, meals, breaks, buffer = 0, 0, 0, 0, 0, 0, day["buffer_min"]
    unknown_move, unknown_walk, districts, continuous_walk = False, False, set(), 0
    legs, known_fare, unknown_fare = [], 0, False

    def include_leg(leg):
        nonlocal moving, waiting, walking, unknown_move, unknown_walk, known_fare, unknown_fare
        legs.append(leg)
        if leg["move_min"] is None or leg["wait_min"] is None:
            unknown_move = True
        else:
            moving += leg["move_min"]
            waiting += leg["wait_min"]
        if leg["walk_m"] is None:
            unknown_walk = True
        else:
            walking += leg["walk_m"]
        if leg["fare_jpy"] is None:
            unknown_fare = True
        else:
            known_fare += leg["fare_jpy"]
    pending = [s for s in day["stops"] if s["location_id"] not in terminal]
    fixed_budget = sum(s["stay_min"] for s in pending) + day["meal_min"] + day["break_min"] + buffer
    if day_events:
        elapsed = max(day["start_min"], max(e["at_min"] for e in day_events))
    if fixed_budget > day["end_min"] - elapsed and not ended:
        issues.append(_issue("fixed_time_conflict", "剩余停留、用餐、休息与余量已超过截止时间，即使不计交通也无法满足；请删可选站或增加时间", severity="conflict", day=day["date"]))
    for index, stop in enumerate(day["stops"]):
        point = places.get(stop["location_id"])
        outcome = terminal.get(stop["location_id"])
        if outcome:
            rows.append({"location_id": stop["location_id"], "outcome": outcome["kind"], "actual_min": outcome["at_min"], "stop": stop})
            if outcome["kind"] == "visit":
                cursor = point
            continue
        if ended:
            rows.append({"location_id": stop["location_id"], "outcome": "not_visited", "stop": stop})
            continue
        if not point or point.get("withdrawn") or (point.get("access") or {}).get("status") in {"closed", "prohibited", "forbidden", "no_entry"}:
            issues.append(_issue("access_blocked", "地点已撤下、关闭、禁止进入或不存在，请移除／替换；不能作为可进入场所推荐", severity="conflict", day=day["date"], location_id=stop["location_id"]))
        if point:
            districts.add(point.get("destination_id"))
            access = point.get("access") or {}
            if access.get("status") in {"unknown", "restricted"} or stale(access.get("checked_at")):
                issues.append(_issue("access_review", "访问范围未知、有限制或资料超过 30 天，请出发前核查", day=day["date"], location_id=point["id"]))
            if stop["visit_mode"] == "entry":
                hours = access.get("opening_hours") or {}
                if hours.get("status") == "verified" and hours.get("source_url") and not stale(hours.get("checked_at")):
                    if date.fromisoformat(day["date"]).weekday() in hours.get("closed_weekdays", []):
                        issues.append(_issue("closed_weekday", "可信开放资料显示当天休息，无法安排入内；可改日期或另核公共区域外观", severity="conflict", day=day["date"], location_id=point["id"]))
                else:
                    issues.append(_issue("entry_unverified", "试点尚无已核验的入店开放时间／周休日数据，不能保证入内；可改为公共区域外观或核查后调整", day=day["date"], location_id=point["id"]))
        leg_mode = stop.get("leg_mode") or req["mode"]
        leg = connection(cursor, point, leg_mode, catalog, day_date=day["date"],
                         departure_min=None if unknown_move else elapsed,
                         overridden=bool(stop.get("leg_mode")))
        include_leg(leg)
        if leg["move_min"] is not None and leg["wait_min"] is not None:
            elapsed += leg["move_min"] + (leg["wait_min"] or 0)
        provisional = provisional or not leg["exact"] or unknown_move
        continuous_walk += leg["walk_m"] or 0
        appointment = stop["appointment_min"]
        if appointment is not None:
            if provisional:
                issues.append(_issue("appointment_unverified", "交通含未知／估算，无法保证预约或关闭时间；请查真实交通并保留余量", day=day["date"], location_id=stop["location_id"]))
            if elapsed > appointment:
                issues.append(_issue("appointment_late", "预计晚于该站预约时间；请增加时间或改约", severity="review" if provisional else "conflict", day=day["date"], location_id=stop["location_id"]))
            if not unknown_move:
                wait = max(0, appointment - elapsed)
                waiting += wait
                elapsed += wait
        hours = ((point or {}).get("access") or {}).get("opening_hours") or {}
        if stop["visit_mode"] == "entry" and hours.get("status") == "verified" and hours.get("source_url") and not stale(hours.get("checked_at")):
            open_min, close_min = hours.get("open_min"), hours.get("close_min")
            if type(open_min) is int and type(close_min) is int and 0 <= open_min < close_min <= 1440:
                if not unknown_move:
                    wait = max(0, open_min - elapsed)
                    elapsed += wait
                    waiting += wait
                if elapsed + stop["stay_min"] > close_min:
                    issues.append(_issue("closing_time", "安排无法在开放窗口内完成停留；请缩短、换日或核查实际抵达时间", severity="review" if provisional else "conflict", day=day["date"], location_id=stop["location_id"]))
        arrival = None if unknown_move else elapsed
        elapsed += stop["stay_min"]
        staying += stop["stay_min"]
        meal = day["meal_min"] if len(pending) and stop is pending[len(pending) // 2] else 0
        # Split rest across remaining stops, giving relaxed trips regular pauses.
        pending_index = pending.index(stop)
        rest = day["break_min"] // max(1, len(pending)) + (1 if pending_index < day["break_min"] % max(1, len(pending)) else 0)
        if continuous_walk > (2500 if req["pace"] == "relaxed" else 4000):
            issues.append(_issue("continuous_walk", "连续步行估算较长；请分段休息、减少跨片区或主动修改交通方式", day=day["date"], location_id=stop["location_id"]))
        if rest or meal:
            continuous_walk = 0
        elapsed += meal + rest
        meals += meal
        breaks += rest
        rows.append({"location_id": stop["location_id"], "outcome": "pending", "arrival_min": arrival,
                     "departure_min": None if unknown_move else elapsed, "provisional": provisional, "leg": leg,
                     "stop": stop, "meal_min": meal, "break_min": rest})
        cursor = point
    return_mode = day.get("return_mode") or req["mode"]
    return_leg = connection(cursor, end, return_mode, catalog, day_date=day["date"],
                            departure_min=None if unknown_move else elapsed,
                            overridden=bool(day.get("return_mode")))
    if not ended:
        include_leg(return_leg)
        if return_leg["move_min"] is not None and return_leg["wait_min"] is not None:
            elapsed += return_leg["move_min"] + (return_leg["wait_min"] or 0)
        elapsed += buffer
        # Empty days still reserve explicitly requested time blocks.
        if not pending:
            elapsed += day["meal_min"] + day["break_min"]
            meals, breaks = day["meal_min"], day["break_min"]
        if unknown_move:
            issues.append(_issue("transport_unknown", "存在未知移动／等待时间，抵达时间与总时长待核查；不能确认赶上截止时间", day=day["date"]))
        elif elapsed > day["end_min"]:
            issues.append(_issue("estimated_overrun", f"草案预计超过截止时间 {elapsed - day['end_min']} 分钟；请删可选站、增加时间或改变交通", day=day["date"]))
        if walking > req["max_walk_m"]:
            issues.append(_issue("walking_budget", "步行估算超过每日体力预算，请缩短路线或主动更改交通方式", day=day["date"]))
        if req["pace"] == "relaxed" and (len(districts) > 1 or day["buffer_min"] < 30 or day["break_min"] < 20):
            issues.append(_issue("pace_mismatch", "轻松偏好建议一天一个片区、至少 20 分钟休息和 30 分钟余量；当前条件偏紧", day=day["date"]))
    unknown_legs = sum(leg["move_min"] is None or leg["wait_min"] is None for leg in legs)
    return {"date": day["date"], "rows": rows, "return_leg": return_leg, "legs": legs, "issues": issues,
            "finish_min": None if unknown_move or ended else elapsed, "totals": {"moving_min": None if unknown_move else moving,
            "waiting_min": None if unknown_move else waiting, "known_moving_min": moving,
            "known_waiting_min": waiting, "unknown_legs": unknown_legs,
            "stay_min": staying, "meal_min": meals, "break_min": breaks,
            "buffer_min": buffer, "walk_m": walking, "walk_complete": not unknown_walk,
            "known_fare_jpy": known_fare, "fare_jpy": None if unknown_fare else known_fare,
            "fare_status": "unknown" if unknown_fare else "known"},
            "ended": ended, "next_id": pending[0]["location_id"] if pending and not ended else None}


def evaluate(plan: dict, catalog: dict, events=None, previous=None) -> dict:
    plan = validate_plan(plan)
    events = events or []
    req = plan["requirements"]
    previous = {day["date"]: day for day in (previous or {}).get("days", [])}
    evaluated = []
    # Source changes invalidate checks; no third-party routes are cached here.
    for day in plan["days"]:
        signature = hashlib.sha256(json.dumps([POLICY_VERSION, day, {k: v for k, v in req.items() if k != "title"}, catalog,
                                              [e for e in events if e["date"] == day["date"] or e["kind"] == "end_trip"], datetime.now(TOKYO).date().isoformat()], sort_keys=True).encode()).hexdigest()
        prior = previous.get(day["date"])
        evaluated.append(prior if prior and prior.get("signature") == signature else {**_evaluate_day(day, req, catalog, events), "signature": signature})
    issues = [issue for day in evaluated for issue in day["issues"]]
    selected = {s["location_id"] for day in plan["days"] for s in day["stops"]}
    for item in set(req["must_ids"]) - selected:
        issues.append(_issue("missing_required", "必去场景未能纳入；请减少其他点、增加时间或调整作品／片区", severity="conflict", location_id=item))
    if selected & set(req["excluded_ids"]):
        issues.append(_issue("excluded_selected", "安排中包含已标为不感兴趣的地点", severity="conflict"))
    places = {p["id"]: p for p in catalog["locations"]}
    for item in selected:
        if item in places and not trip_eligible(places[item], catalog):
            issues.append(_issue("unavailable_selected", "地点已不可访问或不在东京试点范围；保留历史选择，请重新核查", severity="conflict", location_id=item))
        if item in places and not set(req["anime_ids"]).intersection(places[item]["anime_ids"]):
            issues.append(_issue("unrelated_selected", "此站不关联当前所选作品；请手动移除、替换或调整作品选择", severity="conflict", location_id=item))
    return {"days": evaluated, "issues": issues, "status": "conflict" if any(i["severity"] == "conflict" for i in issues) else "draft",
            "promise": "可编辑筹备草案；交通与现场条件尚未通过执行核验"}


def execution_prefix(archive: dict, day_date: str) -> int:
    day = next(day for day in archive["plan"]["days"] if day["date"] == day_date)
    handled = {e["location_id"] for e in archive["events"] if e["date"] == day_date and e["kind"] in {"visit", "skip", "closed"}}
    return max((i + 1 for i, s in enumerate(day["stops"]) if s["location_id"] in handled), default=0)


def preserve_execution(archive: dict, replacement: dict) -> None:
    if archive["state"] == "ended":
        raise ValueError("行程已提前结束，请新建草案；原执行记录保留")
    for old in archive["plan"]["days"]:
        day_events = [e for e in archive["events"] if e["date"] == old["date"]]
        if not day_events:
            continue
        new = next((d for d in replacement["days"] if d["date"] == old["date"]), None)
        prefix = execution_prefix(archive, old["date"])
        if not new or old["stops"][:prefix] != new["stops"][:prefix] or any(old[k] != new[k] for k in ("date", "start", "start_min")):
            raise ValueError("修改或撤销会改变已执行部分，请只调整剩余安排")
        if any(e["kind"] == "end_day" for e in day_events) and old != new:
            raise ValueError("当天已结束，不能重写其安排")


def edit_plan(archive: dict, operation: dict, catalog: dict, *, ai=False) -> tuple[dict, str]:
    if not isinstance(operation, dict):
        raise ValueError("局部修改必须包含操作类型和日期")
    plan = deepcopy(archive["plan"])
    kind = operation.get("kind")
    if kind == "requirements" and not ai:
        _keys(operation, {"kind", "plan"}, {"plan"})
        replacement = validate_plan(operation["plan"])
        if any(s["locked"] for d in plan["days"] for s in d["stops"]):
            for old_day in plan["days"]:
                for position, stop in enumerate(old_day["stops"]):
                    if stop["locked"]:
                        new_day = next((d for d in replacement["days"] if d["date"] == old_day["date"]), None)
                        if not new_day or len(new_day["stops"]) <= position or new_day["stops"][position] != stop:
                            raise ValueError("需求修改会移动锁定项，请先明确解锁")
        preserve_execution(archive, replacement)
        return replacement, "更新需求卡，重新检查受影响日期"
    _keys(operation, {"kind", "date", "location_id", "replacement_id", "value", "position"}, {"kind", "date"})
    day = next((d for d in plan["days"] if d["date"] == operation["date"]), None)
    if not day:
        raise ValueError("找不到需要编辑的日期")
    if kind == "return_mode" and not ai:
        if operation.get("value") not in {None, "walk", "transit"}:
            raise ValueError("回程交通方式无效")
        if operation.get("value") is None:
            day.pop("return_mode", None)
        else:
            day["return_mode"] = operation["value"]
        plan = validate_plan(plan)
        preserve_execution(archive, plan)
        return plan, "更新回程交通方式并重新评估"
    stop = next((s for s in day["stops"] if s["location_id"] == operation.get("location_id")), None)
    available = {p["id"] for p in candidates(plan, catalog)}
    if kind in {"add", "replace"} and operation.get("replacement_id") not in available:
        raise ValueError("只能引用所选作品中当前可用的可信候选 ID")
    if kind == "add":
        day["stops"].append(stop_spec(operation["replacement_id"], required=operation["replacement_id"] in plan["requirements"]["must_ids"], pace=plan["requirements"]["pace"]))
    elif kind in {"remove", "replace", "stay", "move", "lock", "appointment", "visit_mode", "leg_mode"}:
        if not stop:
            raise ValueError("该站不在当天安排中")
        if stop["locked"] and kind not in {"lock", "leg_mode"}:
            raise ValueError("该站已锁定，请先人工解锁")
        if kind in {"remove", "replace"} and (stop["priority"] == "required" or stop["location_id"] in plan["requirements"]["must_ids"]):
            raise ValueError("必去项不能被静默删除，请先在需求卡中调整必去选择")
        if kind == "remove":
            day["stops"].remove(stop)
        elif kind == "replace":
            stop.update(stop_spec(operation["replacement_id"], required=operation["replacement_id"] in plan["requirements"]["must_ids"], pace=plan["requirements"]["pace"]))
        elif kind == "stay":
            stop["stay_min"] = _int(operation.get("value"), 1, 240)
        elif kind == "move":
            position = _int(operation.get("position"), 0, len(day["stops"]) - 1)
            day["stops"].remove(stop)
            day["stops"].insert(position, stop)
        elif kind == "lock" and not ai:
            if type(operation.get("value")) is not bool:
                raise ValueError("锁定值应为是或否")
            stop["locked"] = operation["value"]
        elif kind == "appointment" and not ai:
            stop["appointment_min"] = operation.get("value")
        elif kind == "visit_mode" and not ai:
            stop["visit_mode"] = operation.get("value")
        elif kind == "leg_mode" and not ai:
            if operation.get("value") not in {None, "walk", "transit"}:
                raise ValueError("到站交通方式无效")
            if operation.get("value") is None:
                stop.pop("leg_mode", None)
            else:
                stop["leg_mode"] = operation["value"]
        else:
            raise ValueError("AI 不可修改锁定、预约或访问事实")
    elif kind in {"end_time", "meal", "break", "buffer"}:
        field = {"end_time": "end_min", "meal": "meal_min", "break": "break_min", "buffer": "buffer_min"}[kind]
        day[field] = operation.get("value")
    else:
        raise ValueError("不支持的局部修改")
    plan = validate_plan(plan)
    # Reordering another stop must not displace a locked stop either.
    for old_day, new_day_value in zip(archive["plan"]["days"], plan["days"]):
        for index, locked in enumerate(old_day["stops"]):
            if locked["locked"] and not (kind in {"lock", "leg_mode"} and locked["location_id"] == operation.get("location_id")):
                if len(new_day_value["stops"]) <= index or new_day_value["stops"][index] != locked:
                    raise ValueError("该操作会移动或改变锁定项，请先人工解锁")
    preserve_execution(archive, plan)
    return plan, f"{operation['date']} · {kind} · {operation.get('location_id', operation.get('replacement_id', '当天条件'))}"


def validate_archive(raw: dict) -> dict:
    try:
        return _validate_archive(raw)
    except (KeyError, TypeError, AttributeError, OverflowError, RecursionError) as exc:
        raise ValueError("Trip 备份字段缺失或格式无效") from exc


def _validate_archive(raw: dict) -> dict:
    _keys(raw, {"id", "revision", "created_at", "updated_at", "state", "plan", "history", "events"}, {"id", "revision", "created_at", "updated_at", "state", "plan", "history", "events"})
    _ids([raw["id"]])
    if raw["state"] not in {"draft", "on_trip", "ended"}:
        raise ValueError("不支持的 Trip 状态")
    result = {**raw, "revision": _int(raw["revision"], 1, 1_000_000), "plan": validate_plan(raw["plan"])}
    for field in ("created_at", "updated_at"):
        stamp = datetime.fromisoformat(_text(raw[field], 80))
        if stamp.tzinfo is None:
            raise ValueError("保存时间需要时区")
    if not isinstance(raw["history"], list) or len(raw["history"]) > MAX_HISTORY:
        raise ValueError("历史版本数量超限")
    result["history"] = []
    for item in raw["history"]:
        _keys(item, {"revision", "plan"}, {"revision", "plan"})
        result["history"].append({"revision": _int(item["revision"], 1, result["revision"] - 1), "plan": validate_plan(item["plan"])})
    if not isinstance(raw["events"], list) or len(raw["events"]) > 200:
        raise ValueError("当天事件数量超限")
    result["events"] = []
    dates = {day["date"]: day for day in result["plan"]["days"]}
    handled = set()
    latest = {}
    ended_days, ended_trip = set(), False
    for event in raw["events"]:
        _keys(event, {"kind", "date", "location_id", "at_min", "recorded_at"}, {"kind", "date", "location_id", "at_min", "recorded_at"})
        if event["kind"] not in {"visit", "skip", "closed", "delay", "end_day", "end_trip"} or event["date"] not in dates:
            raise ValueError("无效的当天事件")
        if ended_trip or event["date"] in ended_days:
            raise ValueError("结束后的日期不能继续记录事件")
        day = dates[event["date"]]
        if event["kind"] in {"visit", "skip", "closed"}:
            next_id = next((s["location_id"] for s in day["stops"] if s["location_id"] not in handled), None)
            if event["location_id"] != next_id:
                raise ValueError("事件引用无效或重复处理的站点")
            handled.add(event["location_id"])
        elif event["location_id"] != "":
            raise ValueError("此事件不应引用地点")
        at_min = _int(event["at_min"], day["start_min"], 1439)
        if at_min < latest.get(event["date"], 0):
            raise ValueError("当天事件时间不能倒退")
        latest[event["date"]] = at_min
        stamp = datetime.fromisoformat(_text(event["recorded_at"], 80))
        if stamp.tzinfo is None:
            raise ValueError("事件记录时间需要时区")
        result["events"].append(dict(event))
        if event["kind"] == "end_day":
            ended_days.add(event["date"])
        elif event["kind"] == "end_trip":
            ended_trip = True
    if result["events"] and result["state"] == "draft":
        raise ValueError("筹备状态不能包含已经执行的事件")
    if (result["state"] == "ended") != ended_trip:
        raise ValueError("结束状态与用户主动结束记录不一致")
    return result
