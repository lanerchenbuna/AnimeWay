"""Optional, quota-bound requirement parsing and reviewable local edit proposals.

There is no arbitrary tool executor. Model text cannot supply coordinates,
opening hours, routes, fares, or visit events. All edits pass the manual reducer.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import os
import re

import requests

from core.trip import TOKYO, _keys, candidates, edit_plan, evaluate, new_requirements, resolve_date


ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MAX_OUTPUT_TOKENS = 1200


def service_policy() -> dict:
    def number(name, default):
        try:
            return max(0, int(os.getenv(name, str(default))))
        except ValueError:
            return 0
    return {"daily_limit": number("ANIMEWAY_TRIP_AI_DAILY_CALLS", 0),
            "owner_limit": number("ANIMEWAY_TRIP_AI_BROWSER_CALLS", 3),
            "budget_units": number("ANIMEWAY_TRIP_AI_DAILY_MICROCNY", 0),
            "reserve_units": number("ANIMEWAY_TRIP_AI_CALL_MICROCNY", 0)}


def enabled(api_key: str) -> bool:
    return bool(api_key) and all(service_policy().values())


def local_requirements(text: str, catalog: dict, *, now: datetime | None = None) -> dict:
    """A limited free-text convenience that works without a model or network."""
    text = text[:2000]
    now = now or datetime.now(TOKYO)
    date_match = re.search(r'\d{4}-\d{2}-\d{2}|后天|明天|今天', text)
    day_match = re.search(r'([123一二两三])\s*[天日]', text)
    lookup = {"1": 1, "一": 1, "2": 2, "二": 2, "两": 2, "3": 3, "三": 3}
    names = []
    for anime in catalog["anime"]:
        aliases = [anime.get(k, "") for k in ("name", "cn", "jp", "en")] + anime.get("aliases", [])
        if any(alias and alias.strip("！!。") in text for alias in aliases):
            names.append(anime["id"])
    if not names:
        raise ValueError("没有识别到试点作品，请在文字中注明《孤独摇滚！》或《你的名字。》，或直接编辑下方需求卡；不会用无关作品补位")
    req = new_requirements(resolve_date(date_match[0], now=now) if date_match else now.astimezone(TOKYO).date().isoformat(),
                           lookup[day_match[1]] if day_match else 2, anime_ids=names or None)
    req["pace"] = "relaxed" if any(word in text for word in ("轻松", "不赶", "不想赶", "不想太赶", "慢")) else "normal"
    req["mode"] = "transit" if any(word in text for word in ("地铁", "公交", "铁路", "电车")) else "walk"
    lodging = re.search(r'住(?:在)?\s*([^，,。\s]{1,40})', text)
    arrival = "下午" in text or "抵达" in text or "到东京" in text
    return {"requirements": req, "arrival": arrival, "lodging_name": lodging[1] if lodging else "住宿待确认",
            "note": "日期已按日本时间明确；天数包含抵达日。起终点与每日时间仍需在需求卡确认，未自动定位住宿。"}


def preview_operations(archive, raw, catalog):
    _keys(raw, {"operations", "explanation"}, {"operations"})
    operations = raw["operations"]
    if not isinstance(operations, list) or not 1 <= len(operations) <= 3:
        raise ValueError("AI 每次只能提出 1—3 项局部修改")
    working, diffs = deepcopy(archive), []
    places = {p["id"]: p["name"] for p in catalog["locations"]}
    for operation in operations:
        before = deepcopy(working["plan"])
        working["plan"], description = edit_plan(working, operation, catalog, ai=True)
        for key, name in places.items():
            description = description.replace(key, name)
        diffs.append({"description": description, "before": before, "after": deepcopy(working["plan"])})
    return {"base_revision": archive["revision"], "operations": deepcopy(operations), "plan": working["plan"],
            "diffs": diffs, "evaluation": evaluate(working["plan"], catalog, archive["events"])}


def _request(store, token, trip_id, api_key, system, context, text):
    if not enabled(api_key):
        raise ValueError("AI 未配置 Key 或调用预算；可继续使用表单与人工编辑")
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError("请用 1—2000 字描述修改")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": json.dumps({"context": context, "request": text}, ensure_ascii=False)}]
    if len(json.dumps(messages, ensure_ascii=False).encode()) > 24000:
        raise ValueError("本次上下文过长，请缩小修改范围")
    call_id = store.reserve_ai_call(token, trip_id, **service_policy())
    success = False
    try:
        response = requests.post(ENDPOINT, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                                 json={"model": "qwen-plus", "messages": messages, "temperature": 0, "max_tokens": MAX_OUTPUT_TOKENS,
                                       "stream": False, "response_format": {"type": "json_object"}}, timeout=(5, 20))
        response.raise_for_status()
        if len(response.content) > 128000:
            raise ValueError("AI 响应超出大小限制")
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        success = True
        return parsed
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
        raise ValueError("AI 超时、不可用或返回格式不正确；原行程未改变，可继续人工编辑") from exc
    finally:
        # A failed or timed-out call still consumes its reservation; no blind retries.
        store.finish_ai_call(token, call_id, success)


def request_edit(store, token, archive, text, catalog, api_key):
    pool = candidates(archive["plan"], catalog)[:35]
    context = {"days": [{"date": day["date"], "end_min": day["end_min"], "stops": day["stops"]} for day in archive["plan"]["days"]],
               "candidates": [{"id": p["id"], "name": p["name"], "district": p["destination_id"]} for p in pool],
               "handled": [{"date": e["date"], "kind": e["kind"], "location_id": e["location_id"]} for e in archive["events"]]}
    system = ('只输出 JSON {"operations":[...]}。只提议 1—3 项局部修改。每项有 kind,date，及需要的 location_id/replacement_id/value/position。'
              'kind 仅 add/remove/replace/stay/move/end_time/meal/break/buffer。位置从0开始；时间为当地午夜起分钟数。'
              '只引用候选ID，不改变锁定站或已执行部分。不得生成坐标、交通、费用、开放时间或到访记录。只修改用户明确提出的内容。')
    raw = _request(store, token, archive["id"], api_key, system, context, text)
    return preview_operations(archive, raw, catalog)


def request_requirements(store, token, text, catalog, api_key):
    context = {"today": datetime.now(TOKYO).date().isoformat(), "timezone": "Asia/Tokyo",
               "anime": [{"id": a["id"], "name": a["name"]} for a in catalog["anime"]]}
    system = ('只输出 JSON，仅可有 date_text,day_count,anime_ids,pace,mode,arrival,lodging_name。'
              'date_text 必须保留今天/明天/后天原词或用户明确给出的 ISO 日期，不猜日期。day_count 1—3且包含抵达日；'
              'pace relaxed/normal，mode walk/transit。只引用给出的作品ID；不推测住宿坐标、交通或访问事实。')
    raw = _request(store, token, "", api_key, system, context, text)
    _keys(raw, {"date_text", "day_count", "anime_ids", "pace", "mode", "arrival", "lodging_name"}, {"date_text", "day_count", "anime_ids", "pace", "mode", "arrival", "lodging_name"})
    if not isinstance(raw["date_text"], str):
        raise ValueError("AI 返回日期无效，请人工确认")
    if not isinstance(raw["anime_ids"], list) or any(not isinstance(item, str) for item in raw["anime_ids"]) or not set(raw["anime_ids"]) <= {a["id"] for a in catalog["anime"]}:
        raise ValueError("AI 引用了不在试点内的作品，请手工填写需求")
    if type(raw["arrival"]) is not bool or not isinstance(raw["lodging_name"], str) or len(raw["lodging_name"]) > 300:
        raise ValueError("AI 返回的抵达或住宿字段无效")
    explicit_date = re.search(r'\d{4}-\d{2}-\d{2}|后天|明天|今天', text)
    req = new_requirements(resolve_date(explicit_date[0] if explicit_date else raw["date_text"]), raw["day_count"], anime_ids=raw["anime_ids"])
    req.update(pace=raw["pace"], mode=raw["mode"])
    from core.trip import empty_plan
    empty_plan(req)
    return {"requirements": req, "arrival": raw["arrival"], "lodging_name": raw["lodging_name"], "note": "AI 已整理为候选需求卡；请逐项确认日期、包含抵达日的天数及起终点。"}
