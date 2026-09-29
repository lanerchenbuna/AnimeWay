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


def render_discover(agent, retriever, amap_key: str, dashscope_key: str, catalog=None, *, store=None, token=None) -> None:
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
                                           store=store, token=token)
                        st.rerun()

    prompt = st.chat_input(tr("chat_placeholder"))
    if prompt:
        with st.spinner(tr("searching")):
            _handle_prompt(prompt, agent, dashscope_key, catalog, amap_key=amap_key,
                           store=store, token=token)
        st.rerun()

    _render_candidates(retriever, catalog)
    _render_search_results(amap_key, catalog)


def _handle_prompt(prompt: str, agent, dashscope_key: str, catalog=None, *, amap_key="", store=None, token=None) -> None:
    history = [
        {"role": message.get("role", "user"), "content": message.get("content", "")}
        for message in st.session_state["messages"]
    ]
    append_message("user", prompt)
    if re.search(r"路书|规划.{0,8}(行程|路线)|安排.{0,8}(行程|巡礼)|巡礼.{0,8}(路线|行程)|生成.{0,8}(路线|行程)|行程规划", prompt):
        if not dashscope_key:
            result = {"mode": "answer", "response": "生成智能路书需要 DashScope / Qwen API Key。请在左侧 DashScope Key 中填写后，再告诉我作品、日期和旅行节奏。"}
        elif not token or not store or not catalog:
            result = {"mode": "answer", "response": "本地身份或地点资料尚未就绪，请刷新页面后重试。"}
        else:
            try:
                from core.pilgrimage_agent import generate_routebook
                with st.spinner("Qwen 正在筛选地点，系统正在统一评估交通与时间…"):
                    preview = generate_routebook(prompt, store=store, token=token, catalog=catalog,
                                                 qwen_key=dashscope_key)
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
    from components.map_trip import open_handbook
    from components.trip_planner import render_draft_preview

    catalog = catalog or {}
    plan = preview["plan"]
    st.markdown("#### ✦ AnimeWay 巡礼路书草案")
    st.write(plan["requirements"]["title"])
    render_draft_preview(plan, catalog)
    if preview.get("guide"):
        st.caption(preview["guide"])
    draft_key = "aw_agent_draft_" + message_id
    draft_id = st.session_state.get(draft_key)
    if draft_id and store and token and not store.get_personal_draft(token, draft_id):
        st.session_state.pop(draft_key, None)
        draft_id = None
    if draft_id:
        st.success("已加入未保存草案，可在 Trip 编辑器继续修改并正式保存。")
        if st.button("继续修改这份草案", key="aw_agent_open_" + message_id):
            open_handbook("personal", awp_mode="draft", awp_draft_id=draft_id)
    elif st.button("进入行程编辑器查看与修改", key="aw_agent_draft_button_" + message_id,
                   type="primary", disabled=not store or not token):
        try:
            draft = store.create_personal_draft(token, plan, "routebook")
            st.session_state[draft_key] = draft["id"]
            open_handbook("personal", awp_mode="draft", awp_draft_id=draft["id"])
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
