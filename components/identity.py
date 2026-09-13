"""Anonymous browser identity for private, durable pilgrimage data.

The browser stores a bearer credential in first-party storage. Only its hash is
stored by PrivateStore. Neither query strings nor export files carry credentials.
"""
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from components.i18n import current_locale


_identity_component = components.declare_component(
    "animeway_private_identity",
    path=str(Path(__file__).resolve().parents[1] / "assets" / "identity"),
)


def identity_copy(key: str) -> str:
    messages = {
        "connecting": (
            "正在连接此浏览器的私人巡礼清单；现在可以先浏览。",
            "Connecting this browser's private lists. You can browse while they load.",
            "このブラウザーの非公開リストに接続中です。先に閲覧できます。",
        ),
        "temporary": (
            "浏览器未允许长期保存身份。离开前请在「备份与恢复」下载清单；清除浏览器数据后也需要备份恢复。",
            "This browser cannot retain your identity. Download a backup before leaving; clearing browser data also requires a backup.",
            "ブラウザーに識別情報を保存できません。終了前にバックアップしてください。ブラウザーデータを消去した場合も復元が必要です。",
        ),
        "missing": (
            "未找到此浏览器原有的私人档案。请检查服务端数据目录，或使用自己的清单备份恢复。",
            "The previous private profile could not be found. Check the server data directory or restore your own backup.",
            "以前の非公開データが見つかりません。サーバーの保存先を確認するか、ご自身のバックアップを復元してください。",
        ),
    }
    locale_index = {"zh_CN": 0, "en_US": 1, "ja_JP": 2}.get(current_locale(), 0)
    return messages[key][locale_index]


def private_identity(store) -> str | None:
    """Render the storage handshake on every run; never trust a supplied ID."""
    candidate = st.session_state.get("_aw_identity_candidate")
    if not candidate or not store.has_identity(candidate):
        candidate = store.new_identity()
        st.session_state["_aw_identity_candidate"] = candidate

    result = _identity_component(
        candidate=candidate,
        replace_invalid_token=st.session_state.get("_aw_invalid_identity", ""),
        key="aw_browser_identity",
        default=None,
    )
    token = st.session_state.get("aw_identity_token")
    if isinstance(result, dict):
        incoming = result.get("token")
        if isinstance(incoming, str) and store.has_identity(incoming):
            # Clear prior user's navigation when browser identity changes.
            if token and token != incoming:
                for key in list(st.session_state):
                    if key.startswith(("awp_", "awj_")):
                        st.session_state.pop(key, None)
                for key in ("aw_selected_trip", "aw_selected_location", "aw_history", "aw_control_memory", "aw_view_event"):
                    st.session_state.pop(key, None)
                st.session_state["aw_page"] = "discover"
            token = incoming
            st.session_state["aw_identity_token"] = token
            st.session_state["aw_identity_persistent"] = result.get("persistent") is True
        elif isinstance(incoming, str) and incoming != st.session_state.get("_aw_invalid_identity"):
            for key in list(st.session_state):
                if key.startswith(("awp_", "awj_")):
                    st.session_state.pop(key, None)
            for key in ("aw_selected_trip", "aw_history", "aw_control_memory", "aw_view_event"):
                st.session_state.pop(key, None)
            st.session_state["aw_page"] = "discover"
            st.session_state["_aw_invalid_identity"] = incoming
            st.session_state["aw_identity_missing"] = True
            st.session_state.pop("aw_identity_token", None)
            st.rerun()

    if st.session_state.get("aw_identity_missing"):
        st.warning(identity_copy("missing"))
    if token and store.has_identity(token):
        if st.session_state.get("aw_identity_persistent") is False:
            st.warning(identity_copy("temporary"))
        return token
    st.caption(identity_copy("connecting"))
    return None
