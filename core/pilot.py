"""Small, versioned Tokyo editorial overlay; never rewrites the upstream index.

Content review, access review, transport verification and field testing are
separate states. Loading a record does not promote any of those states.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any
import unicodedata


PILOT_PATH = Path(__file__).resolve().parents[1] / "knowledge_base" / "pilot" / "tokyo.json"
CONTENT_LEVELS = {"basic", "selection", "route"}


def load_pilot() -> dict[str, Any]:
    """Read the checked-in snapshot, returning a fresh, user-editable copy.

    Do not cache this across content withdrawals or expose mutable global data.
    Malformed or newer schemas fail explicitly instead of silently losing data.
    """
    with PILOT_PATH.open(encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported pilot content schema; preserve the existing snapshot.")
    for key in ("anime", "locations", "scenes", "routes", "destinations", "sources"):
        if not isinstance(data.get(key), list):
            raise ValueError(f"Missing pilot content collection: {key}")
    return data


def _get(collection: str, item_id: str) -> dict[str, Any] | None:
    return next((item for item in load_pilot()[collection] if item["id"] == str(item_id)), None)


def get_location(location_id: str) -> dict[str, Any] | None:
    return _get("locations", location_id)


def get_anime(anime_id: str) -> dict[str, Any] | None:
    return _get("anime", anime_id)


def get_route(route_id: str) -> dict[str, Any] | None:
    return _get("routes", route_id)


def _norm(value: Any) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(value)).casefold())


def search_pilot(
    query: str,
    anime_id: str | None = None,
    destination_id: str | None = None,
) -> list[dict[str, Any]]:
    """Search real pilot objects and explicit aliases, with intersecting filters.

    Exact place aliases resolve first, so 東京 cannot accidentally match 京都
    through a shared character. Unknown explicit filters produce no results.
    """
    data = load_pilot()
    places = {item["id"]: item for item in data["destinations"]}
    works = {item["id"]: item for item in data["anime"]}
    anime_id = str(anime_id) if anime_id is not None else None
    if anime_id is not None and anime_id not in works:
        return []
    if destination_id is not None and destination_id not in places:
        return []
    term = _norm(query)
    exact_places = {
        item["id"] for item in places.values()
        if term and term in {_norm(item["name"]), *(_norm(a) for a in item.get("aliases", []))}
    }
    exact_works = {
        item["id"] for item in works.values()
        if term and term in {
            _norm(item["name"]), _norm(item["cn"]), _norm(item["jp"]),
            *(_norm(a) for a in item.get("aliases", [])),
        }
    }

    def belongs(location: dict[str, Any], place_id: str) -> bool:
        current = location["destination_id"]
        visited: set[str] = set()
        while current and current not in visited:
            if current == place_id:
                return True
            visited.add(current)
            current = places.get(current, {}).get("parent_id")
        return False

    results = []
    for location in data["locations"]:
        if location.get("withdrawn", False):
            continue
        if anime_id and anime_id not in location["anime_ids"]:
            continue
        if destination_id and not belongs(location, destination_id):
            continue
        if not term:
            results.append(location)
            continue
        if exact_places:
            matches = any(belongs(location, item_id) for item_id in exact_places)
        elif exact_works:
            matches = bool(exact_works.intersection(location["anime_ids"]))
        else:
            fields = [location["name"], *location.get("aliases", [])]
            for item_id in location["anime_ids"]:
                work = works[item_id]
                fields.extend([work["cn"], work["jp"], *work.get("aliases", [])])
            matches = any(term in _norm(field) for field in fields)
        if matches:
            results.append(location)
    return results


def normalize_legacy_point(point: dict[str, Any], catalog: dict | None = None) -> dict[str, Any]:
    """Map a *known* old point identity into the overlay, without geographic guessing.

    Preserve unrelated/custom records verbatim. Name-only matching would confuse
    identically named stations or overwrite a user-entered place in another city.
    """
    result = deepcopy(point)
    point_id = str(point.get("id", ""))
    if not point_id:
        return result
    for location in (catalog if catalog is not None else load_pilot())["locations"]:
        upstream_ids = {item["record_id"] for item in location.get("upstream", [])}
        if point_id == location["id"] or point_id in upstream_ids:
            result.update(deepcopy(location))
            result["legacy_id"] = point_id
            result["_city"] = location["city"]
            result["_id"] = location["id"]
            # The overlay deliberately has no embedding rights for upstream media.
            result["image"] = None
            return result
    return result


def publication_blockers(route: dict[str, Any]) -> list[str]:
    """Return explicit release blockers; a prototype is always saveable as a draft."""
    publication = route.get("publication", {})
    blockers = list(publication.get("blockers", []))
    if not publication.get("content_ready"):
        blockers.append("内容验收尚未通过")
    if not publication.get("field_verified"):
        blockers.append("尚未完成现场试走")
    if not publication.get("user_validated"):
        blockers.append("真实用户验证尚未完成")
    return list(dict.fromkeys(blockers))


def normalize_legacy_points(points: list[dict[str, Any]], catalog: dict | None = None) -> list[dict[str, Any]]:
    """One legacy result card per canonical place, even with multiple scenes."""
    result = []
    seen = set()
    for point in points:
        normalized = normalize_legacy_point(point, catalog)
        identity = normalized.get("id")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        result.append(normalized)
    return result
