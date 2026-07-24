import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import streamlit as st

from components.i18n import DEFAULT_LOCALE, tr


ITEMS_PER_PAGE = 24
MAX_ITINERARY_ITEMS = 12


def init_session_state() -> None:
    defaults = {
        "itinerary": [],
        "search_results": [],
        "current_anime": None,
        "page": 0,
        "search_candidates": [],
        "messages": [],
        "planned_routes": None,
        "optimized_points": [],
        "is_rec_result": False,
        "last_rec_query": "",
        "locale": DEFAULT_LOCALE,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clean_markdown_output(text: str) -> str:
    if not text:
        return ""
    pattern = r"^```(?:markdown)?\s*([\s\S]*?)\s*```$"
    match = re.match(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else text.strip()


def append_message(
    role: str,
    content: str,
    structured_result: dict | None = None,
    retrieval_context: list | None = None,
) -> dict:
    message = {
        "message_id": uuid4().hex,
        "role": role,
        "content": str(content),
        "structured_result": structured_result or {},
        "retrieval_context": retrieval_context or [],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "feedback": None,
        "locale": st.session_state.get("locale", DEFAULT_LOCALE),
    }
    st.session_state["messages"].append(message)
    return message


def save_feedback(
    query: str,
    response: str,
    is_positive: bool,
    message_id: str | None = None,
) -> None:
    data_dir = Path(os.getenv("ANIMEWAY_DATA_DIR") or Path(tempfile.gettempdir()) / "animeway")
    feedback_file = data_dir / "feedback_log.jsonl"
    bad_case_file = data_dir / "bad_cases.jsonl"
    record = {
        "timestamp": datetime.now().isoformat(),
        "message_id": message_id,
        "query": query,
        "response": response,
        "is_positive": is_positive,
    }

    data_dir.mkdir(parents=True, exist_ok=True)
    with open(feedback_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    if not is_positive:
        with open(bad_case_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    if message_id:
        for message in st.session_state.get("messages", []):
            if message.get("message_id") == message_id:
                message["feedback"] = is_positive
                break

    st.toast(tr("feedback_toast"))


def add_to_itinerary(point: dict, anime_name: str | None = None) -> None:
    point_copy = dict(point)
    anime_name = point.get("_anime_name") or anime_name or "未知动画"
    point_copy["_anime_name"] = anime_name

    local_id = f"{point_copy.get('id')}_{point_copy.get('name') or point_copy.get('cn')}"
    if any(item.get("_local_id") == local_id for item in st.session_state["itinerary"]):
        st.toast(tr("already_bag"))
        return
    if len(st.session_state["itinerary"]) >= MAX_ITINERARY_ITEMS:
        st.toast(tr("bag_limit", limit=MAX_ITINERARY_ITEMS))
        return

    point_copy["_local_id"] = local_id
    st.session_state["itinerary"].append(point_copy)
    st.session_state["planned_routes"] = None
    st.session_state["optimized_points"] = []
    st.toast(tr("added", name=point_copy.get("cn") or point_copy.get("name")))
    st.rerun()


def remove_from_itinerary(index: int) -> None:
    if 0 <= index < len(st.session_state["itinerary"]):
        item = st.session_state["itinerary"].pop(index)
        st.session_state["planned_routes"] = None
        st.session_state["optimized_points"] = []
        st.toast(tr("removed", name=item.get("cn") or item.get("name")))
        st.rerun()
