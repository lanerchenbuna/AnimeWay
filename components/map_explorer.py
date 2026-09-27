"""Streamlit map → work → scene → place discovery with private wishlist actions."""

import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlencode

import streamlit as st
import streamlit.components.v1 as components

from components.map_i18n import access_text, mtext
from core.place_links import blocked
from core.map_explore import (
    initial_state,
    camera_request,
    fit_points,
    navigate,
    go_back,
    apply_map_event,
    wishlist_snapshot,
    search_discovery,
)
from data_factory.normalization import safe_url

_map = components.declare_component(
    "animeway_map", path=str(Path(__file__).resolve().parents[1] / "assets" / "map")
)


def _labels(options):
    # Capture translations while the script has a locale; widget serializers may
    # invoke format_func outside a Streamlit script context (including AppTest).
    labels = {value: mtext(value) if value else mtext("any") for value in options}
    return labels.get


def _remember():
    memory = st.session_state.setdefault("awmap_memory", {})
    for key in list(st.session_state):
        if key.startswith("awmap_ui_"):
            memory[key] = st.session_state[key]
    for key, value in memory.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _go(state, page, **kwargs):
    if kwargs.get("location_id"):
        state["selected_id"] = kwargs["location_id"]
    navigate(state, page, **kwargs)
    st.rerun()


def _save(store, token, detail):
    place = detail["place"]
    try:
        saved = bool(
            store and token and any(p["id"] == place["id"] for p in store.list_wishlist(token))
        )
    except (ValueError, sqlite3.Error):
        saved = False
    if st.button(
        mtext("remove" if saved else "save"),
        key="awmap_save",
        disabled=not store or not token or bool(place.get("withdrawn")),
    ):
        try:
            if saved:
                store.remove_wishlist(token, place["id"])
            else:
                store.add_wishlist(token, wishlist_snapshot(detail))
            st.rerun()
        except (ValueError, sqlite3.Error):
            st.error(mtext("save_error"))


def _scene_image(scene, *, width=None):
    """Show only media cleared for display; always expose its original source."""
    media = scene.get("media", {})
    url = safe_url(media.get("url"))
    source = safe_url(media.get("origin_url") or media.get("source_url") or scene.get("source_url"))
    if not source and scene.get("work_id"):
        source = "https://anitabi.cn/map?" + urlencode({"bangumiId": scene["work_id"]})
    if url and media.get("display_allowed") and not scene.get("upstream_removed"):
        attribution = media.get("attribution") or mtext("source")
        if width:
            st.image(url, caption=attribution, width=width)
        else:
            st.image(url, caption=attribution, width="stretch")
        visible = True
    else:
        visible = False
        st.caption("此场景的图片尚无可在本站展示的来源与权限信息。")
    if source:
        st.markdown(f"[在来源站查看场景 ↗]({source})")
    return visible


def _place(service, state, store, token, catalog):
    detail = service.get_place(state["selected_id"])
    if not detail:
        st.info(mtext("missing"))
        return
    place = detail["place"]
    st.subheader(place["name"])
    if place.get("withdrawn"):
        st.warning(mtext("withdrawn"))
    st.caption(
        f"{mtext(place.get('content_level', 'basic'))} · {mtext('access')}: {access_text(place.get('access', {}).get('status', 'unknown'))}"
    )
    if place.get("access", {}).get("summary"):
        st.write(place["access"]["summary"])
    if place.get("geography", {}).get("status") == "upstream_unverified":
        st.caption(mtext("raw_city"))
    st.caption(f"{mtext('source_time')}: {place.get('reviewed_at') or mtext('unknown')}")
    if place.get("source_version") is not None:
        st.caption(f"{mtext('source_version')}: {place['source_version']}")
    _save(store, token, detail)
    if not blocked(place):
        st.link_button(
            mtext("navigate"),
            "https://www.google.com/maps/search/?"
            + urlencode({"api": 1, "query": f"{place['lat']},{place['lon']}"}),
        )
    st.caption(mtext("coordinate_help"))
    st.code(f"{place['lat']:.6f}, {place['lon']:.6f}", language=None)
    seen_sources = set()
    for row in detail["source_refs"] + detail.get("sources", []):
        url = safe_url(row.get("origin_url") or row.get("source_url") or row.get("url"))
        if url and url not in seen_sources:
            seen_sources.add(url)
            st.link_button(str(row.get("origin") or row.get("name") or mtext("source"))[:100], url)
    from components.map_trip import render_place_actions
    render_place_actions(store, token, detail, catalog)
    st.subheader(mtext("scenes"))
    for scene in detail["scenes"]:
        label = scene.get("title") or place["name"]
        expanded = scene["id"] == state.get("scene_id")
        with st.expander(label, expanded=expanded):
            ep = scene.get("episode")
            seconds = scene.get("timecode_seconds")
            st.write(f"{mtext('episode')}: {ep if ep is not None else mtext('unknown_episode')}")
            st.write(f"{mtext('timecode')}: {seconds if seconds is not None else mtext('unknown')}")
            if st.checkbox(mtext("spoilers"), key=f"awmap_spoiler_{scene['id']}"):
                st.write(scene.get("description") or scene.get("match_summary") or mtext("unknown"))
            if not place.get("withdrawn"):
                _scene_image(scene)
            work_id = str(scene.get("work_id") or scene.get("anime_id"))
            if st.button(mtext("work") + " " + work_id, key=f"awmap_scene_work_{scene['id']}"):
                _go(state, "work", work_id=work_id)


