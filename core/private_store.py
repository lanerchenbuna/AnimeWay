"""Private, durable pilot data, scoped by an unguessable browser bearer identity.

Tokens are never stored verbatim.  This module has no public administrator API;
correction review is deliberately a separate local command.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Any
from urllib.parse import urlsplit
import uuid


SCHEMA_VERSION = 2
BACKUP_VERSION = 2
MAX_BACKUP_BYTES = 5 * 1024 * 1024
MAX_WISHLIST_ITEMS = 5000
MAX_TRIPS = 200
MAX_STOPS = 100
EVENTS = frozenset(
    {"view_location", "view_anime", "save_wishlist", "adopt_route", "start_trip", "restore_backup"}
)
CORRECTION_KINDS = frozenset(
    {"geography", "scene", "access", "image", "source", "duplicate", "other"}
)
CORRECTION_STATUSES = frozenset({"pending", "needs_info", "accepted", "rejected"})
CONNECTION_STATUSES = frozenset({"unknown", "needs_recheck", "reference_only", "estimated"})
ACCESS_STATUSES = frozenset({"unknown", "public_exterior", "restricted", "closed", "prohibited"})
ACCESS_FIELDS = frozenset({"status", "summary", "source_url", "checked_at"})
LOCATION_FIELDS = frozenset(
    {"id", "name", "lat", "lon", "city", "anime_ids", "scene_ids", "source_url",
     "source_version", "legacy", "_anime_name", "access", "viewpoint", "entry"}
)
STOP_FIELDS = LOCATION_FIELDS | {"required", "reason", "stay_min", "stay_max", "stay_status", "visit_mode", "skip_if"}
TRIP_FIELDS = frozenset(
    {"id", "title", "template_id", "template_version", "created_at", "updated_at",
     "revision", "started_at", "stops", "source_reviewed_at", "unknowns", "connection_status", "reference_notes"}
)
_ID = re.compile(r"^[\w.:-]{1,200}$", re.UNICODE)
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _text(value: Any, field: str, limit: int = 2000, *, empty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError(f"Invalid {field}")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError(f"Invalid {field}")
    return value.strip()


def _identifier(value: Any, field: str = "id") -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {field}")
    return value


def _url(value: Any) -> str:
    value = _text(value, "source_url", 2048)
    if value:
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Invalid source_url")
        except ValueError as exc:
            raise ValueError("Invalid source_url") from exc
    return value


def _ids(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 200:
        raise ValueError(f"Invalid {field}")
    return list(dict.fromkeys(_identifier(item, field) for item in value))


def _version(value: Any, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"Invalid {field}")
    return _text(str(value), field, 100)


def _access(raw: Any, *, strict: bool = False) -> dict:
    if not isinstance(raw, dict) or (strict and set(raw) - ACCESS_FIELDS):
        raise ValueError("Invalid access fields")
    status = raw.get("status", "unknown")
    if not isinstance(status, str) or status not in ACCESS_STATUSES:
        raise ValueError("Invalid access status")
    return {
        "status": status,
        "summary": _text(raw.get("summary", ""), "access summary", 3000),
        "source_url": _url(raw.get("source_url", "")),
        "checked_at": _timestamp(raw.get("checked_at") if raw.get("checked_at") is not None else "", "access checked_at", empty=True),
    }


def _location(raw: Any, *, strict: bool = False) -> dict:
    if not isinstance(raw, dict) or (strict and set(raw) - LOCATION_FIELDS):
        raise ValueError("Invalid location fields")
    result: dict[str, Any] = {
        "id": _identifier(raw.get("id")),
        "name": _text(raw.get("name"), "name", 300, empty=False),
    }
    for field, bound in (("lat", 90), ("lon", 180)):
        coordinate = raw.get(field)
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
            raise ValueError(f"Invalid {field}")
        if not math.isfinite(coordinate) or not -bound <= coordinate <= bound:
            raise ValueError(f"Invalid {field}")
        result[field] = float(coordinate)
    result.update(
        city=_text(raw.get("city", ""), "city", 300),
        anime_ids=_ids(raw.get("anime_ids", []), "anime_ids"),
        scene_ids=_ids(raw.get("scene_ids", []), "scene_ids"),
        source_url=_url(raw.get("source_url", "")),
        source_version=_version(raw.get("source_version", ""), "source_version"),
    )
    legacy = raw.get("legacy", False)
    if not isinstance(legacy, bool):
        raise ValueError("Invalid legacy")
    result["legacy"] = legacy
    if "_anime_name" in raw:
        result["_anime_name"] = _text(raw["_anime_name"], "_anime_name", 300)
    if "access" in raw:
        result["access"] = _access(raw["access"], strict=strict)
    for field in ("viewpoint", "entry"):
        if field in raw:
            result[field] = _text(raw[field], field, 3000)
    return result


def _stop(raw: Any, *, strict: bool = False) -> dict:
    if not isinstance(raw, dict) or (strict and set(raw) - STOP_FIELDS):
        raise ValueError("Invalid stop fields")
    result = _location({key: val for key, val in raw.items() if key in LOCATION_FIELDS}, strict=strict)
    required = raw.get("required", True)
    if not isinstance(required, bool):
        raise ValueError("Invalid required")
    result.update(required=required, reason=_text(raw.get("reason", ""), "reason", 2000))
    for field in ("stay_status", "visit_mode", "skip_if"):
        if field in raw:
            result[field] = _text(raw[field], field, 2000 if field == "skip_if" else 100)
    for field in ("stay_min", "stay_max"):
        value = raw.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1440):
            raise ValueError(f"Invalid {field}")
        result[field] = value
    if result["stay_min"] is not None and result["stay_max"] is not None and result["stay_min"] > result["stay_max"]:
        raise ValueError("Invalid stay range")
    return result


def _timestamp(value: Any, field: str, *, empty: bool = False) -> str:
    value = _text(value, field, 80, empty=empty)
    if not value and empty:
        return value
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid {field}") from exc
    return value


def _trip(raw: Any, *, strict: bool = False) -> dict:
    if not isinstance(raw, dict) or (strict and set(raw) - TRIP_FIELDS):
        raise ValueError("Invalid trip fields")
    stops = raw.get("stops")
    if not isinstance(stops, list) or not 1 <= len(stops) <= MAX_STOPS:
        raise ValueError("Invalid trip stops")
    revision = raw.get("revision", 1)
    if isinstance(revision, bool) or not isinstance(revision, int) or not 1 <= revision <= 1_000_000:
        raise ValueError("Invalid revision")
    unknowns = raw.get("unknowns", [])
    if not isinstance(unknowns, list) or len(unknowns) > 100:
        raise ValueError("Invalid unknowns")
    connection_status = raw.get("connection_status", "unknown")
    if not isinstance(connection_status, str) or connection_status not in CONNECTION_STATUSES:
        raise ValueError("Invalid connection_status; the pilot cannot assert verified travel")
    reference_notes = raw.get("reference_notes", [])
    if not isinstance(reference_notes, list) or len(reference_notes) > 20:
        raise ValueError("Invalid reference notes")
    reference_notes = [_text(item, "reference note", 3000) for item in reference_notes]
    clean = {
        "id": _identifier(raw.get("id")),
        "title": _text(raw.get("title"), "title", 300, empty=False),
        "template_id": _identifier(raw.get("template_id"), "template_id"),
        "template_version": _version(raw.get("template_version", ""), "template_version"),
        "created_at": _timestamp(raw.get("created_at"), "created_at"),
        "updated_at": _timestamp(raw.get("updated_at"), "updated_at"),
        "revision": revision,
        "stops": [_stop(stop, strict=strict) for stop in stops],
        "source_reviewed_at": _timestamp(raw.get("source_reviewed_at", ""), "source_reviewed_at", empty=True),
        "unknowns": [_text(item, "unknown", 2000) for item in unknowns],
        "connection_status": connection_status,
        "reference_notes": [] if connection_status == "needs_recheck" else reference_notes,
    }
    if len({stop["id"] for stop in clean["stops"]}) != len(stops):
        raise ValueError("Duplicate trip stop")
    if raw.get("started_at"):
        clean["started_at"] = _timestamp(raw["started_at"], "started_at")
    return clean


def _event_metadata(raw: Any) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("Invalid event metadata")
    clean = {}
    # Deliberately no arbitrary text, search input, source URLs, or nested payloads.
    for key in ("count", "wishlist_count", "trip_count", "stop_count"):
        value = raw.get(key)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100000:
                raise ValueError("Invalid event count")
            clean[key] = value
    if raw.get("source") in {"discover", "anime", "location", "route", "legacy", "backup", "trip"}:
        clean["source"] = raw["source"]
    return clean


class PrivateStore:
    """SQLite store. Every user operation validates and scopes its identity token."""

    def __init__(self, path: str | Path | None = None):
        if path is None:
            directory = Path(os.environ.get("ANIMEWAY_DATA_DIR") or Path(__file__).resolve().parents[1] / ".animeway")
            path = directory / "private.sqlite3"
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Never reset or replace an unreadable database: surface the error to the caller.
        with self._connection() as conn:
            # Changing journal mode can return SQLITE_BUSY immediately during a
            # first-run race, even with busy_timeout. Retry only that condition.
            deadline = time.monotonic() + 10
            while True:
                try:
                    conn.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.02)
            # Serialize first-run initialization across simultaneous browser sessions.
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, SCHEMA_VERSION):
                raise ValueError("Unsupported private database version; keep the file and upgrade the application")
            if version == 0:
                existing = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
                if existing:
                    raise ValueError("Unversioned private database; explicit migration required")
                schema = """
                    CREATE TABLE identities (owner TEXT PRIMARY KEY, created_at TEXT NOT NULL);
                    CREATE TABLE wishlist (
                        owner TEXT NOT NULL REFERENCES identities(owner), location_id TEXT NOT NULL,
                        body TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(owner, location_id)
                    );
                    CREATE TABLE trips (
                        owner TEXT NOT NULL REFERENCES identities(owner), trip_id TEXT NOT NULL,
                        body TEXT NOT NULL, PRIMARY KEY(owner, trip_id)
                    );
                    CREATE TABLE events (
                        id INTEGER PRIMARY KEY, owner TEXT NOT NULL REFERENCES identities(owner),
                        event TEXT NOT NULL, object_id TEXT NOT NULL, metadata TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE corrections (
                        id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES identities(owner),
                        location_id TEXT NOT NULL, kind TEXT NOT NULL, description TEXT NOT NULL,
                        source_url TEXT NOT NULL, status TEXT NOT NULL, review_note TEXT NOT NULL,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE TABLE backup_imports (
                        owner TEXT NOT NULL REFERENCES identities(owner), digest TEXT NOT NULL,
                        created_at TEXT NOT NULL, PRIMARY KEY(owner, digest)
                    );
                    PRAGMA user_version=1;
                """
                for statement in schema.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                version = 1
            if version == 1:
                conn.execute("CREATE TABLE personal_trips (owner TEXT NOT NULL REFERENCES identities(owner), trip_id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(owner,trip_id))")
                conn.execute("CREATE TABLE service_usage (id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES identities(owner), trip_id TEXT NOT NULL, service TEXT NOT NULL, day TEXT NOT NULL, reserved_units INTEGER NOT NULL, state TEXT NOT NULL)")
                conn.execute("PRAGMA user_version=2")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass  # Windows / filesystem permission behavior does not change SQL ownership.

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _owner(conn: sqlite3.Connection, token: str) -> str:
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise ValueError("Unknown browser identity")
        owner = hashlib.sha256(token.encode("ascii")).hexdigest()
        if not conn.execute("SELECT 1 FROM identities WHERE owner=?", (owner,)).fetchone():
            raise ValueError("Unknown browser identity")
        return owner

    @staticmethod
    def _event(conn, owner: str, event: str, object_id: str = "", metadata: dict | None = None):
        conn.execute(
            "INSERT INTO events(owner,event,object_id,metadata,created_at) VALUES(?,?,?,?,?)",
            (owner, event, object_id, _json(_event_metadata(metadata)), _now()),
        )

    @staticmethod
    def _check_portable_size(conn: sqlite3.Connection, owner: str) -> None:
        """Every accepted collection must still fit in its own restore format."""
        size = len(_json({"schema_version": BACKUP_VERSION, "wishlist": [], "trips": [], "personal_trips": []}).encode("utf-8"))
        for table in ("wishlist", "trips", "personal_trips"):
            count, body_size = conn.execute(
                f"SELECT count(*),coalesce(sum(length(CAST(body AS BLOB))),0) FROM {table} WHERE owner=?",
                (owner,),
            ).fetchone()
            size += body_size + max(0, count - 1)
        if size > MAX_BACKUP_BYTES:
            raise ValueError("Private collection exceeds portable backup limit; export and remove unused items first")

    def new_identity(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._connection() as conn:
            conn.execute("INSERT INTO identities(owner,created_at) VALUES(?,?)", (hashlib.sha256(token.encode("ascii")).hexdigest(), _now()))
        return token

    def has_identity(self, token: str) -> bool:
        with self._connection() as conn:
            try:
                self._owner(conn, token)
                return True
            except ValueError:
                return False

    def list_wishlist(self, token: str) -> list[dict]:
        with self._connection() as conn:
            owner = self._owner(conn, token)
            return [json.loads(row["body"]) for row in conn.execute("SELECT body FROM wishlist WHERE owner=? ORDER BY created_at,location_id", (owner,))]

    def add_wishlist(self, token: str, location: dict) -> bool:
        with self._connection() as conn:
            owner = self._owner(conn, token)
            clean = _location(location)
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM wishlist WHERE owner=? AND location_id=?", (owner, clean["id"])).fetchone():
                return False
            if conn.execute("SELECT count(*) FROM wishlist WHERE owner=?", (owner,)).fetchone()[0] >= MAX_WISHLIST_ITEMS:
                raise ValueError("Wishlist storage limit reached; export a backup before adding more")
            conn.execute("INSERT INTO wishlist VALUES(?,?,?,?)", (owner, clean["id"], _json(clean), _now()))
            self._check_portable_size(conn, owner)
            self._event(conn, owner, "save_wishlist", clean["id"])
            return True

    def remove_wishlist(self, token: str, location_id: str) -> None:
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("DELETE FROM wishlist WHERE owner=? AND location_id=?", (owner, _identifier(location_id)))

    def create_trip(self, token: str, route: dict, locations: list[dict]) -> dict:
        with self._connection() as conn:
            owner = self._owner(conn, token)
            if not isinstance(route, dict) or not isinstance(locations, list) or len(locations) > MAX_STOPS:
                raise ValueError("Invalid route")
            points = {point["id"]: point for point in (_location(item) for item in locations)}
            if len(points) != len(locations):
                raise ValueError("Duplicate location")
            raw_stops = route.get("stops", route.get("location_ids", route.get("stop_ids", list(points))))
            if not isinstance(raw_stops, list) or not 1 <= len(raw_stops) <= MAX_STOPS:
                raise ValueError("Invalid route stops")
            stops = []
            for spec in raw_stops:
                spec = {"location_id": spec} if isinstance(spec, (str, int)) else spec
                if not isinstance(spec, dict):
                    raise ValueError("Invalid route stop")
                location_id = _identifier(spec.get("location_id", spec.get("id")))
                if location_id not in points:
                    raise ValueError("Route references a missing location")
                stop = dict(points[location_id])
                stop.update({key: spec[key] for key in ("required", "reason", "stay_min", "stay_max", "scene_ids", "visit_mode", "skip_if", "stay_status") if key in spec})
                if "required" not in spec and "optional" in spec:
                    if not isinstance(spec["optional"], bool):
                        raise ValueError("Invalid optional")
                    stop["required"] = not spec["optional"]
                stops.append(stop)
            now = _now()
            trip = _trip({
                "id": uuid.uuid4().hex, "title": route.get("title", route.get("name")),
                "template_id": route.get("id"), "template_version": _version(route.get("version", ""), "template_version"),
                "created_at": now, "updated_at": now, "revision": 1, "stops": stops,
                "source_reviewed_at": route.get("source_reviewed_at", route.get("reviewed_at", "")) or "",
                "unknowns": route.get("unknowns", []), "connection_status": route.get("connection_status", "unknown"),
                "reference_notes": route.get("reference_notes", []),
            })
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT count(*) FROM trips WHERE owner=?", (owner,)).fetchone()[0] >= MAX_TRIPS:
                raise ValueError("Trip storage limit reached; export a backup before adding more")
            conn.execute("INSERT INTO trips VALUES(?,?,?)", (owner, trip["id"], _json(trip)))
            self._check_portable_size(conn, owner)
            self._event(conn, owner, "adopt_route", trip["template_id"], {"stop_count": len(stops)})
            return trip

    def list_trips(self, token: str) -> list[dict]:
        with self._connection() as conn:
            owner = self._owner(conn, token)
            trips = [json.loads(row["body"]) for row in conn.execute("SELECT body FROM trips WHERE owner=?", (owner,))]
            return sorted(trips, key=lambda trip: trip["updated_at"], reverse=True)

    def get_trip(self, token: str, trip_id: str) -> dict | None:
        with self._connection() as conn:
            owner = self._owner(conn, token)
            row = conn.execute("SELECT body FROM trips WHERE owner=? AND trip_id=?", (owner, _identifier(trip_id))).fetchone()
            return json.loads(row["body"]) if row else None

    def update_trip(self, token: str, trip_id: str, expected_revision: int, *, title: str | None = None, remove_location_id: str | None = None) -> dict:
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT body FROM trips WHERE owner=? AND trip_id=?", (owner, _identifier(trip_id))).fetchone()
            if not row:
                raise ValueError("Trip not found")
            trip = json.loads(row["body"])
            if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or trip["revision"] != expected_revision:
                raise ValueError("Trip changed in another view; reload before editing")
            if title is not None:
                trip["title"] = _text(title, "title", 300, empty=False)
            if remove_location_id is not None:
                remove_location_id = _identifier(remove_location_id)
                stop = next((stop for stop in trip["stops"] if stop["id"] == remove_location_id), None)
                if stop is None:
                    raise ValueError("Stop not found")
                if stop["required"]:
                    raise ValueError("Required stops cannot be removed in the pilot")
                if len(trip["stops"]) == 1:
                    raise ValueError("A trip needs at least one stop")
                trip["stops"] = [stop for stop in trip["stops"] if stop["id"] != remove_location_id]
                trip["connection_status"] = "needs_recheck"
                # No template travel time / distance is copied into personal snapshots.
                notice = "站点已删减，剩余地点之间的连接需要重新核查；原路线耗时不再适用。"
                if notice not in trip["unknowns"]:
                    trip["unknowns"].append(notice)
            trip["revision"] += 1
            trip["updated_at"] = _now()
            trip = _trip(trip)
            conn.execute("UPDATE trips SET body=? WHERE owner=? AND trip_id=?", (_json(trip), owner, trip_id))
            self._check_portable_size(conn, owner)
            return trip

    def delete_trip(self, token: str, trip_id: str) -> None:
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("DELETE FROM trips WHERE owner=? AND trip_id=?", (owner, _identifier(trip_id)))

    def start_trip(self, token: str, trip_id: str) -> dict:
        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT body FROM trips WHERE owner=? AND trip_id=?", (owner, _identifier(trip_id))).fetchone()
            if not row:
                raise ValueError("Trip not found")
            trip = json.loads(row["body"])
            if not trip.get("started_at"):
                trip["started_at"] = _now()
                trip["updated_at"] = trip["started_at"]
                trip["revision"] += 1
                conn.execute("UPDATE trips SET body=? WHERE owner=? AND trip_id=?", (_json(trip), owner, trip_id))
                self._check_portable_size(conn, owner)
                self._event(conn, owner, "start_trip", trip_id)
            return trip

    def export_backup(self, token: str) -> str:
        from core.trip import validate_archive

        with self._connection() as conn:
            owner = self._owner(conn, token)
            conn.execute("BEGIN")
            wishlist = [_location(json.loads(row["body"]), strict=True) for row in conn.execute("SELECT body FROM wishlist WHERE owner=? ORDER BY location_id", (owner,))]
            trips = [_trip(json.loads(row["body"]), strict=True) for row in conn.execute("SELECT body FROM trips WHERE owner=? ORDER BY trip_id", (owner,))]
            personal = [validate_archive(json.loads(row["body"])) for row in conn.execute("SELECT body FROM personal_trips WHERE owner=? ORDER BY trip_id", (owner,))]
            return _json({"schema_version": BACKUP_VERSION, "wishlist": wishlist, "trips": trips, "personal_trips": personal})

    def import_backup(self, token: str, raw: str, *, preview: bool = False) -> dict:
        from core.trip import validate_archive

        with self._connection() as conn:
            owner = self._owner(conn, token)
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BACKUP_BYTES:
                raise ValueError("Backup exceeds 5 MiB limit")
            try:
                payload = json.loads(raw)
            except (ValueError, RecursionError) as exc:
                raise ValueError("Invalid backup JSON") from exc
            if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] not in {1, BACKUP_VERSION}:
                raise ValueError("Unsupported backup schema; no records imported")
            expected = {"schema_version", "wishlist", "trips"} | ({"personal_trips"} if payload["schema_version"] == 2 else set())
            if set(payload) != expected:
                raise ValueError("Unsupported backup fields; no records imported")
            personal_raw = payload.get("personal_trips", [])
            if not isinstance(personal_raw, list) or len(personal_raw) > MAX_TRIPS:
                raise ValueError("Personal Trip import limit exceeded")
            personal = [validate_archive(item) for item in personal_raw]
            if len({item["id"] for item in personal}) != len(personal):
                raise ValueError("Duplicate personal Trip IDs")
            if not isinstance(payload["wishlist"], list) or len(payload["wishlist"]) > MAX_WISHLIST_ITEMS or not isinstance(payload["trips"], list) or len(payload["trips"]) > MAX_TRIPS:
                raise ValueError("Backup item limit exceeded")
            wishlist = [_location(item, strict=True) for item in payload["wishlist"]]
            trips = [_trip(item, strict=True) for item in payload["trips"]]
            if len({trip["id"] for trip in trips}) != len(trips):
                raise ValueError("Duplicate backup trip IDs")
            # Canonical digest makes re-import safe, even after later personal edits.
            digest_body = {"wishlist": sorted(wishlist, key=lambda item: item["id"]), "trips": sorted(trips, key=lambda item: item["id"])}
            if personal:
                digest_body["personal_trips"] = sorted(personal, key=lambda item: item["id"])
            digest = hashlib.sha256(_json(digest_body).encode("utf-8")).hexdigest()
            if preview:
                return {"wishlist": wishlist, "trips": trips, "personal_trips": personal,
                        "digest": digest, "already_imported": bool(conn.execute("SELECT 1 FROM backup_imports WHERE owner=? AND digest=?", (owner, digest)).fetchone())}
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM backup_imports WHERE owner=? AND digest=?", (owner, digest)).fetchone():
                return {"wishlist_added": 0, "trips_added": 0, "already_imported": True}
            if conn.execute("SELECT count(*) FROM personal_trips WHERE owner=?", (owner,)).fetchone()[0] + len(personal) > MAX_TRIPS:
                raise ValueError("Import would exceed personal Trip limits")
            current_ids = {row[0] for row in conn.execute("SELECT location_id FROM wishlist WHERE owner=?", (owner,))}
            if len(current_ids | {point["id"] for point in wishlist}) > MAX_WISHLIST_ITEMS or conn.execute("SELECT count(*) FROM trips WHERE owner=?", (owner,)).fetchone()[0] + len(trips) > MAX_TRIPS:
                raise ValueError("Import would exceed private storage limits")
            added = 0
            for point in wishlist:
                cursor = conn.execute("INSERT OR IGNORE INTO wishlist VALUES(?,?,?,?)", (owner, point["id"], _json(point), _now()))
                added += cursor.rowcount
            for trip in trips:
                trip["id"] = uuid.uuid4().hex
                conn.execute("INSERT INTO trips VALUES(?,?,?)", (owner, trip["id"], _json(trip)))
            for trip in personal:
                trip["id"] = uuid.uuid4().hex
                conn.execute("INSERT INTO personal_trips VALUES(?,?,?)", (owner, trip["id"], _json(trip)))
            self._check_portable_size(conn, owner)
            conn.execute("INSERT INTO backup_imports VALUES(?,?,?)", (owner, digest, _now()))
            self._event(conn, owner, "restore_backup", metadata={"wishlist_count": added, "trip_count": len(trips) + len(personal)})
            return {"wishlist_added": added, "trips_added": len(trips) + len(personal), "already_imported": False}

    def submit_correction(self, token: str, location_id: str, kind: str, description: str, source_url: str = "") -> str:
        with self._connection() as conn:
            owner = self._owner(conn, token)
            location_id = _identifier(location_id)
            if kind not in CORRECTION_KINDS:
                raise ValueError("Invalid correction kind")
            description = _text(description, "description", 3000, empty=False)
            source_url = _url(source_url)
            correction_id, now = uuid.uuid4().hex, _now()
            conn.execute("INSERT INTO corrections VALUES(?,?,?,?,?,?,?,?,?,?)", (correction_id, owner, location_id, kind, description, source_url, "pending", "", now, now))
            return correction_id

    def list_corrections(self, token: str) -> list[dict]:
        with self._connection() as conn:
            owner = self._owner(conn, token)
            return [dict(row) for row in conn.execute("SELECT id,location_id,kind,description,source_url,status,review_note,created_at,updated_at FROM corrections WHERE owner=? ORDER BY created_at DESC", (owner,))]

    def record_event(self, token: str, event: str, object_id: str = "", metadata: dict | None = None) -> None:
        with self._connection() as conn:
            owner = self._owner(conn, token)
            if event not in EVENTS:
                raise ValueError("Unsupported event")
            object_id = _identifier(object_id) if object_id else ""
            self._event(conn, owner, event, object_id, metadata)
