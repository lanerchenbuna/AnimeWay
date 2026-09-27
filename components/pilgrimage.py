"""The pilot's non-AI discovery → handbook → private trip flow.

Only an explicitly provided anonymous token can read or mutate private data.
Catalog objects are never mutated; a saved trip is an independent snapshot.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import inspect
import math
import re
import sqlite3
from typing import Callable
import unicodedata
from urllib.parse import urlencode, urlsplit

import pydeck as pdk
import streamlit as st

from components.i18n import current_locale
from components.pilgrimage_i18n import ptext
from core.pilot import load_pilot

_SELECTION_KEYS = {
    "anime": "aw_selected_anime",
    "location": "aw_selected_location",
    "route": "aw_selected_route",
    "trip": "aw_selected_trip",
}


def _remember_controls() -> None:
    """Keep page controls outside Streamlit's per-render widget cleanup."""
    memory = st.session_state.setdefault("aw_control_memory", {})
    for key, value in st.session_state.items():
        if key in {"aw_discovery_query", "aw_destination_filter"} or key.startswith(
            ("aw_location_selector_", "aw_view_mode_", "aw_keep_")
        ):
            memory[key] = value


def _restore_controls() -> None:
    for key, value in st.session_state.get("aw_control_memory", {}).items():
        if key not in st.session_state:
            st.session_state[key] = value


def _norm(value: object) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(value)).casefold())


def _name(item: dict) -> str:
    preferred = {"zh_CN": "cn", "ja_JP": "jp", "en_US": "en"}.get(current_locale())
    return str(item.get(preferred) or item.get("name") or item.get("title") or item["id"])


def _item(catalog: dict, collection: str, item_id: object) -> dict | None:
    if collection == "locations":
        from core.place_links import places
        return places(catalog).get(str(item_id))
    return next((item for item in catalog.get(collection, []) if str(item["id"]) == str(item_id)), None)


def _belongs(location: dict, destination_id: str, destinations: dict) -> bool:
    current = location.get("destination_id")
    visited = set()
    while current and current not in visited:
        if current == destination_id:
            return True
        visited.add(current)
        current = destinations.get(current, {}).get("parent_id")
    return False


def filter_locations(catalog: dict, query: str = "", destination_id: str = "") -> list[dict]:
    """One result set feeds map, selector and list (including destination ancestry)."""
    term = _norm(query)
    destinations = {item["id"]: item for item in catalog.get("destinations", [])}
    works = {str(item["id"]): item for item in catalog.get("anime", [])}
    if destination_id and destination_id not in destinations:
        return []

    def names(item):
        return [item.get(key, "") for key in ("name", "cn", "jp", "en")] + item.get("aliases", [])

    matching_destinations = {
        item_id for item_id, value in destinations.items()
        if term and term in {_norm(name) for name in names(value)}
    }
    matching_works = {
        item_id for item_id, value in works.items()
        if term and term in {_norm(name) for name in names(value)}
    }
    result = []
    for location in catalog.get("locations", []):
        if location.get("withdrawn"):
            continue
        if destination_id and not _belongs(location, destination_id, destinations):
            continue
        if not term:
            result.append(location)
            continue
        if matching_destinations:
            matches = any(_belongs(location, item_id, destinations) for item_id in matching_destinations)
        elif matching_works:
            matches = bool(matching_works.intersection(map(str, location.get("anime_ids", []))))
        else:
            fields = names(location)
            for item_id in location.get("anime_ids", []):
                fields.extend(names(works.get(str(item_id), {})))
            # Geographic labels only support an actual whole-name/alias match above.
            matches = any(term in _norm(field) for field in fields)
        if matches:
            result.append(location)
    return result


def navigation_url(location: dict) -> str:
    """A public coordinate-only link; never include browser or service credentials."""
    return "https://www.google.com/maps/search/?" + urlencode({
        "api": "1", "query": f"{float(location['lat']):.6f},{float(location['lon']):.6f}",
    })


