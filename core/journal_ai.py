"""Optional AI selects/reorders trusted choices; it never writes travel facts."""
from core.trip import _keys
from core.trip_ai import _request


def order_record(store, token, entry_id, catalog, api_key):
    entry = next((e for e in store.entries(token) if e["id"] == entry_id and e["confirmed"]), None)
    if not entry:
        raise ValueError("只有确认到访的记录可整理")
    clauses = [s + "。" for s in store.short_draft(token, entry_id, catalog).split("。") if s]
    raw = _request(store, token, "", api_key,
        '只输出 JSON {"order":[整数索引]}，重新排列给定的已确认短句，必须完整保留且不重复。不写新经历。',
        {"clauses": clauses}, "整理确认记录的短句顺序，不添加任何事实")
    _keys(raw, {"order"}, {"order"})
    order = raw["order"]
    if not isinstance(order, list) or any(type(i) is not int for i in order) or sorted(order) != list(range(len(clauses))):
        raise ValueError("AI 返回了确认记录之外的内容，原短文保留")
    return "".join(clauses[i] for i in order)


def recommend_choices(store, token, catalog, api_key):
    candidates = store.recommend(token, catalog)
    if not candidates:
        raise ValueError("没有明确兴趣候选，请先关注或收藏")
    allowed = {r["location"]["id"]: r for r in candidates}
    raw = _request(store, token, "", api_key,
        '只输出 JSON {"location_ids":[...]}，从候选中选 1—3 个同片区地点。不可补充地点、费用、交通或经历。',
        {"candidates": [{"id": key, "district": r["location"]["destination_id"], "reason": r["reason"]} for key, r in allowed.items()]},
        "为下一次轻量巡礼选择已有兴趣候选；只提出可确认的选择")
    _keys(raw, {"location_ids"}, {"location_ids"})
    ids = raw["location_ids"]
    if not isinstance(ids, list) or not 1 <= len(ids) <= 3 or any(not isinstance(i, str) or i not in allowed for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("AI 选择超出有效候选，原收藏保留")
    if len({allowed[i]["location"]["destination_id"] for i in ids}) != 1:
        raise ValueError("本次 AI 建议跨片区，请使用人工规划；原收藏保留")
    return [{"location": allowed[i]["location"], "reason": allowed[i]["reason"]} for i in ids]
