from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from io import BytesIO
import json

from PIL import Image
import pytest

from core import contributions as c
from core.journal import clean_photo, recommendations, today
from core.journal_store import JournalStore
from core.pilot import load_pilot
from core.trip import empty_plan, new_requirements, stop_spec


def sample_image(color="red"):
    output = BytesIO()
    exif = Image.Exif()
    exif[270] = "PRIVATE EXIF HOTEL"
    Image.new("RGB", (120, 80), color).save(output, format="JPEG", exif=exif)
    return output.getvalue()


@pytest.fixture
def setup(tmp_path):
    store = JournalStore(tmp_path / "private.db")
    token, other = store.new_identity(), store.new_identity()
    catalog = load_pilot()
    plan = empty_plan(new_requirements((today() - timedelta(days=2)).isoformat(), 1, anime_ids=["328609"], title="SECRET PRIVATE HOTEL"))
    plan["days"][0]["start"]["name"] = "SECRET HOTEL ADDRESS"
    plan["days"][0]["stops"] = [stop_spec("loc-tokyo-shelter"), stop_spec("loc-tokyo-village-vanguard")]
    trip = store.create_personal_trip(token, plan)
    return store, token, other, catalog, trip


def make_entry(setup):
    store, token, _, catalog, trip = setup
    return store.save_entry(token, location_id="loc-tokyo-shelter", visited_on=trip["plan"]["requirements"]["start_date"],
                            confirmed=True, note="PRIVATE NOTE", stay_min=18, trip_id=trip["id"], catalog=catalog)


def make_photo(setup, entry, scope="private"):
    store, token, _, catalog, _ = setup
    return store.save_photo(token, entry["id"], sample_image(), taken_on=entry["date"], rights="own",
                            scope=scope, caption="PRIVATE CAPTION", scene_id="scene-328609-001", catalog=catalog)


def test_no_automatic_visits_skip_never_becomes_footprint_and_delete_not_resurrected(setup):
    store, token, _, catalog, trip = setup
    assert store.entries(token) == []
    active = store.begin_personal_trip(token, trip["id"], 1, catalog)
    active = store.record_personal_event(token, trip["id"], active["revision"], trip["plan"]["days"][0]["date"], "visit", 600, catalog)
    store.record_personal_event(token, trip["id"], active["revision"], trip["plan"]["days"][0]["date"], "skip", 620, catalog)
    assert store.entries(token) == []
    assert store.import_visits(token, trip["id"], catalog) == 1
    assert store.import_visits(token, trip["id"], catalog) == 0
    entry = store.entries(token)[0]
    assert entry["location_id"] == "loc-tokyo-shelter" and entry["stay_min"] is None
    store.delete_entry(token, entry["id"], 1)
    assert store.import_visits(token, trip["id"], catalog) == 0


def test_private_record_reversible_revision_and_identity_isolation(setup):
    store, token, other, catalog, trip = setup
    entry = make_entry(setup)
    changed = store.save_entry(token, location_id=entry["location_id"], visited_on=entry["date"], confirmed=False,
                              entry_id=entry["id"], revision=1, catalog=catalog)
    assert not changed["confirmed"] and store.entries(other) == []
    with pytest.raises(ValueError):
        store.save_entry(other, location_id=entry["location_id"], visited_on=entry["date"], confirmed=True, trip_id=trip["id"], catalog=catalog)
    with pytest.raises(ValueError):
        store.delete_entry(token, entry["id"], 1)
    with pytest.raises(ValueError):
        store.delete_entry(other, entry["id"], 2)
    with pytest.raises(ValueError, match="未来"):
        store.save_entry(token, location_id=entry["location_id"], visited_on=(today()+timedelta(days=1)).isoformat(), confirmed=True, catalog=catalog)
    assert JournalStore(store.path).entries(token)[0] == changed


def test_photo_reencoded_without_metadata_or_public_media_url_and_replacement_revokes(setup):
    store, token, other, catalog, trip = setup
    entry = make_entry(setup)
    photo = make_photo(setup, entry, "share_allowed")
    assert store.photos(other) == []
    data = store.photos(token)[0]["image"]
    with Image.open(BytesIO(data)) as img:
        assert len(img.getexif()) == 0 and img.format == "JPEG"
    assert b"PRIVATE EXIF HOTEL" not in data
    preview = store.preview_share(token, trip["id"], catalog, photo_ids=[photo["id"]])
    sid = store.publish_share(token, trip["id"], 1, preview, catalog)
    assert store.public_share(sid)["photos"]
    store.save_photo(token, entry["id"], sample_image("blue"), taken_on=entry["date"], rights="own", scope="share_allowed",
                     replace_id=photo["id"], scene_id="scene-328609-001", catalog=catalog)
    assert store.public_share(sid) is None
    with pytest.raises(ValueError, match="预览"):
        store.publish_share(token, trip["id"], 1, preview, catalog)


