import math

import pydeck as pdk
import streamlit as st

from components.i18n import current_locale, tr
from components.state import clean_markdown_output, remove_from_itinerary
from components.ui import render_section_header
from utils import ali_ai


def render_plan(route_planner, amap_key: str, dashscope_key: str) -> None:
    st.markdown(
        render_section_header(tr("plan_title"), tr("plan_kicker"), tr("plan_help")),
        unsafe_allow_html=True,
    )
    enable_tsp = st.checkbox(tr("tsp"), value=True)

    if not st.session_state["itinerary"]:
        st.info(tr("plan_empty"))
        return

    _render_itinerary()
    start_addr = st.text_input(tr("start"), placeholder=tr("start_placeholder"))

    if st.button(tr("generate"), type="primary", use_container_width=True):
        _generate_plan(route_planner, start_addr, amap_key, dashscope_key, enable_tsp)

    plan = st.session_state.get("planned_routes")
    if plan:
        _render_summary(plan)
        _render_map(plan["points"], plan["routes"])
        _render_album(plan["points"])
        _render_guide(plan, dashscope_key)


def _render_itinerary() -> None:
    for idx, item in enumerate(st.session_state["itinerary"]):
        c1, c2, c3 = st.columns([0.5, 3, 1])
        with c1:
            st.markdown(f"### {idx + 1}")
        with c2:
            st.markdown(
                f"**{item.get('spot_name') or item.get('name') or tr('unknown_location')}**"
            )
            st.caption(item.get("_anime_name") or tr("unknown_anime"))
        with c3:
            if st.button(tr("remove"), key=f"del_{idx}"):
                remove_from_itinerary(idx)
        st.divider()


def _generate_plan(route_planner, start_addr: str, amap_key: str, dashscope_key: str, enable_tsp: bool) -> None:
    with st.spinner(tr("generating")):
        plan = route_planner.plan(
            list(st.session_state["itinerary"]),
            start_addr=start_addr.strip(),
            amap_key=amap_key,
            enable_tsp=enable_tsp,
        )

    points = plan["points"]
    routes = plan["routes"]
    plan["facts_markdown"] = ali_ai.render_tour_facts_markdown(
        points,
        routes,
        locale=current_locale(),
    )
    plan["guide_text"] = ""
    if dashscope_key:
        with st.spinner(tr("ai_generating")):
            plan["guide_text"] = clean_markdown_output(
                ali_ai.generate_tour_guide_text(
                    points,
                    routes,
                    api_key=dashscope_key,
                    locale=current_locale(),
                )
            )
    st.session_state["optimized_points"] = points
    st.session_state["planned_routes"] = plan


