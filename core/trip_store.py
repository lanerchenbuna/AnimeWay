"""Owner-scoped, versioned personal Trips using the existing private database."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import uuid

from core.private_store import PrivateStore, MAX_TRIPS, _identifier, _json, _now
from core.trip import MAX_HISTORY, TOKYO, edit_plan, evaluate, preserve_execution, validate_archive, validate_plan


class TripStore(PrivateStore):
    MAX_DRAFTS = 8
    DRAFT_SOURCES = {"manual", "routebook", "map", "handbook", "backpack"}

    def __init__(self, path=None):
        super().__init__(path)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""CREATE TABLE IF NOT EXISTS personal_trip_drafts (
                owner TEXT NOT NULL REFERENCES identities(owner),
                draft_id TEXT NOT NULL, revision INTEGER NOT NULL,
                source TEXT NOT NULL, body TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(owner,draft_id))""")

    def list_personal_drafts(self, token):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            return [{"id": row["draft_id"], "revision": row["revision"],
                     "source": row["source"], "plan": json.loads(row["body"]),
                     "updated_at": row["updated_at"]}
                    for row in conn.execute("SELECT * FROM personal_trip_drafts WHERE owner=? ORDER BY updated_at DESC", (owner,))]

    def get_personal_draft(self, token, draft_id):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            row = conn.execute("SELECT * FROM personal_trip_drafts WHERE owner=? AND draft_id=?",
                               (owner, _identifier(draft_id))).fetchone()
            return ({"id": row["draft_id"], "revision": row["revision"],
                     "source": row["source"], "plan": json.loads(row["body"]),
                     "updated_at": row["updated_at"]} if row else None)

    def create_personal_draft(self, token, plan, source="manual"):
        if source not in self.DRAFT_SOURCES:
            raise ValueError("未知的 Trip 草案来源")
        clean = validate_plan(plan)
        draft_id, now = uuid.uuid4().hex, _now()
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT count(*) FROM personal_trip_drafts WHERE owner=?", (owner,)).fetchone()[0] >= self.MAX_DRAFTS:
                raise ValueError("未保存草案已达上限，请先保存或删除旧草案")
            conn.execute("INSERT INTO personal_trip_drafts VALUES(?,?,?,?,?,?)",
                         (owner, draft_id, 1, source, _json(clean), now))
        return {"id": draft_id, "revision": 1, "source": source, "plan": clean, "updated_at": now}

    def edit_personal_draft(self, token, draft_id, revision, operation, catalog):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM personal_trip_drafts WHERE owner=? AND draft_id=?",
                               (owner, _identifier(draft_id))).fetchone()
            if not row:
                raise ValueError("找不到此草案，请从草案列表重新打开")
            if type(revision) is not int or revision != row["revision"]:
                raise ValueError("草案已在另一页面更新，请重新载入后操作")
            plan, _ = edit_plan({"plan": json.loads(row["body"]), "state": "draft", "events": []},
                                operation, catalog)
            now = _now()
            conn.execute("UPDATE personal_trip_drafts SET body=?,revision=?,updated_at=? WHERE owner=? AND draft_id=?",
                         (_json(plan), revision + 1, now, owner, draft_id))
        return {"id": draft_id, "revision": revision + 1, "source": row["source"],
                "plan": plan, "updated_at": now}

    def apply_draft_ai_operations(self, token, draft_id, revision, operations, catalog):
        if not isinstance(operations, list) or not 1 <= len(operations) <= 3:
            raise ValueError("每次最多三项局部修改")
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM personal_trip_drafts WHERE owner=? AND draft_id=?",
                               (owner, _identifier(draft_id))).fetchone()
            if not row or type(revision) is not int or row["revision"] != revision:
                raise ValueError("草案已变化，请重新载入后应用 AI 修改")
            archive = {"plan": json.loads(row["body"]), "state": "draft", "events": []}
            for operation in operations:
                archive["plan"], _ = edit_plan(archive, operation, catalog, ai=True)
            now = _now()
            conn.execute("UPDATE personal_trip_drafts SET body=?,revision=?,updated_at=? WHERE owner=? AND draft_id=?",
                         (_json(archive["plan"]), revision + 1, now, owner, draft_id))
        return {"id": draft_id, "revision": revision + 1, "source": row["source"],
                "plan": archive["plan"], "updated_at": now}

    def commit_personal_draft(self, token, draft_id, revision):
        now = _now()
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT revision,body FROM personal_trip_drafts WHERE owner=? AND draft_id=?",
                               (owner, _identifier(draft_id))).fetchone()
            if not row or type(revision) is not int or row["revision"] != revision:
                raise ValueError("草案已变化，请重新载入后保存")
            if conn.execute("SELECT count(*) FROM personal_trips WHERE owner=?", (owner,)).fetchone()[0] >= MAX_TRIPS:
                raise ValueError("个人 Trip 数量已达上限，请先备份并删除不再使用的行程")
            archive = validate_archive({"id": draft_id, "revision": 1,
                                        "created_at": now, "updated_at": now, "state": "draft",
                                        "plan": json.loads(row["body"]), "history": [], "events": []})
            conn.execute("INSERT INTO personal_trips VALUES(?,?,?)", (owner, archive["id"], _json(archive)))
            self._check_portable_size(conn, owner)
            conn.execute("DELETE FROM personal_trip_drafts WHERE owner=? AND draft_id=?", (owner, draft_id))
        return archive

    def discard_personal_draft(self, token, draft_id, revision):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute("DELETE FROM personal_trip_drafts WHERE owner=? AND draft_id=? AND revision=?",
                                  (owner, _identifier(draft_id), revision))
            if not cursor.rowcount:
                raise ValueError("草案已变化，请重新载入后操作")

    def list_personal_trips(self, token):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            result = [json.loads(row[0]) for row in conn.execute("SELECT body FROM personal_trips WHERE owner=?", (owner,))]
            return sorted(result, key=lambda item: item["updated_at"], reverse=True)

    def get_personal_trip(self, token, trip_id):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            row = conn.execute("SELECT body FROM personal_trips WHERE owner=? AND trip_id=?", (owner, _identifier(trip_id))).fetchone()
            return json.loads(row[0]) if row else None

    def create_personal_trip(self, token, plan):
        now = _now()
        archive = validate_archive({"id": uuid.uuid4().hex, "revision": 1, "created_at": now, "updated_at": now,
                                    "state": "draft", "plan": validate_plan(plan), "history": [], "events": []})
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT count(*) FROM personal_trips WHERE owner=?", (owner,)).fetchone()[0] >= MAX_TRIPS:
                raise ValueError("个人 Trip 数量已达上限，请先备份并删除不再使用的行程")
            conn.execute("INSERT INTO personal_trips VALUES(?,?,?)", (owner, archive["id"], _json(archive)))
            self._check_portable_size(conn, owner)
        return archive

    def _change(self, token, trip_id, revision, mutation, *, history=True):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT body FROM personal_trips WHERE owner=? AND trip_id=?", (owner, _identifier(trip_id))).fetchone()
            if not row:
                raise ValueError("找不到此身份的 Trip")
            archive = json.loads(row[0])
            if type(revision) is not int or revision != archive["revision"]:
                raise ValueError("行程已在另一页面更新，请重新载入后操作")
            before = deepcopy(archive["plan"])
            mutation(archive)
            if history:
                archive["history"] = (archive["history"] + [{"revision": revision, "plan": before}])[-MAX_HISTORY:]
            archive["revision"] += 1
            archive["updated_at"] = _now()
            archive = validate_archive(archive)
            conn.execute("UPDATE personal_trips SET body=? WHERE owner=? AND trip_id=?", (_json(archive), owner, trip_id))
            self._check_portable_size(conn, owner)
            return archive

    def edit_personal_trip(self, token, trip_id, revision, operation, catalog):
        def change(archive):
            archive["plan"], _ = edit_plan(archive, operation, catalog)
        return self._change(token, trip_id, revision, change)

    def restore_personal_version(self, token, trip_id, revision, target_revision):
        def change(archive):
            version = next((item for item in archive["history"] if item["revision"] == target_revision), None)
            if not version:
                raise ValueError("该版本不在最近 20 个规划版本中")
            preserve_execution(archive, version["plan"])
            archive["plan"] = deepcopy(version["plan"])
        return self._change(token, trip_id, revision, change)

    def apply_ai_operations(self, token, trip_id, revision, operations, catalog):
        if not isinstance(operations, list) or not 1 <= len(operations) <= 3:
            raise ValueError("每次最多三项局部修改")
        def change(archive):
            for operation in operations:
                archive["plan"], _ = edit_plan(archive, operation, catalog, ai=True)
        return self._change(token, trip_id, revision, change)

    def begin_personal_trip(self, token, trip_id, revision, catalog):
        def change(archive):
            if archive["state"] != "draft" or not any(day["stops"] for day in archive["plan"]["days"]):
                raise ValueError("请选择尚未开始且至少有一个站点的 Trip")
            if evaluate(archive["plan"], catalog)["status"] == "conflict":
                raise ValueError("请先处理行程中的硬性冲突；原草案保留")
            archive["state"] = "on_trip"
        return self._change(token, trip_id, revision, change, history=False)

    def record_personal_event(self, token, trip_id, revision, day_date, kind, at_min, catalog):
        def change(archive):
            if archive["state"] != "on_trip":
                raise ValueError("请先开始当天模式；已结束的行程不能继续记录")
            day = next((d for d in archive["plan"]["days"] if d["date"] == day_date), None)
            if not day or any(e["date"] == day_date and e["kind"] == "end_day" for e in archive["events"]):
                raise ValueError("该天不存在或已经结束")
            handled = {e["location_id"] for e in archive["events"] if e["kind"] in {"visit", "skip", "closed"}}
            pending = next((s for s in day["stops"] if s["location_id"] not in handled), None)
            if kind in {"visit", "skip", "closed"} and not pending:
                raise ValueError("当天没有待处理站点")
            if kind == "visit":
                location = next((p for p in catalog["locations"] if p["id"] == pending["location_id"]), None)
                if not location or location.get("withdrawn") or (location.get("access") or {}).get("status") in {"closed", "prohibited", "forbidden", "no_entry"}:
                    raise ValueError("此点禁止访问或已撤下，请跳过并反馈")
            archive["events"].append({"kind": kind, "date": day_date, "location_id": pending["location_id"] if kind in {"visit", "skip", "closed"} else "",
                                      "at_min": at_min, "recorded_at": _now()})
            if kind == "end_trip":
                archive["state"] = "ended"
        return self._change(token, trip_id, revision, change, history=False)

    def delete_personal_trip(self, token, trip_id, revision):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT body FROM personal_trips WHERE owner=? AND trip_id=?", (owner, _identifier(trip_id))).fetchone()
            if not row or type(revision) is not int or json.loads(row[0])["revision"] != revision:
                raise ValueError("行程已变化或不存在，请重新载入")
            conn.execute("DELETE FROM personal_trips WHERE owner=? AND trip_id=?", (owner, trip_id))

    def reserve_ai_call(self, token, trip_id, *, daily_limit, owner_limit, budget_units, reserve_units):
        if (any(type(val) is not int for val in (daily_limit, owner_limit, budget_units, reserve_units))
                or daily_limit <= 0 or owner_limit <= 0 or budget_units < 0 or reserve_units < 0
                or ((budget_units == 0) != (reserve_units == 0))):
            raise ValueError("AI 调用上限配置无效；可继续人工编辑")
        today = datetime.now(TOKYO).date().isoformat()
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            if trip_id and not conn.execute("SELECT 1 FROM personal_trips WHERE owner=? AND trip_id=?", (owner, _identifier(trip_id))).fetchone():
                raise ValueError("不能为其他身份的行程发起调用")
            total, reserved = conn.execute("SELECT count(*),coalesce(sum(reserved_units),0) FROM service_usage WHERE service='trip_ai' AND day=?", (today,)).fetchone()
            own = conn.execute("SELECT count(*) FROM service_usage WHERE service='trip_ai' AND day=? AND owner=?", (today, owner)).fetchone()[0]
            budget_exceeded = budget_units > 0 and reserved + reserve_units > budget_units
            if total >= daily_limit or own >= owner_limit or budget_exceeded:
                raise ValueError("今日 AI 次数或预算已达上限；原行程保留，可继续人工编辑")
            call_id = uuid.uuid4().hex
            conn.execute("INSERT INTO service_usage VALUES(?,?,?,?,?,?,?)", (call_id, owner, trip_id, "trip_ai", today, reserve_units, "reserved"))
            return call_id

    def finish_ai_call(self, token, call_id, success):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("UPDATE service_usage SET state=? WHERE id=? AND owner=?", ("succeeded" if success else "failed", call_id, owner))

    def ai_usage(self, token):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            day = datetime.now(TOKYO).date().isoformat()
            count, units = conn.execute("SELECT count(*),coalesce(sum(reserved_units),0) FROM service_usage WHERE owner=? AND day=?", (owner, day)).fetchone()
            return {"day": day, "calls": count, "reserved_cny": units / 1_000_000}
