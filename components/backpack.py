"""Temporary backpack review, with personal Trip as the only route output."""

import streamlit as st

from components.i18n import tr
from components.state import remove_from_itinerary
from components.ui import render_section_header


def render_backpack(catalog, *, store=None, token=None) -> None:
    st.markdown(
        render_section_header(tr("plan_title"), tr("plan_kicker"), tr("plan_help")),
        unsafe_allow_html=True,
    )
    items = st.session_state.get("itinerary", [])
    if not items:
        st.info(tr("plan_empty"))
        return

    for index, item in enumerate(items):
        c1, c2, c3 = st.columns([0.5, 3, 1])
        with c1:
            st.markdown(f"### {index + 1}")
        with c2:
            st.markdown(f"**{item.get('spot_name') or item.get('name') or tr('unknown_location')}**")
            st.caption(item.get("_anime_name") or tr("unknown_anime"))
        with c3:
            if st.button(tr("remove"), key=f"del_{index}"):
                remove_from_itinerary(index)
        st.divider()

    if catalog is not None and store is not None and token:
        st.subheader("用背包地点建立个人 Trip 草案")
        from components.legacy_trip_adoption import render_legacy_conversion
        render_legacy_conversion(items, catalog, store, token,
                                 source="backpack", key="aw_bag_convert", title="背包地点巡礼")
    else:
        st.info("登录私人身份后可核对地点并建立个人 Trip 草案。")