@pytest.mark.parametrize("payload", [b"<svg onload='alert(1)'/>", b"not-an-image", b""])
def test_invalid_photos_rejected(payload):
    with pytest.raises(ValueError):
        clean_photo(payload)


def test_private_scope_wrong_scene_and_foreign_photos_cannot_publish(setup):
    store, token, other, catalog, trip = setup
    entry = make_entry(setup)
    photo = make_photo(setup, entry)
    with pytest.raises(ValueError):
        store.preview_share(token, trip["id"], catalog, photo_ids=[photo["id"]])
    with pytest.raises(ValueError):
        store.save_photo(token, entry["id"], sample_image(), taken_on=entry["date"], rights="private_only", scope="share_allowed", catalog=catalog)
    with pytest.raises(ValueError):
        store.save_photo(token, entry["id"], sample_image(), taken_on=entry["date"], rights="own", scope="private", scene_id="scene-160209-001", catalog=catalog)
    with pytest.raises(ValueError):
        store.delete_photo(other, photo["id"])


def test_share_projection_does_not_leak_private_fields_copy_and_revoke(setup):
    store, token, other, catalog, trip = setup
    make_entry(setup)
    preview = store.preview_share(token, trip["id"], catalog)
    assert set(preview) == {"title", "text", "days", "destination_id", "photo_ids", "photo_checks", "warning"}
    assert "SECRET" not in json.dumps(preview) and trip["plan"]["requirements"]["start_date"] not in json.dumps(preview)
    sid = store.publish_share(token, trip["id"], 1, preview, catalog)
    public = store.public_share(sid)
    assert token not in json.dumps(public) and "PRIVATE" not in json.dumps(public)
    copied = store.copy_share(other, sid, today().isoformat(), catalog)
    assert copied["id"] != trip["id"] and copied["plan"]["requirements"]["start_date"] == today().isoformat()
    assert copied["events"] == [] and copied["history"] == [] and not copied["plan"]["days"][0]["start"]["confirmed"]
    assert "SECRET" not in json.dumps(copied)
    with pytest.raises(ValueError):
        store.revoke_share(other, sid)
    store.revoke_share(token, sid)
    assert store.public_share(sid) is None
    with pytest.raises(ValueError):
        store.copy_share(other, sid, today().isoformat(), catalog)
    assert store.get_personal_trip(other, copied["id"]) == copied


def test_record_or_photo_deletion_revokes_related_public_copy(setup):
    store, token, _, catalog, trip = setup
    entry = make_entry(setup)
    photo = make_photo(setup, entry, "share_allowed")
    sid = store.publish_share(token, trip["id"], 1, store.preview_share(token, trip["id"], catalog, photo_ids=[photo["id"]]), catalog)
    store.delete_entry(token, entry["id"], 1)
    assert not store.photos(token) and not store.public_share(sid)


def test_share_rechecks_trip_revision_and_live_access(setup):
    store, token, other, catalog, trip = setup
    preview = store.preview_share(token, trip["id"], catalog)
    changed = store.edit_personal_trip(token, trip["id"], 1, {"kind": "end_time", "date": trip["plan"]["days"][0]["date"], "value": 1020}, catalog)
    with pytest.raises(ValueError):
        store.publish_share(token, trip["id"], 1, preview, catalog)
    sid = store.publish_share(token, trip["id"], changed["revision"], store.preview_share(token, trip["id"], catalog), catalog)
    bad = deepcopy(catalog)
    next(p for p in bad["locations"] if p["id"] == "loc-tokyo-shelter")["withdrawn"] = True
    with pytest.raises(ValueError):
        store.copy_share(other, sid, today().isoformat(), bad)
    store.delete_personal_trip(token, trip["id"], changed["revision"])
    assert store.public_share(sid) is None