def _work(service, state):
    work_id = state["work_id"]
    overview = service.work_page(work_id)
    if not overview:
        st.info(mtext("missing"))
        return
    work = overview["work"]
    title = work.get("cn") or work.get("name") or work.get("titles", {}).get("cn") or work_id
    st.subheader(title)
    st.caption(work.get("version") or mtext("unknown"))
    if st.button(mtext("work_map"), key="awmap_work_map", disabled=not overview["bounds"]):
        state["filter_work"] = work_id
        st.session_state["awmap_ui_work"] = work_id
        state["page"] = "explore"
        camera_request(state, overview["bounds"])
        st.rerun()
    prefix = f"awmap_ui_{work_id}_"
    eps = [None] + [e if e is not None else "__unknown__" for e in overview["episodes"]]
    regions = [None] + [r if r is not None else "__unknown__" for r in overview["regions"]]
    for suffix, options in (("episode", eps), ("region", regions)):
        key = prefix + suffix
        if key in st.session_state and st.session_state[key] not in options:
            st.session_state[key] = None
    ep = st.selectbox(
        mtext("episode"),
        eps,
        key=prefix + "episode",
        format_func=lambda e, any_label=mtext("any"), unknown=mtext("unknown_episode"): (
            any_label if e is None else unknown if e == "__unknown__" else str(e)
        ),
    )
    region = st.selectbox(
        mtext("region"),
        regions,
        key=prefix + "region",
        format_func=lambda r, any_label=mtext("any"), unknown=mtext("unknown"): (
            any_label if r is None else unknown if r == "__unknown__" else r
        ),
    )
    level = st.selectbox(
        mtext("level"),
        [None, "basic", "selection", "route"],
        key=prefix + "level",
        format_func=_labels([None, "basic", "selection", "route"]),
    )
    signature = (work_id, ep, region, level)
    if state.get("scene_filter") != signature:
        state.update(scene_filter=signature, scene_offset=0)
    result = service.work_page(
        work_id, episode=ep, region=region, level=level, offset=state.get("scene_offset", 0)
    )
    st.caption(f"{mtext('scenes')}: {result['total']}")
    if not result["total"]:
        st.info(mtext("empty"))
    for scene in result["scenes"]:
        episode = scene["episode"] if scene["episode"] is not None else mtext("unknown_episode")
        st.write(f"{episode} · {scene['place_name']}")
        if st.button(mtext("open"), key="awmap_scene_" + scene["id"]):
            _go(state, "place", location_id=scene["location_id"], scene_id=scene["id"])
    left, right = st.columns(2)
    if left.button(mtext("prev"), key="awmap_prev", disabled=result["offset"] == 0):
        state["scene_offset"] = max(0, result["offset"] - 24)
        st.rerun()
    if right.button(
        mtext("next"), key="awmap_next", disabled=result["offset"] + 24 >= result["total"]
    ):
        state["scene_offset"] = result["offset"] + 24
        st.rerun()


