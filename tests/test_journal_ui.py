from datetime import timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core.journal import today
from core.journal_store import JournalStore
from core.pilot import load_pilot
from core.trip import empty_plan, new_requirements, stop_spec


@pytest.fixture
def ui(tmp_path):
    path = tmp_path / "ui.db"
    store = JournalStore(path)
    token = store.new_identity()
    catalog = load_pilot()
    plan = empty_plan(new_requirements((today()-timedelta(days=1)).isoformat(), 1, anime_ids=["328609"]))
    plan["days"][0]["stops"] = [stop_spec("loc-tokyo-shelter")]
    trip = store.create_personal_trip(token, plan)
    script = f"""
import streamlit as st
from components.journal import render_journal, render_rediscovery, render_public_share
from core.journal_store import JournalStore
from core.pilot import load_pilot
s=JournalStore({str(path)!r})
t=st.session_state.get('test_token')
catalog=s.catalog(load_pilot())
mode=st.session_state.get('test_page','journal')
if mode=='journal': render_journal(s,t,catalog)
elif mode=='next': render_rediscovery(s,t,catalog)
else: render_public_share(s,t,catalog,st.session_state.get('share_id'))
"""
    app = AppTest.from_string(script, default_timeout=30)
    app.session_state["test_token"] = token
    app.run()
    assert not app.exception
    return app, store, token, catalog, trip


def click(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception


def test_manual_record_confirm_undo_and_short_text_without_ai(ui):
    app, store, token, catalog, _ = ui
    click(app, "保存私密足迹")
    assert store.entries(token) == []
    app.checkbox(key="awj_new_confirm").check()
    click(app, "保存私密足迹")
    entry = store.entries(token)[0]
    click(app, "撤销到访")
    assert store.entries(token)[0]["confirmed"] is False
    click(app, "重新确认到访")
    app.radio(key="awj_mode").set_value("照片与短文").run()
    assert not app.exception
    click(app, "根据确认到访整理短句（无需 AI）")
    assert "我到访了" in next(a.value for a in app.text_area if "可编辑短文" in a.label)
    click(app, "保存记录与短文")
    assert store.entries(token)[0]["short_text"]
    assert any(b.disabled for b in app.button if b.key=="awj_ai_short")
    app.session_state["test_token"] = store.new_identity()
    app.run()
    assert not app.exception and any("先确认" in m.value for m in app.info)
    assert store.entries(token)[0]["id"] == entry["id"]


def test_share_preview_is_required_and_private_information_not_copied(ui):
    app, store, token, _, _ = ui
    app.radio(key="awj_mode").set_value("分享").run()
    click(app, "生成发布预览")
    assert not store.shares(token)
    assert app.button(key="awj_publish").disabled
    app.checkbox(key="awj_publish_confirm").check().run()
    click(app, "发布公开路线副本")
    shared = store.shares(token)[0]
    assert shared["active"]
    click(app, "撤下此分享")
    assert store.public_share(shared["id"]) is None


def test_follow_dismiss_and_return_intent_without_key(ui):
    app, store, token, catalog, _ = ui
    app.session_state["test_page"] = "next"
    app.run()
    assert not app.exception
    next(m for m in app.multiselect if m.label=="关注作品").set_value(["328609"])
    click(app, "保存关注设置")
    assert store.preferences(token)["follows"][0]["id"] == "328609"
    button = next(b for b in app.button if b.key and b.key.startswith("awj_dismiss_"))
    lid = button.key[len("awj_dismiss_"):]
    button.click().run()
    assert not app.exception and lid in store.preferences(token)["dismissed"]
    click(app, "清空不感兴趣设置")
    assert not store.preferences(token)["dismissed"]
    next(m for m in app.multiselect if m.label=="人工选择至多三个候选").set_value([store.recommend(token, catalog)[0]["location"]["id"]])
    click(app, "预览我的选择")
    before = len(store.list_personal_trips(token))
    click(app, "确认建立独立 Trip 草案")
    assert len(store.list_personal_trips(token)) == before + 1


def test_public_share_separate_identity_copy(ui):
    app, store, token, catalog, trip = ui
    preview = store.preview_share(token, trip["id"], catalog)
    sid = store.publish_share(token, trip["id"], 1, preview, catalog)
    other = store.new_identity()
    app.session_state["test_token"] = other
    app.session_state["test_page"] = "public"
    app.session_state["share_id"] = sid
    app.run()
    assert not app.exception and not store.list_personal_trips(other)
    click(app, "复制为我的个人 Trip")
    assert len(store.list_personal_trips(other)) == 1
    assert store.list_personal_trips(other)[0]["events"] == []
    store.revoke_share(token, sid)
    # Fresh request, no retained private state from the publishing browser.
    again = AppTest.from_string(Path(app._script_path).read_text(), default_timeout=30)
    again.session_state["test_token"] = other
    again.session_state["test_page"] = "public"
    again.session_state["share_id"] = sid
    again.run()
    assert any("已撤下" in w.value for w in again.warning)
