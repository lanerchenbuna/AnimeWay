import streamlit as st
import re

from components.i18n import current_locale, tr
from components.state import (
    ITEMS_PER_PAGE,
    MAX_ITINERARY_ITEMS,
    add_to_itinerary,
    append_message,
    save_feedback,
)
from components.ui import render_agent_intro, render_anime_card
from utils import amap
from core.pilot import normalize_legacy_points


def render_discover(agent, retriever, amap_key: str, dashscope_key: str, catalog=None, *, store=None, token=None, route_planner=None) -> None:
    st.markdown(
        render_agent_intro(qwen_ready=bool(dashscope_key), amap_ready=bool(amap_key), locale=current_locale()),
        unsafe_allow_html=True,
    )

    for index, msg in enumerate(st.session_state["messages"]):
        _render_chat_message(msg, index, store=store, token=token, catalog=catalog)

    st.markdown(f"### {tr('starter_title')}")
    st.caption(tr("starter_help"))
    examples = [
        ("routebook", "生成东京《孤独摇滚！》一日轻松巡礼路书", "帮我规划东京《孤独摇滚！》一日轻松巡礼路书"),
        ("anime", tr("example_anime"), "孤独摇滚圣地"),
        ("city", tr("example_city"), "京都有什么动画圣地"),
        ("theme", tr("example_theme"), "咖啡店巡礼"),
    ]
    with st.container(key="aw_agent_examples"):
        for row in range(0, len(examples), 2):
            example_cols = st.columns(2)
            for column, (example_id, label, query) in zip(example_cols, examples[row:row + 2]):
                with column:
                    if st.button(label, key=f"example_{example_id}", width="stretch"):
                        with st.spinner(tr("searching")):
                            _handle_prompt(query, agent, dashscope_key, catalog, amap_key=amap_key,
                                           store=store, token=token, route_planner=route_planner)
                        st.rerun()

    prompt = st.chat_input(tr("chat_placeholder"))
    if prompt:
        with st.spinner(tr("searching")):
            _handle_prompt(prompt, agent, dashscope_key, catalog, amap_key=amap_key,
                           store=store, token=token, route_planner=route_planner)
        st.rerun()

    _render_candidates(retriever, catalog)
    _render_search_results(amap_key, catalog)


def _handle_prompt(prompt: str, agent, dashscope_key: str, catalog=None, *, amap_key="", store=None, token=None, route_planner=None) -> None:
    history = [
        {"role": message.get("role", "user"), "content": message.get("content", "")}
        for message in st.session_state["messages"]
    ]
    append_message("user", prompt)
    if re.search(r"路书|规划.{0,8}(行程|路线)|安排.{0,8}(行程|巡礼)|巡礼.{0,8}(路线|行程)|生成.{0,8}(路线|行程)|行程规划", prompt):
        if not dashscope_key:
            result = {"mode": "answer", "response": "生成智能路书需要 DashScope / Qwen API Key。请在左侧 DashScope Key 中填写后，再告诉我作品、日期和旅行节奏。"}
        elif not token or not store or not route_planner or not catalog:
            result = {"mode": "answer", "response": "本地身份或路线服务尚未就绪，请刷新页面后重试。"}
        else:
            try:
                from core.pilgrimage_agent import generate_routebook
                with st.spinner("Qwen 正在理解需求并筛选圣地，高德正在计算分段路线…"):
                    preview = generate_routebook(prompt, store=store, token=token, catalog=catalog,
                                                 qwen_key=dashscope_key, amap_key=amap_key,
                                                 route_planner=route_planner, locale=current_locale())
                result = {"mode": "routebook", "response": "我已经根据作品资料生成一份可核查的巡礼路书草案。你可以先查看地点、场景图和交通段，再保存为个人 Trip。",
                          "trip_preview": preview}
            except (ValueError, OSError) as exc:
                result = {"mode": "answer", "response": f"这次没有生成可用路书：{exc}\n\n你可以补充作品名、东京出发日期或缩短天数后重试。"}
    else:
        result = agent.run(prompt, api_key=dashscope_key, history=history)
    query = result.get("query", prompt)
    mode = result.get("mode", "answer")

    if mode == "recommendation":
        _apply_candidates(result.get("candidates", []), is_recommendation=True, query=query)
        names = result.get("recommendations", [])
        content = tr("recommend_found", names=", ".join(names)) if names else tr("recommend_empty")
    elif mode == "search_candidates":
        candidates = result.get("candidates", [])
        _apply_candidates(candidates, is_recommendation=False, query=query)
        content = tr("candidates_found", count=len(candidates))
    elif mode == "search_spots":
        spots = normalize_legacy_points(result.get("spots", []), catalog)
        st.session_state["search_candidates"] = []
        st.session_state["search_results"] = spots
        st.session_state["current_anime"] = f"地点/主题搜索：{query}"
        st.session_state["page"] = 0
        content = tr("spots_found", count=len(spots))
    elif mode == "empty":
        st.session_state["search_candidates"] = []
        st.session_state["search_results"] = []
        st.session_state["current_anime"] = None
        content = tr("empty_result")
    else:
        content = result.get("response") or tr("answer_empty")

    append_message(
        "assistant",
        content,
        structured_result=_compact_result(result, prompt),
        retrieval_context=_summarize_context(result.get("context", [])),
    )


