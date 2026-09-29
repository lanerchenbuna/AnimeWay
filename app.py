"""
AnimeWay - AI-Powered Anime Pilgrimage Planner
"""

import os
from pathlib import Path
import sqlite3

import streamlit as st

from components.discover import render_discover
from components.i18n import current_locale
from components.identity import private_identity
from components.legacy_transfer import render_legacy_transfer
from components.pilgrimage import render_pilgrimage
from components.backpack import render_backpack
from components.map_explorer import render_map_explorer
from components.map_runtime import map_resource, pilot_index
from components.map_i18n import mtext
from components.sidebar import render_sidebar
from components.state import init_session_state
from components.trip_planner import render_personal_trips, render_trip_creation
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
    agent = st.session_state["rag_agent"]

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
    map_enabled = os.getenv("ANIMEWAY_MAP_ENABLED", "1").lower() not in {"0", "false", "off"}
    labels = {
        "zh_CN": ("规划行程", "探索地点", "我的行程"),
        "en_US": ("Plan a trip", "Explore places", "My trips"),
        "ja_JP": ("旅程を計画", "場所を探す", "自分の旅程"),
    }.get(locale, ("规划行程", "探索地点", "我的行程"))
    planning, exploring, my_trips = labels
    pending = st.session_state.pop("aw_pending_tab", None)
    if pending:
        st.session_state["aw_active_tab"] = (
            exploring if pending in {"map", "explore"}
            else my_trips if pending in {"handbook", "trips", "personal", "journal"}
            else planning
        )
    if st.session_state.get("aw_active_tab") not in labels:
        st.session_state["aw_active_tab"] = planning
    tabs = st.tabs(labels, key="aw_active_tab", on_change="rerun")
    active = st.session_state["aw_active_tab"]
    if active == planning:
        with tabs[0]:
            method = st.radio("规划方式", ["表单规划", "一句话路书"], horizontal=True, key="aw_plan_view")
            if method == "表单规划":
                render_trip_creation(store, token, catalog, dashscope_key)
            else:
                st.title("一句话规划巡礼")
                render_discover(agent, retriever, amap_key, dashscope_key, catalog,
                                store=store, token=token)
    elif active == exploring:
        with tabs[1]:
            choices = (["地图探索"] if map_enabled else []) + ["手册与地点", "临时背包"]
            if st.session_state.get("aw_explore_view") not in choices:
                st.session_state["aw_explore_view"] = choices[0]
            mode = st.radio("探索方式", choices, horizontal=True, key="aw_explore_view")
            if mode == "地图探索":
                render_map_explorer(service, store, token, catalog, version, scope, fallback)
            elif mode == "手册与地点":
                if st.session_state.get("aw_page") not in {"discover", "anime", "location", "route"}:
                    st.session_state["aw_page"] = "discover"
                render_pilgrimage(store, token, catalog, api_key=dashscope_key,
                                  show_navigation=False)
            else:
                render_backpack(catalog, store=store, token=token)
    else:
        with tabs[2]:
            if map_enabled and st.session_state.get("awmap_return"):
                if st.button("返回地图中的地点", key="awmap_return_button"):
                    st.session_state.update(aw_explore_view="地图探索", aw_pending_tab="map")
                    st.rerun()
            left, right = st.columns(2)
            with left:
                if st.button("我的行程", key="aw_top_my_trips", width="stretch"):
                    st.session_state.update(aw_my_view="personal", aw_pending_tab="trips")
                    st.rerun()
            with right:
                if st.button("旧资料、记录与备份", key="aw_top_legacy", width="stretch"):
                    st.session_state.update(aw_my_view="legacy", aw_page="trips", aw_pending_tab="trips")
                    st.rerun()
            if st.session_state.get("aw_my_view", "personal") == "personal":
                render_personal_trips(store, token, catalog, dashscope_key)
            else:
                st.caption("旧手册副本、愿望清单与记录继续可读；新安排请从规划行程开始。")
                legacy_pages = [("旧手册副本", "trips"), ("愿望清单", "wishlist"),
                                ("巡礼记录", "journal"), ("再次发现", "rediscovery"),
                                ("备份与反馈", "settings")]
                for column, (title, page) in zip(st.columns(len(legacy_pages)), legacy_pages):
                    with column:
                        if st.button(title, key=f"aw_secondary_{page}", width="stretch"):
                            st.session_state.update(aw_page=page, aw_pending_tab="trips")
                            st.rerun()
                if st.session_state.get("aw_page") not in {"trip", "trips", "wishlist", "settings",
                                                            "journal", "rediscovery", "personal"}:
                    st.session_state["aw_page"] = "trips"
                render_legacy_transfer(store, token)
                render_pilgrimage(store, token, catalog, api_key=dashscope_key,
                                  show_navigation=False)


if __name__ == "__main__":
    main()
