"""Private journal, revocable public projections and explicit interest settings."""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
import secrets
import sqlite3
import uuid

from core.journal import (MAX_JOURNAL_BACKUP, clean_photo, encode_photo, public_projection,
                          recommendations, today, validate_entry, validate_photo, validate_preferences)
from core.private_store import _identifier, _json, _now, _text
from core.trip import _keys, empty_plan, new_requirements, stop_spec
from core.trip_store import TripStore
from core.place_links import places, blocked

DEFAULT_PREFERENCES = {"follows": [], "dismissed": [], "measure_consent": False}


class JournalStore(TripStore):
    def __init__(self, path=None):
        super().__init__(path)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS journal_schema(version INTEGER NOT NULL)")
            version = conn.execute("SELECT version FROM journal_schema").fetchone()
            if version and version[0] != 1:
                raise ValueError("不支持的记录库版本，请保留原数据库")
            if not version:
                statements = [
                    "CREATE TABLE journal_entries(owner TEXT NOT NULL REFERENCES identities(owner),id TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(owner,id))",
                    "CREATE TABLE journal_photos(owner TEXT NOT NULL,id TEXT NOT NULL,entry_id TEXT NOT NULL,body TEXT NOT NULL,image BLOB NOT NULL,PRIMARY KEY(owner,id),FOREIGN KEY(owner,entry_id) REFERENCES journal_entries(owner,id) ON DELETE CASCADE)",
                    "CREATE TABLE journal_tombstones(owner TEXT NOT NULL,source_key TEXT NOT NULL,PRIMARY KEY(owner,source_key))",
                    "CREATE TABLE journal_preferences(owner TEXT PRIMARY KEY REFERENCES identities(owner),body TEXT NOT NULL)",
                    "CREATE TABLE route_shares(id TEXT PRIMARY KEY,owner TEXT NOT NULL REFERENCES identities(owner),trip_id TEXT NOT NULL,body TEXT NOT NULL,active INTEGER NOT NULL,created_at TEXT NOT NULL)",
                    "CREATE TABLE journal_imports(owner TEXT NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(owner,digest))",
                    "CREATE TABLE journal_metrics(owner TEXT NOT NULL,kind TEXT NOT NULL,object_id TEXT NOT NULL,source TEXT NOT NULL,created_at TEXT NOT NULL)",
                    "CREATE TABLE contributor_invites(digest TEXT PRIMARY KEY,expires_on TEXT NOT NULL,uses INTEGER NOT NULL,issued_by TEXT NOT NULL)",
                    "CREATE TABLE contributor_access(owner TEXT PRIMARY KEY,expires_on TEXT NOT NULL)",
                    "CREATE TABLE contributions(id TEXT PRIMARY KEY,owner TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL,priority INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
                    "CREATE TABLE content_edits(id TEXT PRIMARY KEY,object_id TEXT NOT NULL,kind TEXT NOT NULL,before_json TEXT NOT NULL,after_json TEXT NOT NULL,active INTEGER NOT NULL,contribution_id TEXT NOT NULL,reviewer TEXT NOT NULL,minutes INTEGER NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL)",
                    "CREATE TABLE content_notices(id TEXT PRIMARY KEY,object_id TEXT NOT NULL,kind TEXT NOT NULL,body TEXT NOT NULL,created_at TEXT NOT NULL)",
                ]
                for statement in statements:
                    conn.execute(statement)
                conn.execute("INSERT INTO journal_schema VALUES(1)")

    def _prefs(self, conn, owner):
        row = conn.execute("SELECT body FROM journal_preferences WHERE owner=?", (owner,)).fetchone()
        return json.loads(row[0]) if row else deepcopy(DEFAULT_PREFERENCES)

    def preferences(self, token):
        with self._connection() as conn:
            return self._prefs(conn, self._owner(conn, token))

    def save_preferences(self, token, raw, catalog):
        prefs = validate_preferences(raw)
        valid = {"anime": {a["id"] for a in catalog["anime"]}, "destination": {d["id"] for d in catalog["destinations"]}}
        if any(f["id"] not in valid[f["kind"]] for f in prefs["follows"]):
            raise ValueError("请关注当前有效作品或目的地")
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("INSERT INTO journal_preferences VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET body=excluded.body", (owner, _json(prefs)))
            self._journal_size(conn, owner)
            if not prefs["measure_consent"]:
                conn.execute("DELETE FROM journal_metrics WHERE owner=?", (owner,))
        return prefs

    def _metric(self, conn, owner, kind, object_id="", source="manual"):
        if kind not in {"record_saved", "share_published", "share_trip_created", "recommendation_saved", "recommendation_trip_created", "intent_return", "update_opened", "update_saved", "update_trip_created"} or source not in {"manual", "share", "update", "recommendation"}:
            raise ValueError("不支持的产品事件")
        if self._prefs(conn, owner)["measure_consent"]:
            conn.execute("INSERT INTO journal_metrics VALUES(?,?,?,?,?)", (owner, kind, object_id, source, _now()))

    def record_intent(self, token, source="manual"):
        with self._connection() as conn:
            self._metric(conn, self._owner(conn, token), "intent_return", source=source)

    def record_journey_event(self, token, kind, object_id, source):
        with self._connection() as conn:
            self._metric(conn, self._owner(conn, token), kind, _identifier(object_id), source)

    def entries(self, token):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            return [json.loads(r[0]) for r in conn.execute("SELECT body FROM journal_entries WHERE owner=? ORDER BY id", (owner,))]

    @staticmethod
    def _entry(conn, owner, entry_id):
        row = conn.execute("SELECT body FROM journal_entries WHERE owner=? AND id=?", (owner, _identifier(entry_id))).fetchone()
        if not row:
            raise ValueError("找不到此身份的到访记录")
        return json.loads(row[0])

    def save_entry(self, token, *, location_id, visited_on, confirmed, note="", short_text="", stay_min=None,
                   entry_id=None, revision=None, trip_id="", source_key="", catalog):
        point = places(catalog).get(location_id)
        if not point:
            raise ValueError("请选择有稳定身份的地点")
        now = _now()
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            old = self._entry(conn, owner, entry_id) if entry_id else None
            if old and revision != old["revision"]:
                raise ValueError("记录已在另一页面更新，请重新载入")
            if old and old["location_id"] != location_id:
                raise ValueError("已有照片与记录绑定此地点，请新建另一记录")
            if trip_id and not conn.execute("SELECT 1 FROM personal_trips WHERE owner=? AND trip_id=?", (owner, trip_id)).fetchone():
                raise ValueError("不能引用其他身份的 Trip")
            item = validate_entry({"id": old["id"] if old else uuid.uuid4().hex, "revision": old["revision"] + 1 if old else 1,
                "location_id": location_id, "trip_id": old["trip_id"] if old else trip_id, "date": visited_on, "stay_min": stay_min,
                "confirmed": confirmed, "note": note, "short_text": short_text, "source_key": old["source_key"] if old else source_key,
                "created_at": old["created_at"] if old else now, "updated_at": now})
            if not old and conn.execute("SELECT count(*) FROM journal_entries WHERE owner=?", (owner,)).fetchone()[0] >= 500:
                raise ValueError("已达 500 条记录，请先备份整理")
            conn.execute("INSERT INTO journal_entries VALUES(?,?,?) ON CONFLICT(owner,id) DO UPDATE SET body=excluded.body", (owner, item["id"], _json(item)))
            if old:
                self._revoke_entry_shares(conn, owner, item["id"])
            self._journal_size(conn, owner)
            self._metric(conn, owner, "record_saved", item["id"])
            return item

    def import_visits(self, token, trip_id, catalog):
        trip = self.get_personal_trip(token, trip_id)
        if not trip:
            raise ValueError("找不到此身份的 Trip")
        added = 0
        # Each entry is independently durable; repeated import cannot resurrect a deletion.
        for event in trip["events"]:
            if event["kind"] != "visit" or event["date"] > today().isoformat():
                continue
            key = f"{trip_id}:{event['date']}:{event['location_id']}"
            with self._connection() as conn:
                owner = self._owner(conn, token)
                conn.execute("BEGIN IMMEDIATE")
                blocked = conn.execute("SELECT 1 FROM journal_tombstones WHERE owner=? AND source_key=?", (owner, key)).fetchone()
                existing = any(json.loads(r[0])["source_key"] == key for r in conn.execute("SELECT body FROM journal_entries WHERE owner=?", (owner,)))
                if blocked or existing:
                    continue
                if conn.execute("SELECT count(*) FROM journal_entries WHERE owner=?", (owner,)).fetchone()[0] >= 500:
                    raise ValueError("已达记录上限；已导入部分保留，可重复尝试")
                now = _now()
                entry = validate_entry({"id": uuid.uuid4().hex, "revision": 1, "location_id": event["location_id"],
                    "trip_id": trip_id, "date": event["date"], "stay_min": None, "confirmed": True, "note": "", "short_text": "",
                    "source_key": key, "created_at": now, "updated_at": now})
                conn.execute("INSERT INTO journal_entries VALUES(?,?,?)", (owner, entry["id"], _json(entry)))
                self._journal_size(conn, owner)
                self._metric(conn, owner, "record_saved", entry["id"])
                added += 1
        return added

    def _revoke_entry_shares(self, conn, owner, entry_id):
        photos = {r[0] for r in conn.execute("SELECT id FROM journal_photos WHERE owner=? AND entry_id=?", (owner, entry_id))}
        for row in conn.execute("SELECT id,body FROM route_shares WHERE owner=? AND active=1", (owner,)).fetchall():
            if photos.intersection(json.loads(row["body"])["photo_ids"]):
                conn.execute("UPDATE route_shares SET active=0 WHERE id=?", (row["id"],))

    def delete_entry(self, token, entry_id, revision):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            item = self._entry(conn, owner, entry_id)
            if item["revision"] != revision:
                raise ValueError("记录已更新，请重新载入后删除")
            self._revoke_entry_shares(conn, owner, entry_id)
            if item["source_key"]:
                conn.execute("INSERT OR IGNORE INTO journal_tombstones VALUES(?,?)", (owner, item["source_key"]))
            conn.execute("DELETE FROM journal_entries WHERE owner=? AND id=?", (owner, entry_id))

    def photos(self, token, entry_id=None):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            rows = conn.execute("SELECT body,image FROM journal_photos WHERE owner=?", (owner,))
            return [{**json.loads(r["body"]), "image": bytes(r["image"])} for r in rows if not entry_id or json.loads(r["body"])["entry_id"] == entry_id]

    def save_photo(self, token, entry_id, raw, *, taken_on, rights, scope, scene_id="", caption="", replace_id=None, catalog):
        data = clean_photo(raw)
        meta = validate_photo({"id": replace_id or uuid.uuid4().hex, "entry_id": entry_id, "scene_id": scene_id,
                               "taken_on": taken_on, "rights": rights, "scope": scope, "caption": caption})
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            entry = self._entry(conn, owner, entry_id)
            if scene_id and not any(s["id"] == scene_id and s["location_id"] == entry["location_id"] for s in catalog["scenes"]):
                raise ValueError("场景必须属于这条到访记录的地点")
            if replace_id:
                if not conn.execute("SELECT 1 FROM journal_photos WHERE owner=? AND id=? AND entry_id=?", (owner, replace_id, entry_id)).fetchone():
                    raise ValueError("找不到需要替换的照片")
                self._revoke_entry_shares(conn, owner, entry_id)
            elif conn.execute("SELECT count(*) FROM journal_photos WHERE owner=?", (owner,)).fetchone()[0] >= 50:
                raise ValueError("首版每个身份最多 50 张照片，请备份并整理")
            conn.execute("INSERT INTO journal_photos VALUES(?,?,?,?,?) ON CONFLICT(owner,id) DO UPDATE SET body=excluded.body,image=excluded.image",
                         (owner, meta["id"], entry_id, _json(meta), data))
            self._journal_size(conn, owner)
        return meta

    def delete_photo(self, token, photo_id):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT entry_id FROM journal_photos WHERE owner=? AND id=?", (owner, photo_id)).fetchone()
            if not row:
                raise ValueError("找不到此身份的照片")
            self._revoke_entry_shares(conn, owner, row[0])
            conn.execute("DELETE FROM journal_photos WHERE owner=? AND id=?", (owner, photo_id))

    def photo_scope(self, token, photo_id, rights, scope):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT body FROM journal_photos WHERE owner=? AND id=?", (owner, photo_id)).fetchone()
            if not row:
                raise ValueError("找不到此身份的照片")
            meta = validate_photo({**json.loads(row[0]), "rights": rights, "scope": scope})
            self._revoke_entry_shares(conn, owner, meta["entry_id"])
            conn.execute("UPDATE journal_photos SET body=? WHERE owner=? AND id=?", (_json(meta), owner, photo_id))
            self._journal_size(conn, owner)

    def short_draft(self, token, entry_id, catalog):
        with self._connection() as conn:
            item = self._entry(conn, self._owner(conn, token), entry_id)
        if not item["confirmed"]:
            raise ValueError("先确认到访，再整理文字")
        name = next((p["name"] for p in catalog["locations"] if p["id"] == item["location_id"]), item["location_id"])
        return f"我到访了{name}。" + (f"我记录的停留时间为 {item['stay_min']} 分钟。" if item["stay_min"] else "")

    def preview_share(self, token, trip_id, catalog, *, title="东京巡礼路线", text="", photo_ids=None):
        trip = self.get_personal_trip(token, trip_id)
        if not trip:
            raise ValueError("找不到此身份的 Trip")
        ids = list(photo_ids or [])
        if len(ids) != len(set(ids)) or len(ids) > 4:
            raise ValueError("公开副本最多选择四张自己的照片")
        entries = {e["id"]: e for e in self.entries(token)}
        photos = {p["id"]: p for p in self.photos(token)}
        stops = {s["location_id"] for d in trip["plan"]["days"] for s in d["stops"]}
        for photo_id in ids:
            photo = photos.get(photo_id)
            entry = entries.get(photo["entry_id"]) if photo else None
            if not photo or photo["rights"] != "own" or photo["scope"] != "share_allowed" or not entry or not entry["confirmed"] or entry["location_id"] not in stops:
                raise ValueError("只能选择已确认到访、与路线相关且明确允许分享的本人照片")
        public = public_projection(trip["plan"], catalog, title=title, text=text, photo_ids=ids)
        public["photo_checks"] = {pid: hashlib.sha256(photos[pid]["image"]).hexdigest() for pid in ids}
        return public

    def publish_share(self, token, trip_id, revision, preview, catalog):
        # Reconstruct and compare the exact preview. Never store caller-supplied extra fields.
        _keys(preview, {"title", "text", "destination_id", "days", "photo_ids", "photo_checks", "warning"},
              {"title", "text", "destination_id", "days", "photo_ids", "photo_checks", "warning"})
        clean = self.preview_share(token, trip_id, catalog, title=preview["title"], text=preview["text"], photo_ids=preview["photo_ids"])
        if clean != preview:
            raise ValueError("预览内容已变化，请重新预览")
        share_id = secrets.token_urlsafe(24)
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT body FROM personal_trips WHERE owner=? AND trip_id=?", (owner, trip_id)).fetchone()
            if not row or json.loads(row[0])["revision"] != revision:
                raise ValueError("Trip 已变化，请重新预览")
            if conn.execute("SELECT count(*) FROM route_shares WHERE owner=? AND active=1", (owner,)).fetchone()[0] >= 20:
                raise ValueError("最多保留 20 份有效分享，请先撤下旧副本")
            # A concurrent image change/deletion must not publish stale permissions.
            for pid in clean["photo_ids"]:
                row = conn.execute("SELECT body,entry_id,image FROM journal_photos WHERE owner=? AND id=?", (owner, pid)).fetchone()
                if not row or json.loads(row["body"])["scope"] != "share_allowed" or hashlib.sha256(bytes(row["image"])).hexdigest() != clean["photo_checks"][pid] or not self._entry(conn, owner, row["entry_id"])["confirmed"]:
                    raise ValueError("照片或到访状态已变化，请重新预览")
            clean.pop("photo_checks")
            conn.execute("INSERT INTO route_shares VALUES(?,?,?,?,1,?)", (share_id, owner, trip_id, _json(clean), _now()))
            self._metric(conn, owner, "share_published", share_id)
        return share_id

    def public_share(self, share_id, catalog=None):
        if not isinstance(share_id, str) or len(share_id) != 32:
            return None
        with self._connection() as conn:
            row = conn.execute("SELECT owner,body FROM route_shares WHERE id=? AND active=1", (share_id,)).fetchone()
            if not row:
                return None
            result = json.loads(row["body"])
            from core.pilot import load_pilot
            current = catalog if catalog is not None else self.catalog(load_pilot())
            if catalog is None:
                import os
                from pathlib import Path
                from core.map_query import MapQueryService
                from core.place_links import current_catalog
                root = os.getenv("ANIMEWAY_SNAPSHOT_DIR") or "knowledge_base/releases"
                if os.getenv("ANIMEWAY_SNAPSHOT_DIR") or (Path(root) / "current.json").exists():
                    try:
                        service = MapQueryService.from_snapshot(root, lambda: self.catalog(load_pilot()))
                        current = current_catalog(service, current)
                    except (OSError, ValueError, sqlite3.Error, TypeError, KeyError):
                        return None
            current_places = places(current)
            if any(blocked(current_places.get(s['location_id'])) for day in result['days'] for s in day['stops']):
                return None
            for day in result['days']:
                for stop in day['stops']:
                    stop['name'] = current_places[stop['location_id']]['name']
            photos = []
            for pid in result.pop("photo_ids"):
                p = conn.execute("SELECT body,image,entry_id FROM journal_photos WHERE owner=? AND id=?", (row["owner"], pid)).fetchone()
                if not p or json.loads(p["body"])["scope"] != "share_allowed" or not self._entry(conn, row["owner"], p["entry_id"])["confirmed"]:
                    return None
                # No capture date, caption, EXIF, filename, private record/photo ID.
                photos.append(bytes(p["image"]))
            return {**result, "photos": photos}

    def shares(self, token):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            return [{"id": r["id"], "active": bool(r["active"]), "title": json.loads(r["body"])["title"]} for r in conn.execute("SELECT id,body,active FROM route_shares WHERE owner=?", (owner,))]

    def revoke_share(self, token, share_id):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            if not conn.execute("UPDATE route_shares SET active=0 WHERE owner=? AND id=?", (owner, share_id)).rowcount:
                raise ValueError("找不到此身份的分享")

    def preview_copy_share(self, share_id, start_date, catalog):
        shared = self.public_share(share_id, catalog)
        if not shared:
            raise ValueError("分享不存在或已经撤下")
        places = {p["id"]: p for p in catalog["locations"]}
        ids = [s["location_id"] for d in shared["days"] for s in d["stops"]]
        if any(i not in places or places[i].get("withdrawn") or places[i]["access"]["status"] in {"closed", "prohibited", "forbidden", "no_entry"} for i in ids):
            raise ValueError("有地点已撤下或不宜访问，暂停复制；请按当前资料重新选择")
        works = list(dict.fromkeys(a for i in ids for a in places[i]["anime_ids"]))
        plan = empty_plan(new_requirements(start_date, len(shared["days"]), anime_ids=works, title=shared["title"]))
        for day, source in zip(plan["days"], shared["days"]):
            day["stops"] = [{**stop_spec(s["location_id"], required=s["required"]), "stay_min": s["stay_min"]} for s in source["stops"]]
        plan["requirements"]["must_ids"] = [s["location_id"] for d in shared["days"] for s in d["stops"] if s["required"]]
        from core.trip import evaluate
        return {"plan": plan, "check": evaluate(plan, catalog)}

    def copy_share(self, token, share_id, start_date, catalog):
        plan = self.preview_copy_share(share_id, start_date, catalog)["plan"]
        # Recheck revocation and create the Trip under the same write transaction.
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM route_shares WHERE id=? AND active=1", (share_id,)).fetchone():
                raise ValueError("分享已撤下")
            from core.trip import validate_archive
            now = _now()
            trip = validate_archive({"id": uuid.uuid4().hex, "revision": 1, "state": "draft", "created_at": now, "updated_at": now, "plan": plan, "history": [], "events": []})
            if conn.execute("SELECT count(*) FROM personal_trips WHERE owner=?", (owner,)).fetchone()[0] >= 200:
                raise ValueError("个人 Trip 已达上限")
            conn.execute("INSERT INTO personal_trips VALUES(?,?,?)", (owner, trip["id"], _json(trip)))
            self._check_portable_size(conn, owner)
            self._metric(conn, owner, "share_trip_created", share_id, "share")
        return trip

    def delete_personal_trip(self, token, trip_id, revision):
        # Same transaction as deletion; never leave an unintended active public copy.
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT body FROM personal_trips WHERE owner=? AND trip_id=?", (owner, trip_id)).fetchone()
            if not row or json.loads(row[0])["revision"] != revision:
                raise ValueError("Trip 已变化或不存在")
            conn.execute("UPDATE route_shares SET active=0 WHERE owner=? AND trip_id=?", (owner, trip_id))
            conn.execute("DELETE FROM personal_trips WHERE owner=? AND trip_id=?", (owner, trip_id))

    def recommend(self, token, catalog):
        return recommendations(catalog, self.preferences(token), self.list_wishlist(token), self.entries(token))

    def save_recommendation(self, token, location_id, catalog):
        point = next((r["location"] for r in self.recommend(token, catalog) if r["location"]["id"] == location_id), None)
        if not point:
            raise ValueError("推荐已失效，请刷新")
        added = self.add_wishlist(token, point)
        if added:
            with self._connection() as conn:
                self._metric(conn, self._owner(conn, token), "recommendation_saved", location_id, "recommendation")
        return added

    def create_recommended_trip(self, token, ids, start_date, catalog):
        current = {r["location"]["id"]: r["location"] for r in self.recommend(token, catalog)}
        if not isinstance(ids, list) or not 1 <= len(ids) <= 3 or any(i not in current for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("候选或兴趣已变化，请重新预览")
        works = list(dict.fromkeys(a for i in ids for a in current[i]["anime_ids"]))
        plan = empty_plan(new_requirements(start_date, 1, anime_ids=works, title="下一次东京巡礼"))
        plan["days"][0]["stops"] = [stop_spec(i) for i in ids]
        trip = self.create_personal_trip(token, plan)
        with self._connection() as conn:
            self._metric(conn, self._owner(conn, token), "recommendation_trip_created", trip["id"], "recommendation")
        return trip

    def _journal_payload(self, conn, owner):
        return {"schema_version": 1,
                "entries": [json.loads(r[0]) for r in conn.execute("SELECT body FROM journal_entries WHERE owner=? ORDER BY id", (owner,))],
                "photos": [{**json.loads(r["body"]), "data": encode_photo(bytes(r["image"]))} for r in conn.execute("SELECT body,image FROM journal_photos WHERE owner=? ORDER BY id", (owner,))],
                "preferences": self._prefs(conn, owner),
                "deleted_sources": [r[0] for r in conn.execute("SELECT source_key FROM journal_tombstones WHERE owner=? ORDER BY source_key", (owner,))]}

    def _journal_size(self, conn, owner):
        if len(_json(self._journal_payload(conn, owner)).encode()) > MAX_JOURNAL_BACKUP:
            raise ValueError("记录与照片备份超过 16 MiB，请先备份并整理；原数据保留")

    def export_journal(self, token):
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN")
            return _json(self._journal_payload(conn, owner))

    def import_journal(self, token, raw, *, preview=False):
        if not isinstance(raw, str) or len(raw.encode()) > MAX_JOURNAL_BACKUP:
            raise ValueError("记录备份不得超过 16 MiB")
        try:
            data = json.loads(raw)
            _keys(data, {"schema_version", "entries", "photos", "preferences", "deleted_sources"},
                  {"schema_version", "entries", "photos", "preferences", "deleted_sources"})
            if type(data["schema_version"]) is not int or data["schema_version"] != 1 or not isinstance(data["entries"], list) or len(data["entries"]) > 500 or not isinstance(data["photos"], list) or len(data["photos"]) > 50:
                raise ValueError("不支持的记录备份")
            entries = [validate_entry(e) for e in data["entries"]]
            if len({e["id"] for e in entries}) != len(entries):
                raise ValueError("重复记录编号")
            prefs = validate_preferences(data["preferences"])
            deleted = data["deleted_sources"]
            if not isinstance(deleted, list):
                raise ValueError("删除标记无效")
            deleted = [_text(k, "source key", 400) for k in deleted]
            photos, photo_ids = [], set()
            for item in data["photos"]:
                _keys(item, {"id", "entry_id", "scene_id", "taken_on", "rights", "scope", "caption", "data"})
                meta = validate_photo({k: v for k, v in item.items() if k != "data"})
                if meta["id"] in photo_ids or meta["entry_id"] not in {e["id"] for e in entries}:
                    raise ValueError("照片重复或没有归属记录")
                photo_ids.add(meta["id"])
                image = clean_photo(base64.b64decode(item["data"], validate=True))
                photos.append((meta, image))
        except (KeyError, TypeError, RecursionError, AttributeError) as exc:
            raise ValueError("记录备份格式不正确，未导入数据") from exc
        digest = hashlib.sha256(_json(data).encode()).hexdigest()
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN" if preview else "BEGIN IMMEDIATE")
            if preview:
                return {"entries": entries, "photos": [meta for meta, _ in photos], "digest": digest,
                        "already_imported": bool(conn.execute("SELECT 1 FROM journal_imports WHERE owner=? AND digest=?", (owner, digest)).fetchone())}
            if conn.execute("SELECT 1 FROM journal_imports WHERE owner=? AND digest=?", (owner, digest)).fetchone():
                return 0
            if conn.execute("SELECT count(*) FROM journal_entries WHERE owner=?", (owner,)).fetchone()[0] + len(entries) > 500 or conn.execute("SELECT count(*) FROM journal_photos WHERE owner=?", (owner,)).fetchone()[0] + len(photos) > 50:
                raise ValueError("恢复后超出记录或照片上限")
            mapping = {e["id"]: uuid.uuid4().hex for e in entries}
            for entry in entries:
                entry = {**entry, "id": mapping[entry["id"]], "trip_id": "", "source_key": ""}
                conn.execute("INSERT INTO journal_entries VALUES(?,?,?)", (owner, entry["id"], _json(entry)))
            for meta, image in photos:
                meta = {**meta, "id": uuid.uuid4().hex, "entry_id": mapping[meta["entry_id"]], "scope": "private"}
                conn.execute("INSERT INTO journal_photos VALUES(?,?,?,?,?)", (owner, meta["id"], meta["entry_id"], _json(meta), image))
            current = self._prefs(conn, owner)
            known = {(f["kind"], f["id"]) for f in current["follows"]}
            current["follows"] += [f for f in prefs["follows"] if (f["kind"], f["id"]) not in known]
            current["dismissed"] = list(dict.fromkeys(current["dismissed"] + prefs["dismissed"]))
            validate_preferences(current)
            conn.execute("INSERT INTO journal_preferences VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET body=excluded.body", (owner, _json(current)))
            for key in deleted:
                conn.execute("INSERT OR IGNORE INTO journal_tombstones VALUES(?,?)", (owner, key))
            self._journal_size(conn, owner)
            conn.execute("INSERT INTO journal_imports VALUES(?,?)", (owner, digest))
            return len(entries)

    def catalog(self, baseline):
        from core.contributions import current_catalog
        with self._connection() as conn:
            return current_catalog(conn, baseline)