def _render_summary(plan: dict) -> None:
    st.divider()
    st.markdown(f"### {tr('route_summary')}")
    summary = plan["summary"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(tr("stops"), summary["stop_count"])
    c2.metric(tr("distance"), f"{summary['total_distance_km']} km")
    c3.metric(tr("duration"), f"{summary['total_duration_min']} min")
    c4.metric(
        tr("online_offline"),
        f"{summary['online_segments']}/{summary['offline_segments']}",
    )

    for warning in plan["warnings"]:
        st.warning(warning)

    st.markdown(f"#### {tr('segments')}")
    for seg in plan["segments"]:
        steps = " / ".join(seg["steps"][:3]) if seg["steps"] else tr("no_steps")
        cache_hint = f" · {tr('cached')}" if seg.get("cached") else ""
        estimate_hint = f" · {tr('estimated')}" if seg.get("estimated") else ""
        provider_hint = (
            f" · {seg.get('provider')}/{seg.get('provider_version')}"
            if seg.get("provider")
            else ""
        )
        st.markdown(
            f"**{seg['index']}. {seg['from']} → {seg['to']}**  \n"
            f"{seg['mode']} · {seg['distance_km']} km · {seg['duration_min']} min"
            f"{estimate_hint}{cache_hint}{provider_hint}  \n"
            f"{steps}"
        )


def calculate_map_view(points: list[dict]) -> dict[str, float]:
    coordinates = [
        (float(point["lon"]), float(point["lat"]))
        for point in points
        if point.get("lon") is not None and point.get("lat") is not None
    ]
    if not coordinates:
        return {"latitude": 35.0, "longitude": 139.0, "zoom": 4.0}

    lons = [coordinate[0] for coordinate in coordinates]
    lats = [coordinate[1] for coordinate in coordinates]
    longitude = (min(lons) + max(lons)) / 2
    latitude = (min(lats) + max(lats)) / 2
    if len(coordinates) == 1:
        return {"latitude": latitude, "longitude": longitude, "zoom": 14.0}

    lon_span = max(lons) - min(lons)
    lat_span = max(lats) - min(lats)
    effective_span = max(lon_span, lat_span * 1.6, 0.002)
    zoom = max(3.0, min(15.0, math.log2(360 / effective_span) - 1.2))
    return {"latitude": latitude, "longitude": longitude, "zoom": zoom}


def build_map_paths(
    points: list[dict],
    routes: list[dict],
    locale: str = "zh_CN",
) -> list[dict]:
    paths = []
    for index, route in enumerate(routes):
        if index + 1 >= len(points):
            break
        polyline = route.get("polyline") or []
        has_real_geometry = route.get("type") != "offline" and len(polyline) >= 2
        if len(polyline) < 2:
            polyline = [
                [float(points[index]["lon"]), float(points[index]["lat"])],
                [float(points[index + 1]["lon"]), float(points[index + 1]["lat"])],
            ]

        if route.get("type") == "offline":
            color = [255, 105, 135]
            label = {
                "en_US": "Offline straight-line estimate",
                "ja_JP": "オフライン直線推定",
            }.get(locale, "离线估算直线")
            geometry = "estimated"
        elif has_real_geometry:
            color = [65, 137, 230]
            label = {
                "en_US": "Online provider route",
                "ja_JP": "オンライン実経路",
            }.get(locale, "在线真实路径")
            geometry = "provider_polyline"
        else:
            color = [246, 180, 65]
            label = {
                "en_US": "Online result without route geometry",
                "ja_JP": "経路形状のないオンライン結果",
            }.get(locale, "在线结果（无路径几何，直线连接）")
            geometry = "online_without_polyline"
        paths.append(
            {
                "path": polyline,
                "color": color,
                "label": label,
                "geometry": geometry,
            }
        )
    return paths


def _render_map(points: list[dict], routes: list[dict]) -> None:
    map_points = [(float(point["lon"]), float(point["lat"])) for point in points]
    if not map_points:
        return

    st.divider()
    view = calculate_map_view(points)
    path_data = build_map_paths(points, routes, current_locale())
    scatter_data = [
        {
            "position": [point[0], point[1]],
            "name": points[idx].get("cn")
            or points[idx].get("name", tr("unknown_location")),
        }
        for idx, point in enumerate(map_points)
    ]

    st.pydeck_chart(pdk.Deck(
        map_style=pdk.map_styles.CARTO_DARK,
        parameters={"clearColor": [8, 11, 28, 255]},
        initial_view_state=pdk.ViewState(
            latitude=view["latitude"],
            longitude=view["longitude"],
            zoom=view["zoom"],
                pitch=32,
                bearing=-8,
        ),
        layers=[
            pdk.Layer(
                "PathLayer",
                data=path_data,
                pickable=True,
                get_path="path",
                get_color="color",
                width_scale=20,
                width_min_pixels=3,
            ),
            pdk.Layer(
                "ScatterplotLayer",
                data=scatter_data,
                get_position="position",
                get_color=[255, 112, 166],
                get_line_color=[255, 255, 255],
                stroked=True,
                line_width_min_pixels=2,
                get_radius=120,
                radius_min_pixels=7,
                radius_max_pixels=18,
            ),
        ],
        tooltip={"text": "{name}{label}"},
    ))
    st.caption(tr("map_legend"))


def _render_album(points: list[dict]) -> None:
    images = [
        {"name": point.get("cn") or point.get("name", "圣地"), "src": point.get("image") or point.get("img")}
        for point in points
        if point.get("image") or point.get("img")
    ]
    if not images:
        return

    st.markdown(f"##### {tr('album')}")
    cols = st.columns(len(images) if len(images) <= 4 else 4)
    for idx, image in enumerate(images[:4]):
        with cols[idx]:
            st.image(image["src"], caption=image["name"], use_container_width=True)


def _render_guide(plan: dict, dashscope_key: str) -> None:
    st.divider()
    st.markdown(f"### {tr('facts')}")
    st.caption(tr("facts_help"))
    facts_markdown = plan.get("facts_markdown") or ali_ai.render_tour_facts_markdown(
        plan.get("points", []),
        plan.get("routes", []),
        locale=current_locale(),
    )
    st.markdown(facts_markdown)

    guide_text = plan.get("guide_text")
    if guide_text:
        st.markdown(f"### {tr('ai_guide')}")
        st.markdown(guide_text)
        return

    if not dashscope_key:
        st.info(tr("ai_key_help"))
        return

    if st.button(tr("ai_only"), key="generate_ai_guide"):
        with st.spinner(tr("ai_generating")):
            plan["guide_text"] = clean_markdown_output(
                ali_ai.generate_tour_guide_text(
                    plan.get("points", []),
                    plan.get("routes", []),
                    api_key=dashscope_key,
                    locale=current_locale(),
                )
            )
        st.session_state["planned_routes"] = plan
        st.rerun()
