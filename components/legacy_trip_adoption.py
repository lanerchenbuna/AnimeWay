"""Review an old location list before opening a personal Trip draft."""
from __future__ import annotations

import streamlit as st

from components.map_trip import open_handbook
from components.trip_planner import _attempt, render_draft_preview
from core.journal import today
from core.trip_adoption import audit_legacy_conversion, draft_from_legacy, review_legacy_places


def render_legacy_conversion(items, catalog, store, token, *, source, key, title):
    rows = _attempt(lambda: review_legacy_places(items, catalog))
    if rows is None:
        return
    st.caption("原清单保持不变。先逐项核对，再选择能进入东京试点 Trip 的地点；未选地点不会进入新草案。历史路线说明、场景标注和旧交通结论不会自动复制。")
    for index, row in enumerate(rows, 1):
        status = "可选择" if row["eligible"] else row["reason"]
        st.write(f"{index}. {row['name']} · {'必去' if row['required'] else '可选'} · {status}")
        if row["eligible"]:
            st.caption(f"停留 {row['stay_min']} 分钟{'（原记录未填，采用草案默认值）' if row['stay_defaulted'] else ''}")
        if row["changed_facts"]:
            st.caption(f"原记录：{row['source_name']}；当前资料变化：{'、'.join(row['changed_facts'])}。新 Trip 将读取当前资料。")

    eligible = [row for row in rows if row["eligible"]]
    if not eligible:
        st.warning("原清单中没有可转换的东京试点地点。原内容仍可查看和使用。")
        return
    labels = {row["id"]: row["name"] for row in eligible}
    all_works = {work for row in eligible for work in row["anime_ids"]}
    defaults = list(labels) if len(labels) <= 10 and 1 <= len(all_works) <= 3 else []
    selected = st.multiselect("进入新草案的地点（沿用原顺序）", list(labels), default=defaults,
                              format_func=labels.get, key=f"{key}_selected")
    name = st.text_input("新 Trip 名称", value=title, key=f"{key}_title", max_chars=300)
    start = st.date_input("开始日期（日本时间）", value=today(), key=f"{key}_date")
    count = st.selectbox("安排天数", [1, 2, 3], key=f"{key}_days")
    modes = {"walk": "步行为主（短途估算）", "transit": "公共交通为主（待核查）"}
    mode = st.selectbox("交通方式", list(modes), format_func=modes.get, key=f"{key}_mode")

    plan = None
    audit = None
    if selected:
        try:
            plan = draft_from_legacy(items, catalog, selected_ids=selected,
                                     start_date=start.isoformat(), day_count=count, title=name, mode=mode)
            audit = audit_legacy_conversion(items, catalog, plan, selected)
        except (ValueError, KeyError, TypeError) as exc:
            st.warning(str(exc))
    if audit:
        st.caption(f"转换核对：原清单 {audit['source_count']} 项，进入草案 {audit['selected_count']} 项，未进入 {len(audit['omitted'])} 项；沿用原顺序、必去属性和停留时长。")
        for omitted in audit["omitted"]:
            st.warning(f"第 {omitted['index']} 项 {omitted['name']} 未进入：{omitted['reason']}")
        for difference in audit["differences"]:
            st.error(f"转换不一致：{difference}")
    if plan:
        render_draft_preview(plan, catalog)
    reviewed = st.checkbox("我已核对原清单与新草案的地点、顺序和未转换项", key=f"{key}_reviewed")
    if st.button("进入个人 Trip 草案编辑器", key=f"{key}_create", type="primary",
                 disabled=not (store and token and plan and audit and audit["matches"] and reviewed)):
        draft = _attempt(lambda: store.create_personal_draft(token, plan, source))
        if draft:
            open_handbook("personal", awp_mode="draft", awp_draft_id=draft["id"])