def _compact_result(result: dict, user_query: str) -> dict:
    return {
        "intent": result.get("intent"),
        "mode": result.get("mode", "answer"),
        "query": result.get("query", user_query),
        "user_query": user_query,
        "candidates": result.get("candidates", []),
        "spots": result.get("spots", []),
        "recommendations": result.get("recommendations", []),
        "thought": result.get("thought", ""),
        "requires_api_key": bool(result.get("requires_api_key")),
        "trip_preview": result.get("trip_preview"),
        "locale": current_locale(),
    }


def _summarize_context(context: list[dict]) -> list[dict]:
    return [
        {
            "anime_id": item.get("anime_id"),
            "anime": item.get("meta", {}).get("titles", {}).get("cn"),
            "spots_count": len(item.get("spots", [])),
        }
        for item in context[:5]
    ]


def _render_chat_message(message: dict, index: int, *, store=None, token=None, catalog=None) -> None:
    role = message.get("role", "assistant")
    with st.chat_message(role):
        st.markdown(message.get("content", ""))
        if role != "assistant":
            return

        structured = message.get("structured_result") or {}
        if structured.get("mode") == "routebook" and structured.get("trip_preview"):
            _render_routebook(structured["trip_preview"], message.get("message_id") or f"routebook_{index}",
                              store=store, token=token, catalog=catalog)
        thought = structured.get("thought")
        context = message.get("retrieval_context") or []
        if thought or context:
            with st.expander(tr("trace"), expanded=False):
                if thought:
                    st.markdown(f"**{thought}**")
                if context:
                    st.json(context)

        if structured.get("mode") != "answer":
            return

        message_id = message.get("message_id") or f"legacy_{index}"
        feedback = message.get("feedback")
        col_up, col_down, _ = st.columns([1, 1, 8])
        with col_up:
            if st.button("👍", key=f"fb_up_{message_id}", disabled=feedback is not None):
                save_feedback(
                    structured.get("user_query", ""),
                    message.get("content", ""),
                    True,
                    message_id=message_id,
                )
                st.rerun()
        with col_down:
            if st.button("👎", key=f"fb_down_{message_id}", disabled=feedback is not None):
                save_feedback(
                    structured.get("user_query", ""),
                    message.get("content", ""),
                    False,
                    message_id=message_id,
                )
                st.rerun()
        if feedback is not None:
            st.caption(tr("feedback_saved", icon="👍" if feedback else "👎"))


