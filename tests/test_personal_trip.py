"""Constraint, persistence, migration and AI boundary acceptance tasks."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import json
import sqlite3

import pytest
import requests

from core.pilot import load_pilot
from core.trip import TOKYO, empty_plan, evaluate, new_requirements, propose, resolve_date, stop_spec, validate_archive, validate_plan
from core.trip_ai import local_requirements, preview_operations, request_edit
from core.trip_store import TripStore
from core.trip_transport import connection


@pytest.fixture
def prepared(tmp_path):
    catalog = load_pilot()
    store = TripStore(tmp_path / "private.db")
    owner, other = store.new_identity(), store.new_identity()
    plan = empty_plan(new_requirements("2026-10-10", 2, anime_ids=["328609", "160209"]))
    groups = [["loc-tokyo-shimokitazawa-station", "loc-tokyo-village-vanguard", "loc-tokyo-shelter"],
              ["loc-tokyo-yotsuya-akasaka", "loc-tokyo-suga-stairs"]]
    for day, ids in zip(plan["days"], groups):
        day["stops"] = [stop_spec(item) for item in ids]
        day["start"] = {"name": "已选出发点", "location_id": ids[0], "lat": None, "lon": None, "confirmed": True}
        day["end"] = {**day["start"], "location_id": ids[-1]}
    trip = store.create_personal_trip(owner, plan)
    return store, owner, other, catalog, trip


def test_relative_date_uses_tokyo_and_arrival_day_is_included():
    utc = datetime(2026, 9, 10, 16, tzinfo=timezone.utc)
    assert resolve_date("后天", now=utc) == "2026-09-13"
    parsed = local_requirements("后天下午到东京，住新宿，两天，孤独摇滚和你的名字，不想太赶", load_pilot(), now=utc)
    assert parsed["requirements"]["start_date"] == "2026-09-13"
    assert parsed["requirements"]["day_count"] == 2
    assert parsed["requirements"]["pace"] == "relaxed"
    assert parsed["arrival"] and parsed["lodging_name"] == "新宿"
    assert len(parsed["requirements"]["anime_ids"]) == 2
    with pytest.raises(ValueError):
        resolve_date("后天", now=datetime(2026, 9, 10))


def test_candidates_keep_must_dedupe_and_never_fill_unrelated():
    catalog = load_pilot()
    plan = empty_plan(new_requirements("2026-10-10", 2, anime_ids=["160209"]))
    plan["requirements"]["must_ids"] = ["loc-tokyo-suga-stairs"]
    plan["requirements"]["excluded_ids"] = ["loc-tokyo-yunika"]
    choices = propose(plan, catalog)
    assert 1 <= len(choices) <= 2
    places = {p["id"]: p for p in catalog["locations"]}
    for choice in choices:
        stops = [s for d in choice["plan"]["days"] for s in d["stops"]]
        ids = [s["location_id"] for s in stops]
        assert len(ids) == len(set(ids))
        assert "loc-tokyo-suga-stairs" in ids and "loc-tokyo-yunika" not in ids
        assert all("160209" in places[item]["anime_ids"] for item in ids)
        assert next(s for s in stops if s["location_id"] == "loc-tokyo-suga-stairs")["locked"]
    plan["requirements"]["anime_ids"] = ["not-in-catalog"]
    assert all(not d["stops"] for d in propose(plan, catalog)[0]["plan"]["days"])


def test_unknown_anchors_transit_and_cost_never_become_zero_or_driving(prepared):
    _, _, _, catalog, trip = prepared
    plan = deepcopy(trip["plan"])
    plan["days"][0]["start"]["confirmed"] = False
    plan["requirements"]["mode"] = "transit"
    result = evaluate(plan, catalog)
    day = result["days"][0]
    assert day["finish_min"] is None and day["totals"]["fare_jpy"] is None
    assert day["totals"]["moving_min"] is None and day["totals"]["waiting_min"] is None
    assert all(row["leg"]["mode"] == "transit" for row in day["rows"])
    assert {i["code"] for i in result["issues"]} >= {"anchor_unknown", "transport_unknown"}


def test_time_budget_includes_every_part_and_end_anchor(prepared):
    _, _, _, catalog, trip = prepared
    result = evaluate(trip["plan"], catalog)
    day, check = trip["plan"]["days"][0], result["days"][0]
    totals = check["totals"]
    expected = sum(totals[k] for k in ("moving_min", "waiting_min", "stay_min", "meal_min", "break_min", "buffer_min"))
    assert check["finish_min"] == day["start_min"] + expected
    assert totals["meal_min"] == 60 and totals["break_min"] == 30 and totals["buffer_min"] == 30
    assert check["return_leg"]["status"] == "same_location"
    changed = deepcopy(trip["plan"])
    changed["days"][0]["end"] = changed["days"][0]["start"]
    assert evaluate(changed, catalog)["days"][0]["finish_min"] > check["finish_min"]


def test_impossible_must_and_closed_weekday_have_locatable_conflicts(prepared):
    _, _, _, catalog, trip = prepared
    plan = deepcopy(trip["plan"])
    day = plan["days"][0]
    day["end_min"] = day["start_min"] + 20
    plan["requirements"]["must_ids"] = ["missing-must"]
    place = next(p for p in catalog["locations"] if p["id"] == day["stops"][0]["location_id"])
    day["stops"][0]["visit_mode"] = "entry"
    place["access"]["opening_hours"] = {"status": "verified", "source_url": "https://official.example.test/access",
                                      "checked_at": datetime.now(TOKYO).date().isoformat(), "closed_weekdays": [5]}
    result = evaluate(plan, catalog)
    assert result["status"] == "conflict"
    assert {i["code"] for i in result["issues"]} >= {"fixed_time_conflict", "missing_required", "closed_weekday"}
    assert next(i for i in result["issues"] if i["code"] == "closed_weekday")["location_id"] == place["id"]
    day["stops"][0]["visit_mode"] = "exterior"
    assert "closed_weekday" not in {i["code"] for i in evaluate(plan, catalog)["issues"]}


def test_estimate_cannot_confirm_appointment_or_promote_reference(prepared):
    _, _, _, catalog, trip = prepared
    plan = deepcopy(trip["plan"])
    plan["days"][1]["stops"][1]["appointment_min"] = 545
    result = evaluate(plan, catalog)
    assert "appointment_unverified" in {i["code"] for i in result["issues"]}
    leg = result["days"][1]["rows"][1]["leg"]
    assert leg["status"] == "estimated" and leg["exact"] is False
    assert "官方" in leg["reference"] and leg["source_url"]


def test_locked_position_cannot_be_silently_displaced(prepared):
    store, owner, _, catalog, trip = prepared
    day = trip["plan"]["days"][0]
    middle = day["stops"][1]["location_id"]
    locked = store.edit_personal_trip(owner, trip["id"], 1, {"kind": "lock", "date": day["date"], "location_id": middle, "value": True}, catalog)
    for op in ({"kind": "stay", "location_id": middle, "value": 5},
               {"kind": "remove", "location_id": day["stops"][0]["location_id"]},
               {"kind": "move", "location_id": day["stops"][2]["location_id"], "position": 0}):
        with pytest.raises(ValueError, match="锁定"):
            store.edit_personal_trip(owner, trip["id"], locked["revision"], {"date": day["date"], **op}, catalog)
    assert store.get_personal_trip(owner, trip["id"]) == locked


def test_one_day_edit_reuses_other_checks_and_undo_is_new_revision(prepared):
    store, owner, _, catalog, trip = prepared
    previous = evaluate(trip["plan"], catalog)
    day = trip["plan"]["days"][1]
    edited = store.edit_personal_trip(owner, trip["id"], 1, {"kind": "end_time", "date": day["date"], "value": day["end_min"] - 60}, catalog)
    check = evaluate(edited["plan"], catalog, previous=previous)
    assert check["days"][0] is previous["days"][0]
    assert check["days"][1] is not previous["days"][1]
    undo = store.restore_personal_version(owner, trip["id"], 2, 1)
    assert undo["revision"] == 3 and undo["plan"] == trip["plan"]
    with pytest.raises(ValueError, match="另一页面"):
        store.edit_personal_trip(owner, trip["id"], 1, {"kind": "end_time", "date": day["date"], "value": 1100}, catalog)


def test_today_events_and_undo_preserve_execution_prefix(prepared):
    store, owner, _, catalog, trip = prepared
    active = store.begin_personal_trip(owner, trip["id"], 1, catalog)
    day = active["plan"]["days"][0]
    for kind, at in (("visit", 600), ("skip", 605), ("delay", 640)):
        active = store.record_personal_event(owner, trip["id"], active["revision"], day["date"], kind, at, catalog)
    with pytest.raises(ValueError, match="已执行"):
        store.edit_personal_trip(owner, trip["id"], active["revision"], {"kind": "stay", "date": day["date"], "location_id": day["stops"][0]["location_id"], "value": 3}, catalog)
    edited = store.edit_personal_trip(owner, trip["id"], active["revision"], {"kind": "stay", "date": day["date"], "location_id": day["stops"][2]["location_id"], "value": 10}, catalog)
    restored = store.restore_personal_version(owner, trip["id"], edited["revision"], active["revision"])
    assert restored["events"] == active["events"]
    rows = evaluate(restored["plan"], catalog, restored["events"])["days"][0]["rows"]
    assert [r["outcome"] for r in rows] == ["visit", "skip", "pending"]
    assert rows[-1]["arrival_min"] >= 640
    ended = store.record_personal_event(owner, trip["id"], restored["revision"], day["date"], "end_trip", 650, catalog)
    future = evaluate(ended["plan"], catalog, ended["events"])["days"][1]
    assert all(r["outcome"] == "not_visited" for r in future["rows"])
    assert ended["state"] == "ended"


def test_personal_backup_restore_and_owner_isolation(prepared):
    store, owner, other, _, trip = prepared
    assert not store.get_personal_trip(other, trip["id"])
    with pytest.raises(ValueError):
        store.delete_personal_trip(other, trip["id"], 1)
    raw = store.export_backup(owner)
    assert json.loads(raw)["schema_version"] == 2
    assert owner not in raw and "service_usage" not in raw
    store.import_backup(other, raw)
    restored = store.list_personal_trips(other)[0]
    assert restored["id"] != trip["id"] and restored["plan"] == trip["plan"]
    assert store.import_backup(other, raw)["already_imported"]
    assert TripStore(store.path).get_personal_trip(owner, trip["id"]) == trip


def test_v1_database_migrates_without_losing_identity_or_saved_data(tmp_path):
    path = tmp_path / "v1.db"
    store = TripStore(path)
    token = store.new_identity()
    store.add_wishlist(token, load_pilot()["locations"][0])
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("DROP TABLE personal_trips")
        conn.execute("DROP TABLE service_usage")
        conn.execute("PRAGMA user_version=1")
    migrated = TripStore(path)
    assert migrated.has_identity(token) and len(migrated.list_wishlist(token)) == 1
    old = {"schema_version": 1, "wishlist": [], "trips": []}
    assert not migrated.import_backup(token, json.dumps(old))["already_imported"]
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


@pytest.mark.parametrize("mutate", [
    lambda item: item.update(api_key="hidden"),
    lambda item: item["plan"]["days"][0]["stops"][0].update(lat=35),
    lambda item: item["plan"]["requirements"].update(day_count=100000),
    lambda item: item["plan"]["requirements"].pop("start_date"),
    lambda item: item["plan"]["days"][0]["start"].update(source_key="hidden"),
    lambda item: item["history"].append({"revision": 1, "plan": {}, "secret": "hidden"}),
])
def test_import_rejects_invalid_nested_fields_atomically(prepared, mutate):
    store, owner, other, _, _ = prepared
    payload = json.loads(store.export_backup(owner))
    mutate(payload["personal_trips"][0])
    before = store.export_backup(other)
    with pytest.raises(ValueError):
        store.import_backup(other, json.dumps(payload))
    assert store.export_backup(other) == before


def test_ai_preview_rejects_fact_injection_unknown_id_and_lock_edit(prepared):
    _, _, _, catalog, trip = prepared
    day = trip["plan"]["days"][0]
    for operation in [{"kind": "add", "date": day["date"], "replacement_id": "fake"},
                      {"kind": "stay", "date": day["date"], "location_id": day["stops"][0]["location_id"], "value": 10, "fare": 0},
                      {"kind": "lock", "date": day["date"], "location_id": day["stops"][0]["location_id"], "value": False}]:
        with pytest.raises(ValueError):
            preview_operations(trip, {"operations": [operation]}, catalog)
    preview = preview_operations(trip, {"operations": [{"kind": "stay", "date": day["date"], "location_id": day["stops"][0]["location_id"], "value": 10}]}, catalog)
    assert preview["base_revision"] == 1
    assert preview["plan"]["days"][0]["stops"][0]["stay_min"] == 10
    assert trip["plan"]["days"][0]["stops"][0]["stay_min"] == 25


def test_budget_atomicity_and_timeout_preserve_original(prepared, monkeypatch):
    store, owner, _, catalog, trip = prepared
    policy = {"daily_limit": 3, "owner_limit": 2, "budget_units": 200000, "reserve_units": 100000}
    def reserve(_):
        try:
            return store.reserve_ai_call(owner, trip["id"], **policy)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=5) as executor:
        calls = list(executor.map(reserve, range(5)))
    assert sum(bool(c) for c in calls) == 2
    assert store.ai_usage(owner)["reserved_cny"] == 0.2
    for name, value in {"ANIMEWAY_TRIP_AI_DAILY_CALLS": "5", "ANIMEWAY_TRIP_AI_BROWSER_CALLS": "5", "ANIMEWAY_TRIP_AI_DAILY_MICROCNY": "500000", "ANIMEWAY_TRIP_AI_CALL_MICROCNY": "100000"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("core.trip_ai.requests.post", lambda *a, **k: (_ for _ in ()).throw(requests.Timeout()))
    with pytest.raises(ValueError, match="原行程未改变"):
        request_edit(store, owner, trip, "缩短第二天", catalog, "synthetic-key")
    assert store.get_personal_trip(owner, trip["id"]) == trip
    assert store.ai_usage(owner)["calls"] == 3


def test_no_duplicate_stops_and_archive_round_trip(prepared):
    _, _, _, catalog, trip = prepared
    raw = deepcopy(trip["plan"])
    raw["days"][1]["stops"].append(deepcopy(raw["days"][0]["stops"][0]))
    with pytest.raises(ValueError, match="只安排一次"):
        validate_plan(raw)
    assert validate_archive(trip) == trip
    assert connection(None, None, "transit", catalog)["move_min"] is None



def test_time_limited_proposal_trims_optional_but_keeps_required():
    catalog = load_pilot()
    plan = empty_plan(new_requirements("2026-10-10", 1, anime_ids=["160209"]))
    plan["requirements"]["must_ids"] = ["loc-tokyo-suga-stairs"]
    day = plan["days"][0]
    day["end_min"] = day["start_min"] + 150  # 120 reserved + 25 stay, not two stays.
    for option in propose(plan, catalog):
        assert [s["location_id"] for s in option["plan"]["days"][0]["stops"]] == ["loc-tokyo-suga-stairs"]
        assert "删减" in option["reason"]
    day["end_min"] = day["start_min"] + 10
    option = propose(plan, catalog)[0]
    assert option["plan"]["days"][0]["stops"][0]["priority"] == "required"
    assert evaluate(option["plan"], catalog)["status"] == "conflict"


def test_no_unrelated_work_fallback_or_silent_remaining_stops(prepared):
    _, _, _, catalog, trip = prepared
    with pytest.raises(ValueError, match="没有识别到"):
        local_requirements("明天去巡礼 EVA，两天", catalog)
    plan = deepcopy(trip["plan"])
    plan["requirements"]["anime_ids"] = ["160209"]
    assert "unrelated_selected" in {i["code"] for i in evaluate(plan, catalog)["issues"]}


def test_early_end_invalidates_all_days_in_cached_evaluation(prepared):
    store, owner, _, catalog, trip = prepared
    active = store.begin_personal_trip(owner, trip["id"], 1, catalog)
    previous = evaluate(active["plan"], catalog, active["events"])
    ended = store.record_personal_event(owner, trip["id"], active["revision"], "2026-10-10", "end_trip", 600, catalog)
    checked = evaluate(ended["plan"], catalog, ended["events"], previous)
    assert all(d["ended"] and d["next_id"] is None for d in checked["days"])
    assert all(row["outcome"] == "not_visited" for d in checked["days"] for row in d["rows"])


def test_ai_json_response_stays_a_preview_and_does_not_send_private_anchors(prepared, monkeypatch):
    from core import trip_ai
    store, owner, _, catalog, trip = prepared
    monkeypatch.setattr(trip_ai, "service_policy", lambda: {"daily_limit": 2, "owner_limit": 2, "budget_units": 200000, "reserve_units": 100000})
    def respond(url, **kwargs):
        payload = kwargs["json"]
        assert url == trip_ai.ENDPOINT and kwargs["timeout"] == (5, 20)
        assert payload["max_tokens"] == 1200
        context = json.loads(payload["messages"][1]["content"])["context"]
        assert "start" not in context["days"][0] and "history" not in context
        assert "confirmed" not in json.dumps(context) and owner not in json.dumps(payload)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"choices": [{"message": {"content": json.dumps({"operations": [{"kind": "end_time", "date": "2026-10-11", "value": 1020}]})}}]}).encode()
        return response
    monkeypatch.setattr(trip_ai.requests, "post", respond)
    preview = trip_ai.request_edit(store, owner, trip, "第二天提前一小时结束", catalog, "synthetic-test-key")
    assert preview["plan"]["days"][1]["end_min"] == 1020
    assert store.get_personal_trip(owner, trip["id"]) == trip
    changed = store.apply_ai_operations(owner, trip["id"], preview["base_revision"], preview["operations"], catalog)
    assert changed["plan"] == preview["plan"] and len(changed["history"]) == 1
    assert store.ai_usage(owner)["calls"] == 1
    with pytest.raises(ValueError, match="未配置"):
        trip_ai.request_edit(store, owner, changed, "缩短", catalog, "")
    assert store.ai_usage(owner)["calls"] == 1


def test_transport_boundary_dataset_does_not_claim_provider_coverage():
    from scripts.evaluate_trip_transport import run_samples
    result = run_samples()
    assert result["policy_cases"] == result["policy_passed"] == 30
    assert result["live_provider_queries"] == 0 and result["provider_coverage_verified"] is False


def test_adding_missing_required_point_marks_and_locks_it(prepared):
    store, owner, _, catalog, trip = prepared
    plan = deepcopy(trip["plan"])
    required_id = "loc-tokyo-yunika"
    plan["requirements"]["must_ids"] = [required_id]
    saved = store.create_personal_trip(owner, plan)
    changed = store.edit_personal_trip(owner, saved["id"], 1,
        {"kind": "add", "date": plan["days"][1]["date"], "replacement_id": required_id}, catalog)
    added = changed["plan"]["days"][1]["stops"][-1]
    assert added["priority"] == "required" and added["locked"]


def test_archive_rejects_events_after_end_or_inconsistent_end_state(prepared):
    store, owner, other, catalog, trip = prepared
    active = store.begin_personal_trip(owner, trip["id"], 1, catalog)
    ended = store.record_personal_event(owner, trip["id"], active["revision"], "2026-10-10", "end_trip", 600, catalog)
    payload = json.loads(store.export_backup(owner))
    payload["personal_trips"][0]["events"].append({**ended["events"][0], "kind": "delay", "at_min": 610})
    before = store.export_backup(other)
    with pytest.raises(ValueError, match="结束后"):
        store.import_backup(other, json.dumps(payload))
    assert store.export_backup(other) == before
    ended["state"] = "on_trip"
    with pytest.raises(ValueError, match="不一致"):
        validate_archive(ended)


def test_ai_requirements_preserve_users_explicit_relative_date(prepared, monkeypatch):
    from core import trip_ai
    store, owner, _, catalog, _ = prepared
    monkeypatch.setattr(trip_ai, "_request", lambda *args: {"date_text": "2026-01-01", "day_count": 2,
        "anime_ids": ["328609"], "pace": "relaxed", "mode": "transit", "arrival": True, "lodging_name": "新宿"})
    parsed = trip_ai.request_requirements(store, owner, "后天下午到东京，孤独摇滚两天", catalog, "synthetic-key")
    assert parsed["requirements"]["start_date"] == resolve_date("后天")
    assert parsed["lodging_name"] == "新宿" and parsed["arrival"]
    assert "lat" not in parsed["requirements"]
