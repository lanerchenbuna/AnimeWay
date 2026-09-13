"""Durability, data ownership and safe portable snapshots for the pilot store."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import secrets
import sqlite3

import pytest

from core import private_store
from core.private_store import MAX_BACKUP_BYTES, PrivateStore
from scripts.review_corrections import main as review_main


def location(index=1, **changes):
    return {
        "id": f"tokyo-{index}", "name": f"地点 {index}", "lat": 35.7,
        "lon": 139.7, "city": "東京都新宿区", "anime_ids": ["your-name"],
        "scene_ids": [f"scene-{index}"], "source_url": "https://example.org/place",
        "source_version": "2026-09-08", **changes,
    }


def route(**changes):
    return {
        "id": "tokyo-half-day", "title": "东京半日手册", "version": "1",
        "reviewed_at": "2026-09-08", "connection_status": "unknown",
        "unknowns": ["步行连接尚待核查"],
        "stops": [
            {"location_id": "tokyo-1", "required": True, "reason": "核心场景", "stay_min": 15, "stay_max": 25},
            {"location_id": "tokyo-2", "required": False, "reason": "有时间可顺路", "stay_min": 5, "stay_max": 10},
            {"location_id": "tokyo-3", "required": False},
        ],
        **changes,
    }


@pytest.fixture
def store(tmp_path):
    return PrivateStore(tmp_path / "private.sqlite3")


def adopted(store, token):
    return store.create_trip(token, route(), [location(i) for i in range(1, 4)])


def test_reopen_restores_identity_wishlist_trip_and_correction(tmp_path):
    path = tmp_path / "durable" / "private.sqlite3"
    first = PrivateStore(path)
    token = first.new_identity()
    first.add_wishlist(token, location())
    trip = adopted(first, token)
    correction = first.submit_correction(token, "tokyo-1", "geography", "城市归属有误")

    reopened = PrivateStore(path)
    assert reopened.has_identity(token)
    assert reopened.list_wishlist(token)[0]["id"] == "tokyo-1"
    assert reopened.get_trip(token, trip["id"]) == trip
    assert reopened.list_corrections(token)[0]["id"] == correction
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        owners = [row[0] for row in conn.execute("SELECT owner FROM identities")]
        assert owners == [hashlib.sha256(token.encode()).hexdigest()]
        assert token not in "".join(conn.iterdump())


def test_data_directory_is_configurable_and_durable(monkeypatch, tmp_path):
    monkeypatch.setenv("ANIMEWAY_DATA_DIR", str(tmp_path / "volume"))
    store = PrivateStore()
    assert store.path == tmp_path / "volume" / "private.sqlite3"
    token = store.new_identity()
    assert PrivateStore().has_identity(token)


def test_first_run_initialization_is_safe_for_concurrent_sessions(tmp_path):
    path = tmp_path / "parallel.sqlite3"
    with ThreadPoolExecutor(max_workers=8) as executor:
        tokens = list(executor.map(lambda _: PrivateStore(path).new_identity(), range(16)))
    store = PrivateStore(path)
    assert len(set(tokens)) == 16
    assert all(store.has_identity(token) for token in tokens)


def test_wishlist_is_not_limited_to_backpack_and_duplicates_are_idempotent(store):
    token = store.new_identity()
    for index in range(30):
        assert store.add_wishlist(token, location(index))
    assert not store.add_wishlist(token, location(5, name="do not overwrite a personal snapshot"))
    assert len(store.list_wishlist(token)) == 30
    assert store.list_wishlist(token)[5]["name"] == "地点 5"
    store.remove_wishlist(token, "tokyo-5")
    store.remove_wishlist(token, "tokyo-5")
    assert len(store.list_wishlist(token)) == 29


def test_other_identity_cannot_read_update_start_or_delete_private_data(store):
    owner, attacker = store.new_identity(), store.new_identity()
    store.add_wishlist(owner, location())
    trip = adopted(store, owner)
    store.submit_correction(owner, "tokyo-1", "access", "入口有变化")
    assert store.list_wishlist(attacker) == []
    assert store.list_trips(attacker) == []
    assert store.list_corrections(attacker) == []
    assert store.get_trip(attacker, trip["id"]) is None
    with pytest.raises(ValueError, match="not found"):
        store.update_trip(attacker, trip["id"], 1, title="forged")
    with pytest.raises(ValueError, match="not found"):
        store.start_trip(attacker, trip["id"])
    store.delete_trip(attacker, trip["id"])
    store.remove_wishlist(attacker, "tokyo-1")
    assert store.get_trip(owner, trip["id"]) == trip
    assert len(store.list_wishlist(owner)) == 1
    assert json.loads(store.export_backup(attacker)) == {"schema_version": 2, "wishlist": [], "trips": [], "personal_trips": []}


@pytest.mark.parametrize("token", [None, "", "a" * 42, "a" * 44, "not-an-identity", "a" * 43])
def test_all_private_operations_reject_unknown_identity(store, token):
    assert not store.has_identity(token)
    operations = [
        lambda: store.list_wishlist(token),
        lambda: store.add_wishlist(token, location()),
        lambda: store.remove_wishlist(token, "tokyo-1"),
        lambda: adopted(store, token),
        lambda: store.list_trips(token),
        lambda: store.get_trip(token, "known-trip"),
        lambda: store.update_trip(token, "known-trip", 1, title="test"),
        lambda: store.delete_trip(token, "known-trip"),
        lambda: store.start_trip(token, "known-trip"),
        lambda: store.export_backup(token),
        lambda: store.import_backup(token, '{}'),
        lambda: store.submit_correction(token, "tokyo-1", "other", "test"),
        lambda: store.list_corrections(token),
        lambda: store.record_event(token, "view_location", "tokyo-1"),
    ]
    for operation in operations:
        with pytest.raises(ValueError, match="identity"):
            operation()


def test_trip_snapshot_survives_template_change_and_deleted_template(store):
    token = store.new_identity()
    template = route()
    points = [location(i) for i in range(1, 4)]
    trip = store.create_trip(token, template, points)
    edited = store.update_trip(token, trip["id"], trip["revision"], title="我自己的下午", remove_location_id="tokyo-2")
    template.update(title="changed title", version="2", stops=[])
    points[0]["name"] = "changed place"
    del template
    saved = PrivateStore(store.path).get_trip(token, trip["id"])
    assert saved == edited
    assert saved["title"] == "我自己的下午"
    assert saved["template_version"] == "1"
    assert saved["stops"][0]["name"] == "地点 1"
    assert saved["stops"][0]["scene_ids"] == ["scene-1"]
    assert saved["source_reviewed_at"] == "2026-09-08"


def test_access_and_viewpoint_survive_template_loss_and_portable_restore(store):
    owner, target = store.new_identity(), store.new_identity()
    access = {"status": "restricted", "summary": "仅在公共区域观察，禁止擅自入内。", "source_url": "https://example.org/entry", "checked_at": "2026-09-08", "hours": None, "api_key": "sk-hidden"}
    point = location(access=access, viewpoint="勿占用车道，还原机位待核验。", entry="依照现场指引。")
    template = route()
    template["stops"][0].update(visit_mode="public_exterior", skip_if="影响通行时跳过", stay_status="editorial_suggestion")
    store.add_wishlist(owner, point)
    trip = store.create_trip(owner, template, [point, location(2), location(3)])
    access["summary"] = "this changed upstream"
    saved = store.get_trip(owner, trip["id"])["stops"][0]
    assert saved["access"]["summary"] == "仅在公共区域观察，禁止擅自入内。"
    assert set(saved["access"]) == {"status", "summary", "source_url", "checked_at"}
    assert saved["entry"] == "依照现场指引。"
    assert saved["viewpoint"] == "勿占用车道，还原机位待核验。"
    assert saved["skip_if"] == "影响通行时跳过"
    raw = store.export_backup(owner)
    assert "sk-hidden" not in raw
    store.import_backup(target, raw)
    assert store.list_trips(target)[0]["stops"][0] == saved
    assert store.list_wishlist(target)[0]["access"] == saved["access"]


@pytest.mark.parametrize("target", ["access", "connection_status", "viewpoint"])
def test_restored_snapshot_cannot_smuggle_secrets_or_trusted_travel_state(store, target):
    owner, other = store.new_identity(), store.new_identity()
    adopted(store, owner)
    payload = json.loads(store.export_backup(owner))
    trip = payload["trips"][0]
    if target == "access":
        trip["stops"][0]["access"] = {"status": "unknown", "summary": "test", "admin": {"token": "secret"}}
    elif target == "viewpoint":
        trip["stops"][0]["viewpoint"] = {"api_key": "secret"}
    else:
        trip["connection_status"] = "verified"
    with pytest.raises(ValueError):
        store.import_backup(other, json.dumps(payload))
    assert store.list_trips(other) == []


def test_remove_optional_invalidates_connections_and_cannot_remove_required(store):
    token = store.new_identity()
    trip = store.create_trip(token, route(distance_km=3, duration_minutes=80, connections=[{"duration": 10}]), [location(i) for i in range(1, 4)])
    with pytest.raises(ValueError, match="Required"):
        store.update_trip(token, trip["id"], 1, remove_location_id="tokyo-1")
    edited = store.update_trip(token, trip["id"], 1, remove_location_id="tokyo-2")
    assert len(edited["stops"]) == 2
    assert edited["connection_status"] == "needs_recheck"
    assert "原路线耗时不再适用" in edited["unknowns"][-1]
    assert "duration_minutes" not in edited
    assert "distance_km" not in edited
    assert "connections" not in edited


def test_stale_revision_does_not_overwrite_and_failed_edits_are_atomic(store):
    token = store.new_identity()
    trip = adopted(store, token)
    edited = store.update_trip(token, trip["id"], 1, title="updated")
    with pytest.raises(ValueError, match="another view"):
        store.update_trip(token, trip["id"], 1, title="stale")
    with pytest.raises(ValueError, match="Required"):
        store.update_trip(token, trip["id"], 2, title="must not leak", remove_location_id="tokyo-1")
    assert store.get_trip(token, trip["id"]) == edited


def test_start_is_idempotent_and_distinct_from_completion(store):
    token = store.new_identity()
    trip = adopted(store, token)
    first = store.start_trip(token, trip["id"])
    second = store.start_trip(token, trip["id"])
    assert first == second
    assert first["started_at"]
    assert "completed_at" not in first
    assert first["revision"] == trip["revision"] + 1
    with closing(sqlite3.connect(store.path)) as conn, conn:
        events = [row[0] for row in conn.execute("SELECT event FROM events")]
    assert events == ["adopt_route", "start_trip"]
    with pytest.raises(ValueError, match="Unsupported event"):
        store.record_event(token, "complete_trip", trip["id"])


def test_backup_only_includes_allowed_user_data_and_drops_extra_fields(store):
    token = store.new_identity()
    api_key = "sk-test-secret-should-not-escape"
    store.add_wishlist(token, location(api_key=api_key, nested={"token": token}, image="https://example.org/protected.jpg"))
    store.create_trip(token, route(api_key=api_key, auth={"token": token}), [location(i, auth=token) for i in range(1, 4)])
    store.submit_correction(token, "tokyo-1", "other", "private correction text")
    store.record_event(token, "view_location", "tokyo-1", {"api_key": api_key, "nested": {"token": token}, "source": "location", "count": 2})
    raw = store.export_backup(token)
    payload = json.loads(raw)
    assert set(payload) == {"schema_version", "wishlist", "trips", "personal_trips"}
    assert token not in raw
    assert hashlib.sha256(token.encode()).hexdigest() not in raw
    assert api_key not in raw
    assert "private correction text" not in raw
    assert "protected.jpg" not in raw
    with closing(sqlite3.connect(store.path)) as conn, conn:
        event = json.loads(conn.execute("SELECT metadata FROM events WHERE event='view_location'").fetchone()[0])
    assert event == {"source": "location", "count": 2}


def test_restore_reids_trips_and_repeat_import_preserves_personal_edits(store):
    first, second = store.new_identity(), store.new_identity()
    store.add_wishlist(first, location())
    original = adopted(store, first)
    started = store.start_trip(first, original["id"])
    raw = store.export_backup(first)
    result = store.import_backup(second, raw)
    assert result == {"wishlist_added": 1, "trips_added": 1, "already_imported": False}
    restored = store.list_trips(second)[0]
    assert restored["id"] != original["id"]
    assert restored["started_at"] == started["started_at"]
    assert restored["stops"] == started["stops"]
    assert store.get_trip(second, original["id"]) is None
    edited = store.update_trip(second, restored["id"], restored["revision"], title="恢复后修改")
    result = store.import_backup(second, json.dumps(json.loads(raw), indent=2))
    assert result == {"wishlist_added": 0, "trips_added": 0, "already_imported": True}
    assert store.list_trips(second) == [edited]
    assert len(store.list_wishlist(second)) == 1
    assert store.get_trip(first, original["id"]) == started


@pytest.mark.parametrize("bad_coordinate", [float("nan"), float("inf"), -91, 91, True, "35.0", None])
def test_invalid_coordinates_cannot_enter_store_or_backup(store, bad_coordinate):
    token = store.new_identity()
    with pytest.raises(ValueError, match="lat"):
        store.add_wishlist(token, location(lat=bad_coordinate))
    payload = {"schema_version": 1, "wishlist": [location(), location(2, lat=bad_coordinate)], "trips": []}
    with pytest.raises(ValueError, match="lat"):
        store.import_backup(token, json.dumps(payload))
    assert store.list_wishlist(token) == []


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(token="secret"),
    lambda p: p.update(schema_version=999),
    lambda p: p.update(schema_version=True),
    lambda p: p["wishlist"][0].update(api_key="secret"),
    lambda p: p["wishlist"][0].update(anime_ids=[{"nested": "secret"}]),
    lambda p: p["wishlist"][0].update(source_version={"api_key": "secret"}),
    lambda p: p["trips"][0].update(admin={"token": "secret"}),
    lambda p: p["trips"][0]["stops"][0].update(secret="secret"),
    lambda p: p["trips"][0].update(unknowns=[{"api_key": "secret"}]),
    lambda p: p["trips"][0].update(stops=[]),
    lambda p: p["trips"][0].update(created_at="invalid date"),
    lambda p: p["trips"][0]["stops"][0].update(lon=181),
    lambda p: p["trips"][0]["stops"][0].update(required="false"),
    lambda p: p["trips"][0]["stops"][0].update(stay_min=20, stay_max=10),
    lambda p: p["trips"].append(deepcopy(p["trips"][0])),
])
def test_malformed_backup_is_rejected_transactionally(store, mutation):
    owner, target = store.new_identity(), store.new_identity()
    store.add_wishlist(owner, location())
    adopted(store, owner)
    store.add_wishlist(target, location(99))
    original = store.export_backup(target)
    payload = json.loads(store.export_backup(owner))
    mutation(payload)
    with pytest.raises(ValueError):
        store.import_backup(target, json.dumps(payload))
    assert store.export_backup(target) == original


@pytest.mark.parametrize("raw", ["", "{", "[]", "null", "\"text\"", "{}"])
def test_invalid_json_backup_never_writes_records(store, raw):
    token = store.new_identity()
    with pytest.raises(ValueError):
        store.import_backup(token, raw)
    assert store.list_trips(token) == []
    assert store.list_wishlist(token) == []


def test_backup_size_and_item_limits(store):
    token = store.new_identity()
    with pytest.raises(ValueError, match="5 MiB"):
        store.import_backup(token, " " * (MAX_BACKUP_BYTES + 1))
    with pytest.raises(ValueError, match="item limit"):
        store.import_backup(token, json.dumps({"schema_version": 1, "wishlist": [{}] * 5001, "trips": []}))
    assert store.list_wishlist(token) == []


def test_storage_capacity_keeps_the_entire_collection_portable(store, monkeypatch):
    token = store.new_identity()
    store.add_wishlist(token, location())
    before = store.export_backup(token)
    monkeypatch.setattr(private_store, "MAX_BACKUP_BYTES", len(before.encode("utf-8")) + 50)
    with pytest.raises(ValueError, match="portable backup limit"):
        store.add_wishlist(token, location(2))
    assert store.export_backup(token) == before
    target = store.new_identity()
    assert store.import_backup(target, before)["wishlist_added"] == 1


def test_merge_over_capacity_rolls_back_all_added_records(store, monkeypatch):
    owner, target = store.new_identity(), store.new_identity()
    store.add_wishlist(owner, location())
    store.add_wishlist(target, location(99))
    incoming, before = store.export_backup(owner), store.export_backup(target)
    monkeypatch.setattr(private_store, "MAX_BACKUP_BYTES", max(len(incoming.encode()), len(before.encode())) + 50)
    with pytest.raises(ValueError, match="portable backup limit"):
        store.import_backup(target, incoming)
    assert store.export_backup(target) == before


def test_corrupt_and_unknown_database_versions_are_never_recreated(tmp_path):
    corrupted = tmp_path / "corrupt.sqlite3"
    content = b"this is not a sqlite database"
    corrupted.write_bytes(content)
    with pytest.raises(sqlite3.DatabaseError):
        PrivateStore(corrupted)
    assert corrupted.read_bytes() == content
    future = tmp_path / "future.sqlite3"
    with closing(sqlite3.connect(future)) as conn, conn:
        conn.execute("CREATE TABLE retained(value TEXT)")
        conn.execute("INSERT INTO retained VALUES('keep me')")
        conn.execute("PRAGMA user_version=999")
    with pytest.raises(ValueError, match="Unsupported"):
        PrivateStore(future)
    with closing(sqlite3.connect(future)) as conn, conn:
        assert conn.execute("SELECT value FROM retained").fetchone()[0] == "keep me"


def test_unversioned_existing_data_requires_explicit_migration(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE existing(id TEXT)")
        conn.execute("INSERT INTO existing VALUES('saved')")
    with pytest.raises(ValueError, match="migration"):
        PrivateStore(path)
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute("SELECT id FROM existing").fetchone()[0] == "saved"


def test_correction_owner_can_see_review_status_but_no_other_identity(store, capsys):
    owner, other = store.new_identity(), store.new_identity()
    correction_id = store.submit_correction(owner, "tokyo-1", "geography", "不是高山市", "https://example.org/evidence")
    assert store.list_corrections(other) == []
    row = store.list_corrections(owner)[0]
    assert row["status"] == "pending"
    assert "owner" not in row
    assert review_main(["--db", str(store.path), "list", "--status", "pending"]) == 0
    output = capsys.readouterr().out
    assert correction_id in output
    assert owner not in output and hashlib.sha256(owner.encode()).hexdigest() not in output
    for status in ["needs_info", "accepted", "rejected", "pending"]:
        assert review_main(["--db", str(store.path), "set", correction_id, "--status", status, "--note", f"review: {status}"]) == 0
        assert store.list_corrections(owner)[0]["status"] == status
        assert store.list_corrections(owner)[0]["review_note"] == f"review: {status}"
    assert store.list_corrections(other) == []
    assert review_main(["--db", str(store.path), "set", secrets.token_hex(16), "--status", "accepted", "--note", "no such object"]) == 1


def test_correction_source_does_not_allow_credentials_or_executable_urls(store):
    token = store.new_identity()
    for url in ["javascript:alert(1)", "https://user:password@example.org", "file:///etc/passwd"]:
        with pytest.raises(ValueError, match="source_url"):
            store.submit_correction(token, "tokyo-1", "source", "test", url)
    with pytest.raises(ValueError, match="kind"):
        store.submit_correction(token, "tokyo-1", "admin", "test")
    with pytest.raises(ValueError, match="description"):
        store.submit_correction(token, "tokyo-1", "other", " ")
    assert store.list_corrections(token) == []


def test_cli_stats_reports_events_not_claimed_completions(store, capsys):
    token = store.new_identity()
    store.add_wishlist(token, location())
    adopted(store, token)
    assert review_main(["--db", str(store.path), "stats"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert {row["event"] for row in output["events"]} == {"adopt_route", "save_wishlist"}
    assert "不是人数" in output["note"]


def test_cli_missing_database_does_not_create_empty_file(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(SystemExit):
        review_main(["--db", str(path), "list"])
    assert not path.exists()
