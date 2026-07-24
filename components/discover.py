import streamlit as st

from components.i18n import current_locale, tr
from components.state import (
    ITEMS_PER_PAGE,
    MAX_ITINERARY_ITEMS,
    add_to_itinerary,
    append_message,
    save_feedback,
)
from components.ui import render_anime_card, render_section_header
from utils import amap


def render_discover(agent, retriever, amap_key: str, dashscope_key: str) -> None:
    st.markdown(
        render_section_header(
            tr("discover_title"),
            tr("discover_kicker"),
            tr("discover_help"),
        ),
        unsafe_allow_html=True,
    )

    for index, msg in enumerate(st.session_state["messages"]):
        _render_chat_message(msg, index)

    st.caption(tr("example_title"))
    examples = [
        ("anime", tr("example_anime"), "孤独摇滚圣地"),
        ("city", tr("example_city"), "京都有什么动画圣地"),
        ("theme", tr("example_theme"), "咖啡店巡礼"),
    ]
    example_cols = st.columns(3)
    for column, (example_id, label, query) in zip(example_cols, examples):
        with column:
            if st.button(label, key=f"example_{example_id}", use_container_width=True):
                with st.spinner(tr("searching")):
                    _handle_prompt(query, agent, dashscope_key)
                st.rerun()

    prompt = st.chat_input(tr("chat_placeholder"))
    if prompt:
        with st.spinner(tr("searching")):
            _handle_prompt(prompt, agent, dashscope_key)
        st.rerun()

    _render_candidates(retriever)
    _render_search_results(amap_key)


def _handle_prompt(prompt: str, agent, dashscope_key: str) -> None:
    history = [
        {"role": message.get("role", "user"), "content": message.get("content", "")}
        for message in st.session_state["messages"]
    ]
    append_message("user", prompt)
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
        spots = result.get("spots", [])
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


def _render_chat_message(message: dict, index: int) -> None:
    role = message.get("role", "assistant")
    with st.chat_message(role):
        st.markdown(message.get("content", ""))
        if role != "assistant":
            return

        structured = message.get("structured_result") or {}
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


def _apply_candidates(candidates: list[dict], is_recommendation: bool, query: str) -> None:
    st.session_state["search_candidates"] = candidates
    st.session_state["search_results"] = []
    st.session_state["current_anime"] = None
    st.session_state["is_rec_result"] = is_recommendation
    st.session_state["last_rec_query"] = query


def _render_candidates(retriever) -> None:
    if not st.session_state.get("search_candidates") or st.session_state.get("search_results"):
        return

    st.markdown(f"### {tr('choose_anime')}")
    cols = st.columns(3)
    for idx, candidate in enumerate(st.session_state["search_candidates"][:20]):
        with cols[idx % 3]:
            image = candidate.get("image") or "https://via.placeholder.com/300x160.png?text=No+Cover"
            st.image(image, use_container_width=True)
            st.markdown(f"**{candidate['cn']}**")
            st.caption(candidate["summary"])

            if st.button(
                tr("expand_spots"),
                key=f"sel_{candidate['id']}_{idx}",
                help=tr("loading_spots", name=candidate["cn"]),
                use_container_width=True,
            ):
                with st.status(tr("loading_spots", name=candidate["cn"])):
                    raw_points = retriever.get_spots_by_anime_id(candidate["id"])
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


def _render_search_results(amap_key: str) -> None:
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
