"""Public discovery adapters and small, serializable map navigation state."""

from copy import deepcopy
from uuid import uuid4
import math

from core.map_catalog import source_key
from core.map_query import _bounds
from core.private_store import _location
from core.sqlite_retrieval import SQLiteRetriever

TOKYO_BBOX = [139.55, 35.55, 139.85, 35.78]


def initial_state():
    return {
        "bbox": TOKYO_BBOX[:],
        "zoom": 12,
        "selected_id": None,
        "scene_id": None,
        "work_id": None,
        "page": "explore",
        "history": [],
        "camera": None,
        "events": [],
        "tile_error": False,
    }


def camera_request(state, bbox, *, padding=40):
    state["bbox"] = list(_bounds(bbox))
    state["camera"] = {"id": uuid4().hex, "bbox": list(bbox), "padding": padding}


def fit_points(points):
    if not points:
        return None
    lats = [float(p["lat"]) for p in points]
    lons = sorted({(float(p["lon"]) + 360) % 360 for p in points})
    gaps = [
        (lons[(i + 1) % len(lons)] + (360 if i == len(lons) - 1 else 0) - x, i)
        for i, x in enumerate(lons)
    ]
    _, end = max(gaps)
    west = lons[(end + 1) % len(lons)]
    east = lons[end]
    if east < west:
        east += 360
    pad = max(0.003, (east - west) * 0.08)
    if east - west + 2 * pad >= 360:
        west, east = -180, 180
    else:
        west, east = ((west - pad + 180) % 360) - 180, ((east + pad + 180) % 360) - 180
    pad_lat = max(0.003, (max(lats) - min(lats)) * 0.08)
    return [
        west,
        max(-85, min(85, min(lats) - pad_lat)),
        east,
        max(-85, min(85, max(lats) + pad_lat)),
    ]


def navigate(state, page, *, location_id=None, work_id=None, scene_id=None):
    state["history"] = (
        state["history"]
        + [{k: deepcopy(v) for k, v in state.items() if k not in {"history", "events", "camera"}}]
    )[-20:]
    state["page"] = page
    if location_id is not None:
        state["selected_id"] = location_id
    state["scene_id"] = scene_id
    if work_id is not None:
        state["work_id"] = work_id


def go_back(state):
    if state["history"]:
        previous = state["history"].pop()
        state.update(previous)
        camera_request(state, state["bbox"], padding=0)
    else:
        state["page"] = "explore"


def apply_map_event(state, event, visible_ids, context):
    if not isinstance(event, dict) or event.get("context") != context:
        return False
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or len(event_id) > 100 or event_id in state["events"]:
        return False
    kind = event.get("kind")
    if kind == "viewport":
        try:
            bbox = list(_bounds(event.get("bbox")))
            zoom = event["zoom"]
            if (
                isinstance(zoom, bool)
                or not isinstance(zoom, (int, float))
                or not math.isfinite(zoom)
                or not 0 <= zoom <= 24
            ):
                return False
        except (ValueError, TypeError, KeyError):
            return False
        state.update(bbox=bbox, zoom=zoom)
        if event.get("camera_id") == (state.get("camera") or {}).get("id"):
            state["camera"] = None
    elif kind == "select" and event.get("id") in visible_ids:
        state["selected_id"] = event["id"]
        navigate(state, "place", location_id=event["id"])
    elif kind == "tile_error":
        state["tile_error"] = True
    else:
        return False
    state["events"] = (state["events"] + [event_id])[-30:]
    return True


def wishlist_snapshot(detail):
    place = detail["place"]
    if place.get("withdrawn"):
        raise ValueError("Withdrawn place cannot be newly saved")
    refs = detail.get("source_refs", [])
    # Explicit portable whitelist: no raw sources, media rights or private data.
    return _location(
        {
            "id": place["id"],
            "name": place["name"],
            "lat": place["lat"],
            "lon": place["lon"],
            "city": place.get("city") or "",
            "anime_ids": place.get("anime_ids", []),
            "scene_ids": place.get("scene_ids", []),
            "source_url": place.get("source_url")
            or (refs[0].get("source_url") if refs else "")
            or "",
            "source_version": str(place.get("source_version") or ""),
            "access": place.get("access", {"status": "unknown"}),
        }
    )


def search_discovery(service, query):
    retriever = SQLiteRetriever(service.db_path)
    works = retriever.search_anime(query, k=20) if query.strip() else []
    spots = retriever.search_spots(query, k=20) if query.strip() else []
    locations = {}
    for spot in spots:
        detail = service.get_place(source_key(spot["anime_id"], spot["id"]))
        if detail and not detail["place"].get("withdrawn"):
            locations[detail["place"]["id"]] = detail["place"]
    # Editorial aliases/destination names are authoritative for the Tokyo pilot.
    overlay = service._editorial()
    if overlay and query.strip():
        from components.pilgrimage import filter_locations

        for place in filter_locations(overlay, query)[:20]:
            detail = service.get_place(place["id"])
            if detail and not detail["place"].get("withdrawn"):
                locations[place["id"]] = detail["place"]
        term = query.casefold().strip()
        for work in overlay.get("anime", []):
            if any(
                term in str(value).casefold()
                for value in [
                    work.get("name"),
                    work.get("cn"),
                    work.get("jp"),
                    *work.get("aliases", []),
                ]
            ):
                works = [w for w in works if str(w["id"]) != str(work["id"])]
                works.insert(
                    0,
                    {
                        "id": work["id"],
                        "cn": work.get("cn") or work["name"],
                        "jp": work.get("jp", ""),
                    },
                )
    return {"works": works[:20], "places": list(locations.values())[:20]}