def test_journal_backup_roundtrip_no_credentials_no_public_restore_and_atomic_invalid(setup):
    store, token, other, catalog, _ = setup
    entry = make_entry(setup)
    make_photo(setup, entry, "share_allowed")
    prefs = store.preferences(token)
    prefs["follows"] = [{"kind":"anime","id":"328609","since":"2026-01-01T00:00:00+00:00"}]
    prefs["measure_consent"] = True
    store.save_preferences(token, prefs, catalog)
    raw = store.export_journal(token)
    assert token not in raw and "service_usage" not in raw and "route_shares" not in raw
    assert store.import_journal(other, raw) == 1
    restored = store.entries(other)[0]
    assert restored["id"] != entry["id"] and restored["trip_id"] == "" and restored["note"] == "PRIVATE NOTE"
    assert store.photos(other)[0]["scope"] == "private"
    assert not store.preferences(other)["measure_consent"]
    assert store.import_journal(other, raw) == 0 and not store.shares(other)
    corrupt = json.loads(raw)
    corrupt["entries"][0]["api_key"] = "unsafe"
    before = store.export_journal(other)
    with pytest.raises(ValueError):
        store.import_journal(other, json.dumps(corrupt))
    assert store.export_journal(other) == before


def test_preferences_recommendations_and_consent_are_explicit(setup):
    store, token, _, catalog, _ = setup
    assert store.recommend(token, catalog) == []
    prefs = store.preferences(token)
    prefs["follows"] = [{"kind":"anime","id":"328609","since":"2026-01-01T00:00:00+00:00"}]
    store.save_preferences(token, prefs, catalog)
    recommended = store.recommend(token, catalog)
    assert recommended and all("328609" in r["location"]["anime_ids"] for r in recommended)
    lid = recommended[0]["location"]["id"]
    store.save_recommendation(token, lid, catalog)
    assert not c.maintenance_report(store)["metrics"]
    prefs["measure_consent"] = True
    store.save_preferences(token, prefs, catalog)
    copied = store.create_recommended_trip(token, [lid], today().isoformat(), catalog)
    assert copied["plan"]["days"][0]["stops"][0]["location_id"] == lid
    assert c.maintenance_report(store)["metrics"][0]["kind"] == "recommendation_trip_created"
    prefs["dismissed"] = [lid]
    prefs["measure_consent"] = False
    store.save_preferences(token, prefs, catalog)
    assert lid not in [r["location"]["id"] for r in store.recommend(token, catalog)]
    assert not c.maintenance_report(store)["metrics"]
    # A skipped event was never fed into preference inference.
    confirmed = [{"location_id": "loc-tokyo-shelter", "confirmed": False}]
    assert recommendations(catalog, {"follows": [], "dismissed": [], "measure_consent": False}, [], confirmed) == []


def test_new_point_invitation_intake_and_review_never_apply_unreviewed(setup, monkeypatch):
    store, token, other, catalog, _ = setup
    args = {"kind":"new_location","description":"候选作品地点","evidence_url":"https://official.example.test/point",
            "observed_on":today().isoformat(),"proposal":{"name":"测试候选","lat":35.68,"lon":139.70,"anime_id":"328609","destination_id":"shinjuku"},"catalog":catalog}
    with pytest.raises(ValueError, match="邀请"):
        c.submission(store, token, **args)
    invite = c.issue_invite(store, "Synthetic reviewer")
    c.redeem_invite(store, token, invite)
    with pytest.raises(ValueError):
        c.redeem_invite(store, other, invite)
    cid = c.submission(store, token, **args)
    assert len(store.catalog(catalog)["locations"]) == len(catalog["locations"])
    assert c.own_submissions(store, other) == []
    monkeypatch.setenv("ANIMEWAY_CONTRIBUTION_QUEUE_LIMIT", "1")
    with pytest.raises(ValueError, match="积压"):
        c.submission(store, token, **args)
    c.review(store, cid, status="needs_info", reviewer="Synthetic reviewer", note="补充入口来源", minutes=3, catalog=catalog)
    c.supplement(store, token, cid, "补充入口来源文字", "https://official.example.test/access")
    patch = {"name":"测试候选","lat":35.68,"lon":139.70,"destination_id":"shinjuku","anime_ids":["328609"],
             "source_url":"https://official.example.test/point", "access":{"status":"unknown","summary":"仅关联待核查",
             "source_url":"https://official.example.test/access","checked_at":today().isoformat()}}
    reviewed = c.review(store, cid, status="accepted", reviewer="Synthetic reviewer", note="接受为基础候选，非已核实场景", minutes=5, patch=patch, catalog=catalog)
    live = store.catalog(catalog)
    assert len(live["locations"]) == len(catalog["locations"]) + 1
    assert c.own_submissions(store, token)[0]["body"]["review_minutes"] == 8
    c.withdraw_edit(store, reviewed["edit_id"], "Synthetic reviewer", "证据不足回撤")
    assert len(store.catalog(catalog)["locations"]) == len(catalog["locations"])
    assert c.own_submissions(store, token)[0]["status"] == "withdrawn"


