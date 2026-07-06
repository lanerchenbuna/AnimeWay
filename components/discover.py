import time

import streamlit as st

from components.state import ITEMS_PER_PAGE, add_to_itinerary, save_feedback
from components.ui import render_agent_status, render_anime_card
from core.agent import AnimeRagAgent
from utils import amap


def render_discover(agent, retriever, amap_key: str, dashscope_key: str) -> None:
    st.markdown("### 次元观测者")
    st.info("输入作品、地点或氛围，例如：孤独摇滚圣地、京都有什么动画圣地、咖啡店巡礼。")

    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    prompt = st.chat_input("输入你的巡礼需求")
    if prompt:
        _handle_prompt(prompt, agent, retriever, dashscope_key)

    _render_candidates(retriever)
    _render_search_results(amap_key)


def _handle_prompt(prompt: str, agent, retriever, dashscope_key: str) -> None:
    if not dashscope_key:
        st.error("需要 DashScope Key 才能启动对话与推荐。")
        return

    with st.chat_message("user"):
        st.write(prompt)
    st.session_state["messages"].append({"role": "user", "content": prompt})

    if "rag_agent" not in st.session_state:
        st.session_state["rag_agent"] = AnimeRagAgent(retriever=retriever)

    result = st.session_state["rag_agent"].run(prompt, api_key=dashscope_key, history=st.session_state["messages"])
    query = result.get("query", prompt)
    mode = result.get("mode", "answer")

    with st.chat_message("assistant"):
        if mode == "recommendation":
            _apply_candidates(result.get("candidates", []), is_recommendation=True, query=query)
            names = result.get("recommendations", [])
            if names:
                st.write(f"推荐作品：{', '.join(names)}")
        elif mode == "search_candidates":
            st.markdown(render_agent_status("searching", f"搜索作品：{query}"), unsafe_allow_html=True)
            _apply_candidates(result.get("candidates", []), is_recommendation=False, query=query)
        elif mode == "search_spots":
            spots = result.get("spots", [])
            st.session_state["search_candidates"] = []
            st.session_state["search_results"] = spots
            st.session_state["current_anime"] = f"地点/主题搜索：{query}"
            st.session_state["page"] = 0
            st.success(f"找到 {len(spots)} 个相关地点。")
        elif mode == "empty":
            st.session_state["search_candidates"] = []
            st.session_state["search_results"] = []
            st.session_state["current_anime"] = None
            st.warning("知识库里暂时没有匹配结果。")
        else:
            _render_agent_answer(prompt, result)


def _apply_candidates(candidates: list[dict], is_recommendation: bool, query: str) -> None:
    st.session_state["search_candidates"] = candidates
    st.session_state["search_results"] = []
    st.session_state["current_anime"] = None
    st.session_state["is_rec_result"] = is_recommendation
    st.session_state["last_rec_query"] = query
    if candidates:
        st.success(f"找到 {len(candidates)} 个候选作品。")
    else:
        st.warning("未找到可展开的作品候选。")


def _render_agent_answer(prompt: str, result: dict) -> None:
    response = result.get("response", "没有生成回答。")
    thought = result.get("thought", "")
    context = result.get("context", [])
    with st.expander("检索轨迹", expanded=False):
        st.markdown(f"**{thought}**")
        st.json([
            {
                "anime": item.get("meta", {}).get("titles", {}).get("cn"),
                "spots_count": len(item.get("spots", [])),
            }
            for item in context[:5]
        ])
    st.markdown("### 回答")
    st.markdown(response)

    col_up, col_down, _ = st.columns([1, 1, 8])
    with col_up:
        if st.button("👍", key=f"fb_up_{int(time.time())}"):
            save_feedback(prompt, response, True)
    with col_down:
        if st.button("👎", key=f"fb_down_{int(time.time())}"):
            save_feedback(prompt, response, False)


def _render_candidates(retriever) -> None:
    if not st.session_state.get("search_candidates") or st.session_state.get("search_results"):
        return

    st.markdown("### 选择作品")
    cols = st.columns(3)
    for idx, candidate in enumerate(st.session_state["search_candidates"][:20]):
        with cols[idx % 3]:
            image = candidate.get("image") or "https://via.placeholder.com/300x160.png?text=No+Cover"
            st.image(image, use_container_width=True)
            st.markdown(f"**{candidate['cn']}**")
            st.caption(candidate["summary"])

            if st.button("展开圣地", key=f"sel_{candidate['id']}_{idx}", help=f"查看 {candidate['cn']} 的圣地"):
                with st.status(f"正在读取 {candidate['cn']} 的地点..."):
                    raw_points = retriever.get_spots_by_anime_id(candidate["id"])
                    if raw_points:
                        st.session_state["search_results"] = [
                            {**dict(point), "_anime_name": candidate["cn"], "_city": point.get("city") or "Unknown"}
                            for point in raw_points
                        ]
                        st.session_state["current_anime"] = candidate["cn"]
                        st.session_state["page"] = 0
                        st.session_state["search_candidates"] = []
                        st.rerun()
                    else:
                        st.error("这个作品暂时没有圣地数据。")


def _render_search_results(amap_key: str) -> None:
    if not st.session_state["search_results"]:
        return

    st.divider()
    back_col, title_col = st.columns([1, 4])
    with back_col:
        if st.button("返回", type="secondary"):
            st.session_state["search_results"] = []
            st.session_state["current_anime"] = None
            st.rerun()

    total = len(st.session_state["search_results"])
    with title_col:
        st.markdown(f"### {st.session_state['current_anime']}（{total} 个地点）")

    start = st.session_state["page"] * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    for point in st.session_state["search_results"][start:end]:
        _enrich_city(point, amap_key)
        st.markdown(render_anime_card(point), unsafe_allow_html=True)
        _, button_col = st.columns([4, 1])
        with button_col:
            if st.button("加入背包", key=f"add_{point['id']}_p{st.session_state['page']}"):
                add_to_itinerary(point, point.get("_anime_name"))

    if total > ITEMS_PER_PAGE:
        prev_col, page_col, next_col = st.columns([1, 2, 1])
        with prev_col:
            if st.session_state["page"] > 0 and st.button("上一页", key="pg_prev"):
                st.session_state["page"] -= 1
                st.rerun()
        with page_col:
            st.markdown(f"<center>第 {st.session_state['page'] + 1} / {((total - 1) // ITEMS_PER_PAGE) + 1} 页</center>", unsafe_allow_html=True)
        with next_col:
            if end < total and st.button("下一页", key="pg_next"):
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
