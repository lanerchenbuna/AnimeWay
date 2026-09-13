"""Protect identities, geography and trust states used by saved handbooks."""

from copy import deepcopy
import json

import pytest

from core import pilot


def test_pilot_relationships_are_complete_and_do_not_duplicate_real_route_stops():
    data = pilot.load_pilot()
    collections = {}
    for name in ("anime", "locations", "scenes", "routes", "destinations", "sources"):
        rows = data[name]
        assert all(isinstance(row["id"], str) for row in rows)
        assert len({row["id"] for row in rows}) == len(rows)
        collections[name] = {row["id"]: row for row in rows}
    assert 50 <= len(data["locations"]) <= 80
    assert len(data["routes"]) == 3
    for location in data["locations"]:
        assert location["destination_id"] in collections["destinations"]
        assert set(location["anime_ids"]) <= collections["anime"].keys()
        assert location["content_level"] in pilot.CONTENT_LEVELS
        assert location["city"] == "东京都"
        assert 35.55 < location["lat"] < 35.8
        assert 139.55 < location["lon"] < 139.9
        assert location["upstream"]
        for scene_id in location["scene_ids"]:
            assert collections["scenes"][scene_id]["location_id"] == location["id"]
    for scene in data["scenes"]:
        assert scene["anime_id"] in collections["anime"]
        assert set(scene["source_ids"]) <= collections["sources"].keys()
    for route in data["routes"]:
        stops = route["stops"]
        assert len({stop["location_id"] for stop in stops}) == len(stops)
        assert any(stop["required"] for stop in stops)
        assert any(not stop["required"] for stop in stops) or route.get("optional_extensions")
        assert all(stop["stay_min"] <= stop["stay_max"] for stop in stops)
        for stop in stops:
            location = collections["locations"][stop["location_id"]]
            assert set(stop["scene_ids"]) <= set(location["scene_ids"])
            assert stop["reason"]


def test_legacy_mapping_fixes_known_wrong_city_without_changing_input_or_other_cities():
    original = {
        "id": "a592d0d101934baa3379a97ff7ca667adf546961",
        "name": "新宿駅南口", "city": "高山市", "_city": "高山市", "note": "my note",
    }
    before = deepcopy(original)
    corrected = pilot.normalize_legacy_point(original)
    assert corrected["id"] == "loc-tokyo-shinjuku-south"
    assert corrected["city"] == corrected["_city"] == "东京都"
    assert corrected["legacy_id"] == original["id"]
    assert corrected["note"] == "my note"
    assert original == before
    same_name_elsewhere = {"id": "user-kyoto", "name": "新宿駅南口", "city": "京都市"}
    assert pilot.normalize_legacy_point(same_name_elsewhere) == same_name_elsewhere
    assert pilot.normalize_legacy_point({"name": "新宿駅南口"}) == {"name": "新宿駅南口"}


@pytest.mark.parametrize("query", ["东京", "東京", "Tokyo", "東京都"])
def test_tokyo_aliases_include_only_pilot_geography(query):
    found = pilot.search_pilot(query)
    assert len(found) == len(pilot.load_pilot()["locations"])
    assert not pilot.search_pilot("京都")
    assert not pilot.search_pilot("高山市")


def test_filters_intersect_and_unknown_object_ids_do_not_expand_scope():
    yotsuya = pilot.search_pilot("", anime_id="160209", destination_id="yotsuya")
    assert yotsuya and all(row["destination_id"] == "yotsuya" for row in yotsuya)
    assert not pilot.search_pilot("下北泽", anime_id="160209")
    assert not pilot.search_pilot("东京", destination_id="kyoto")
    assert not pilot.search_pilot("", anime_id="does-not-exist")
    assert pilot.search_pilot("Bocchi", anime_id="328609")
    assert pilot.search_pilot("須賀神社")


def test_multiple_scenes_share_one_real_location():
    stairs = pilot.get_location("loc-tokyo-suga-stairs")
    assert stairs is not None and len(stairs["scene_ids"]) == 3
    ids = {pilot.normalize_legacy_point({"id": row["record_id"]})["id"]
           for row in stairs["upstream"]}
    assert ids == {stairs["id"]}
    results = pilot.normalize_legacy_points([{"id": row["record_id"]} for row in stairs["upstream"]])
    assert len(results) == 1
    assert len(results[0]["scene_ids"]) == 3


def test_unknown_facts_and_image_rights_are_not_invented():
    data = pilot.load_pilot()
    for scene in data["scenes"]:
        media = scene["media"]
        assert media["display_allowed"] is False
        assert media["download_allowed"] is False
        assert media["share_allowed"] is False
        assert not media["url"]
        assert media["source_url"] and media["attribution"]
        assert scene["episode"] is None and scene["timecode"] is None
    for route in data["routes"]:
        assert route["status"] in {"prototype", "desk_reviewed"}
        assert not route["publication"]["field_verified"]
        assert not route["publication"]["user_validated"]
        assert pilot.publication_blockers(route)
        for connection in route["connections"]:
            if connection["status"] == "unverified":
                assert connection["duration_min"] is None
                assert connection["distance_m"] is None


def test_accepted_short_route_bounds_official_time_and_keeps_extensions_out():
    route = pilot.get_route("route-yotsuya-stairs")
    assert route["publication"]["content_ready"]
    assert len(route["stops"]) == 2
    connection = route["connections"][0]
    assert connection["status"] == "official_reference"
    assert connection["duration_min"] == 10
    assert connection["source_url"] == "https://sugajinjya.or.jp/access/"
    assert connection["field_measured"] is False
    assert not route["publication"]["field_verified"]
    assert all(extension["status"] == "future_unverified"
               for extension in route["optional_extensions"])


def test_returned_templates_are_independent_and_missing_objects_are_explicit():
    first = pilot.load_pilot()
    first["routes"][0]["stops"].clear()
    assert pilot.load_pilot()["routes"][0]["stops"]
    assert pilot.get_location("unknown") is None
    assert pilot.get_anime("unknown") is None
    assert pilot.get_route("unknown") is None


def test_new_content_schema_fails_explicitly(tmp_path, monkeypatch):
    content = tmp_path / "pilot.json"
    content.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
    monkeypatch.setattr(pilot, "PILOT_PATH", content)
    with pytest.raises(ValueError, match="Unsupported"):
        pilot.load_pilot()


def test_withdrawn_content_disappears_from_discovery_without_losing_saved_identity(monkeypatch):
    data = pilot.load_pilot()
    withdrawn = data["locations"][0]
    withdrawn["withdrawn"] = True
    monkeypatch.setattr(pilot, "load_pilot", lambda: deepcopy(data))
    assert withdrawn["id"] not in {row["id"] for row in pilot.search_pilot("")}
    assert pilot.get_location(withdrawn["id"])["withdrawn"] is True
