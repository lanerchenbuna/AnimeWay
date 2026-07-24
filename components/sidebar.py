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

        st.markdown(
            f"""
<div class="bag-status">
    <div class="bag-status__line">
        <span>{tr("bag_count", count=len(st.session_state["itinerary"]), limit=MAX_ITINERARY_ITEMS)}</span>
        <strong>{len(st.session_state["itinerary"]):02d}</strong>
    </div>
    <div class="bag-status__meter"><span style="width:{min(100, len(st.session_state["itinerary"]) / MAX_ITINERARY_ITEMS * 100):.0f}%"></span></div>
</div>
""",
            unsafe_allow_html=True,
        )

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

        st.divider()
        with st.expander(tr("service_keys"), expanded=False):
            st.caption(tr("service_keys_help"))
            amap_key = st.text_input(tr("amap_key"), type="password", key="amap_key")
            dashscope_key = st.text_input(
                tr("dashscope_key"),
                type="password",
                key="dashscope_key",
            )

        amap_key = amap_key.strip() if amap_key else ""
        dashscope_key = str(dashscope_key).strip() if dashscope_key else ""
        if not amap_key:
            amap_key = os.getenv("AMAP_API_KEY", "").strip()
        if not dashscope_key:
            dashscope_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        if os.getenv("DASHSCOPE_API_KEY") and not st.session_state.get("dashscope_key"):
            st.caption(tr("server_key"))

        st.markdown(
            '<div class="sidebar-footer"><span class="signal-dot"></span>'
            "LOCAL INDEX ONLINE<br><small>AnimeWay / 0.2</small></div>",
            unsafe_allow_html=True,
        )

    return amap_key, dashscope_key
