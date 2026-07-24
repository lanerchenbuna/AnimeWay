"""
AnimeWay - AI-Powered Anime Pilgrimage Planner
"""

import streamlit as st

from components.discover import render_discover
from components.i18n import current_locale, tr
from components.plan import render_plan
from components.sidebar import render_sidebar
from components.state import init_session_state
from components.ui import render_hero
from core.route_planner import RoutePlanner


st.set_page_config(
    page_title="AnimeWay | 次元航线",
    layout="wide",
    page_icon="⛩️",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def load_agent_resources():
    from core.agent import AnimeRagAgent

    agent = AnimeRagAgent()
    return agent.retriever


def load_css() -> None:
    with open("assets/style.css", "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


def main() -> None:
    load_css()
    init_session_state()

    retriever = load_agent_resources()
    if "rag_agent" not in st.session_state:
        from core.agent import AnimeRagAgent

        st.session_state["rag_agent"] = AnimeRagAgent(retriever=retriever)
    if "route_planner" not in st.session_state:
        st.session_state["route_planner"] = RoutePlanner()

    agent = st.session_state["rag_agent"]
    route_planner = st.session_state["route_planner"]

    amap_key, dashscope_key = render_sidebar()

    locale = current_locale()
    st.markdown(render_hero(locale), unsafe_allow_html=True)
    tab_discover, tab_plan = st.tabs([tr("nav_discover"), tr("nav_plan")])

    with tab_discover:
        render_discover(agent, retriever, amap_key, dashscope_key)

    with tab_plan:
        render_plan(route_planner, amap_key, dashscope_key)


if __name__ == "__main__":
    main()