def test_correction_priority_updates_followers_and_undo_in_reverse_order(setup):
    store, token, other, catalog, _ = setup
    prefs = store.preferences(token)
    prefs["follows"] = [{"kind":"anime","id":"328609","since":"2026-01-01T00:00:00+00:00"}]
    store.save_preferences(token, prefs, catalog)
    cid = c.submission(store, other, kind="correction", location_id="loc-tokyo-shelter", description="现场暂停",
        evidence_url="https://official.example.test/access", observed_on=today().isoformat(), catalog=catalog)
    patch = {"access":{"status":"closed","summary":"Synthetic closed test","source_url":"https://official.example.test/access","checked_at":today().isoformat()}}
    result = c.review(store, cid, status="accepted", reviewer="Synthetic reviewer", note="暂停访问", minutes=4, patch=patch, catalog=catalog)
    live = store.catalog(catalog)
    assert next(p for p in live["locations"] if p["id"]=="loc-tokyo-shelter")["access"]["status"] == "closed"
    assert c.follow_updates(store, token, live)
    assert not c.follow_updates(store, other, live)
    assert "loc-tokyo-shelter" not in [r["location"]["id"] for r in store.recommend(token, live)]
    cid2 = c.submission(store, other, kind="correction", location_id="loc-tokyo-shelter", description="撤下",
        evidence_url="https://official.example.test/access", observed_on=today().isoformat(), catalog=live)
    result2 = c.review(store, cid2, status="accepted", reviewer="Synthetic reviewer", note="撤下", minutes=2, patch={"withdrawn":True}, catalog=catalog)
    with pytest.raises(ValueError, match="逆序"):
        c.withdraw_edit(store, result["edit_id"], "Synthetic reviewer", "不能覆盖新变更")
    c.withdraw_edit(store, result2["edit_id"], "Synthetic reviewer", "回退")
    c.withdraw_edit(store, result["edit_id"], "Synthetic reviewer", "回退")
    assert next(p for p in store.catalog(catalog)["locations"] if p["id"]=="loc-tokyo-shelter")["access"] == next(p for p in catalog["locations"] if p["id"]=="loc-tokyo-shelter")["access"]
    report = c.maintenance_report(store)
    assert report["later_correction_reports"] == 1


def test_activity_expiry_checked_date_and_travel_date_overlap(setup):
    store, _, _, catalog, _ = setup
    item = {"id":"event-synthetic","title":"Synthetic event","destination_id":"tokyo","anime_ids":["328609"],
            "start_date":(today()-timedelta(days=1)).isoformat(),"end_date":today().isoformat(),"checked_at":today().isoformat(),
            "source_url":"https://official.example.test/event","summary":"Fixture, not real event"}
    eid = c.publish_activity(store, item, "Synthetic reviewer", 5, catalog)
    assert c.activities(store.catalog(catalog))
    assert not c.activities(store.catalog(catalog), start=(today()+timedelta(days=1)).isoformat())
    old = deepcopy(item)
    old["id"] = "event-expired"
    old["end_date"] = (today()-timedelta(days=1)).isoformat()
    c.publish_activity(store, old, "Synthetic reviewer", 2, catalog)
    assert len(c.activities(store.catalog(catalog))) == 1
    c.withdraw_edit(store, eid, "Synthetic reviewer", "撤下活动")
    assert not c.activities(store.catalog(catalog))


def test_schema_upgrade_is_idempotent_and_concurrent(tmp_path):
    from core.trip_store import TripStore
    path = tmp_path / "old.db"
    previous = TripStore(path)
    token = previous.new_identity()
    with ThreadPoolExecutor(max_workers=4) as pool:
        stores = list(pool.map(lambda _: JournalStore(path), range(4)))
    assert all(s.has_identity(token) for s in stores)
    assert json.loads(stores[0].export_backup(token))["schema_version"] == 2


