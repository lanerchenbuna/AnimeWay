"""Form-first personal Trip workflow, including local edits and today's mode."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
import sqlite3

import streamlit as st

from components.i18n import current_locale
from core.trip import TOKYO, candidates, clock, empty_plan, evaluate, minutes, new_day, new_requirements, propose, resolve_date, validate_plan
from core import trip_ai


def _attempt(action):
    try:
        return action()
    except (ValueError, KeyError, TypeError) as exc:
        st.error(str(exc))
    except (OSError, sqlite3.Error):
        st.error("私人数据暂不可用，原行程未清空。请检查保存目录后重试。")
    return None


def _open(trip_id=None, *, rerun=True):
    st.session_state["awp_selected"] = trip_id
    st.session_state["awp_mode"] = "detail" if trip_id else "new"
    st.session_state["aw_pending_tab"] = "trips" if trip_id else "planning"
    st.session_state.pop("awp_ai_preview", None)
    if rerun:
        st.rerun()


def open_draft(draft_id, *, rerun=True):
    st.session_state["awp_draft_id"] = draft_id
    st.session_state["awp_mode"] = "draft"
    st.session_state["aw_pending_tab"] = "trips"
    st.session_state.pop("awp_ai_preview", None)
    if rerun:
        st.rerun()


def _create_draft(store, token, plan, source="manual"):
    draft = _attempt(lambda: store.create_personal_draft(token, plan, source))
    if draft:
        open_draft(draft["id"], rerun=False)


def _edit_record(store, token, record, operation, catalog):
    if record.get("_draft"):
        return store.edit_personal_draft(token, record["id"], record["revision"], operation, catalog)
    return store.edit_personal_trip(token, record["id"], record["revision"], operation, catalog)


def _adopt(store, token, plan):
    _create_draft(store, token, plan)


def _name(catalog, location_id):
    point = next((p for p in catalog["locations"] if p["id"] == location_id), None)
    return point["name"] if point else f"已失效地点 {location_id}"


def _anchor_input(anchor, catalog, prefix, label):
    places = {p["id"]: p["name"] for p in catalog["locations"] if not p.get("withdrawn") and (p.get("access") or {}).get("status") not in {"closed", "prohibited", "forbidden", "no_entry"}}
    selected = anchor.get("location_id", "")
    if selected and selected not in places:
        places[selected] = "原起终点已失效，请重新选择"
    labels = {"": "住宿／自定义位置（需坐标确认）", **places}
    choice = st.selectbox(label, list(labels), index=list(labels).index(selected), format_func=labels.get, key=f"{prefix}_place")
    st.caption("选择已知地点时以资料库坐标为准；自定义住宿仅输入名称不能完成定位。")
    name = st.text_input(f"{label}名称", value=anchor.get("name", "住宿待确认"), key=f"{prefix}_name", max_chars=300)
    col1, col2 = st.columns(2)
    with col1:
        lat = st.number_input(f"{label}纬度（自定义）", min_value=35.4, max_value=35.9, value=anchor.get("lat"), format="%.6f", key=f"{prefix}_lat")
    with col2:
        lon = st.number_input(f"{label}经度（自定义）", min_value=139.3, max_value=139.95, value=anchor.get("lon"), format="%.6f", key=f"{prefix}_lon")
    confirmed = st.checkbox(f"我已在地图确认{label}位置", value=anchor.get("confirmed", False), key=f"{prefix}_confirmed")
    return {"location_id": choice, "name": places[choice] if choice else name,
            "lat": None if choice else lat, "lon": None if choice else lon, "confirmed": confirmed}


def _requirements_form(plan, catalog, prefix, *, disabled=False):
    req = plan["requirements"]
    count = st.selectbox("旅行天数（包含抵达当天）", [1, 2, 3], index=req["day_count"] - 1, key=f"{prefix}_count")
    st.caption("所有日期与时间均为日本时间 Asia/Tokyo。先选择天数，再编辑每日条件。")
    works = {a["id"]: f"{a.get('cn', a['name'])} · {a.get('version', '')}" for a in catalog["anime"]}
    for work_id in req["anime_ids"]:
        works.setdefault(work_id, f"已失效作品 {work_id}")
    places = {p["id"]: p["name"] for p in catalog["locations"]}
    # Preserve withdrawn/missing saved IDs as explicitly invalid choices, never drop silently.
    for item in req["must_ids"] + req["excluded_ids"]:
        places.setdefault(item, f"已失效地点 {item}")
    with st.form(f"{prefix}_form"):
        title = st.text_input("行程名称", req["title"], key=f"{prefix}_title", max_chars=300)
        start = st.text_input("开始日期（YYYY-MM-DD / 今天 / 明天 / 后天）", req["start_date"], key=f"{prefix}_date")
        anime_ids = st.multiselect("想巡礼的作品（最多三部）", list(works), default=req["anime_ids"], format_func=works.get, key=f"{prefix}_works")
        must = st.multiselect("必去场景所在地点", list(places), default=req["must_ids"], format_func=places.get, key=f"{prefix}_must")
        excluded = st.multiselect("不感兴趣的地点", list(places), default=req["excluded_ids"], format_func=places.get, key=f"{prefix}_excluded")
        pace_labels = {"relaxed": "轻松：少换片区、多休息和余量", "normal": "普通节奏"}
        pace = st.selectbox("体力与节奏", list(pace_labels), index=list(pace_labels).index(req["pace"]), format_func=pace_labels.get, key=f"{prefix}_pace")
        mode_labels = {"walk": "短途步行草案（估算）", "transit": "公交／铁路（须外部核查）"}
        mode = st.selectbox("交通偏好", list(mode_labels), index=list(mode_labels).index(req["mode"]), format_func=mode_labels.get, key=f"{prefix}_mode")
        walking = st.number_input("每日步行预算（米）", 500, 20000, req["max_walk_m"], step=500, key=f"{prefix}_walk")
        days = []
        for index in range(count):
            day = deepcopy(plan["days"][index]) if index < len(plan["days"]) else new_day((date.fromisoformat(req["start_date"]) + timedelta(days=index)).isoformat())
            day_prefix = f"{prefix}_day{index}"
            with st.expander(f"第 {index + 1} 天 · 时间、起终点与休息", expanded=index == 0):
                day["day_type"] = st.selectbox("当天类型", ["arrival", "full"], index=0 if day["day_type"] == "arrival" else 1,
                                                format_func={"arrival": "抵达日（只安排实际可用时段）", "full": "完整一天"}.get, key=f"{day_prefix}_type")
                a, b = st.columns(2)
                with a:
                    start_time = st.text_input("可开始巡礼时间 HH:MM", clock(day["start_min"]), key=f"{day_prefix}_start")
                with b:
                    end_time = st.text_input("必须到达终点的时间 HH:MM", clock(day["end_min"]), key=f"{day_prefix}_end")
                day["start"] = _anchor_input(day["start"], catalog, f"{day_prefix}_origin", "当天起点")
                day["end"] = _anchor_input(day["end"], catalog, f"{day_prefix}_destination", "当天终点")
                day["meal_min"] = st.number_input("用餐预留（分钟）", 0, 180, day["meal_min"], step=5, key=f"{day_prefix}_meal")
                day["break_min"] = st.number_input("分段休息（分钟）", 0, 180, day["break_min"], step=5, key=f"{day_prefix}_break")
                day["buffer_min"] = st.number_input("机动余量（分钟）", 0, 180, day["buffer_min"], step=5, key=f"{day_prefix}_buffer")
                day["_start_text"], day["_end_text"] = start_time, end_time
                days.append(day)
        submitted = st.form_submit_button("确认条件并检查草案", disabled=disabled)
    if not submitted:
        return None
    def collect():
        resolved = resolve_date(start)
        new_req = {**req, "title": title, "start_date": resolved, "day_count": count, "anime_ids": anime_ids,
                   "must_ids": must, "excluded_ids": excluded, "pace": pace, "mode": mode, "max_walk_m": walking}
        for index, day in enumerate(days):
            day["date"] = (date.fromisoformat(resolved) + timedelta(days=index)).isoformat()
            day["start_min"], day["end_min"] = minutes(day.pop("_start_text")), minutes(day.pop("_end_text"))
            for stop in day["stops"]:
                stop["priority"] = "required" if stop["location_id"] in must else "optional"
                if stop["priority"] == "required":
                    stop["locked"] = True
        return validate_plan({"requirements": new_req, "days": days})
    return _attempt(collect)


def _checks(result, catalog):
    st.caption(result["promise"])
    conflicts = [i for i in result["issues"] if i["severity"] == "conflict"]
    if conflicts:
        st.error(f"有 {len(conflicts)} 项硬性冲突，不能视为可执行方案。")
    with st.expander(f"行前检查：{len(result['issues'])} 项冲突／待核查", expanded=bool(conflicts)):
        seen = set()
        for issue in result["issues"]:
            key = (issue["date"], issue["code"], issue["location_id"])
            if key in seen:
                continue
            seen.add(key)
            name = _name(catalog, issue["location_id"]) if issue["location_id"] else "当天条件"
            st.write(f"{issue['date']} · {name}：{issue['message']}")
    st.caption("未知费用不按 0 元计算；含估算的时间不能用于确认预约、关闭时间或末班车。")
    for day in result["days"]:
        totals = day["totals"]
        fare = "待核查" if totals["fare_jpy"] is None else f"{totals['fare_jpy']} 日元"
        st.caption(f"{day['date']} · 已知移动／等待 {totals['known_moving_min'] + totals['known_waiting_min']} 分钟"
                   f" · 待核查交通 {totals['unknown_legs']} 段 · 交通费用：{fare}"
                   f" · 预计结束 {clock(day['finish_min'])}")


def render_draft_preview(plan, catalog):
    """The same compact preview for form, AI and legacy conversion entries."""
    result = evaluate(plan, catalog)
    req = plan["requirements"]
    st.caption(f"{req['start_date']} · {req['day_count']} 日 · "
               f"{'步行为主' if req['mode'] == 'walk' else '公共交通为主'} · 日本时间")
    for day in plan["days"]:
        st.write(f"{day['date']}：" + (" → ".join(_name(catalog, stop["location_id"])
                                                for stop in day["stops"]) or "尚无站点"))
    _checks(result, catalog)
    return result


def _new(store, token, catalog, api_key):
    st.subheader("建立 1—3 日巡礼行程")
    if "awp_seed" not in st.session_state:
        st.session_state["awp_seed"] = empty_plan(new_requirements("明天"))
    with st.expander("用一句话整理需求（可选）"):
        text = st.text_area("例如：后天下午到东京，住新宿，两天，巡礼孤独摇滚和你的名字，不想太赶", key="awp_free_text", max_chars=2000)
        ai = st.checkbox("使用可选 AI 整理这段文字", key="awp_req_ai", disabled=not trip_ai.enabled(api_key))
        st.caption("默认使用本地规则，不调用模型。选择 AI 时仅发送这段文字和可选作品，结果仍需在需求卡确认。")
        if st.button("整理为可编辑需求卡", key="awp_parse", disabled=ai and not token):
            parsed = _attempt(lambda: trip_ai.request_requirements(store, token, text, catalog, api_key) if ai else trip_ai.local_requirements(text, catalog))
            if parsed:
                seed = empty_plan(parsed["requirements"])
                if parsed["arrival"]:
                    seed["days"][0] = new_day(seed["days"][0]["date"], arrival=True)
                for day in seed["days"]:
                    day["start"]["name"] = day["end"]["name"] = parsed["lodging_name"]
                st.session_state["awp_seed"] = seed
                st.session_state["awp_seed_epoch"] = st.session_state.get("awp_seed_epoch", 0) + 1
                st.session_state.pop("awp_options", None)
                st.session_state["awp_parse_note"] = parsed["note"]
                st.rerun()
    if st.session_state.get("awp_parse_note"):
        st.info(st.session_state["awp_parse_note"])
    seed = st.session_state["awp_seed"]
    plan = _requirements_form(seed, catalog, f"awp_new_{st.session_state.get('awp_seed_epoch', 0)}")
    if plan:
        st.session_state["awp_seed"] = plan
        st.session_state["awp_options"] = propose(plan, catalog)
        st.session_state.pop("awp_qwen_option", None)
    qwen_ready = trip_ai.enabled(api_key) and bool(token)
    st.caption("本地草案无需 Key。需要 AI 按你的条件编排站点时，在左侧填入 DashScope API Key；Qwen 只选择本地候选地点，不编造交通、费用或开放信息。")
    if st.button("用 Qwen 生成路书草案", key="awp_generate_qwen", disabled=not qwen_ready):
        try:
            with st.spinner("正在让 Qwen 编排候选地点并检查草案…"):
                option = trip_ai.request_itinerary(store, token, st.session_state["awp_seed"], catalog, api_key)
            st.session_state["awp_qwen_option"] = option
        except ValueError as exc:
            st.error(str(exc))
        st.rerun()
    if not qwen_ready:
        st.caption("填写左侧 DashScope Key 并启用本地身份后，即可生成 AI 路书；每个浏览器身份每日最多 3 次。")
    options = list(st.session_state.get("awp_options", []))
    qwen_option = st.session_state.get("awp_qwen_option")
    if qwen_option:
        options.append(qwen_option)
    for index, option in enumerate(options):
        with st.container(border=True):
            st.subheader(option["label"])
            st.write(option["reason"])
            render_draft_preview(option["plan"], catalog)
            st.button("打开草案并修改", key=f"awp_adopt_{index}", disabled=not token, type="primary",
                      on_click=_adopt, args=(store, token, option["plan"]))


def render_trip_creation(store, token, catalog, api_key=""):
    st.title("规划行程")
    st.caption("选择作品、日期与交通方式，查看草案，修改后再保存到我的行程。")
    _new(store, token, catalog, api_key)


def _local_edit(store, token, archive, day, stop, catalog):
    prefix = f"awp_edit_{archive['id']}_{archive['revision']}_{stop['location_id']}"
    with st.expander("编辑此站：停留、顺序、交通、替换、锁定"):
        st.caption("锁定同时保护站点位置和停留；要改变核心项，请先人工解锁。已执行部分不接受规划修改。")
        st.caption("停留为经验建议：轻松节奏约 20—40 分钟，普通节奏约 10—25 分钟；请按拍摄与体力调整。")
        choices = {"stay": "调整停留", "move": "调整顺序", "leg_mode": "调整到此站的交通方式", "replace": "替换地点", "remove": "删除可选站", "lock": "锁定／解锁", "appointment": "预约／关闭截止时间", "visit_mode": "公共区域外观／计划入内"}
        kind = st.selectbox("操作", list(choices), format_func=choices.get, key=f"{prefix}_kind")
        operation = {"kind": kind, "date": day["date"], "location_id": stop["location_id"]}
        invalid = False
        if kind == "stay":
            operation["value"] = st.number_input("停留分钟（经验建议，可修改）", 1, 240, stop["stay_min"], key=f"{prefix}_stay")
        elif kind == "move":
            operation["position"] = st.number_input("新位置（第几站）", 1, len(day["stops"]), day["stops"].index(stop) + 1, key=f"{prefix}_position") - 1
        elif kind == "replace":
            pool = {p["id"]: p["name"] for p in candidates(archive["plan"], catalog)}
            if not pool:
                st.caption("没有符合兴趣及访问条件的替代候选")
                return
            operation["replacement_id"] = st.selectbox("替代场景所在地点", list(pool), format_func=pool.get, key=f"{prefix}_replacement")
        elif kind == "lock":
            operation["value"] = st.checkbox("锁定此站", value=stop["locked"], key=f"{prefix}_lock")
        elif kind == "leg_mode":
            modes = {None: "跟随行程默认方式", "walk": "步行估算", "transit": "公共交通，待核查"}
            operation["value"] = st.selectbox("到此站的交通方式", list(modes),
                                               index=list(modes).index(stop.get("leg_mode")),
                                               format_func=modes.get, key=f"{prefix}_leg_mode")
        elif kind == "appointment":
            value = st.text_input("当地时间 HH:MM（留空取消）", "" if stop["appointment_min"] is None else clock(stop["appointment_min"]), key=f"{prefix}_appointment")
            if value:
                operation["value"] = _attempt(lambda: minutes(value))
                invalid = operation["value"] is None
            else:
                operation["value"] = None
        elif kind == "visit_mode":
            modes = {"exterior": "允许的公共区域外观", "entry": "计划入内（另核开放与许可）"}
            operation["value"] = st.selectbox("到访方式", list(modes), index=list(modes).index(stop["visit_mode"]), format_func=modes.get, key=f"{prefix}_visitmode")
        if st.button("应用此项人工修改", key=f"{prefix}_apply", disabled=invalid):
            if _attempt(lambda: _edit_record(store, token, archive, operation, catalog)):
                st.rerun()


def _today_focus(store, token, archive, result, catalog):
    """One field-use panel backed by the same evaluated remainder as the editor."""
    days = result["days"]
    local_date = datetime.now(TOKYO).date().isoformat()
    preferred = next((i for i, day in enumerate(days) if day["date"] == local_date and not day["ended"]),
                     next((i for i, day in enumerate(days) if not day["ended"]), 0))
    st.header("当天使用")
    selected_date = st.selectbox("选择要记录的行程日期（日本时间）", [day["date"] for day in days],
                                 index=preferred, key=f"awp_today_day_{archive['id']}")
    checked_day = next(day for day in days if day["date"] == selected_date)
    if selected_date != local_date:
        st.warning("所选日期不是当前日本日期。补记或提前操作前，请确认日期和现场时间。")
    if checked_day["ended"]:
        st.info("这一天已经结束；原到访和跳过记录仍在下方完整日程中。")
        return
    pending = [row for row in checked_day["rows"] if row["outcome"] == "pending"]
    places = {point["id"]: point for point in catalog["locations"]}
    current = pending[0] if pending else None
    point = places.get(current["location_id"]) if current else None
    with st.container(border=True):
        st.subheader("现在")
        if current:
            leg = current["leg"]
            st.markdown(f"**{_name(catalog, current['location_id'])}**")
            st.caption(f"到此站：{'步行' if leg['mode'] == 'walk' else '公共交通'}"
                       f"{'（单段设置）' if leg['overridden'] else ''} · {leg['reason']}")
            st.caption(f"预计抵达 {clock(current['arrival_min'])}；停留 {current['stop']['stay_min']} 分钟。估算或未知时间不能当作现场时刻表。")
            if point:
                from core.place_links import blocked
                st.write((point.get("access") or {}).get("summary") or "访问条件待核查")
                if point.get("entry"):
                    st.caption(f"入口：{point['entry']}")
                viewpoint = point.get("viewpoint")
                if isinstance(viewpoint, dict):
                    viewpoint = viewpoint.get("summary")
                if viewpoint:
                    st.caption(f"机位／视角：{viewpoint}")
                if blocked(point):
                    st.warning("当前资料显示关闭、禁止进入或已撤下；不能确认到访，请选择跳过或临时关闭并核查现场。")
                else:
                    from core.trip_navigation import directions_url
                    link = _attempt(lambda: directions_url(point, leg["mode"]))
                    if link:
                        st.link_button("按所选交通方式打开外部导航", link, width="stretch")
                        st.caption("外部地图可能更改路线；请在地图内核对交通方式、当前位置和可进入区域。打开导航不会记录到访。")
        else:
            st.success("当天所有站点已经处理。是否前往终点，请核对下方交通段。")
    with st.container(border=True):
        st.subheader("下一步")
        if len(pending) > 1:
            following = pending[1]
            leg = following["leg"]
            st.write(f"当前站处理后：{_name(catalog, following['location_id'])}")
            st.caption(f"预计到下一站：{'步行' if leg['mode'] == 'walk' else '公共交通'} · {leg['reason']}")
        else:
            leg = checked_day["return_leg"]
            st.write("返回当天终点")
            st.caption(f"{'步行' if leg['mode'] == 'walk' else '公共交通'} · {leg['reason']}")
            from core.trip_navigation import directions_url
            from core.trip_transport import resolve_anchor
            planned_day = next(day for day in archive["plan"]["days"] if day["date"] == selected_date)
            destination = resolve_anchor(planned_day["end"], catalog)
            link = _attempt(lambda: directions_url(destination, leg["mode"])) if destination else None
            if link:
                st.link_button("按回程交通方式导航到终点", link, width="stretch")
            else:
                st.caption("终点位置未确认或已失效，请先核对终点；不生成导航链接。")
    totals = checked_day["totals"]
    fare = "待核查" if totals["fare_jpy"] is None else f"{totals['fare_jpy']} 日元"
    st.caption(f"剩余已知移动／等待 {totals['known_moving_min'] + totals['known_waiting_min']} 分钟；"
               f"待核查交通 {totals['unknown_legs']} 段；费用 {fare}；预计结束 {clock(checked_day['finish_min'])}。")
    day_issues = [issue for issue in result["issues"] if issue["date"] == selected_date]
    for issue in day_issues[:3]:
        st.warning(issue["message"])
    if len(day_issues) > 3:
        st.caption(f"另有 {len(day_issues) - 3} 项行前问题，可在完整日程中查看。")
    last_visit = next((event for event in reversed(archive["events"])
                       if event["date"] == selected_date and event["kind"] == "visit"), None)
    if last_visit:
        st.caption(f"最近已确认到访：{_name(catalog, last_visit['location_id'])}。剩余交通从该站估算；若已离开或改线，请核对实际起点。")
    else:
        st.caption("剩余交通从计划起点估算；应用不读取你的位置。请在外部地图确认当前出发点。")
    prefix = f"awp_today_{archive['id']}_{archive['revision']}_{selected_date}"
    at_text = st.text_input("现场当地时间 HH:MM", datetime.now(TOKYO).strftime("%H:%M"), key=f"{prefix}_time")
    confirm = st.checkbox("我已核对行程日期、现场时间和这次操作", key=f"{prefix}_confirm")

    def record(kind):
        if _attempt(lambda: store.record_personal_event(token, archive["id"], archive["revision"],
                                                        selected_date, kind, minutes(at_text), catalog)):
            st.rerun()

    if current:
        from core.place_links import blocked
        visit, skip, closed = st.columns(3)
        with visit:
            if st.button("我已到访", key=f"{prefix}_visit", disabled=not confirm or blocked(point), width="stretch"):
                record("visit")
        with skip:
            if st.button("跳过此站", key=f"{prefix}_skip", disabled=not confirm, width="stretch"):
                record("skip")
        with closed:
            if st.button("此站临时关闭", key=f"{prefix}_closed", disabled=not confirm, width="stretch"):
                record("closed")
    st.caption("导航、跳过和临时关闭均不会记为到访；每次操作后按保留的站点与交通设置重新评估剩余安排。")
    with st.expander("更新现场时间或提前结束"):
        if st.button("记录当前时间并重算", key=f"{prefix}_delay", disabled=not confirm):
            record("delay")
        if st.button("提前结束当天", key=f"{prefix}_end_day", disabled=not confirm):
            record("end_day")
        if st.button("结束整趟行程", key=f"{prefix}_end_trip", disabled=not confirm):
            record("end_trip")


def export_personal_checklist(archive, catalog):
    from components.pilgrimage import navigation_url

    result = evaluate(archive["plan"], catalog, archive["events"])
    req = archive["plan"]["requirements"]
    lines = [req["title"], f"版本 {archive['revision']} · {req['timezone']} · 状态 {archive['state']}",
             f"默认交通：{'步行' if req['mode'] == 'walk' else '公共交通'}",
             "个人筹备草案，非已验证行程。此文字文件可离线读取；外部导航需网络，无图片／离线地图。", result["promise"], ""]
    for day, check in zip(archive["plan"]["days"], result["days"]):
        lines.extend([f"{day['date']} {clock(day['start_min'])}—{clock(day['end_min'])}",
                      f"起点：{day['start']['name']}（{'已确认' if day['start']['confirmed'] else '未确认'}）",
                      f"终点：{day['end']['name']}（{'已确认' if day['end']['confirmed'] else '未确认'}）",
             f"用餐 {day['meal_min']} / 休息 {day['break_min']} / 余量 {day['buffer_min']} 分钟",
             f"已知移动／等待 {check['totals']['known_moving_min'] + check['totals']['known_waiting_min']} 分钟；"
             f"待核查交通 {check['totals']['unknown_legs']} 段；"
             f"交通费用 {'待核查' if check['totals']['fare_jpy'] is None else str(check['totals']['fare_jpy']) + ' 日元'}"])
        for index, row in enumerate(check["rows"], 1):
            point = next((p for p in catalog["locations"] if p["id"] == row["location_id"]), None)
            lines.extend([f"{index}. {_name(catalog, row['location_id'])} · {row['outcome']}",
                          f"停留建议 {row['stop']['stay_min']} 分钟；{'必去' if row['stop']['priority']=='required' else '可选'}"])
            if point:
                lines.extend([(point.get("access") or {}).get("summary", "访问状态未知"), point.get("entry", ""), point.get("viewpoint", ""), point.get("source_url", ""),
                              f"{point['lat']:.6f}, {point['lon']:.6f}"])
                if not point.get("withdrawn") and (point.get("access") or {}).get("status") not in {"prohibited", "closed", "forbidden", "no_entry"} and row["outcome"] == "pending":
                    lines.append(navigation_url(point))
            if row.get("leg"):
                lines.append(f"到站交通 {'步行' if row['leg']['mode'] == 'walk' else '公共交通'}：{row['leg']['reason']}")
        lines.append(f"到终点交通 {'步行' if check['return_leg']['mode'] == 'walk' else '公共交通'}：{check['return_leg']['reason']}")
        lines.append("")
    lines.append("行前仍需检查：")
    lines.extend(f"{i['date']} {_name(catalog, i['location_id']) if i['location_id'] else ''}：{i['message']}" for i in result["issues"])
    return '\n'.join(lines)


def _editor_days(store, token, archive, catalog, result):
    plan = archive["plan"]
    prefix = f"awp_{archive['id']}_{archive['revision']}"
    places = {point["id"]: point for point in catalog["locations"]}
    for day, check in zip(plan["days"], result["days"]):
        st.subheader(f"{day['date']} · {clock(day['start_min'])}—{clock(day['end_min'])}")
        st.write(f"{day['start']['name']} → {day['end']['name']}")
        totals = check["totals"]
        st.caption(f"已知移动 {totals['known_moving_min']} / 已知等待 {totals['known_waiting_min']} / 待核查交通 {totals['unknown_legs']} 段 / 停留 {totals['stay_min']} / 用餐 {totals['meal_min']} / 休息 {totals['break_min']} / 余量 {totals['buffer_min']} 分钟")
        if archive["state"] == "on_trip":
            st.caption("以上为剩余安排预算；系统不推测你是否已用餐或休息，可在需求卡主动调整剩余预留。")
        fare = "待核查" if totals["fare_jpy"] is None else f"{totals['fare_jpy']} 日元"
        st.caption(f"步行{'合计' if totals['walk_complete'] else '已知部分'} {totals['walk_m']/1000:.1f} km；交通费用 {fare}（已知部分 {totals['known_fare_jpy']} 日元；场所费用另核）。预计结束 {clock(check['finish_min'])}（草案）")
        for index, row in enumerate(check["rows"], 1):
            stop, point = row["stop"], places.get(row["location_id"])
            with st.container(border=True):
                st.markdown(f"**{index}. {_name(catalog, stop['location_id'])}**")
                st.caption(f"{'必去' if stop['priority']=='required' else '可选'} · {'已锁定' if stop['locked'] else '可编辑'} · 建议停留 {stop['stay_min']} 分钟")
                outcome = {"visit": "已到访（用户确认）", "skip": "已跳过，未记到访", "closed": "临时关闭，未记到访", "not_visited": "提前结束后未到访", "pending": "待处理"}[row["outcome"]]
                st.write(outcome)
                if row["outcome"] == "pending":
                    st.caption(f"抵达 {clock(row['arrival_min'])} / 离开 {clock(row['departure_min'])} · {'含估算，待核查' if row['provisional'] else '仅时间预算'}")
                    st.caption(f"本段休息 {row['break_min']} / 用餐 {row['meal_min']} 分钟")
                    st.caption(f"到站交通：{'步行' if row['leg']['mode'] == 'walk' else '公共交通'}{'（单段设置）' if row['leg']['overridden'] else ''} · {row['leg']['status']}")
                    st.write(row["leg"]["reason"])
                    if row["leg"].get("reference"):
                        st.caption(row["leg"]["reference"])
                        st.link_button("查看官方接近参考", row["leg"]["source_url"])
                    if point:
                        from components.pilgrimage import _navigation, _scene
                        st.write((point.get("access") or {}).get("summary", "访问资料未知"))
                        _navigation(point)
                        with st.expander("查看原作关联与到访依据"):
                            for scene in catalog["scenes"]:
                                if scene["location_id"] == point["id"] and not point.get("withdrawn") and not scene.get("upstream_removed"):
                                    _scene(scene, catalog)
                    if archive["state"] != "ended":
                        _local_edit(store, token, archive, day, stop, catalog)
                elif row.get("actual_min") is not None:
                    st.caption(f"用户记录时间 {clock(row['actual_min'])}；不从计划时间推断到访")
        st.caption(f"到终点：{'步行' if check['return_leg']['mode'] == 'walk' else '公共交通'}{'（单段设置）' if check['return_leg']['overridden'] else ''} · {check['return_leg']['reason']}")
        if archive["state"] != "ended" and not check["ended"]:
            with st.expander("调整到终点的交通方式"):
                return_modes = {None: "跟随行程默认方式", "walk": "步行估算", "transit": "公共交通，待核查"}
                choice = st.selectbox("回程方式", list(return_modes),
                                      index=list(return_modes).index(day.get("return_mode")),
                                      format_func=return_modes.get, key=f"{prefix}_{day['date']}_return_mode")
                if st.button("应用回程交通设置", key=f"{prefix}_{day['date']}_return_apply"):
                    if _attempt(lambda: _edit_record(store, token, archive,
                                                     {"kind": "return_mode", "date": day["date"], "value": choice}, catalog)):
                        st.rerun()
        if archive["state"] != "ended" and not check["ended"]:
            with st.expander("增加相关场景／缩短当天时间"):
                pool = {p["id"]: p["name"] for p in candidates(plan, catalog) if p["id"] not in {s["location_id"] for d in plan["days"] for s in d["stops"]}}
                if pool:
                    choice = st.selectbox("可增加地点", list(pool), format_func=pool.get, key=f"{prefix}_{day['date']}_add_choice")
                    if st.button("增加到当天末尾并检查", key=f"{prefix}_{day['date']}_add"):
                        if _attempt(lambda: _edit_record(store, token, archive, {"kind": "add", "date": day["date"], "replacement_id": choice}, catalog)):
                            st.rerun()
                end_text = st.text_input("新的当天截止时间 HH:MM", clock(day["end_min"]), key=f"{prefix}_{day['date']}_end_text")
                if st.button("更新截止时间并检查", key=f"{prefix}_{day['date']}_end"):
                    if _attempt(lambda: _edit_record(store, token, archive, {"kind": "end_time", "date": day["date"], "value": minutes(end_text)}, catalog)):
                        st.rerun()


def _detail(store, token, catalog, api_key):
    archive = _attempt(lambda: store.get_personal_trip(token, st.session_state.get("awp_selected", ""))) if token else None
    if not archive:
        st.warning("未找到此浏览器的个人 Trip，请从列表进入或使用自己的备份恢复。")
        return
    plan, prefix = archive["plan"], f"awp_{archive['id']}_{archive['revision']}"
    st.header(plan["requirements"]["title"])
    st.caption(f"日本时间 · 版本 {archive['revision']} · { {'draft':'筹备草案','on_trip':'当天使用中','ended':'已提前结束'}[archive['state']] }")
    st.caption(f"行程默认交通：{'步行' if plan['requirements']['mode'] == 'walk' else '公共交通'}；单段设置保留在各站和回程")
    cached = st.session_state.get("awp_check_cache", {})
    result = evaluate(plan, catalog, archive["events"], cached.get(archive["id"]))
    st.session_state["awp_check_cache"] = {archive["id"]: result}
    if archive["state"] == "on_trip":
        _today_focus(store, token, archive, result, catalog)
        if not st.checkbox("查看完整日程与编辑工具", key=f"awp_full_editor_{archive['id']}"):
            return
    _checks(result, catalog)
    if archive["state"] != "ended":
        with st.expander("编辑需求卡：日期、住宿、每日时间、作品与体力"):
            changed = _requirements_form(plan, catalog, f"{prefix}_requirements")
            if changed and _attempt(lambda: _edit_record(store, token, archive, {"kind": "requirements", "plan": changed}, catalog)):
                st.rerun()
    if archive["state"] == "draft":
        accept_unknown = st.checkbox("我知道仍有待核查内容，准备按草案使用当天清单", key=f"{prefix}_ack")
        if st.button("开始当天模式", key=f"{prefix}_begin", disabled=not accept_unknown or result["status"] == "conflict"):
            if _attempt(lambda: store.begin_personal_trip(token, archive["id"], archive["revision"], catalog)):
                st.rerun()
    places = {p["id"]: p for p in catalog["locations"]}
    if st.checkbox("查看每日地点地图（当前坐标）", key="awp_live_map"):
        from core.place_links import blocked
        for day in plan["days"]:
            rows = [{"lat": places[s["location_id"]]["lat"], "lon": places[s["location_id"]]["lon"]}
                    for s in day["stops"] if not blocked(places.get(s["location_id"]))]
            st.caption(day["date"] + " · 顺序与到访状态见当天清单")
            if rows:
                st.map(rows)
    if hasattr(store, "entries") and st.button("管理到访记录与照片", key="awp_journal"):
        from components.map_trip import open_handbook
        open_handbook("journal", awj_mode="足迹", awj_import_trip=archive["id"])
    _editor_days(store, token, archive, catalog, result)
    if archive["history"] and archive["state"] != "ended":
        with st.expander("撤销／恢复旧规划版本"):
            st.caption("保留最近 20 个规划版本；恢复会生成新版本，现场执行记录不会被撤销。")
            versions = [item["revision"] for item in reversed(archive["history"])]
            version = st.selectbox("恢复到版本", versions, key=f"{prefix}_restore_version")
            old = next(item["plan"] for item in archive["history"] if item["revision"] == version)
            st.write({"日期": old["requirements"]["start_date"], "天数": len(old["days"]), "各日站数": [len(d["stops"]) for d in old["days"]]})
            if st.button("确认恢复这个规划版本", key=f"{prefix}_undo"):
                if _attempt(lambda: store.restore_personal_version(token, archive["id"], archive["revision"], version)):
                    st.rerun()
    _ai_editor(store, token, archive, catalog, api_key)
    st.download_button("下载个人 Trip 文字清单", export_personal_checklist(archive, catalog).encode(), file_name="animeway-personal-trip.txt", mime="text/plain", key=f"{prefix}_download")
    st.caption("跨浏览器请到顶部「备份与反馈」下载完整备份，另一浏览器恢复后为独立副本，不自动同步。")
    with st.expander("删除这份个人 Trip"):
        confirm = st.checkbox("已备份并确认删除此 Trip 与其历史／执行记录", key=f"{prefix}_delete_confirm")
        if st.button("删除个人 Trip", key=f"{prefix}_delete", disabled=not confirm):
            def delete():
                store.delete_personal_trip(token, archive["id"], archive["revision"])
                return True
            if _attempt(delete):
                st.session_state["awp_mode"] = "list"
                st.rerun()


def _draft_detail(store, token, catalog, api_key):
    draft = _attempt(lambda: store.get_personal_draft(token, st.session_state.get("awp_draft_id", ""))) if token else None
    if not draft:
        st.warning("未找到这份未保存草案，请从草案列表重新打开。")
        return
    record = {**draft, "state": "draft", "events": [], "_draft": True}
    plan = draft["plan"]
    source_names = {"manual": "表单", "routebook": "智能路书", "map": "地图地点",
                    "handbook": "旧手册", "backpack": "临时背包"}
    st.header(plan["requirements"]["title"])
    st.caption(f"未保存草案 · 来源：{source_names.get(draft['source'], draft['source'])} · 日本时间 · 自动暂存于当前私人档案")
    st.caption("草案不会出现在已保存 Trip 中，也不包含在私人备份文件里；确认后点击下方保存。")
    result = render_draft_preview(plan, catalog)
    with st.expander("修改作品、日期、交通及每日条件"):
        changed = _requirements_form(plan, catalog, f"awp_draft_{draft['id']}_{draft['revision']}")
        if changed and _attempt(lambda: _edit_record(store, token, record,
                                                     {"kind": "requirements", "plan": changed}, catalog)):
            st.rerun()
    _editor_days(store, token, record, catalog, result)
    _ai_editor(store, token, record, catalog, api_key)
    if st.button("保存到我的行程", key=f"awp_commit_{draft['id']}_{draft['revision']}", type="primary"):
        saved = _attempt(lambda: store.commit_personal_draft(token, draft["id"], draft["revision"]))
        if saved:
            _open(saved["id"])
    with st.expander("删除未保存草案"):
        if st.button("删除这份草案", key=f"awp_discard_{draft['id']}_{draft['revision']}"):
            def discard():
                store.discard_personal_draft(token, draft["id"], draft["revision"])
                return True
            if _attempt(discard):
                st.session_state["awp_mode"] = "list"
                st.rerun()


def _ai_editor(store, token, archive, catalog, api_key):
    if archive["state"] == "ended":
        return
    with st.expander("可选 AI：提出局部修改，确认后应用"):
        policy = trip_ai.service_policy()
        usage = _attempt(lambda: store.ai_usage(token)) or {"calls": 0, "reserved_cny": 0}
        st.caption(f"今日此浏览器已调用 {usage['calls']} 次，个人上限 {policy['owner_limit']} 次；应用实例上限 {policy['daily_limit']} 次。此计数不是费用上限，实际账单由 DashScope 账号结算。")
        if not trip_ai.enabled(api_key):
            st.info("填写 DashScope / Qwen Key 后可生成 AI 修改预览；人工编辑与保存不需要 Key。")
        text = st.text_area("例如：把第二天提前一小时结束，保留锁定站", key=f"awp_ai_text_{archive['id']}", max_chars=2000)
        st.caption("只发送当前站点选择、时间条件、候选名称和这段指令，不发送住宿坐标、身份凭据或完整历史。")
        if st.button("生成修改预览", key=f"awp_ai_request_{archive['id']}", disabled=not trip_ai.enabled(api_key)):
            with st.spinner("正在整理局部修改；当前草案保持原状…"):
                preview = _attempt(lambda: trip_ai.request_edit(store, token, archive, text, catalog, api_key))
            if preview:
                st.session_state["awp_ai_preview"] = {"trip_id": archive["id"], **preview}
        preview = st.session_state.get("awp_ai_preview")
        if preview and preview.get("trip_id") == archive["id"]:
            if preview["base_revision"] != archive["revision"]:
                st.info("原行程已变化，旧 AI 预览已失效。请重新生成。")
            else:
                for diff in preview["diffs"]:
                    st.write(diff["description"])
                    # Render explicit before/after choices instead of model-authored factual explanations.
                    for before, after in zip(diff["before"]["days"], diff["after"]["days"]):
                        if before != after:
                            st.write(f"{before['date']}：截止 {clock(before['end_min'])} → {clock(after['end_min'])}")
                            st.write("修改前：" + " → ".join(f"{_name(catalog,s['location_id'])} {s['stay_min']}分" for s in before['stops']))
                            st.write("修改后：" + " → ".join(f"{_name(catalog,s['location_id'])} {s['stay_min']}分" for s in after['stops']))
                _checks(preview["evaluation"], catalog)
                if st.button("确认应用这些 AI 修改", key=f"awp_ai_apply_{archive['id']}"):
                    def action():
                        if archive.get("_draft"):
                            return store.apply_draft_ai_operations(
                                token, archive["id"], preview["base_revision"], preview["operations"], catalog)
                        return store.apply_ai_operations(
                            token, archive["id"], preview["base_revision"], preview["operations"], catalog)
                    if _attempt(action):
                        st.session_state.pop("awp_ai_preview", None)
                        st.rerun()


def render_personal_trips(store, token, catalog, api_key=""):
    st.title("我的行程 · 东京 1—3 日")
    st.caption("按作品、日期、住宿和体力建立草案；修改自动暂存，确认后保存到我的行程。交通能力以核查状态为准。")
    if current_locale() != "zh_CN":
        st.caption("Trip editor content is currently in Chinese. Switching language does not change saved data. / 旅程編集は現在中国語です。言語切替で保存データは変わりません。")
    a, b = st.columns(2)
    with a:
        if st.button("规划新行程", key="awp_new"):
            _open()
    with b:
        if st.button("返回行程列表", key="awp_list"):
            st.session_state["awp_mode"] = "list"
            st.rerun()
    if not token:
        st.info("匿名身份尚未就绪；可以编辑候选需求，但连接完成前不能保存。")
    mode = st.session_state.get("awp_mode", "list")
    if mode == "new":
        _new(store, token, catalog, api_key)
    elif mode == "draft":
        _draft_detail(store, token, catalog, api_key)
    elif mode == "detail":
        _detail(store, token, catalog, api_key)
    else:
        drafts = _attempt(lambda: store.list_personal_drafts(token)) if token else []
        if drafts:
            st.subheader("未保存草案")
            for draft in drafts:
                with st.container(border=True):
                    st.write(draft["plan"]["requirements"]["title"])
                    st.caption(f"{draft['plan']['requirements']['start_date']} · {len(draft['plan']['days'])} 日 · 最后修改 {draft['updated_at']}")
                    if st.button("继续修改草案", key=f"awp_open_draft_{draft['id']}"):
                        open_draft(draft["id"])
        st.subheader("已保存的行程")
        trips = _attempt(lambda: store.list_personal_trips(token)) if token else []
        if not trips:
            st.info("还没有已保存的行程。可从两部试点作品开始，或从手册创建草案。")
        for trip in trips or []:
            with st.container(border=True):
                st.write(trip["plan"]["requirements"]["title"])
                st.caption(f"{trip['plan']['requirements']['start_date']} · {len(trip['plan']['days'])} 日 · 版本 {trip['revision']}")
                if st.button("继续这份行程", key=f"awp_open_{trip['id']}"):
                    _open(trip["id"])
