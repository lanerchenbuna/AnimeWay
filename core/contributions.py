"""Invited submissions and local operator review. No web admin or auto fact edits."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import secrets
import uuid

from core.journal import day_value, region_ids, source_url, today
from core.private_store import _identifier, _json, _now, _text
from core.trip import _int, _keys, validate_anchor

STATUSES = {"pending", "needs_info", "accepted", "rejected", "withdrawn"}


def capacity():
    try:
        return max(0, min(200, int(os.getenv("ANIMEWAY_CONTRIBUTION_QUEUE_LIMIT", "20"))))
    except ValueError:
        return 0


def current_catalog(conn, baseline):
    catalog = deepcopy(baseline)
    catalog.setdefault("activities", [])
    for row in conn.execute("SELECT kind,object_id,after_json,created_at FROM content_edits WHERE active=1 ORDER BY rowid"):
        collection = {"location": "locations", "activity": "activities"}[row["kind"]]
        item = json.loads(row["after_json"])
        items = catalog[collection]
        items[:] = [p for p in items if p["id"] != row["object_id"]] + [item]
    return catalog


def issue_invite(store, reviewer, *, days=14, uses=1):
    reviewer = _text(reviewer, "reviewer", 120, empty=False)
    _int(days, 1, 90)
    _int(uses, 1, 20)
    secret = secrets.token_urlsafe(24)
    with store._connection() as conn:
        conn.execute("INSERT INTO contributor_invites VALUES(?,?,?,?)",
                     (hashlib.sha256(secret.encode()).hexdigest(), (today() + timedelta(days=days)).isoformat(), uses, reviewer))
    return secret


def redeem_invite(store, token, invitation):
    if not isinstance(invitation, str) or len(invitation) > 100:
        raise ValueError("邀请码无效")
    with store._connection() as conn:
        owner = store._owner(conn, token)
        conn.execute("BEGIN IMMEDIATE")
        digest = hashlib.sha256(invitation.encode()).hexdigest()
        row = conn.execute("SELECT * FROM contributor_invites WHERE digest=?", (digest,)).fetchone()
        if not row or row["uses"] <= 0 or row["expires_on"] < today().isoformat():
            raise ValueError("邀请码无效、已使用或已过期")
        conn.execute("UPDATE contributor_invites SET uses=uses-1 WHERE digest=?", (digest,))
        conn.execute("INSERT INTO contributor_access VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET expires_on=excluded.expires_on", (owner, row["expires_on"]))


def submission(store, token, *, kind, location_id="", description, evidence_url, observed_on, proposal=None, catalog):
    if kind not in {"correction", "new_location"}:
        raise ValueError("不支持的投稿类型")
    proposal = proposal or {}
    _keys(proposal, {"name", "lat", "lon", "anime_id", "destination_id"})
    if kind == "correction":
        point = next((p for p in catalog["locations"] if p["id"] == location_id), None)
        if not point:
            raise ValueError("纠错必须关联当前地点")
    else:
        _keys(proposal, {"name", "lat", "lon", "anime_id", "destination_id"}, {"name", "lat", "lon", "anime_id", "destination_id"})
        validate_anchor({"name": proposal["name"], "lat": proposal["lat"], "lon": proposal["lon"], "confirmed": True})
        if proposal["anime_id"] not in {a["id"] for a in catalog["anime"]} or proposal["destination_id"] not in {d["id"] for d in catalog["destinations"]}:
            raise ValueError("当前新增点位仅限试点作品与已有东京片区")
    body = {"kind": kind, "location_id": _identifier(location_id) if location_id else "", "description": _text(description, "evidence description", 3000, empty=False),
            "evidence_url": source_url(evidence_url), "observed_on": day_value(observed_on, past=True), "proposal": proposal,
            "review_note": "", "reviewer": "", "review_minutes": None, "reviewed_at": None, "edit_id": ""}
    core_ids = {s["location_id"] for r in catalog["routes"] for s in r["stops"] if s.get("required")}
    priority = 0 if location_id in core_ids else 1
    with store._connection() as conn:
        owner = store._owner(conn, token)
        conn.execute("BEGIN IMMEDIATE")
        pending = conn.execute("SELECT count(*) FROM contributions WHERE status IN ('pending','needs_info')").fetchone()[0]
        if kind == "new_location":
            invite = conn.execute("SELECT expires_on FROM contributor_access WHERE owner=?", (owner,)).fetchone()
            if not invite or invite[0] < today().isoformat():
                raise ValueError("新增地点需有效邀请；现有地点仍可提交纠错")
            if pending >= capacity():
                raise ValueError("审核积压已达维护上限，暂停新增点位投稿")
        if pending >= 200 or conn.execute("SELECT count(*) FROM contributions WHERE owner=? AND status IN ('pending','needs_info')", (owner,)).fetchone()[0] >= 10:
            raise ValueError("待处理投稿已达上限，请先补充或处理现有记录")
        cid, now = uuid.uuid4().hex, _now()
        conn.execute("INSERT INTO contributions VALUES(?,?,?,?,?,?,?)", (cid, owner, _json(body), "pending", priority, now, now))
    return cid


def own_submissions(store, token):
    with store._connection() as conn:
        owner = store._owner(conn, token)
        return [{**dict(r), "body": json.loads(r["body"])} for r in conn.execute("SELECT id,body,status,priority,created_at,updated_at FROM contributions WHERE owner=? ORDER BY created_at DESC", (owner,))]


def supplement(store, token, cid, description, evidence_url):
    with store._connection() as conn:
        owner = store._owner(conn, token)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT body,status FROM contributions WHERE owner=? AND id=?", (owner, cid)).fetchone()
        if not row or row["status"] != "needs_info":
            raise ValueError("只有本人待补充投稿可以补资料")
        body = json.loads(row["body"])
        body["description"] = _text(description, "description", 3000, empty=False)
        body["evidence_url"] = source_url(evidence_url)
        conn.execute("UPDATE contributions SET body=?,status='pending',updated_at=? WHERE id=?", (_json(body), _now(), cid))


def queue(store):
    with store._connection() as conn:
        return [{**dict(r), "body": json.loads(r["body"])} for r in conn.execute(
            "SELECT id,body,status,priority,created_at,updated_at FROM contributions ORDER BY priority,created_at")]


def review_location_patch(before, patch, catalog, now, reviewer):
    _keys(patch, {"name", "lat", "lon", "destination_id", "anime_ids", "source_url", "access", "entry", "viewpoint", "withdrawn"})
    item = deepcopy(before)
    if not item:
        item = {"id": "loc-contribution-" + uuid.uuid4().hex, "city": "东京都", "scene_ids": [], "source_ids": [],
                "aliases": [], "upstream": [], "content_level": "basic", "withdrawn": False, "change_log": [],
                "access": {"status": "unknown", "summary": "访问与场景关联待核查", "source_url": "", "checked_at": now[:10]}}
    item.update(deepcopy(patch))
    for key in ("name", "entry", "viewpoint"):
        item[key] = _text(item.get(key, ""), key, 3000, empty=key != "name")
    validate_anchor({"name": item["name"], "lat": item.get("lat"), "lon": item.get("lon"), "confirmed": True})
    if item.get("destination_id") not in {d["id"] for d in catalog["destinations"]}:
        raise ValueError("未开放新目的地，仅可修改现有东京片区")
    if not isinstance(item.get("anime_ids"), list) or not item["anime_ids"] or not set(item["anime_ids"]) <= {a["id"] for a in catalog["anime"]}:
        raise ValueError("作品关联必须来自试点列表")
    item["source_url"] = source_url(item.get("source_url"))
    access = item["access"]
    _keys(access, {"status", "summary", "source_url", "checked_at", "hours", "fees"})
    if access.get("status") not in {"unknown", "public_exterior", "restricted", "closed", "prohibited"}:
        raise ValueError("访问状态无效")
    access["summary"] = _text(access.get("summary"), "access summary", 3000, empty=False)
    access["source_url"] = source_url(access.get("source_url"))
    access["checked_at"] = day_value(access.get("checked_at"), past=True)
    if access.get("hours") is not None or access.get("fees") is not None:
        raise ValueError("本投稿流程不接受未经独立结构化核验的时刻或费用")
    if type(item["withdrawn"]) is not bool:
        raise ValueError("撤下标记无效")
    item["source_version"] = int((before or {}).get("source_version", 0)) + 1
    item["reviewed_at"] = now[:10]
    item["change_log"] = item.get("change_log", []) + [{"date": now[:10], "summary": "维护者审核更新，详见来源", "reviewer": reviewer}]
    return item


def review(store, cid, *, status, reviewer, note, minutes, patch=None, catalog):
    if status not in {"needs_info", "accepted", "rejected"}:
        raise ValueError("请选择待补充、采纳或拒绝")
    reviewer = _text(reviewer, "reviewer", 120, empty=False)
    note = _text(note, "review note", 3000, empty=False)
    _int(minutes, 1, 1440)
    with store._connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT body,status FROM contributions WHERE id=?", (cid,)).fetchone()
        if not row or row["status"] not in {"pending", "needs_info"}:
            raise ValueError("投稿不存在或已有终态；事实回撤请使用撤回命令")
        body, now = json.loads(row["body"]), _now()
        body.update(review_note=note, reviewer=reviewer, review_minutes=(body.get("review_minutes") or 0) + minutes, reviewed_at=now)
        if status == "accepted":
            if not patch:
                raise ValueError("采纳必须提供人工审核的事实变更，不自动复制投稿")
            live = current_catalog(conn, catalog)
            before = next((p for p in live["locations"] if p["id"] == body["location_id"]), None)
            if body["kind"] == "correction" and not before:
                raise ValueError("原地点已失效")
            after = review_location_patch(before, patch, live, now, reviewer)
            edit_id = uuid.uuid4().hex
            conn.execute("INSERT INTO content_edits VALUES(?,?,?,?,?,1,?,?,?,?,?)",
                (edit_id, after["id"], "location", _json(before), _json(after), cid, reviewer, minutes, note, now))
            notice = {"summary": note, "anime_ids": after["anime_ids"], "destination_id": after["destination_id"]}
            conn.execute("INSERT INTO content_notices VALUES(?,?,?,?,?)", (uuid.uuid4().hex, after["id"], "location", _json(notice), now))
            body["edit_id"] = edit_id
        conn.execute("UPDATE contributions SET body=?,status=?,updated_at=? WHERE id=?", (_json(body), status, now, cid))
        return body


def withdraw_edit(store, edit_id, reviewer, note):
    reviewer, note = _text(reviewer, "reviewer", 120, empty=False), _text(note, "note", 3000, empty=False)
    with store._connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT rowid,* FROM content_edits WHERE id=? AND active=1", (edit_id,)).fetchone()
        if not row:
            raise ValueError("没有可撤回的内容变更")
        if conn.execute("SELECT 1 FROM content_edits WHERE object_id=? AND active=1 AND rowid>?", (row["object_id"], row["rowid"])).fetchone():
            raise ValueError("该对象有后续变更，请从最新变更逆序撤回")
        conn.execute("UPDATE content_edits SET active=0 WHERE id=?", (edit_id,))
        after, now = json.loads(row["after_json"]), _now()
        notice = {"summary": f"审核变更已撤回：{note}", "anime_ids": after.get("anime_ids", []), "destination_id": after["destination_id"], "reviewer": reviewer}
        conn.execute("INSERT INTO content_notices VALUES(?,?,?,?,?)", (uuid.uuid4().hex, row["object_id"], row["kind"], _json(notice), now))
        if row["contribution_id"]:
            body = json.loads(conn.execute("SELECT body FROM contributions WHERE id=?", (row["contribution_id"],)).fetchone()[0])
            body.update(review_note=notice["summary"], reviewer=reviewer, reviewed_at=now)
            conn.execute("UPDATE contributions SET status='withdrawn',body=?,updated_at=? WHERE id=?", (_json(body), now, row["contribution_id"]))


def publish_activity(store, raw, reviewer, minutes, catalog):
    """Local-only editorial entry; no scraper and no public user submission overwrite."""
    _keys(raw, {"id", "title", "destination_id", "anime_ids", "start_date", "end_date", "checked_at", "source_url", "summary"},
          {"id", "title", "destination_id", "anime_ids", "start_date", "end_date", "checked_at", "source_url", "summary"})
    item = deepcopy(raw)
    item["id"] = _identifier(item["id"])
    item["title"] = _text(item["title"], "title", 200, empty=False)
    item["summary"] = _text(item["summary"], "summary", 2000, empty=False)
    item["source_url"] = source_url(item["source_url"])
    for field in ("start_date", "end_date", "checked_at"):
        item[field] = day_value(item[field], past=field == "checked_at")
    if item["end_date"] < item["start_date"] or item["checked_at"] < (today() - timedelta(days=30)).isoformat():
        raise ValueError("活动日期或核查日期无效／已过期")
    if item["destination_id"] not in {d["id"] for d in catalog["destinations"]} or not isinstance(item["anime_ids"], list) or not set(item["anime_ids"]) <= {a["id"] for a in catalog["anime"]}:
        raise ValueError("仅支持已有试点目的地与作品")
    reviewer = _text(reviewer, "official-source reviewer", 120, empty=False)
    _int(minutes, 1, 1440)
    with store._connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        before = next((a for a in current_catalog(conn, catalog)["activities"] if a["id"] == item["id"]), None)
        edit_id, now = uuid.uuid4().hex, _now()
        conn.execute("INSERT INTO content_edits VALUES(?,?,?,?,?,1,?,?,?,?,?)", (edit_id, item["id"], "activity", _json(before), _json(item), "", reviewer, minutes, "官方来源经维护者确认", now))
        conn.execute("INSERT INTO content_notices VALUES(?,?,?,?,?)", (uuid.uuid4().hex, item["id"], "activity", _json({"summary": item["title"], "anime_ids": item["anime_ids"], "destination_id": item["destination_id"]}), now))
    return edit_id


def activities(catalog, *, start=None, end=None):
    start = max(start or today().isoformat(), today().isoformat())
    end = end or start
    return [a for a in catalog.get("activities", []) if a["end_date"] >= start and a["start_date"] <= end
            and (today() - timedelta(days=30)).isoformat() <= a["checked_at"] <= today().isoformat()]


def follow_updates(store, token, catalog):
    prefs = store.preferences(token)
    with store._connection() as conn:
        notices = [dict(r) for r in conn.execute("SELECT * FROM content_notices ORDER BY created_at DESC")]
    result = []
    for row in notices:
        body = json.loads(row["body"])
        pseudo = {"destination_id": body["destination_id"]}
        relevant = any(row["created_at"] >= f["since"] and ((f["kind"] == "anime" and f["id"] in body["anime_ids"])
                       or (f["kind"] == "destination" and f["id"] in region_ids(pseudo, catalog))) for f in prefs["follows"])
        if row["kind"] == "activity" and row["object_id"] not in {a["id"] for a in activities(catalog, end="9999-12-31")}:
            continue
        if relevant:
            result.append({**row, "body": body})
    return result[:30]


def maintenance_report(store):
    now = datetime.now(timezone.utc)
    items = queue(store)
    pending = [i for i in items if i["status"] in {"pending", "needs_info"}]
    overdue = [i for i in pending if (now - datetime.fromisoformat(i["created_at"])).days >= 7]
    with store._connection() as conn:
        accepted = conn.execute("SELECT object_id,created_at,contribution_id FROM content_edits WHERE contribution_id<>''").fetchall()
        repeated = sum(any(i["body"]["location_id"] == r["object_id"] and i["created_at"] > r["created_at"] and i["id"] != r["contribution_id"] for i in items) for r in accepted)
        metrics = [dict(r) for r in conn.execute("SELECT kind,source,count(*) AS operations,count(DISTINCT owner) AS consenting_browsers FROM journal_metrics GROUP BY kind,source")]
        events = [dict(r) for r in conn.execute("SELECT owner,kind,created_at FROM journal_metrics ORDER BY created_at")]
    cohorts = []
    owners = {r["owner"] for r in events}
    for days in (30, 90):
        mature = returned = 0
        for owner in owners:
            records = [r for r in events if r["owner"] == owner]
            first = datetime.fromisoformat(records[0]["created_at"])
            if now - first < timedelta(days=days):
                continue
            mature += 1
            returned += any(r["kind"] == "intent_return" and first + timedelta(days=1) <= datetime.fromisoformat(r["created_at"]) <= first + timedelta(days=days) for r in records)
        cohorts.append({"days": days, "mature_consenting_browsers": mature, "return_with_intent": returned if mature else None,
                        "rate": returned / mature if mature else None})
    return {"pending": len(pending), "overdue_7_days": len(overdue), "new_place_intake_paused": len(pending) >= capacity(),
            "queue_limit": capacity(), "review_minutes": sum(i["body"].get("review_minutes") or 0 for i in items),
            "accepted_edits": len(accepted), "later_correction_reports": repeated,
            "later_report_rate": repeated / len(accepted) if accepted else None, "metrics": metrics, "intent_cohorts": cohorts,
            "cohort_definition": "首次同意后记录的有效动作起算；窗口成熟后，统计第 1 至第 30/90 天主动报告再次出行意图的浏览器。不是全部用户留存。",
            "expansion_decision": "暂停公开扩展，待真实用户、现场质量与维护成本验收；本报告不替代发布签认",
            "note": "后续纠错投稿不等于已证实事实错误；匿名浏览器不等于人数；没有成熟观察期不宣称 30/90 天留存。"}
