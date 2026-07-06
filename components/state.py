import json
import os
import re
from datetime import datetime

import streamlit as st


ITEMS_PER_PAGE = 24


def init_session_state() -> None:
    defaults = {
        "itinerary": [],
        "search_results": [],
        "current_anime": None,
        "page": 0,
        "search_candidates": [],
        "messages": [],
        "planned_routes": None,
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


def save_feedback(query: str, response: str, is_positive: bool) -> None:
    feedback_file = "evaluation/feedback_log.jsonl"
    bad_case_file = "evaluation/bad_cases.log"
    record = {
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "response": response,
        "is_positive": is_positive,
    }

    os.makedirs("evaluation", exist_ok=True)
    with open(feedback_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    if not is_positive:
        bad_cases = []
        if os.path.exists(bad_case_file):
            try:
                with open(bad_case_file, "r", encoding="utf-8") as f:
                    bad_cases = json.load(f)
            except (OSError, json.JSONDecodeError):
                bad_cases = []
        bad_cases.append(record)
        with open(bad_case_file, "w", encoding="utf-8") as f:
            json.dump(bad_cases, f, indent=2, ensure_ascii=False)

    st.toast("反馈已记录。")


def add_to_itinerary(point: dict, anime_name: str | None = None) -> None:
    point_copy = dict(point)
    anime_name = point.get("_anime_name") or anime_name or "未知动画"
    point_copy["_anime_name"] = anime_name

    local_id = f"{point_copy.get('id')}_{point_copy.get('name') or point_copy.get('cn')}"
    if any(item.get("_local_id") == local_id for item in st.session_state["itinerary"]):
        st.toast("这个地点已经在背包里了。")
        return

    point_copy["_local_id"] = local_id
    st.session_state["itinerary"].append(point_copy)
    st.toast(f"已加入背包：{point_copy.get('cn') or point_copy.get('name')}")
    st.rerun()


def remove_from_itinerary(index: int) -> None:
    if 0 <= index < len(st.session_state["itinerary"]):
        item = st.session_state["itinerary"].pop(index)
        st.toast(f"已移除：{item.get('cn') or item.get('name')}")
        st.rerun()