def _explore(service, state, store, token, catalog, version):
    with st.form("awmap_search_form"):
        search_field, search_action = st.columns([5, 1], vertical_alignment="bottom")
        with search_field:
            query = st.text_input(mtext("search"), key="awmap_ui_query")
        with search_action:
            submitted = st.form_submit_button(mtext("search_go"), width="stretch")
    if submitted or state.get("search_query") != query:
        state["search_query"] = query
        state["search"] = (
            search_discovery(service, query) if query.strip() else {"works": [], "places": []}
        )
    search = state.get("search", {"works": [], "places": []})
    works = {str(w["id"]): w.get("cn") or w.get("name") or str(w["id"]) for w in catalog["anime"]}
    works.update(
        {str(w["id"]): w.get("cn") or w.get("name") or str(w["id"]) for w in search["works"]}
    )
    for retained in (state.get("filter_work"), st.session_state.get("awmap_ui_work")):
        if retained:
            works.setdefault(retained, retained)
    work_rows = search["works"] if query.strip() else catalog["anime"]
    if work_rows:
        work_columns = st.columns(min(3, len(work_rows)))
        for index, row in enumerate(work_rows):
            work_id = str(row["id"])
            with work_columns[index % len(work_columns)]:
                if st.button(works[work_id], key="awmap_work_" + work_id, width="stretch"):
                    _go(state, "work", work_id=work_id)
    for place in search["places"]:
        if st.button(place["name"], key="awmap_search_place_" + place["id"]):
            state["selected_id"] = place["id"]
            camera_request(state, fit_points([place]))
            _go(state, "place", location_id=place["id"])
    if query.strip() and not search["works"] and not search["places"]:
        st.info(mtext("empty"))
    destinations = {p["id"]: p["name"] for p in catalog.get("destinations", [])}
    with st.expander(mtext("filter")):
        work_id = st.selectbox(
            mtext("work"),
            [None, *works],
            format_func=lambda v, any_label=mtext("any"): works.get(v, any_label),
            key="awmap_ui_work",
        )
        destination = st.selectbox(
            mtext("region"),
            [None, *destinations],
            format_func=lambda v, any_label=mtext("any"): destinations.get(v, any_label),
            key="awmap_ui_destination",
        )
        city = st.text_input(mtext("city"), key="awmap_ui_city")
        level = st.selectbox(
            mtext("level"),
            [None, "basic", "selection", "route"],
            format_func=_labels([None, "basic", "selection", "route"]),
            key="awmap_ui_level",
        )
        access_options = [None, "unknown", "open", "public_exterior", "restricted",
                          "closed", "forbidden", "prohibited", "no_entry"]
        access = st.selectbox(
            mtext("access"),
            access_options,
            format_func={
                v: access_text(v) if v else mtext("any") for v in access_options
            }.get,
            key="awmap_ui_access",
        )
    state["filter_work"] = work_id
    filters = {}
    if destination:
        filters["destination_id"] = destination
    if city.strip():
        filters["city"] = city.strip()
    if level:
        filters["content_levels"] = [level]
    if access:
        filters["access_statuses"] = [access]
    work_ids = [work_id] if work_id else None
    context = hashlib.sha256(
        json.dumps([version, filters, work_ids], sort_keys=True).encode()
    ).hexdigest()[:16]
    changed = state.get("context") != context
    if changed:
        state["context"] = context
        state["selected_id"] = None
        if work_id:
            work = service.work_page(work_id)
            if work and work["bounds"]:
                camera_request(state, work["bounds"])
    # Consume component state before querying, so a viewport update is rendered
    # in this run instead of forcing a second rerun that can swallow a UI click.
    event = st.session_state.get("awmap_canvas")
    if apply_map_event(state, event, set(st.session_state.get("awmap_visible_ids", [])), context):
        if state["page"] != "explore":
            st.rerun()
    if st.button(mtext("fit"), key="awmap_fit"):
        world = service.query_places([-180, -85, 180, 85], 10, work_ids, filters)
        points = world["features"] or [
            point for cluster in world["clusters"] for point in cluster["extent"]
        ]
        bounds = fit_points(points)
        if bounds:
            camera_request(state, bounds)
    result = service.query_places(state["bbox"], state["zoom"], work_ids, filters)
    st.session_state["awmap_visible_ids"] = [p["id"] for p in result["features"]]
    st.caption(mtext("place_count").format(count=result["total"]))
    mode = st.radio(
        mtext("title"),
        ["map", "list"],
        format_func=_labels(["map", "list"]),
        horizontal=True,
        key="awmap_ui_mode",
        index=0,
        label_visibility="collapsed",
    )
    saved = []
    if store and token:
        try:
            saved = [p["id"] for p in store.list_wishlist(token)]
        except (ValueError, sqlite3.Error):
            pass
    if mode == "map":
        st.session_state.setdefault("awmap_ui_tiles", True)
        tiles = st.checkbox(mtext("tiles"), key="awmap_ui_tiles")
        _map(
            result=result,
            bbox=state["bbox"],
            camera=state.get("camera"),
            selected_id=state["selected_id"],
            saved_ids=saved,
            context=context,
            tiles_enabled=tiles,
            labels={
                key: mtext(key)
                for key in ("map", "help", "tile_error", "no_tiles", "cluster", "cluster_hint")
            },
            key="awmap_canvas",
            default=None,
        )
        st.caption(mtext("legend"))
        if state.get("tile_error"):
            st.info(mtext("tile_error"))
    if result["requires_zoom"]:
        st.info(mtext("cluster_hint"))
        pages = list(range((len(result["clusters"]) + 19) // 20))
        if st.session_state.get("awmap_cluster_page", 0) not in pages:
            st.session_state["awmap_cluster_page"] = 0
        page = st.selectbox(
            mtext("cluster"), pages, format_func=lambda n: str(n + 1), key="awmap_cluster_page"
        )
        for cluster in result["clusters"][page * 20 : (page + 1) * 20]:
            if st.button(
                f"{cluster['count']} · {cluster['lat']:.2f}, {cluster['lon']:.2f}",
                key="awmap_cluster_" + cluster["id"],
            ):
                state["zoom"] = min(19, state["zoom"] + 2)
                camera_request(state, fit_points(cluster["extent"]))
                st.rerun()
    elif mode == "list" and result["features"]:
        features = result["features"]
        page_size = 12
        page_count = (len(features) + page_size - 1) // page_size
        page_key = "awmap_ui_list_page"
        if st.session_state.get(page_key, 0) >= page_count:
            st.session_state[page_key] = 0
        if page_count > 1:
            page = st.selectbox("地点页码", range(page_count), format_func=lambda value: f"第 {value + 1} / {page_count} 页", key=page_key)
        else:
            page = 0
        for place in features[page * page_size:(page + 1) * page_size]:
            detail = service.get_place(place["id"])
            with st.container(border=True):
                media, description = st.columns([1, 2.6], gap="medium")
                with media:
                    if detail and detail.get("scenes"):
                        _scene_image(detail["scenes"][0], width=250)
                    else:
                        st.caption(mtext("no_image"))
                with description:
                    st.subheader(place["name"])
                    st.caption(f"{mtext(place['content_level'])} · {access_text(place['access_status'])}")
                    if detail:
                        place_data = detail["place"]
                        summary = (place_data.get("access") or {}).get("summary")
                        if summary:
                            st.write(summary)
                        st.caption(f"{len(detail.get('scenes', []))} 个关联场景 · {place_data.get('city') or '东京'}")
                    if st.button(mtext("open"), key="awmap_list_open_" + place["id"], type="primary"):
                        _go(state, "place", location_id=place["id"])
    elif result["features"]:
        places = {p["id"]: p for p in result["features"]}
        selected = state["selected_id"] if state["selected_id"] in places else next(iter(places))
        key = "awmap_ui_place"
        if st.session_state.get(key) not in places or changed:
            st.session_state[key] = selected
        selected = st.selectbox(
            mtext("choose"), list(places), format_func=lambda v: places[v]["name"], key=key
        )
        state["selected_id"] = selected
        if st.button(mtext("open"), key="awmap_open"):
            _go(state, "place", location_id=selected)
        st.caption(
            mtext(places[selected]["content_level"])
            + " · "
            + access_text(places[selected]["access_status"])
        )
    else:
        st.info(mtext("empty"))


def render_map_explorer(
    service, store, token, catalog, version="pilot", scope="pilot", fallback=False
):
    _remember()
    state = st.session_state.setdefault("awmap_state", initial_state())
    if state.get("version") != version:
        state.update(version=version, search_query=None)
        if state.get("selected_id") and service.get_place(state["selected_id"]) is None:
            state.update(selected_id=None, page="explore")
    st.header(mtext("title"))
    st.caption(mtext(scope))
    if fallback:
        st.warning(mtext("fallback"))
    if state["page"] != "explore" and st.button(mtext("back"), key="awmap_back"):
        go_back(state)
        st.rerun()
    try:
        if state["page"] == "place":
            _place(service, state, store, token, catalog)
        elif state["page"] == "work":
            _work(service, state)
        else:
            _explore(service, state, store, token, catalog, version)
    except (sqlite3.Error, OSError, ValueError):
        st.error(mtext("fallback"))
