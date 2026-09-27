"""Pure public Work/Place/Scene/SourceRef projection (contract version 1).

Pass the current editorial catalog, including withdrawals/content edits. This
module never reads private storage and does not infer physical-place matches.
It is an offline builder, not a viewport query or a UI session cache.
"""
from copy import deepcopy
from typing import Any
from urllib.parse import quote

from data_factory.normalization import normalize_spot

CATALOG_VERSION = 1


def source_key(work_id: Any, point_id: Any, provider: str = "anitabi") -> str:
    return ":".join(quote(str(part), safe="") for part in (provider, work_id, point_id))


def _unique(rows: list[dict]) -> dict[str, dict]:
    result = {}
    for row in rows:
        key = str(row["id"])
        if key in result:
            raise ValueError(f"Duplicate editorial ID: {key}")
        result[key] = deepcopy(row)
    return result


def build_map_catalog(payload: dict, editorial: dict | None = None) -> dict:
    """Project normalized index items, preserving authoritative editorial facts.

    Unmapped source points get separate places even when coordinates match.
    Source keys remain resolvable for withdrawn places; callers must filter them
    when recommending. Legacy coordinate-derived IDs cannot survive corrections
    without an explicit mapping: we expose identity_kind instead of guessing.
    """
    editorial = editorial or {}
    places = _unique(editorial.get("locations", []))
    scenes = _unique(editorial.get("scenes", []))
    works = {}
    refs = {}
    place_by_source = {}
    scene_by_source = {}
    for location_id, place in places.items():
        for upstream in place.get("upstream", []):
            key = source_key(upstream["anime_id"], upstream["record_id"], upstream["provider"])
            if key in place_by_source and place_by_source[key] != location_id:
                raise ValueError(f"Source maps to multiple places: {key}")
            place_by_source[key] = location_id
            refs[key] = {
                "id": key, "provider": upstream["provider"], "work_id": str(upstream["anime_id"]),
                "point_id": str(upstream["record_id"]), "location_id": location_id,
                "source_url": upstream.get("source_url"), "snapshot": upstream.get("source_snapshot"),
                "upstream_updated_at": None, "identity_kind": "editorial_mapping",
            }
    for scene_id, scene in scenes.items():
        scene["work_id"] = str(scene["anime_id"])
        scene.setdefault("timecode_seconds", None)
        scene.setdefault("source_ref_ids", [])
        if scene["location_id"] not in places:
            raise ValueError(f"Dangling scene place: {scene_id}")
        if scene.get("upstream_record_id"):
            key = source_key(scene["work_id"], scene["upstream_record_id"])
            if place_by_source.get(key) != scene["location_id"]:
                raise ValueError(f"Scene/source place mismatch: {scene_id}")
            if key in scene_by_source:
                raise ValueError(f"Source maps to multiple scenes: {key}")
            scene_by_source[key] = scene_id
            scene["source_ref_ids"] = [key]
    seen = {}
    for item in payload.get("items", []):
        work_id = str(item["anime_id"])
        if work_id in works:
            raise ValueError(f"Duplicate work: {work_id}")
        works[work_id] = {"id": work_id, **deepcopy(item.get("meta", {}))}
        works[work_id]["id"] = work_id
        for raw in item.get("spots", []):
            spot = normalize_spot(raw, int(work_id))
            if spot is None:
                raise ValueError(f"Invalid normalized point in work {work_id}")
            record = spot.model_dump(mode="json", exclude_none=True)
            key = source_key(work_id, spot.id)
            if key in seen:
                if seen[key] != record:
                    raise ValueError(f"Conflicting source point: {key}")
                continue
            seen[key] = record
            location_id = place_by_source.get(key, f"loc:{key}")
            place_by_source[key] = location_id
            if location_id not in places:
                places[location_id] = {
                    "id": location_id, "name": spot.name, "lat": spot.lat, "lon": spot.lon,
                    "city": spot.city, "geography": {"status": "upstream_unverified"},
                    "content_level": "basic", "access": {"status": "unknown"},
                    "withdrawn": False, "source_version": payload.get("stats", {}).get("generated_at"),
                }
            refs[key] = {
                **refs.get(key, {}), "id": key, "provider": "anitabi", "work_id": work_id,
                "point_id": spot.id, "location_id": location_id, "identity_kind": spot.identity_kind,
                "source_url": spot.source_url or f"https://anitabi.cn/map?bangumiId={work_id}",
                "origin": spot.origin, "origin_url": spot.origin_url,
                "upstream_updated_at": None, "source_raw": deepcopy(spot.source_raw),
                "normalization_issues": list(spot.normalization_issues),
                "legacy_variants": deepcopy(spot.legacy_variants),
            }
            if key not in scene_by_source:
                scene_id = f"scene:{key}"
                scene_by_source[key] = scene_id
                scenes[scene_id] = {
                    "id": scene_id, "work_id": work_id, "anime_id": work_id,
                    "location_id": location_id, "title": spot.name,
                    "episode": spot.episode, "timecode_seconds": spot.timecode_seconds,
                    "description": spot.scene, "group": spot.group,
                    "source_ref_ids": [key], "match_status": "community_reported",
                    "spoiler_level": "unspecified",
                    "media": {"reference_url": spot.image, "url": "", "display_allowed": False,
                              "download_allowed": False, "share_allowed": False,
                              "rights_status": "origin_and_permissions_pending"},
                }
    for work_id, work in _unique(editorial.get("anime", [])).items():
        works[work_id] = {**works.get(work_id, {}), **work, "id": work_id}
    for place in places.values():
        # Relationships are derived from scenes, not trusted stale cached arrays.
        place["scene_ids"] = []
        place["anime_ids"] = []
    for work in works.values():
        work["scene_ids"] = []
    for scene_id, scene in scenes.items():
        if scene["work_id"] not in works:
            raise ValueError(f"Dangling scene work: {scene_id}")
        works[scene["work_id"]]["scene_ids"].append(scene_id)
        place = places[scene["location_id"]]
        place["scene_ids"].append(scene_id)
        if scene["work_id"] not in place["anime_ids"]:
            place["anime_ids"].append(scene["work_id"])
    return {
        "schema_version": CATALOG_VERSION, "editorial_place_ids": [str(p["id"]) for p in editorial.get("locations", [])], "works": works, "places": places, "scenes": scenes,
        "source_refs": refs, "place_by_source": place_by_source,
        "editorial_sources": _unique(editorial.get("sources", [])),
        "editorial_scene_ids": [str(s["id"]) for s in editorial.get("scenes", [])],
        "destinations": _unique(editorial.get("destinations", [])),
    }
