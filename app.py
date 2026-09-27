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
from components.map_explorer import render_map_explorer
from components.map_runtime import map_resource, pilot_index
from components.map_i18n import mtext
from components.sidebar import render_sidebar
from components.state import init_session_state
from core.route_planner import RoutePlanner
from core.private_store import PrivateStore
from core.journal_store import JournalStore
from core.pilot import load_pilot


st.set_page_config(
    page_title="AnimeWay | 次元航线",
    layout="wide",
    page_icon="⛩️",
    initial_sidebar_state="auto",
)


@st.cache_resource
def load_agent_resources(resource_key):
    from core.agent import AnimeRagAgent

    try:
        agent = AnimeRagAgent()
        return agent.retriever, False
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        # A broken explicit snapshot must not stop the handbook/map shell or mix
        # unrelated legacy data into a claimed full snapshot.
        from core.sqlite_retrieval import SQLiteRetriever

        _, path = pilot_index(load_pilot().get("version"))
        return SQLiteRetriever(path), True


def load_css() -> None:
    with open("assets/style.css", "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


@st.cache_resource
def load_private_store(data_dir: str) -> PrivateStore:
    return JournalStore(Path(data_dir) / "private.sqlite3")


def main() -> None:
    load_css()
    init_session_state()

    root = os.getenv("ANIMEWAY_SNAPSHOT_DIR") or "knowledge_base/releases"
    try:
        pointer = (Path(root) / "current.json").read_bytes()
    except OSError:
        pointer = b"missing"
    resource_key = (root, pointer, os.getenv("ANIMEWAY_INDEX_DB"))
    retriever, public_fallback = load_agent_resources(resource_key)
    if public_fallback:
        st.warning(mtext("fallback"))
    if (
        "rag_agent" not in st.session_state
        or st.session_state.get("aw_public_resource_key") != resource_key
    ):
        from core.agent import AnimeRagAgent

        st.session_state["rag_agent"] = AnimeRagAgent(retriever=retriever)
        st.session_state["aw_public_resource_key"] = resource_key
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
        st.error(
            {
                "zh_CN": "私人清单暂时无法读取。原数据不会被重建或清空；请检查保存目录，仍可浏览巡礼内容。",
                "en_US": "Private lists could not be loaded. Existing data is preserved; check the storage directory. You can still browse.",
                "ja_JP": "非公開リストを読み込めません。既存データは消去しません。保存先を確認してください。閲覧は続けられます。",
            }.get(locale, "Private storage is unavailable; existing data is preserved.")
        )
    catalog = store.catalog(load_pilot()) if store else load_pilot()
    service, version, scope, fallback = map_resource(store, catalog)
    from core.place_links import current_catalog
    extra_ids = set()
    if token and store:
        if st.session_state.get("aw_page") == "wishlist":
            extra_ids.update(p["id"] for p in store.list_wishlist(token))
        if st.session_state.get("aw_page") == "location":
            extra_ids.add(st.session_state.get("aw_selected_location", ""))
        if st.session_state.get("aw_page") == "journal":
            extra_ids.update(e["location_id"] for e in store.entries(token))
        if st.session_state.get("aw_selected_trip"):
            saved_trip = store.get_trip(token, st.session_state["aw_selected_trip"])
            extra_ids.update(p["id"] for p in (saved_trip or {}).get("stops", []))
    catalog = current_catalog(service, catalog, extra_ids)
    if st.query_params.get("share"):
        from components.journal import render_public_share

        render_public_share(store, token, catalog, st.query_params.get("share"))
        return
    handbook_label = {
        "zh_CN": "手册与 Trip",
        "en_US": "Handbooks & Trips",
        "ja_JP": "手帳と旅程",
    }.get(locale, "手册与 Trip")
    map_enabled = os.getenv("ANIMEWAY_MAP_ENABLED", "1").lower() not in {"0", "false", "off"}
    labels = [handbook_label, tr("nav_discover"), tr("nav_plan")] + ([mtext("title")] if map_enabled else [])
    if "aw_agent_defaulted" not in st.session_state:
        st.session_state["aw_active_tab"] = tr("nav_discover")
        st.session_state["aw_agent_defaulted"] = True
    pending = st.session_state.pop("aw_pending_tab", None)
    if pending:
        st.session_state["aw_active_tab"] = mtext("title") if pending == "map" and map_enabled else handbook_label
    if st.session_state.get("aw_active_tab") not in labels:
        st.session_state["aw_active_tab"] = tr("nav_discover")
    tabs = st.tabs(labels, key="aw_active_tab", on_change="rerun")
    tab_handbook, tab_discover, tab_plan = tabs[:3]
    if map_enabled:
        with tabs[3]:
            render_map_explorer(service, store, token, catalog, version, scope, fallback)

    with tab_handbook:
        if map_enabled and st.session_state.get("awmap_return"):
            if st.button("返回地图中的地点", key="awmap_return_button"):
                st.session_state["aw_pending_tab"] = "map"
                st.rerun()
        render_legacy_transfer(store, token)
        render_pilgrimage(store, token, catalog, api_key=dashscope_key)

    with tab_discover:
        render_discover(agent, retriever, amap_key, dashscope_key, catalog,
                        store=store, token=token, route_planner=route_planner)

    with tab_plan:
        render_plan(route_planner, amap_key, dashscope_key, catalog)


if __name__ == "__main__":
    main()
