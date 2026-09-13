"""Explicitly copy the legacy session backpack to a durable wish list."""
import hashlib

import streamlit as st

from components.i18n import current_locale
from core.pilot import normalize_legacy_point


def wishlist_point(point: dict) -> dict:
    normalized = normalize_legacy_point(dict(point))
    if normalized.get("location_id"):
        normalized["id"] = normalized["location_id"]
    if not normalized.get("id"):
        raw = f"{point.get('name', '')}|{point.get('lat')}|{point.get('lon')}"
        normalized["id"] = "legacy-" + hashlib.sha256(raw.encode()).hexdigest()[:24]
    normalized["name"] = normalized.get("name") or point.get("cn") or "Unknown location"
    normalized["city"] = normalized.get("city") or point.get("_city") or ""
    normalized["source_url"] = normalized.get("source_url") or ""
    normalized["legacy"] = not bool(normalized.get("scene_ids"))
    normalized["_anime_name"] = point.get("_anime_name", "")
    return normalized


def transfer_backpack(store, token: str, points: list[dict]) -> tuple[int, int]:
    added = 0
    failed = 0
    for point in points:
        try:
            added += bool(store.add_wishlist(token, wishlist_point(point)))
        except (TypeError, ValueError):
            failed += 1
    return added, failed


def render_legacy_transfer(store, token: str | None) -> None:
    points = st.session_state.get("itinerary", [])
    if not points:
        return
    locale = current_locale()
    copy = {
        "zh_CN": (
            "把临时背包转存到长期愿望清单",
            "原背包保留用于路线预览。重复地点不会重复收藏。",
            "转存背包", "已新增 {added} 个收藏；{failed} 个无效地点未转存。",
        ),
        "en_US": (
            "Keep your temporary backpack in your wish list",
            "Your backpack remains available for route previews. Existing wishes are not duplicated.",
            "Save backpack", "Added {added} wishes; skipped {failed} invalid locations.",
        ),
        "ja_JP": (
            "一時バッグを行きたい場所に保存",
            "バッグは経路プレビューに残ります。登録済みの場所は重複しません。",
            "バッグを保存", "{added} 件追加、無効な場所 {failed} 件は保存されませんでした。",
        ),
    }.get(locale, (
        "Save temporary backpack", "Keep the current backpack for route previews.",
        "Save backpack", "Added {added}; skipped {failed}.",
    ))
    with st.expander(copy[0]):
        st.caption(copy[1])
        if st.button(copy[2], key="aw_transfer_backpack", disabled=token is None):
            added, failed = transfer_backpack(store, token, points)
            st.success(copy[3].format(added=added, failed=failed))