def _render_routebook(preview: dict, message_id: str, *, store=None, token=None, catalog=None) -> None:
    from components.map_explorer import _scene_image
    from components.plan import _render_map
    from core.trip import clock, evaluate
    from data_factory.normalization import safe_url

    catalog = catalog or {}
    locations = {point["id"]: point for point in catalog.get("locations", [])}
    scenes = {scene["id"]: scene for scene in catalog.get("scenes", [])}
    plan = preview["plan"]
    access_labels = {"public": "公共区域", "open": "可访问", "restricted": "访问受限",
                     "unknown": "访问待核查", "closed": "暂时关闭", "prohibited": "禁止进入"}
    st.markdown("#### ✦ AnimeWay 巡礼路书")
    st.caption(f"{plan['requirements']['title']} · {plan['requirements']['start_date']} · {plan['requirements']['day_count']} 天 · 日本时间")
    checks = evaluate(plan, catalog)
    if checks["issues"]:
        with st.expander(f"行前核查：{len(checks['issues'])} 项提醒", expanded=False):
            for issue in checks["issues"][:12]:
                st.write(f"{issue['date']} · {issue['message']}")
    for day_index, day in enumerate(preview.get("days", [])):
        st.markdown(f"### {day['date']} · {clock(day['start_min'])}—{clock(day['end_min'])}")
        points = [locations[key] for key in day["location_ids"] if key in locations]
        planned_stops = {stop["location_id"]: stop for stop in plan["days"][day_index]["stops"]}
        route = day.get("route", {})
        segments = route.get("segments", [])
        eta = day["start_min"]
        for number, point in enumerate(points, 1):
            segment = segments[number - 2] if number > 1 and number - 2 < len(segments) else None
            if segment:
                eta += int(segment.get("duration_min", 0) or 0)
            stay = int(planned_stops.get(point["id"], {}).get("stay_min", 25))
            with st.container(border=True):
                scene = next((scenes[key] for key in point.get("scene_ids", []) if key in scenes), None)
                media, details = st.columns([1, 2.3], gap="medium")
                with media:
                    if scene:
                        _scene_image(scene, width=240)
                    else:
                        st.caption("该地点暂无可展示的场景图")
                with details:
                    st.markdown(f"**{number:02d} · {point['name']}**")
                    st.caption(f"参考到达 {clock(eta)} · 停留 {stay} 分钟")
                    access = point.get("access") or {}
                    status = access.get("status", "unknown")
                    st.caption(f"{point.get('city') or '东京'} · {access_labels.get(status, '访问待核查')}")
                    summary = access.get("summary")
                    if summary:
                        st.write(summary)
                    source = safe_url(point.get("source_url"))
                    if source:
                        st.markdown(f"[核查地点来源 ↗]({source})")
            eta += stay
        st.caption("到达时间仅累计列出的站间移动与停留；起终点交通、用餐、排队及现场变化需另行确认。")
        summary = route.get("summary", {})
        if summary:
            a, b, c = st.columns(3)
            a.metric("路段距离", f"{summary.get('total_distance_km', 0)} km")
            b.metric("移动时间", f"{summary.get('total_duration_min', 0)} 分钟")
            c.metric("在线 / 估算", f"{summary.get('online_segments', 0)} / {summary.get('offline_segments', 0)}")
        if len(points) > 1:
            _render_map(points, route.get("routes", []))
        if segments:
            with st.expander(f"查看 {len(segments)} 段交通与导航说明"):
                for segment in segments:
                    steps = "；".join(segment.get("steps", [])[:4]) or "未返回详细导航步骤"
                    status = "离线估算" if segment.get("estimated") else "高德路线"
                    st.write(f"**{segment['index']}. {segment['from']} → {segment['to']}** · {segment['mode']} · {segment['distance_km']} km · {segment['duration_min']} 分钟 · {status}")
                    st.caption(steps)
    for warning in preview.get("warnings", []):
        st.warning(warning)
    if preview.get("guide"):
        with st.expander("路书依据与使用提醒"):
            st.markdown(preview["guide"])
    saved_key = "aw_agent_saved_" + message_id
    if st.session_state.get(saved_key):
        st.success("已保存为个人 Trip 草案")
    elif st.button("保存为我的个人 Trip", key="aw_agent_save_" + message_id, type="primary", disabled=not store or not token):
        try:
            archive = store.create_personal_trip(token, plan)
            st.session_state[saved_key] = archive["id"]
            st.success("已保存为个人 Trip 草案")
        except (ValueError, OSError) as exc:
            st.error(str(exc))


def _apply_candidates(candidates: list[dict], is_recommendation: bool, query: str) -> None:
    st.session_state["search_candidates"] = candidates
    st.session_state["search_results"] = []
    st.session_state["current_anime"] = None
    st.session_state["is_rec_result"] = is_recommendation
    st.session_state["last_rec_query"] = query


