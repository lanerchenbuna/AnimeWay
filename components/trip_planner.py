"""Form-first personal Trip workflow, including local edits and today's mode."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
import sqlite3
import time

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
    st.session_state.pop("awp_ai_preview", None)
    if rerun:
        st.rerun()


def _adopt(store, token, plan):
    saved = _attempt(lambda: store.create_personal_trip(token, plan))
    if saved:
        origin = st.session_state.get("awj_origin", {})
        if hasattr(store, "record_journey_event") and 0 <= time.time() - origin.get("at", 0) <= 1800 and any(s["location_id"] == origin.get("location_id") for d in plan["days"] for s in d["stops"]):
            _attempt(lambda: store.record_journey_event(token, "update_trip_created", origin["location_id"], "update"))
            st.session_state.pop("awj_origin", None)
        _open(saved["id"], rerun=False)


def _name(catalog, location_id):
    point = next((p for p in catalog["locations"] if p["id"] == location_id), None)
    return point["name"] if point else f"已失效地点 {location_id}"


def _anchor_input(anchor, catalog, prefix, label):
    places = {p["id"]: p["name"] for p in catalog["locations"] if not p.get("withdrawn") and (p.get("access") or {}).get("status") not in {"closed", "prohibited"}}
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
        title = st.text_input("Trip 名称", req["title"], key=f"{prefix}_title", max_chars=300)
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


def _new(store, token, catalog, api_key):
    st.subheader("建立 1—3 日个人 Trip")
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
    for index, option in enumerate(st.session_state.get("awp_options", [])):
        with st.container(border=True):
            st.subheader(option["label"])
            st.write(option["reason"])
            for day in option["plan"]["days"]:
                st.write(f"{day['date']} · {clock(day['start_min'])}—{clock(day['end_min'])}")
                st.write(" → ".join(_name(catalog, stop["location_id"]) for stop in day["stops"]) or "未找到符合所选作品的候选地点")
            _checks(evaluate(option["plan"], catalog), catalog)
            st.button("保存这份个人 Trip 草案", key=f"awp_adopt_{index}", disabled=not token, type="primary",
                      on_click=_adopt, args=(store, token, option["plan"]))


def _local_edit(store, token, archive, day, stop, catalog):
    prefix = f"awp_edit_{archive['id']}_{archive['revision']}_{stop['location_id']}"
    with st.expander("编辑此站：停留、顺序、替换、锁定"):
        st.caption("锁定同时保护站点位置和停留；要改变核心项，请先人工解锁。已执行部分不接受规划修改。")
        st.caption("停留为经验建议：轻松节奏约 20—40 分钟，普通节奏约 10—25 分钟；请按拍摄与体力调整。")
        choices = {"stay": "调整停留", "move": "调整顺序", "replace": "替换地点", "remove": "删除可选站", "lock": "锁定／解锁", "appointment": "预约／关闭截止时间", "visit_mode": "公共区域外观／计划入内"}
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
            if _attempt(lambda: store.edit_personal_trip(token, archive["id"], archive["revision"], operation, catalog)):
                st.rerun()


def _today(store, token, archive, checked_day, catalog):
    if archive["state"] != "on_trip" or checked_day["ended"]:
        return
    pending = checked_day["next_id"]
    st.markdown(f"**当前待处理站：{_name(catalog, pending) if pending else '当天站点已处理完'}**")
    following = [row for row in checked_day["rows"] if row["outcome"] == "pending"]
    if len(following) > 1:
        st.caption(f"下一站：{_name(catalog, following[1]['location_id'])}")
    prefix = f"awp_today_{archive['id']}_{archive['revision']}_{checked_day['date']}"
    current = st.text_input("现场当地时间 HH:MM（请确认）", datetime.now(TOKYO).strftime("%H:%M"), key=f"{prefix}_time")
    labels = {"visit": "我已到访此站", "skip": "跳过此站", "closed": "此站临时关闭", "delay": "报告迟到／当前时间", "end_day": "提前结束当天", "end_trip": "提前结束整趟旅行"}
    kind = st.selectbox("当天操作", list(labels), format_func=labels.get, key=f"{prefix}_kind")
    st.caption("到访仅由你主动确认；跳过和关闭不会计为到访。迟到后仅调整剩余安排，原执行记录保留。")
    confirm = st.checkbox("确认记录这次现场操作", key=f"{prefix}_confirm")
    if st.button("记录并检查剩余安排", key=f"{prefix}_record", disabled=not confirm):
        if _attempt(lambda: store.record_personal_event(token, archive["id"], archive["revision"], checked_day["date"], kind, minutes(current), catalog)):
            st.rerun()


def export_personal_checklist(archive, catalog):
    from components.pilgrimage import navigation_url

    result = evaluate(archive["plan"], catalog, archive["events"])
    req = archive["plan"]["requirements"]
    lines = [req["title"], f"版本 {archive['revision']} · {req['timezone']} · 状态 {archive['state']}",
             "个人筹备草案，非已验证行程。此文字文件可离线读取；外部导航需网络，无图片／离线地图。", result["promise"], ""]
    for day, check in zip(archive["plan"]["days"], result["days"]):
        lines.extend([f"{day['date']} {clock(day['start_min'])}—{clock(day['end_min'])}",
                      f"起点：{day['start']['name']}（{'已确认' if day['start']['confirmed'] else '未确认'}）",
                      f"终点：{day['end']['name']}（{'已确认' if day['end']['confirmed'] else '未确认'}）",
                      f"用餐 {day['meal_min']} / 休息 {day['break_min']} / 余量 {day['buffer_min']} 分钟；费用未知"])
        for index, row in enumerate(check["rows"], 1):
            point = next((p for p in catalog["locations"] if p["id"] == row["location_id"]), None)
            lines.extend([f"{index}. {_name(catalog, row['location_id'])} · {row['outcome']}",
                          f"停留建议 {row['stop']['stay_min']} 分钟；{'必去' if row['stop']['priority']=='required' else '可选'}"])
            if point:
                lines.extend([(point.get("access") or {}).get("summary", "访问状态未知"), point.get("entry", ""), point.get("viewpoint", ""), point.get("source_url", ""),
                              f"{point['lat']:.6f}, {point['lon']:.6f}"])
                if not point.get("withdrawn") and (point.get("access") or {}).get("status") not in {"prohibited", "closed"} and row["outcome"] == "pending":
                    lines.append(navigation_url(point))
            if row.get("leg"):
                lines.append(row["leg"]["reason"])
        lines.append("")
    lines.append("行前仍需检查：")
    lines.extend(f"{i['date']} {_name(catalog, i['location_id']) if i['location_id'] else ''}：{i['message']}" for i in result["issues"])
    return '\n'.join(lines)


def _detail(store, token, catalog, api_key):
    archive = _attempt(lambda: store.get_personal_trip(token, st.session_state.get("awp_selected", ""))) if token else None
    if not archive:
        st.warning("未找到此浏览器的个人 Trip，请从列表进入或使用自己的备份恢复。")
        return
    plan, prefix = archive["plan"], f"awp_{archive['id']}_{archive['revision']}"
    st.header(plan["requirements"]["title"])
    st.caption(f"日本时间 · 版本 {archive['revision']} · { {'draft':'筹备草案','on_trip':'当天使用中','ended':'已提前结束'}[archive['state']] }")
    cached = st.session_state.get("awp_check_cache", {})
    result = evaluate(plan, catalog, archive["events"], cached.get(archive["id"]))
    st.session_state["awp_check_cache"] = {archive["id"]: result}
    _checks(result, catalog)
    if archive["state"] != "ended":
        with st.expander("编辑需求卡：日期、住宿、每日时间、作品与体力"):
            changed = _requirements_form(plan, catalog, f"{prefix}_requirements")
            if changed and _attempt(lambda: store.edit_personal_trip(token, archive["id"], archive["revision"], {"kind": "requirements", "plan": changed}, catalog)):
                st.rerun()
    if archive["state"] == "draft":
        accept_unknown = st.checkbox("我知道仍有待核查内容，准备按草案使用当天清单", key=f"{prefix}_ack")
        if st.button("开始当天模式", key=f"{prefix}_begin", disabled=not accept_unknown or result["status"] == "conflict"):
            if _attempt(lambda: store.begin_personal_trip(token, archive["id"], archive["revision"], catalog)):
                st.rerun()
    places = {p["id"]: p for p in catalog["locations"]}
    for day, check in zip(plan["days"], result["days"]):
        st.subheader(f"{day['date']} · {clock(day['start_min'])}—{clock(day['end_min'])}")
        st.write(f"{day['start']['name']} → {day['end']['name']}")
        totals = check["totals"]
        st.caption(f"移动 {totals['moving_min'] if totals['moving_min'] is not None else '未知'} / 等待 {totals['waiting_min'] if totals['waiting_min'] is not None else '未知'} / 停留 {totals['stay_min']} / 用餐 {totals['meal_min']} / 休息 {totals['break_min']} / 余量 {totals['buffer_min']} 分钟")
        if archive["state"] == "on_trip":
            st.caption("以上为剩余安排预算；系统不推测你是否已用餐或休息，可在需求卡主动调整剩余预留。")
        st.caption(f"步行草案{'合计' if totals['walk_complete'] else '已估算部分'} {totals['walk_m']/1000:.1f} km；交通与场所费用合计未知。预计结束 {clock(check['finish_min'])}（草案）")
        _today(store, token, archive, check, catalog)
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
                                if scene["location_id"] == point["id"]:
                                    _scene(scene, catalog)
                    if archive["state"] != "ended":
                        _local_edit(store, token, archive, day, stop, catalog)
                elif row.get("actual_min") is not None:
                    st.caption(f"用户记录时间 {clock(row['actual_min'])}；不从计划时间推断到访")
        st.caption(f"到终点的连接：{check['return_leg']['reason']}")
        if archive["state"] != "ended" and not check["ended"]:
            with st.expander("增加相关场景／缩短当天时间"):
                pool = {p["id"]: p["name"] for p in candidates(plan, catalog) if p["id"] not in {s["location_id"] for d in plan["days"] for s in d["stops"]}}
                if pool:
                    choice = st.selectbox("可增加地点", list(pool), format_func=pool.get, key=f"{prefix}_{day['date']}_add_choice")
                    if st.button("增加到当天末尾并检查", key=f"{prefix}_{day['date']}_add"):
                        if _attempt(lambda: store.edit_personal_trip(token, archive["id"], archive["revision"], {"kind": "add", "date": day["date"], "replacement_id": choice}, catalog)):
                            st.rerun()
                end_text = st.text_input("新的当天截止时间 HH:MM", clock(day["end_min"]), key=f"{prefix}_{day['date']}_end_text")
                if st.button("更新截止时间并检查", key=f"{prefix}_{day['date']}_end"):
                    if _attempt(lambda: store.edit_personal_trip(token, archive["id"], archive["revision"], {"kind": "end_time", "date": day["date"], "value": minutes(end_text)}, catalog)):
                        st.rerun()
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


def _ai_editor(store, token, archive, catalog, api_key):
    if archive["state"] == "ended":
        return
    with st.expander("可选 AI：提出局部修改，确认后应用"):
        policy = trip_ai.service_policy()
        usage = _attempt(lambda: store.ai_usage(token)) or {"calls": 0, "reserved_cny": 0}
        st.caption(f"今日此浏览器 {usage['calls']} 次／预留预算 ¥{usage['reserved_cny']:.4f}。服务每日上限 {policy['daily_limit']} 次／¥{policy['budget_units']/1e6:.2f}；每次预留 ¥{policy['reserve_units']/1e6:.4f}。预留额不是实际账单。")
        if not trip_ai.enabled(api_key):
            st.info("未配置 AI Key 或服务预算，人工编辑与保存均可使用。")
        text = st.text_area("例如：把第二天提前一小时结束，保留锁定站", key=f"awp_ai_text_{archive['id']}", max_chars=2000)
        st.caption("只发送当前站点选择、时间条件、候选名称和这段指令，不发送住宿坐标、身份凭据或完整历史。")
        if st.button("生成修改预览", key=f"awp_ai_request_{archive['id']}", disabled=not trip_ai.enabled(api_key)):
            with st.spinner("正在整理局部修改；原行程保持保存状态…"):
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
                    if _attempt(lambda: store.apply_ai_operations(token, archive["id"], preview["base_revision"], preview["operations"], catalog)):
                        st.session_state.pop("awp_ai_preview", None)
                        st.rerun()


def render_personal_trips(store, token, catalog, api_key=""):
    st.title("个人 Trip · 东京 1—3 日")
    st.caption("v0.9 草案模式：按作品、日期、住宿和体力筹备；所有交通能力以核查状态为准。")
    if current_locale() != "zh_CN":
        st.caption("Trip editor content is currently in Chinese. Switching language does not change saved data. / 旅程編集は現在中国語です。言語切替で保存データは変わりません。")
    a, b = st.columns(2)
    with a:
        if st.button("新建个人 Trip", key="awp_new"):
            _open()
    with b:
        if st.button("返回我的 Trip 列表", key="awp_list"):
            st.session_state["awp_mode"] = "list"
            st.rerun()
    if not token:
        st.info("匿名身份尚未就绪；可以编辑候选需求，但连接完成前不能保存。")
    mode = st.session_state.get("awp_mode", "list")
    if mode == "new":
        _new(store, token, catalog, api_key)
    elif mode == "detail":
        _detail(store, token, catalog, api_key)
    else:
        trips = _attempt(lambda: store.list_personal_trips(token)) if token else []
        if not trips:
            st.info("还没有个人 Trip。可从两部试点作品开始，或从已保存手册转为个人安排。")
        for trip in trips or []:
            with st.container(border=True):
                st.write(trip["plan"]["requirements"]["title"])
                st.caption(f"{trip['plan']['requirements']['start_date']} · {len(trip['plan']['days'])} 日 · 版本 {trip['revision']}")
                if st.button("继续这份个人 Trip", key=f"awp_open_{trip['id']}"):
                    _open(trip["id"])
