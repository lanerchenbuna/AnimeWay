"""
AnimeWay - AI-Powered Anime Pilgrimage Planner
"""

import os
from pathlib import Path
import sqlite3

import streamlit as st

from components.discover import render_discover
from components.i18n import current_locale, tr
from components.identity import private_identity
from components.legacy_transfer import render_legacy_transfer
from components.pilgrimage import render_pilgrimage
from components.plan import render_plan
from components.sidebar import render_sidebar
from components.state import init_session_state
from components.ui import render_hero
from core.route_planner import RoutePlanner
from core.private_store import PrivateStore
from core.journal_store import JournalStore
from core.pilot import load_pilot


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


@st.cache_resource
def load_private_store(data_dir: str) -> PrivateStore:
    return JournalStore(Path(data_dir) / "private.sqlite3")


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
    data_dir = os.getenv("ANIMEWAY_DATA_DIR") or str(Path(__file__).resolve().parent / ".animeway")
    try:
        store = load_private_store(data_dir)
        token = private_identity(store)
    except (OSError, sqlite3.Error, ValueError):
        store, token = None, None
        st.error({
            "zh_CN": "私人清单暂时无法读取。原数据不会被重建或清空；请检查保存目录，仍可浏览巡礼内容。",
            "en_US": "Private lists could not be loaded. Existing data is preserved; check the storage directory. You can still browse.",
            "ja_JP": "非公開リストを読み込めません。既存データは消去しません。保存先を確認してください。閲覧は続けられます。",
        }.get(locale, "Private storage is unavailable; existing data is preserved."))
    catalog = store.catalog(load_pilot()) if store else load_pilot()
    if st.query_params.get("share"):
        from components.journal import render_public_share
        render_public_share(store, token, catalog, st.query_params.get("share"))
        return
    handbook_label = {
        "zh_CN": "巡礼手册",
        "en_US": "Pilgrimage handbooks",
        "ja_JP": "巡礼ハンドブック",
    }.get(locale, "巡礼手册")
    tab_handbook, tab_discover, tab_plan = st.tabs(
        [handbook_label, tr("nav_discover"), tr("nav_plan")]
    )

    with tab_handbook:
        render_legacy_transfer(store, token)
        render_pilgrimage(store, token, catalog, api_key=dashscope_key)

    with tab_discover:
        st.markdown(render_hero(locale), unsafe_allow_html=True)
        render_discover(agent, retriever, amap_key, dashscope_key, catalog)

    with tab_plan:
        render_plan(route_planner, amap_key, dashscope_key, catalog)


if __name__ == "__main__":
    main()