def _valid_url(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return ""


def _source(url: object, key: str = "source") -> None:
    safe = _valid_url(url)
    if safe:
        st.link_button(ptext(key), safe)
    else:
        st.caption(ptext("source_missing"))


def _access_text(location: dict) -> str:
    access = location.get("access") or {}
    return access.get("summary") or ptext("access_unknown")


def _forbidden(location: dict) -> bool:
    return (location.get("access") or {}).get("status") in {"prohibited", "no_entry", "closed", "forbidden"} or bool(location.get("withdrawn"))


def _viewpoint_text(location: dict) -> str:
    viewpoint = location.get("viewpoint")
    if isinstance(viewpoint, dict):
        return viewpoint.get("summary") or ptext("viewpoint_unknown")
    return viewpoint or ptext("viewpoint_unknown")


def _attempt(action: Callable, *, error: str = "invalid"):
    try:
        return action()
    except (ValueError, UnicodeError):
        st.error(ptext(error))
    except (OSError, sqlite3.Error):
        st.error(ptext("unavailable"))
    return None


def _go(page: str, item_id: str | None = None) -> None:
    _remember_controls()
    old = {"page": st.session_state.get("aw_page", "discover")}
    old.update({key: st.session_state.get(key) for key in _SELECTION_KEYS.values()})
    history = st.session_state.setdefault("aw_history", [])
    if old["page"] != page or (page in _SELECTION_KEYS and old.get(_SELECTION_KEYS[page]) != item_id):
        st.session_state["aw_history"] = (history + [old])[-20:]
    st.session_state["aw_page"] = page
    if item_id is not None and page in _SELECTION_KEYS:
        st.session_state[_SELECTION_KEYS[page]] = item_id
    st.rerun()


def _back() -> None:
    _remember_controls()
    history = list(st.session_state.get("aw_history", []))
    previous = history.pop() if history else {"page": "discover"}
    st.session_state["aw_history"] = history
    st.session_state["aw_page"] = previous.pop("page")
    for key, value in previous.items():
        st.session_state[key] = value
    st.rerun()


def _view_event(store, token: str | None, page: str, item_id: str) -> None:
    stamp = (page, item_id)
    if token and st.session_state.get("aw_view_event") != stamp:
        _attempt(lambda: store.record_event(token, f"view_{page}", item_id))
    st.session_state["aw_view_event"] = stamp


def _wishlist_button(store, token, location: dict, key: str) -> None:
    saved = False
    if token:
        places = _attempt(lambda: store.list_wishlist(token)) or []
        saved = any(item["id"] == location["id"] for item in places)
    label = "remove_place" if saved else "save_place"
    if st.button(ptext(label), key=f"aw_wish_{key}_{location['id']}", disabled=not token):
        def change():
            if saved:
                store.remove_wishlist(token, location["id"])
            else:
                store.add_wishlist(token, location)
                import time
                origin = st.session_state.get("awj_origin", {})
                if hasattr(store, "record_journey_event") and origin.get("location_id") == location["id"] and 0 <= time.time() - origin.get("at", 0) <= 1800:
                    store.record_journey_event(token, "update_saved", location["id"], "update")
            return True
        if _attempt(change):
            st.session_state["aw_flash"] = ptext("saved")
            st.rerun()


def _navigation(location: dict) -> None:
    if _forbidden(location):
        st.caption(ptext("navigation_suspended"))
        return
    try:
        url = navigation_url(location)
    except (KeyError, TypeError, ValueError):
        st.caption(ptext("unknown"))
        return
    st.link_button(ptext("navigate"), url, width="stretch")
    st.caption(ptext("copy_location"))
    st.code(f"{location['name']}\n{location.get('city', '')}\n{float(location['lat']):.6f}, {float(location['lon']):.6f}", language=None)


def _level(location: dict) -> None:
    level = location.get("content_level", "basic")
    st.caption(ptext(f"level_{level if level in {'basic', 'selection', 'route'} else 'basic'}"))
    st.caption(ptext("checked", date=location.get("reviewed_at") or ptext("unknown")))


def _scene(scene: dict, catalog: dict, *, link_place: bool = False) -> None:
    st.markdown(f"**{scene.get('title') or ptext('scene_reference')}**")
    anime = _item(catalog, "anime", scene.get("anime_id"))
    if anime:
        st.caption(_name(anime))
    facts = []
    if scene.get("episode"):
        facts.append(f"{ptext('episode')}: {scene['episode']}")
    if scene.get("timecode"):
        facts.append(f"{ptext('timecode')}: {scene['timecode']}")
    st.caption(" · ".join(facts) if facts else ptext("unknown_episode"))
    status = scene.get("match_status")
    st.caption(ptext("scene_reviewed" if status in {"verified", "reviewed", "confirmed"} else "scene_pending"))
    if scene.get("evidence"):
        evidence = scene["evidence"]
        st.write(evidence.get("summary", "") if isinstance(evidence, dict) else evidence)
    media = scene.get("media") or {}
    media_items = media if isinstance(media, list) else [media]
    for item in media_items:
        media_type = item.get("type")
        st.caption(ptext("real_photo" if media_type in {"real", "real_photo", "photo"} else "scene_reference" if media_type in {"anime", "anime_frame", "screenshot", "reference"} else "unclassified_media"))
        media_url = _valid_url(item.get("url"))
        if item.get("display_allowed") is True and media_url:
            try:
                st.image(media_url, caption=item.get("attribution"), width="stretch")
            except (ValueError, OSError):
                st.caption(ptext("media_missing"))
        else:
            st.caption(ptext("media_link_only") if media else ptext("media_missing"))
        if item.get("attribution"):
            st.caption(str(item["attribution"]))
    _source(scene.get("source_url") or (media_items[0].get("source_url") if media_items else ""))
    if link_place and st.button(ptext("open_location"), key=f"aw_scene_location_{scene['id']}"):
        _go("location", scene["location_id"])


def _map_selection(map_key: str, selector_key: str, allowed: set[str]) -> None:
    state = st.session_state.get(map_key, {})
    objects = state.get("selection", {}).get("objects", {}).get("pilot-points", [])
    if objects and objects[0].get("id") in allowed:
        st.session_state[selector_key] = objects[0]["id"]


def _locations_view(locations: list[dict], catalog: dict, store, token, scope: str) -> None:
    st.session_state[f"aw_visible_locations_{scope}"] = [place["id"] for place in locations]
    if not locations:
        st.info(ptext("query_empty"))
        return
    st.subheader(ptext("locations"))
    ids = [item["id"] for item in locations]
    lookup = {item["id"]: item for item in locations}
    selector_key = f"aw_location_selector_{scope}"
    if st.session_state.get(selector_key) not in lookup:
        st.session_state[selector_key] = ids[0]
    mode_labels = {key: ptext(key) for key in ("list", "map")}
    mode = st.radio(ptext("view_mode"), ["list", "map"], format_func=mode_labels.get,
                    horizontal=True, key=f"aw_view_mode_{scope}")
    if mode == "map":
        st.caption(ptext("map_help"))
        points = [{"id": place["id"], "name": place["name"], "lat": place["lat"], "lon": place["lon"],
                   "color": [240, 120, 50] if place["id"] == st.session_state[selector_key] else [55, 125, 210]}
                  for place in locations
                  if isinstance(place.get("lat"), (int, float)) and isinstance(place.get("lon"), (int, float))
                  and math.isfinite(place["lat"]) and math.isfinite(place["lon"])]
        if points:
            deck = pdk.Deck(
                layers=[pdk.Layer("ScatterplotLayer", points, id="pilot-points", get_position="[lon, lat]",
                                  get_radius=35, radius_min_pixels=7, get_fill_color="color", pickable=True)],
                initial_view_state=pdk.ViewState(latitude=sum(p["lat"] for p in points) / len(points),
                                                longitude=sum(p["lon"] for p in points) / len(points), zoom=12),
                map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
                tooltip={"text": "{name}"},
            )
            digest = hashlib.sha256("|".join(ids).encode()).hexdigest()[:12]
            map_key = f"aw_pilot_map_{scope}_{digest}"
            options = {"key": map_key, "height": 350, "use_container_width": True}
            if "on_select" in inspect.signature(st.pydeck_chart).parameters:
                options.update(selection_mode="single-object", on_select=lambda: _map_selection(map_key, selector_key, set(ids)))
            try:
                st.pydeck_chart(deck, **options)
            except (ValueError, TypeError):
                st.caption(ptext("map_unavailable"))
    selected = st.selectbox(ptext("selected_location"), ids, format_func=lambda key: lookup[key]["name"], key=selector_key)
    location = lookup[selected]
    st.caption(f"{location.get('city', '')} · {location.get('name', '')}")
    _level(location)
    _wishlist_button(store, token, location, scope)
    if st.button(ptext("open_location"), key=f"aw_open_selected_{scope}"):
        _go("location", selected)
    if mode == "list":
        # All labels are visible; the selector and highlighted row keep the same ID as the map.
        for place in locations:
            prefix = "● " if place["id"] == selected else "○ "
            st.write(f"{prefix}{place['name']} · {place.get('city', '')}")


def _route_card(route: dict, suffix: str) -> None:
    with st.container(border=True):
        st.markdown(f"**{route['title']}**")
        st.write(route.get("summary", ""))
        if route.get("status") != "published":
            st.caption(ptext("desk_reviewed" if (route.get("publication") or {}).get("content_ready") else "prototype"))
        if route.get("duration_hint"):
            st.caption(route["duration_hint"])
        if st.button(ptext("open_route"), key=f"aw_route_card_{suffix}_{route['id']}"):
            _go("route", route["id"])


def _discover(catalog: dict, store, token) -> None:
    st.title(ptext("title"))
    st.caption(ptext("intro"))
    if token and hasattr(store, "list_personal_trips"):
        personal = _attempt(lambda: store.list_personal_trips(token)) or []
        if personal:
            st.write(personal[0]["plan"]["requirements"]["title"])
            if st.button(ptext("personal"), key="aw_continue_personal", type="primary"):
                st.session_state["awp_selected"] = personal[0]["id"]
                st.session_state["awp_mode"] = "detail"
                _go("personal")
    if token:
        trips = _attempt(lambda: store.list_trips(token)) or []
        if trips:
            with st.container(border=True):
                st.write(trips[0]["title"])
                if st.button(ptext("open_trip"), key="aw_continue_latest", type="primary"):
                    _go("trip", trips[0]["id"])
    query = st.text_input(ptext("search"), placeholder=ptext("search_hint"), key="aw_discovery_query")
    destinations = {item["id"]: item for item in catalog.get("destinations", [])}
    if st.session_state.get("aw_destination_filter", "") not in {"", *destinations}:
        st.session_state["aw_destination_filter"] = ""
    destination_labels = {"": ptext("all_destinations"), **{key: _name(item) for key, item in destinations.items()}}
    destination = st.selectbox(ptext("destination"), ["", *destinations],
                               format_func=destination_labels.get,
                               key="aw_destination_filter")
    locations = filter_locations(catalog, query, destination)
    ids = {item["id"] for item in locations}
    anime_ids = {str(item_id) for item in locations for item_id in item.get("anime_ids", [])}
    st.subheader(ptext("works"))
    for anime in catalog.get("anime", []):
        if str(anime["id"]) not in anime_ids:
            continue
        with st.container(border=True):
            st.markdown(f"**{_name(anime)}**")
            st.caption(str(anime.get("version") or anime.get("format") or ""))
            if st.button(ptext("open_anime"), key=f"aw_work_{anime['id']}"):
                _go("anime", anime["id"])
    if destination:
        place = destinations[destination]
        st.subheader(_name(place))
        st.write(place.get("summary") or place.get("description") or "")
    else:
        with st.expander(ptext("destinations")):
            for dest in destinations.values():
                if not any(_belongs(location, dest["id"], destinations) for location in locations):
                    continue
                st.write(_name(dest))
                st.caption(dest.get("summary") or dest.get("description") or "")
                if st.button(ptext("open_destination"), key=f"aw_dest_{dest['id']}"):
                    # The selectbox already exists; a callback-safe deferred update is applied next render.
                    st.session_state["aw_pending_destination"] = dest["id"]
                    st.session_state["aw_pending_query"] = ""
                    st.rerun()
    routes = [route for route in catalog.get("routes", [])
              if any(stop["location_id"] in ids for stop in route.get("stops", []))]
    st.subheader(ptext("routes"))
    for route in sorted(routes, key=lambda item: not (item.get("publication") or {}).get("content_ready")):
        _route_card(route, "discover")
    scene_count = sum(scene.get("location_id") in ids for scene in catalog.get("scenes", []))
    st.caption(ptext("count", locations=len(locations), scenes=scene_count))
    st.caption(ptext("count_scope"))
    _locations_view(locations, catalog, store, token, "discover")


def _anime_page(catalog: dict, store, token, anime_id: str) -> None:
    anime = _item(catalog, "anime", anime_id)
    if not anime:
        st.warning(ptext("not_found"))
        return
    _view_event(store, token, "anime", anime_id)
    st.title(_name(anime))
    st.caption(str(anime.get("version") or anime.get("format") or ""))
    st.write(anime.get("summary") or "")
    locations = [item for item in catalog["locations"]
                 if str(anime_id) in map(str, item.get("anime_ids", [])) and not item.get("withdrawn")]
    location_ids = {item["id"] for item in locations}
    scenes = [item for item in catalog["scenes"]
              if str(item.get("anime_id")) == str(anime_id) and item["location_id"] in location_ids]
    st.caption(ptext("count", locations=len(locations), scenes=len(scenes)))
    st.caption(ptext("count_scope"))
    st.subheader(ptext("representative_scenes"))
    featured = sorted(scenes, key=lambda item: not item.get("featured", False))
    for scene in featured[:3]:
        with st.container(border=True):
            _scene(scene, catalog, link_place=True)
    if len(featured) > 3:
        with st.expander(ptext("all_scenes")):
            for scene in featured[3:]:
                _scene(scene, catalog, link_place=True)
    st.subheader(ptext("routes"))
    for route in catalog["routes"]:
        if str(anime_id) in map(str, route.get("anime_ids", [])):
            _route_card(route, "anime")
    _locations_view(locations, catalog, store, token, f"anime_{anime_id}")


def _correction_form(location: dict, store, token) -> None:
    keys = {"geography": "geo", "scene": "scene", "access": "access_issue", "image": "media", "other": "other"}
    labels = {key: ptext(value) for key, value in keys.items()}
    with st.expander(ptext("correction")):
        with st.form(f"aw_correction_{location['id']}", clear_on_submit=True):
            kind = st.selectbox(ptext("correction_kind"), list(keys), format_func=labels.get)
            description = st.text_area(ptext("correction_description"), max_chars=3000)
            source_url = st.text_input(ptext("optional_source"), max_chars=2048)
            submitted = st.form_submit_button(ptext("submit_correction"), disabled=not token)
        if submitted:
            if _attempt(lambda: store.submit_correction(token, location["id"], kind, description, source_url)):
                st.success(ptext("correction_saved"))


def _location_page(catalog: dict, store, token, location_id: str) -> None:
    location = _item(catalog, "locations", location_id)
    if not location or location.get("withdrawn"):
        st.warning(ptext("not_found"))
        return
    _view_event(store, token, "location", location_id)
    st.title(location["name"])
    st.caption(location.get("city", ""))
    _level(location)
    _wishlist_button(store, token, location, "detail")
    import os
    if os.getenv("ANIMEWAY_MAP_ENABLED", "1").lower() not in {"0", "false", "off"} and st.button("在地图中安排 Trip／记录", key="aw_location_map_trip"):
        from components.map_trip import open_map
        open_map(location_id)
    st.subheader(ptext("access"))
    if _forbidden(location) or (location.get("access") or {}).get("status") == "restricted":
        st.warning(ptext("access_restricted"))
    st.write(_access_text(location))
    access = location.get("access") or {}
    st.caption(ptext("checked", date=access.get("checked_at") or ptext("unknown")))
    if access.get("source_url"):
        _source(access["source_url"])
    st.subheader(ptext("viewpoint"))
    st.write(_viewpoint_text(location))
    if location.get("entry"):
        st.write(location["entry"])
    _navigation(location)
    st.subheader(ptext("evidence"))
    scenes = [scene for scene in catalog["scenes"] if scene["location_id"] == location_id]
    if not scenes:
        st.caption(ptext("scene_pending"))
    for scene in scenes:
        with st.container(border=True):
            _scene(scene, catalog)
    _source(location.get("source_url"))
    changes = location.get("change_log") or location.get("changes") or location.get("change_notes") or []
    if changes:
        with st.expander(ptext("changes")):
            for change in changes:
                st.write(f"{change.get('date', '')} · {change.get('summary', '')}" if isinstance(change, dict) else change)
    for route in catalog["routes"]:
        if any(stop["location_id"] == location_id for stop in route.get("stops", [])):
            _route_card(route, "location")
    _correction_form(location, store, token)


def _route_page(catalog: dict, store, token, route_id: str) -> None:
    route = _item(catalog, "routes", route_id)
    if not route:
        st.warning(ptext("not_found"))
        return
    st.title(route["title"])
    st.write(route.get("summary", ""))
    if route.get("status") != "published" or not (route.get("publication") or {}).get("content_ready"):
        st.info(ptext("desk_reviewed" if (route.get("publication") or {}).get("content_ready") else "prototype"))
        st.caption(ptext("prototype_help"))
    st.caption(ptext("owner", owner=route.get("owner") or ptext("unknown")))
    st.caption(ptext("checked", date=route.get("reviewed_at") or ptext("unknown")))
    st.caption(ptext("version", version=route.get("version", "")))
    st.subheader(ptext("why_route"))
    st.write(route.get("reason", ""))
    if route.get("duration_hint"):
        st.write(route["duration_hint"])
    st.caption(ptext("start_end"))
    def endpoint(value):
        if isinstance(value, dict):
            return value.get("name") or value.get("summary") or ptext("unknown")
        return str(value or ptext("unknown"))
    st.write(f"{endpoint(route.get('start'))} → {endpoint(route.get('end'))}")
    selected_stops = []
    forbidden = False
    for index, stop in enumerate(route.get("stops", []), 1):
        location = _item(catalog, "locations", stop["location_id"])
        if not location:
            forbidden = True
            continue
        with st.container(border=True):
            st.markdown(f"**{index}. {location['name']}**")
            required = stop.get("required", True)
            st.caption(ptext("required" if required else "optional"))
            st.write(stop.get("reason", ""))
            _stay(stop)
            if required:
                keep = True
            else:
                keep = st.checkbox(ptext("keep_stop"), value=True, key=f"aw_keep_{route_id}_{route.get('version')}_{location['id']}")
            if keep:
                selected_stops.append(stop)
                forbidden = forbidden or _forbidden(location)
            if _forbidden(location):
                st.warning(ptext("access_restricted"))
            st.caption(_access_text(location))
            if stop.get("skip_if"):
                st.caption(stop["skip_if"])
            if st.button(ptext("open_location"), key=f"aw_route_location_{route_id}_{location['id']}"):
                _go("location", location["id"])
    removed = len(selected_stops) != len(route.get("stops", []))
    _connection_notes({**route, "connection_status": "needs_recheck" if removed else route.get("connection_status", "unknown")})
    _unknowns(route.get("unknowns", []))
    st.caption(ptext("adoption_help"))
    if forbidden:
        st.warning(ptext("route_unavailable"))
    if st.button(ptext("adopt"), type="primary", key=f"aw_adopt_{route_id}", disabled=not token or forbidden or not selected_stops):
        personal_route = deepcopy(route)
        personal_route["stops"] = deepcopy(selected_stops)
        if removed:
            personal_route["connection_status"] = "needs_recheck"
            personal_route["unknowns"] = list(personal_route.get("unknowns", [])) + [ptext("recheck")]
        trip = _attempt(lambda: store.create_trip(token, personal_route, catalog["locations"]))
        if trip:
            _go("trip", trip["id"])


def _stay(stop: dict) -> None:
    low, high = stop.get("stay_min"), stop.get("stay_max")
    if low is not None and high is not None:
        st.caption(ptext("stay", low=low, high=high))


def _unknowns(items: list) -> None:
    if items:
        st.subheader(ptext("unknowns"))
        for item in items:
            st.write(f"• {item}")


def _connection_notes(item: dict) -> None:
    status = item.get("connection_status", "unknown")
    st.warning(ptext("recheck" if status == "needs_recheck" else "connections_reference" if status == "reference_only" else "connections_unknown"))
    if status == "needs_recheck" and item.get("reference_notes"):
        st.caption("以下为保存时的历史参考，当前连接需重新核查。")
    for note in item.get("reference_notes", []):
        st.write(note)


def _trips_page(catalog: dict, store, token) -> None:
    st.title(ptext("trips"))
    st.caption(ptext("private_help"))
    trips = _attempt(lambda: store.list_trips(token)) if token else []
    if not trips:
        st.info(ptext("trips_empty"))
    for trip in trips or []:
        with st.container(border=True):
            st.markdown(f"**{trip['title']}**")
            st.caption(f"{len(trip['stops'])} · {trip['updated_at'][:10]}")
            if st.button(ptext("open_trip"), key=f"aw_open_trip_{trip['id']}"):
                _go("trip", trip["id"])


def export_checklist(trip: dict, catalog: dict, *, locale: str | None = None) -> str:
    """Explicit textual projection: no images, identity tokens, keys or hidden fields."""
    from core.place_links import trip_view
    trip = trip_view(trip, catalog)
    def tr(key, **params):
        return ptext(key, locale=locale, **params)
    lines = [trip["title"], tr("personal_copy"), "", tr("offline_help"), "",
             tr("recheck" if trip.get("connection_status") == "needs_recheck" else "connections_reference" if trip.get("connection_status") == "reference_only" else "connections_unknown"), ""]
    if trip.get("connection_status") == "needs_recheck" and trip.get("reference_notes"):
        lines.append("以下为保存时的历史参考，当前连接需重新核查。")
    lines.extend(trip.get("reference_notes", []))
    for number, stop in enumerate(trip["stops"], 1):
        live = _item(catalog, "locations", stop["id"]) or {}
        access = live.get("access") or stop.get("access") or {}
        lines.extend([f"{number}. {stop['name']}", stop.get("city", ""),
                      tr("required" if stop.get("required", True) else "optional"), stop.get("reason", ""),
                      access.get("summary") or tr("access_unknown"),
                      tr("checked", date=access.get("checked_at") or tr("unknown"))])
        viewpoint = live.get("viewpoint") or stop.get("viewpoint")
        if isinstance(viewpoint, str) and viewpoint:
            lines.append(viewpoint)
        entry = live.get("entry") or stop.get("entry")
        if isinstance(entry, str) and entry:
            lines.append(entry)
        if _valid_url(access.get("source_url")):
            lines.append(access["source_url"])
        if stop.get("skip_if"):
            lines.append(stop["skip_if"])
        if live.get("withdrawn") or _forbidden(live):
            lines.append(tr("access_restricted"))
        if stop.get("stay_min") is not None and stop.get("stay_max") is not None:
            lines.append(tr("stay", low=stop["stay_min"], high=stop["stay_max"]))
        for scene_id in stop.get("scene_ids", []):
            scene = _item(catalog, "scenes", scene_id)
            if scene:
                lines.append(scene.get("title", ""))
                lines.append(tr("unknown_episode") if scene.get("episode") is None else f"{tr('episode')}: {scene['episode']}")
                if _valid_url(scene.get("source_url")):
                    lines.append(scene["source_url"])
        coordinate = f"{float(stop['lat']):.6f}, {float(stop['lon']):.6f}"
        if stop.get("missing"):
            coordinate = f"{tr('historical_coordinate')}: {coordinate}"
        lines.extend([coordinate,
                      tr("navigation_suspended") if _forbidden(live or stop) else navigation_url(stop), ""])
    lines.extend([tr("unknowns"), *[str(item) for item in trip.get("unknowns", [])]])
    return "\n".join(lines)


def _trip_page(catalog: dict, store, token, trip_id: str) -> None:
    trip = _attempt(lambda: store.get_trip(token, trip_id)) if token else None
    if not trip:
        st.warning(ptext("not_found"))
        return
    from core.place_links import trip_view, blocked
    trip = trip_view(trip, catalog)
    st.title(trip["title"])
    st.caption(ptext("personal_copy"))
    if hasattr(store, "create_personal_trip") and st.button(ptext("convert_trip"), key=f"aw_convert_{trip_id}"):
        from core.trip import empty_plan, new_requirements, stop_spec
        def convert():
            works = list(dict.fromkeys(work for stop in trip["stops"] for work in stop.get("anime_ids", [])))[:3]
            plan = empty_plan(new_requirements("明天", 1, anime_ids=works or None, title=trip["title"]))
            plan["requirements"]["must_ids"] = [s["id"] for s in trip["stops"] if s.get("required", True)]
            plan["days"][0]["stops"] = [{**stop_spec(s["id"], required=s.get("required", True)),
                                         "stay_min": s.get("stay_max") or 20} for s in trip["stops"]]
            return store.create_personal_trip(token, plan)
        saved = _attempt(convert)
        if saved:
            st.session_state["awp_selected"] = saved["id"]
            st.session_state["awp_mode"] = "detail"
            _go("personal")
    title = st.text_input(ptext("trip_title"), value=trip["title"], max_chars=300, key=f"aw_trip_title_{trip_id}_{trip['revision']}")
    if st.button(ptext("rename"), key=f"aw_rename_{trip_id}"):
        if _attempt(lambda: store.update_trip(token, trip_id, trip["revision"], title=title)):
            st.rerun()
    template = _item(catalog, "routes", trip.get("template_id"))
    if template and str(template.get("version", "")) != str(trip.get("template_version", "")):
        st.info(ptext("template_updated"))
        if st.button(ptext("view_current_template"), key=f"aw_current_template_{trip_id}"):
            _go("route", template["id"])
    if trip.get("started_at"):
        st.success(ptext("started"))
    elif st.button(ptext("begin"), key=f"aw_begin_{trip_id}", type="primary"):
        if _attempt(lambda: store.start_trip(token, trip_id)):
            st.rerun()
    st.subheader(ptext("today"))
    _connection_notes(trip)
    if st.checkbox("查看当前地点地图", key="aw_trip_live_map"):
        points = [{"lat": s["lat"], "lon": s["lon"]} for s in trip["stops"] if not blocked(s)]
        if points:
            st.map(points)
    for index, stop in enumerate(trip["stops"], 1):
        live = _item(catalog, "locations", stop["id"])
        with st.container(border=True):
            st.markdown(f"**{index}. {stop['name']}**")
            st.caption(ptext("required" if stop.get("required", True) else "optional"))
            st.write(stop.get("reason", ""))
            _stay(stop)
            st.write(_access_text(live or stop))
            if stop.get("facts_changed"):
                st.info(ptext("content_updated"))
            if live and _forbidden(live):
                st.warning(ptext("access_restricted"))
            st.caption(_viewpoint_text(live or stop))
            if (live or stop).get("entry"):
                st.caption((live or stop)["entry"])
            if stop.get("skip_if"):
                st.caption(stop["skip_if"])
            for scene_id in stop.get("scene_ids", []):
                scene = _item(catalog, "scenes", scene_id)
                if scene and not (live or {}).get("withdrawn"):
                    with st.expander(scene.get("title") or ptext("scene_reference")):
                        _scene(scene, catalog)
            _navigation(stop)
            if live and not live.get("withdrawn") and st.button(ptext("open_location"), key=f"aw_trip_location_{trip_id}_{stop['id']}"):
                _go("location", stop["id"])
            if not stop.get("required", True) and st.button(ptext("remove_optional"), key=f"aw_remove_stop_{trip_id}_{stop['id']}"):
                if _attempt(lambda: store.update_trip(token, trip_id, trip["revision"], remove_location_id=stop["id"])):
                    st.rerun()
    _unknowns(trip.get("unknowns", []))
    st.download_button(ptext("offline"), export_checklist(trip, catalog).encode("utf-8"),
                       file_name=f"animeway-checklist-{trip_id[:12]}.txt", mime="text/plain", key=f"aw_offline_{trip_id}")
    st.caption(ptext("offline_help"))
    with st.expander(ptext("delete_trip")):
        confirmed = st.checkbox(ptext("confirm_delete"), key=f"aw_confirm_delete_{trip_id}")
        if st.button(ptext("delete_trip"), key=f"aw_delete_trip_{trip_id}", disabled=not confirmed):
            def delete():
                store.delete_trip(token, trip_id)
                return True
            if _attempt(delete):
                _go("trips")


def _wishlist_page(catalog: dict, store, token) -> None:
    st.title(ptext("wishlist"))
    st.caption(ptext("private_help"))
    locations = _attempt(lambda: store.list_wishlist(token)) if token else []
    if not locations:
        st.info(ptext("wishlist_empty"))
    for saved in locations or []:
        from core.place_links import resolve_saved
        saved = resolve_saved(saved, catalog)
        live = _item(catalog, "locations", saved["id"])
        with st.container(border=True):
            st.markdown(f"**{saved['name']}**")
            st.caption(saved.get("city", ""))
            if saved.get("facts_changed"):
                st.info(ptext("content_updated"))
            _wishlist_button(store, token, saved, "wishlist")
            if live and not live.get("withdrawn"):
                import os
                if os.getenv("ANIMEWAY_MAP_ENABLED", "1").lower() not in {"0", "false", "off"} and st.button("在地图中安排 Trip／记录", key=f"aw_wishlist_map_{saved['id']}"):
                    from components.map_trip import open_map
                    open_map(saved['id'])
                if st.button(ptext("open_location"), key=f"aw_wishlist_location_{saved['id']}"):
                    _go("location", saved["id"])
            else:
                st.caption(ptext("level_basic"))
                if live and _forbidden(live):
                    st.warning(ptext("access_restricted"))
                _navigation(saved)


def _settings_page(catalog: dict, store, token) -> None:
    st.title(ptext("backup"))
    st.write(ptext("private_help"))
    st.caption(ptext("backup_help"))
    if token:
        raw = _attempt(lambda: store.export_backup(token))
        if raw is not None:
            st.download_button(ptext("backup_download"), raw.encode("utf-8"), file_name="animeway-private-backup.json",
                               mime="application/json", key="aw_backup_download")
    upload = st.file_uploader(ptext("backup_upload"), type=["json"], key="aw_backup_upload", disabled=not token)
    from components.import_review import render_import_review
    approved = render_import_review(store, token, upload, catalog)
    if st.button(ptext("restore"), key="aw_restore", disabled=approved is None):
        def restore():
            if upload.size > 5 * 1024 * 1024:
                raise ValueError("Backup too large")
            return store.import_backup(token, approved)
        if _attempt(restore) is not None:
            st.success(ptext("restored"))
    st.subheader(ptext("corrections"))
    corrections = _attempt(lambda: store.list_corrections(token)) if token else []
    if not corrections:
        st.caption(ptext("corrections_empty"))
    for report in corrections or []:
        location = _item(catalog, "locations", report["location_id"])
        with st.container(border=True):
            st.write(location["name"] if location else report["location_id"])
            status_key = {"needs_info": "reviewing", "accepted": "resolved"}.get(report["status"], report["status"])
            st.caption(f"{ptext(status_key)} · {report.get('updated_at', '')[:10]}")
            st.write(report["description"])
            if report.get("review_note"):
                st.write(report["review_note"])
            if report.get("source_url"):
                _source(report["source_url"])
    with st.expander(ptext("rights")):
        st.write(ptext("media_link_only"))
        for source in catalog.get("sources", []):
            st.write(source.get("name") or source.get("title") or source["id"])
            st.caption(source.get("attribution") or "")
            url = source.get("url") or source.get("source_url")
            if url:
                _source(url)


def render_pilgrimage(store, token: str | None, catalog: dict | None = None, api_key: str = "") -> None:
    """Render within the application's primary tab without requiring an LLM key."""
    if catalog is None:
        try:
            catalog = load_pilot()
        except (ValueError, OSError):
            st.error(ptext("unavailable"))
            return
    _restore_controls()
    if "aw_pending_destination" in st.session_state:
        st.session_state["aw_destination_filter"] = st.session_state.pop("aw_pending_destination")
    if "aw_pending_query" in st.session_state:
        st.session_state["aw_discovery_query"] = st.session_state.pop("aw_pending_query")
    st.session_state.setdefault("aw_page", "discover")
    nav = st.columns(5)
    for column, page in zip(nav, ("discover", "personal", "trips", "wishlist", "settings")):
        with column:
            if st.button(ptext("backup" if page == "settings" else page), key=f"aw_nav_{page}", width="stretch"):
                _go(page)
    if hasattr(store, "entries"):
        left, right = st.columns(2)
        with left:
            if st.button("我的巡礼记录", key="aw_nav_journal", width="stretch"):
                _go("journal")
        with right:
            if st.button("下一次巡礼", key="aw_nav_rediscovery", width="stretch"):
                _go("rediscovery")
    if not token:
        st.info(ptext("identity_pending"))
    flash = st.session_state.pop("aw_flash", "")
    if flash:
        st.success(flash)
    page = st.session_state["aw_page"]
    if page in _SELECTION_KEYS:
        if st.button(ptext("back"), key="aw_back"):
            _back()
    if page == "discover":
        _discover(catalog, store, token)
    elif page == "anime":
        _anime_page(catalog, store, token, st.session_state.get("aw_selected_anime", ""))
    elif page == "location":
        _location_page(catalog, store, token, st.session_state.get("aw_selected_location", ""))
    elif page == "route":
        _route_page(catalog, store, token, st.session_state.get("aw_selected_route", ""))
    elif page == "trip":
        _trip_page(catalog, store, token, st.session_state.get("aw_selected_trip", ""))
    elif page == "trips":
        _trips_page(catalog, store, token)
    elif page == "wishlist":
        _wishlist_page(catalog, store, token)
    elif page == "settings":
        _settings_page(catalog, store, token)
    elif page == "personal":
        from components.trip_planner import render_personal_trips
        render_personal_trips(store, token, catalog, api_key)
    elif page == "journal":
        from components.journal import render_journal
        render_journal(store, token, catalog, api_key)
    elif page == "rediscovery":
        from components.journal import render_rediscovery
        render_rediscovery(store, token, catalog, api_key)
    else:
        st.session_state["aw_page"] = "discover"
        st.rerun()
    _remember_controls()