def _render_candidates(retriever, catalog=None) -> None:
    if not st.session_state.get("search_candidates") or st.session_state.get("search_results"):
        return

    st.markdown(f"### {tr('choose_anime')}")
    cols = st.columns(3)
    for idx, candidate in enumerate(st.session_state["search_candidates"][:20]):
        with cols[idx % 3]:
            image = candidate.get("image") or "https://via.placeholder.com/300x160.png?text=No+Cover"
            st.image(image, width="stretch")
            st.markdown(f"**{candidate['cn']}**")
            st.caption(candidate["summary"])

            if st.button(
                tr("expand_spots"),
                key=f"sel_{candidate['id']}_{idx}",
                help=tr("loading_spots", name=candidate["cn"]),
                width="stretch",
            ):
                with st.status(tr("loading_spots", name=candidate["cn"])):
                    raw_points = normalize_legacy_points(retriever.get_spots_by_anime_id(candidate["id"]), catalog)
                    if raw_points:
                        st.session_state["search_results"] = [
                            {
                                **dict(point),
                                "_anime_name": candidate["cn"],
                                "_city": point.get("city") or tr("unknown_city"),
                            }
                            for point in raw_points
                        ]
                        st.session_state["current_anime"] = candidate["cn"]
                        st.session_state["page"] = 0
                        st.session_state["search_candidates"] = []
                        st.rerun()
                    else:
                        st.error(tr("no_spots"))


def _render_search_results(amap_key: str, catalog=None) -> None:
    if catalog is not None:
        st.session_state["search_results"] = [p for p in normalize_legacy_points(st.session_state.get("search_results", []), catalog)
            if not p.get("withdrawn") and (p.get("access") or {}).get("status") not in {"closed", "prohibited"}]
    if not st.session_state["search_results"]:
        return

    st.divider()
    back_col, title_col = st.columns([1, 4])
    with back_col:
        if st.button(tr("back"), type="secondary"):
            st.session_state["search_results"] = []
            st.session_state["current_anime"] = None
            st.rerun()

    total = len(st.session_state["search_results"])
    with title_col:
        st.markdown(
            f"### {tr('result_count', name=st.session_state['current_anime'], count=total)}"
        )

    start = st.session_state["page"] * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    for point in st.session_state["search_results"][start:end]:
        _enrich_city(point, amap_key)
        st.markdown(render_anime_card(point, current_locale()), unsafe_allow_html=True)
        _, button_col = st.columns([4, 1])
        with button_col:
            backpack_full = len(st.session_state["itinerary"]) >= MAX_ITINERARY_ITEMS
            if st.button(
                tr("bag_full") if backpack_full else tr("add_bag"),
                key=f"add_{point['id']}_p{st.session_state['page']}",
                disabled=backpack_full,
            ):
                add_to_itinerary(point, point.get("_anime_name"))

    if total > ITEMS_PER_PAGE:
        prev_col, page_col, next_col = st.columns([1, 2, 1])
        with prev_col:
            if st.session_state["page"] > 0 and st.button(tr("prev"), key="pg_prev"):
                st.session_state["page"] -= 1
                st.rerun()
        with page_col:
            st.markdown(
                "<center>"
                + tr(
                    "page",
                    current=st.session_state["page"] + 1,
                    total=((total - 1) // ITEMS_PER_PAGE) + 1,
                )
                + "</center>",
                unsafe_allow_html=True,
            )
        with next_col:
            if end < total and st.button(tr("next"), key="pg_next"):
                st.session_state["page"] += 1
                st.rerun()


def _enrich_city(point: dict, amap_key: str) -> None:
    if point.get("_city") and point.get("_city") not in ["Unknown", "Unknown City", ""]:
        return
    if not amap_key:
        point["_city"] = point.get("city") or "Unknown City"
        return

    try:
        city_code = amap.get_regeo_city(point["lon"], point["lat"], amap_key)
        if city_code:
            address = amap.get_address_from_coords(point["lon"], point["lat"], amap_key)
            point["_city"] = address.split("市")[0] + "市" if "市" in address else point.get("city") or "Unknown City"
    except Exception:
        point["_city"] = point.get("city") or "Unknown City"
