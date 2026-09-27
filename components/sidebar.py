import html
import os

import streamlit as st

from components.i18n import LANGUAGE_OPTIONS, current_locale, tr
from components.state import MAX_ITINERARY_ITEMS


def render_sidebar() -> tuple[str, str]:
    with st.sidebar:
        locale = current_locale()
        st.markdown(
            f"""
<div class="sidebar-brand">
    <div class="sidebar-brand__mark">A<span>W</span></div>
    <div>
        <div class="sidebar-brand__kicker">{tr("sidebar_kicker", locale=locale)}</div>
        <div class="sidebar-brand__title">{tr("sidebar_title", locale=locale)}</div>
    </div>
</div>
""",
            unsafe_allow_html=True,
        )

        labels_by_locale = {value: label for label, value in LANGUAGE_OPTIONS.items()}
        st.selectbox(
            tr("language", locale=locale),
            options=list(labels_by_locale),
            format_func=labels_by_locale.get,
            key="locale",
        )

        st.markdown(f"#### {tr('connect_title', locale=locale)}")
        st.caption(tr("connect_help", locale=locale))
        dashscope_key_input = st.text_input("DashScope / Qwen API Key", type="password", key="dashscope_key")
        amap_key_input = st.text_input("高德 Web 服务 API Key", type="password", key="amap_key")
        st.caption(tr("connect_note", locale=locale))

        amap_key = amap_key_input.strip() if amap_key_input else ""
        dashscope_key = str(dashscope_key_input).strip() if dashscope_key_input else ""
        if not amap_key:
            amap_key = os.getenv("AMAP_API_KEY", "").strip()
        if not dashscope_key:
            dashscope_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        if os.getenv("DASHSCOPE_API_KEY") and not st.session_state.get("dashscope_key"):
            st.caption(tr("server_key"))

        st.divider()
        with st.expander(f"巡礼背包 · {len(st.session_state['itinerary'])}/{MAX_ITINERARY_ITEMS}", expanded=bool(st.session_state["itinerary"])):
            if st.session_state["itinerary"]:
                for idx, item in enumerate(st.session_state["itinerary"], start=1):
                    name = html.escape(str(item.get("cn") or item.get("name") or "—"))
                    anime = html.escape(str(item.get("_anime_name") or tr("unknown_anime")))
                    st.markdown(
                        f'<div class="bag-item"><b>{idx:02d}</b><span>{name}<small>{anime}</small></span></div>',
                        unsafe_allow_html=True,
                    )
                st.success(tr("bag_ready"))
            else:
                st.caption(tr("bag_empty"))

        st.markdown(
            '<div class="sidebar-footer"><span class="signal-dot"></span>'
            "ANIMEWAY · TOKYO PILOT<br><small>作品 · 地点 · 路书 · 记录</small></div>",
            unsafe_allow_html=True,
        )

    return amap_key, dashscope_key