def test_ai_short_text_cannot_add_experiences_or_unknown_recommendations(setup, monkeypatch):
    from core import journal_ai
    store, token, _, catalog, _ = setup
    entry = make_entry(setup)
    monkeypatch.setattr(journal_ai, "_request", lambda *args: {"order":[1,0]})
    text = journal_ai.order_record(store, token, entry["id"], catalog, "fake-key")
    assert "18" in text and "我到访了" in text and "PRIVATE NOTE" not in text
    assert store.entries(token)[0]["short_text"] == ""
    monkeypatch.setattr(journal_ai, "_request", lambda *args: {"order":[0], "text":"虚构天气"})
    with pytest.raises(ValueError):
        journal_ai.order_record(store, token, entry["id"], catalog, "fake-key")
    monkeypatch.setattr(journal_ai, "_request", lambda *args: {"location_ids":["nonexistent"]})
    with pytest.raises(ValueError):
        journal_ai.recommend_choices(store, token, catalog, "fake-key")
    choice = store.recommend(token, catalog)[0]["location"]["id"]
    monkeypatch.setattr(journal_ai, "_request", lambda *args: {"location_ids":[choice]})
    result = journal_ai.recommend_choices(store, token, catalog, "fake-key")
    assert result[0]["location"]["id"] == choice and result[0]["reason"]


def test_expansion_cannot_activate_without_real_gates(tmp_path):
    from core.expansion import expansion_status
    payload = {
        "schema_version": 1, "name": "测试目的地", "status": "candidate_only",
        "public_enabled": False, "planner_enabled": False, "content_owner": None,
        "release_gates": {"scene_and_access_review": False, "route_field_walk": False},
        "cost_observations": {"source_review_minutes": None},
    }
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(payload))
    status = expansion_status(candidate)
    assert status["destination"] == "测试目的地"
    assert status["missing"] and not status["public_enabled"] and not status["planner_enabled"]
    payload["public_enabled"] = True
    candidate.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="真实验收"):
        expansion_status(candidate)


def test_immature_retention_is_unknown_and_withdrawn_consent_erases_events(setup):
    store, token, _, catalog, _ = setup
    prefs = store.preferences(token)
    prefs["measure_consent"] = True
    store.save_preferences(token, prefs, catalog)
    store.record_intent(token)
    report = c.maintenance_report(store)
    assert all(row["mature_consenting_browsers"] == 0 and row["rate"] is None for row in report["intent_cohorts"])
    prefs["measure_consent"] = False
    store.save_preferences(token, prefs, catalog)
    assert not c.maintenance_report(store)["metrics"]


def test_photo_permission_change_revokes_share_without_reupload(setup):
    store, token, other, catalog, trip = setup
    photo = make_photo(setup, make_entry(setup), "share_allowed")
    preview = store.preview_share(token, trip["id"], catalog, photo_ids=[photo["id"]])
    sid = store.publish_share(token, trip["id"], 1, preview, catalog)
    original = store.photos(token)[0]["image"]
    with pytest.raises(ValueError):
        store.photo_scope(other, photo["id"], "own", "private")
    assert store.public_share(sid)
    store.photo_scope(token, photo["id"], "private_only", "private")
    assert store.public_share(sid) is None
    assert store.photos(token)[0]["image"] == original
    with pytest.raises(ValueError):
        store.preview_share(token, trip["id"], catalog, photo_ids=[photo["id"]])


def test_reviewed_closure_reaches_legacy_search_records(setup):
    from core.pilot import normalize_legacy_point
    store, token, _, catalog, _ = setup
    target = next(p for p in catalog["locations"] if p["id"] == "loc-tokyo-shelter")
    cid = c.submission(store, token, kind="correction", location_id=target["id"], description="Observed closure",
                       evidence_url="https://official.example.test/closure", observed_on=today().isoformat(), catalog=catalog)
    c.review(store, cid, status="accepted", reviewer="Synthetic reviewer", note="Closure checked", minutes=10,
             patch={"access":{"status":"closed", "summary":"Closed", "source_url":"https://official.example.test/closure", "checked_at":today().isoformat()}}, catalog=catalog)
    result = normalize_legacy_point({"id":target["upstream"][0]["record_id"]}, store.catalog(catalog))
    assert result["id"] == target["id"] and result["access"]["status"] == "closed"
