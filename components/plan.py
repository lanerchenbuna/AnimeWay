import pydeck as pdk
import streamlit as st

from components.state import clean_markdown_output, remove_from_itinerary
from utils import ali_ai


def render_plan(route_planner, amap_key: str, dashscope_key: str) -> None:
    st.markdown("## 冒险之书")
    enable_tsp = st.checkbox("智能路线优化（TSP）", value=True)

    if not st.session_state["itinerary"]:
        st.info("背包里还没有地点。先去发现页收集圣地。")
        return

    _render_itinerary()
    start_addr = st.text_input("出发地", placeholder="可选，例如：秋叶原站")

    if st.button("生成路线预览与路书", type="primary", use_container_width=True):
        _generate_plan(route_planner, start_addr, amap_key, dashscope_key, enable_tsp)


def _render_itinerary() -> None:
    for idx, item in enumerate(st.session_state["itinerary"]):
        c1, c2, c3 = st.columns([0.5, 3, 1])
        with c1:
            st.markdown(f"### {idx + 1}")
        with c2:
            st.markdown(f"**{item.get('spot_name') or item.get('name') or '未知地点'}**")
            st.caption(item.get("_anime_name") or "未知动画")
        with c3:
            if st.button("移除", key=f"del_{idx}"):
                remove_from_itinerary(idx)
        st.divider()


def _generate_plan(route_planner, start_addr: str, amap_key: str, dashscope_key: str, enable_tsp: bool) -> None:
    with st.spinner("正在生成路线预览..."):
        plan = route_planner.plan(
            list(st.session_state["itinerary"]),
            start_addr=start_addr.strip(),
            amap_key=amap_key,
            enable_tsp=enable_tsp,
        )

    points = plan["points"]
    routes = plan["routes"]
    st.session_state["optimized_points"] = points
    st.session_state["planned_routes"] = plan

    _render_summary(plan)
    _render_map(points)
    _render_album(points)
    _render_guide(points, routes, dashscope_key)


def _render_summary(plan: dict) -> None:
    st.divider()
    st.markdown("### 路线摘要")
    summary = plan["summary"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("站点", summary["stop_count"])
    c2.metric("距离", f"{summary['total_distance_km']} km")
    c3.metric("预计耗时", f"{summary['total_duration_min']} min")
    c4.metric("在线/离线", f"{summary['online_segments']}/{summary['offline_segments']}")

    for warning in plan["warnings"]:
        st.warning(warning)

    st.markdown("#### 分段明细")
    for seg in plan["segments"]:
        steps = " / ".join(seg["steps"][:3]) if seg["steps"] else "暂无步骤"
        cache_hint = " · 已缓存" if seg.get("cached") else ""
        st.markdown(
            f"**{seg['index']}. {seg['from']} → {seg['to']}**  \n"
            f"{seg['mode']} · {seg['distance_km']} km · {seg['duration_min']} min{cache_hint}  \n"
            f"{steps}"
        )


def _render_map(points: list[dict]) -> None:
    map_points = [(float(point["lon"]), float(point["lat"])) for point in points]
    if not map_points:
        return

    st.divider()
    mid_lat = sum(point[1] for point in map_points) / len(map_points)
    mid_lon = sum(point[0] for point in map_points) / len(map_points)
    path_data = [{"path": [[point[0], point[1]] for point in map_points], "color": [255, 126, 179]}]
    scatter_data = [
        {"position": [point[0], point[1]], "name": points[idx].get("cn") or points[idx].get("name", "圣地")}
        for idx, point in enumerate(map_points)
    ]

    st.pydeck_chart(pdk.Deck(
        map_style=None,
        initial_view_state=pdk.ViewState(latitude=mid_lat, longitude=mid_lon, zoom=11, pitch=0),
        layers=[
            pdk.Layer("PathLayer", data=path_data, pickable=True, get_path="path", get_color="color", width_scale=20, width_min_pixels=2),
            pdk.Layer("ScatterplotLayer", data=scatter_data, get_position="position", get_color=[122, 175, 255], get_radius=200),
        ],
        tooltip={"text": "{name}"},
    ))


def _render_album(points: list[dict]) -> None:
    images = [
        {"name": point.get("cn") or point.get("name", "圣地"), "src": point.get("image") or point.get("img")}
        for point in points
        if point.get("image") or point.get("img")
    ]
    if not images:
        return

    st.markdown("##### 巡礼相册")
    cols = st.columns(len(images) if len(images) <= 4 else 4)
    for idx, image in enumerate(images[:4]):
        with cols[idx]:
            st.image(image["src"], caption=image["name"], use_container_width=True)


def _render_guide(points: list[dict], routes: list[dict], dashscope_key: str) -> None:
    st.divider()
    if not dashscope_key:
        st.info("已生成路线预览。填写 DashScope Key 后，可继续生成 AI 路书文案。")
        return

    ali_ai.dashscope.api_key = dashscope_key
    with st.spinner("AI 导游正在生成路书..."):
        text = clean_markdown_output(ali_ai.generate_tour_guide_text(points, routes))
    st.markdown("### 您的冒险之书")
    st.markdown(text)
