"""Private journal, explicit public preview and consent-based rediscovery."""
from __future__ import annotations

from datetime import date
from html import escape
import os
import time

import streamlit as st

from core import contributions as c
from core.place_links import places
from core.journal import encode_photo, share_card_svg, today
from core.private_store import _now
from components.trip_planner import _attempt


def photo_inline(data, *, label="个人照片"):
    # Inline data avoids creating an unauthenticated Streamlit media URL.
    st.markdown(f'<img alt="{escape(label, quote=True)}" src="data:image/jpeg;base64,{encode_photo(data)}" style="width:100%;max-width:640px;border-radius:12px">',
                unsafe_allow_html=True)


def _place_names(catalog):
    return {key: p["name"] for key, p in places(catalog).items()}


def _ai_budget(store, token):
    from core.trip_ai import service_policy
    usage, policy = store.ai_usage(token), service_policy()
    st.caption(f"此浏览器今日 {usage['calls']} 次，预留 ¥{usage['reserved_cny']:.4f}；服务每日 {policy['daily_limit']} 次／预留 ¥{policy['budget_units']/1e6:.2f}。预留并非实际账单。")


def render_journal(store, token, catalog, api_key=""):
    st.title("我的巡礼记录")
    st.caption("默认私密；到访由你确认，不读取连续定位。足迹撤销不改写 Trip 原始现场日志，个人足迹以这里的确认状态为准。")
    if not token:
        st.info("请等待匿名身份连接后保存记录。")
        return
    pending = st.session_state.pop("awj_pending_entry", None)
    if pending and any(e["id"] == pending for e in store.entries(token)):
        st.session_state.update(awj_mode="照片与短文", awj_edit_entry=pending)
    mode = st.radio("记录工作区", ["足迹", "照片与短文", "分享", "贡献", "记录备份"], horizontal=True, key="awj_mode")
    if mode == "足迹":
        _footprints(store, token, catalog)
    elif mode == "照片与短文":
        _photos_and_text(store, token, catalog, api_key)
    elif mode == "分享":
        _sharing(store, token, catalog)
    elif mode == "贡献":
        render_contributions(store, token, catalog)
    else:
        _backup(store, token, catalog)


def _footprints(store, token, catalog):
    trips = store.list_personal_trips(token)
    with st.expander("从 Trip 导入已确认到访"):
        if trips:
            labels = {t["id"]: t["plan"]["requirements"]["title"] for t in trips}
            tid = st.selectbox("选择旅行", list(labels), format_func=labels.get, key="awj_import_trip")
            st.caption("仅导入已明确到访且日期不在未来的站点；计划、跳过、临时关闭不成为到访。重复导入不会复活已删除或已撤销的记录。")
            if st.button("确认导入到访记录", key="awj_import_visits"):
                count = _attempt(lambda: store.import_visits(token, tid, catalog))
                if count is not None:
                    st.success(f"新增 {count} 条记录")
        else:
            st.caption("没有个人 Trip，仍可直接补记到访。")
    names = _place_names(catalog)
    with st.expander("补记一次到访"):
        with st.form("awj_new_entry"):
            lid = st.selectbox("到访地点", list(names), format_func=names.get, key="awj_new_place")
            when = st.date_input("实际到访日期", value=today(), max_value=today(), key="awj_new_date")
            stay = st.number_input("实际停留分钟（不清楚则留空）", min_value=1, max_value=1440, value=None, key="awj_new_stay")
            note = st.text_area("私人笔记", max_chars=3000, key="awj_new_note")
            confirm = st.checkbox("我确认实际到访了该地点", key="awj_new_confirm")
            submit = st.form_submit_button("保存私密足迹")
        if submit:
            if not confirm:
                st.error("尚未确认到访，未生成足迹")
            elif _attempt(lambda: store.save_entry(token, location_id=lid, visited_on=when.isoformat(), confirmed=True, note=note, stay_min=stay, catalog=catalog)):
                st.success("足迹已保存")
    entries = store.entries(token)
    confirmed = [e for e in entries if e["confirmed"]]
    planned = {s["location_id"] for t in trips for d in t["plan"]["days"] for s in d["stops"]}
    skipped = {e["location_id"] for t in trips for e in t["events"] if e["kind"] == "skip"}
    st.write(f"确认到访 {len(confirmed)} 次 / {len({e['location_id'] for e in confirmed})} 个地点；Trip 中计划地点 {len(planned)} 个、明确跳过 {len(skipped)} 个（口径独立）。")
    if confirmed and st.checkbox("查看个人足迹地图", key="awj_map"):
        live_places = places(catalog)
        rows = [{"lat": live_places[e["location_id"]]["lat"], "lon": live_places[e["location_id"]]["lon"]} for e in confirmed if e["location_id"] in live_places and not live_places[e["location_id"]].get("withdrawn")]
        if rows:
            st.map(rows)
    for entry in sorted(entries, key=lambda e: e["date"], reverse=True):
        with st.container(border=True):
            st.write(f"{entry['date']} · {names.get(entry['location_id'], '原地点已失效')} · {'已到访' if entry['confirmed'] else '已撤销到访'}")
            st.text(entry["note"])
            if st.button("撤销到访" if entry["confirmed"] else "重新确认到访", key=f"awj_toggle_{entry['id']}_{entry['revision']}"):
                if _attempt(lambda e=entry: store.save_entry(token, location_id=e["location_id"], visited_on=e["date"],
                    confirmed=not e["confirmed"], note=e["note"], short_text=e["short_text"], stay_min=e["stay_min"],
                    entry_id=e["id"], revision=e["revision"], catalog=catalog)):
                    st.rerun()
            with st.expander("删除记录及其照片"):
                st.caption("会撤下引用这些照片的分享；已被别人保存的副本、文件与截图无法远程收回。")
                check = st.checkbox("确认永久删除", key=f"awj_delete_confirm_{entry['id']}")
                if st.button("删除记录", key=f"awj_delete_{entry['id']}", disabled=not check):
                    _attempt(lambda e=entry: store.delete_entry(token, e["id"], e["revision"]))
                    st.rerun()


def _fill_short(store, token, entry_id, catalog, key):
    draft = _attempt(lambda: store.short_draft(token, entry_id, catalog))
    if draft:
        st.session_state[key] = draft


def _photos_and_text(store, token, catalog, api_key):
    entries = store.entries(token)
    if not entries:
        st.info("先确认或补记一次到访，再整理照片。")
        return
    names = _place_names(catalog)
    options = {e["id"]: f"{e['date']} · {names.get(e['location_id'], e['location_id'])}" for e in entries}
    entry_id = st.selectbox("选择记录", list(options), format_func=options.get, key="awj_edit_entry")
    entry = next(e for e in entries if e["id"] == entry_id)
    key = f"awj_record_{entry_id}_{entry['revision']}"
    with st.form(f"{key}_form"):
        when = st.date_input("更正到访日期", value=date.fromisoformat(entry["date"]), max_value=today())
        note = st.text_area("私人笔记（不会自动进入分享）", value=entry["note"], max_chars=3000)
        short = st.text_area("可编辑短文（仍为私密）", value=st.session_state.get("awj_short_seed", {}).get(entry_id, entry["short_text"]), max_chars=2000, key=f"{key}_short")
        stay = st.number_input("实际停留分钟", 1, 1440, entry["stay_min"])
        submit = st.form_submit_button("保存记录与短文")
    if submit and _attempt(lambda: store.save_entry(token, location_id=entry["location_id"], visited_on=when.isoformat(),
            confirmed=entry["confirmed"], note=note, short_text=short, stay_min=stay, entry_id=entry_id, revision=entry["revision"], catalog=catalog)):
        st.session_state.pop("awj_short_seed", None)
        st.rerun()
    st.button("根据确认到访整理短句（无需 AI）", key="awj_short",
              on_click=_fill_short, args=(store, token, entry_id, catalog, f"{key}_short"))
    st.caption("只使用你确认的到访和实际停留，不添加天气、心情或虚构经历；你可以自行改写。")
    from core import journal_ai, trip_ai
    with st.expander("可选 AI 整理短句顺序"):
        _ai_budget(store, token)
        st.caption("仅发送已确认的地点短句和实际停留，不发送照片、日期、笔记或住宿。与 Trip AI 共用服务次数和预留预算；原短文在确认前不变。")
        if st.button("生成短句顺序预览", key="awj_ai_short", disabled=not trip_ai.enabled(api_key)):
            draft = _attempt(lambda: journal_ai.order_record(store, token, entry_id, catalog, api_key))
            if draft:
                st.session_state["awj_ai_short_preview"] = {"id": entry_id, "revision": entry["revision"], "text": draft}
        draft = st.session_state.get("awj_ai_short_preview")
        if draft and draft["id"] == entry_id:
            st.text(draft["text"])
            if st.button("确认保存整理短文", disabled=draft["revision"] != entry["revision"], key="awj_ai_short_apply"):
                if _attempt(lambda: store.save_entry(token, location_id=entry["location_id"], visited_on=entry["date"], confirmed=entry["confirmed"],
                    note=entry["note"], short_text=draft["text"], stay_min=entry["stay_min"], entry_id=entry_id, revision=draft["revision"], catalog=catalog)):
                    st.session_state.pop("awj_ai_short_preview", None)
                    st.rerun()
    photos = store.photos(token, entry_id)
    scenes = {"": "暂不配对具体场景", **{s["id"]: s["title"] for s in catalog["scenes"] if s["location_id"] == entry["location_id"]}}
    with st.expander("上传／替换个人照片"):
        st.caption("移除 EXIF/GPS；不自动识别机位或验真。每张原图 ≤8 MiB／2000 万像素，保存压缩 JPEG，每身份最多 50 张。原作图不会进入公开合成图。")
        with st.form("awj_photo_form", clear_on_submit=True):
            replace = st.selectbox("新增或替换", [""] + [p["id"] for p in photos], format_func=lambda i: "新增照片" if not i else f"替换照片 {i[:8]}")
            upload = st.file_uploader("个人照片", type=["jpg", "jpeg", "png", "webp"], key="awj_upload")
            taken = st.date_input("拍摄日期", value=date.fromisoformat(entry["date"]), max_value=today(), key="awj_taken")
            scene = st.selectbox("对应场景", list(scenes), format_func=scenes.get, key="awj_scene")
            rights = st.selectbox("照片授权", ["private_only", "own"], format_func={"private_only": "仅私密保管，不确认公开使用权", "own": "本人拍摄且有权公开使用"}.get)
            scope = st.checkbox("允许我稍后在预览中选择此照片分享（此处不会公开）")
            caption = st.text_input("私人照片说明", max_chars=500)
            submitted = st.form_submit_button("保存个人照片")
        if submitted:
            if not upload:
                st.error("请先选择照片")
            elif _attempt(lambda: store.save_photo(token, entry_id, upload.getvalue(), taken_on=taken.isoformat(),
                rights=rights, scope="share_allowed" if scope else "private", scene_id=scene, caption=caption,
                replace_id=replace or None, catalog=catalog)):
                st.rerun()
    for photo in photos:
        with st.container(border=True):
            photo_inline(photo["image"])
            st.caption(f"{photo['taken_on']} · {'允许后续选择分享' if photo['scope']=='share_allowed' else '私密'}")
            st.text(photo["caption"])
            st.write(scenes.get(photo["scene_id"], "原场景已失效，配对待核查"))
            linked = next((s for s in catalog["scenes"] if s["id"] == photo["scene_id"]), None)
            point = places(catalog).get(entry["location_id"])
            media = (linked or {}).get("media") or {}
            from data_factory.normalization import safe_url
            url = safe_url(media.get("url") or media.get("reference_url"))
            if linked and linked.get("location_id") == entry["location_id"] and not linked.get("upstream_removed") and point and not point.get("withdrawn") and media.get("display_allowed") and url:
                if st.checkbox("查看获许可的场景图进行对照（不写入照片或分享）", key="awj_compare_" + photo["id"]):
                    st.image(url, caption=media.get("attribution") or "场景来源")
            else:
                st.caption("场景图展示许可未确认或已失效；个人照片仍为独立私密记录。")
            if linked and safe_url(linked.get("source_url")):
                st.link_button("查看原作关联来源（不合成原作图）", safe_url(linked["source_url"]))
            with st.expander("调整照片使用范围"):
                with st.form(f"awj_scope_{photo['id']}"):
                    rights = st.selectbox("使用权确认", ["private_only", "own"], index=0 if photo["rights"]=="private_only" else 1,
                                          format_func={"private_only":"仅私密保管", "own":"本人拍摄且有权公开使用"}.get)
                    sharing = st.checkbox("允许以后明确选择分享", value=photo["scope"]=="share_allowed")
                    submitted = st.form_submit_button("更新范围并撤下旧分享")
                if submitted:
                    def update_scope():
                        store.photo_scope(token, photo["id"], rights, "share_allowed" if sharing else "private")
                        return True
                    if _attempt(update_scope):
                        st.rerun()
            if st.button("删除这张照片并撤下引用分享", key=f"awj_delete_photo_{photo['id']}"):
                _attempt(lambda p=photo: store.delete_photo(token, p["id"]))
                st.rerun()


def _sharing(store, token, catalog):
    trips = store.list_personal_trips(token)
    st.caption("公开链接可由持有链接的人访问。预览默认不含酒店、具体日期、私有笔记、到访日志、照片拍摄日期或身份。标题与分享短文请自行检查，照片需另行选择。")
    if trips:
        labels = {t["id"]: t["plan"]["requirements"]["title"] for t in trips}
        tid = st.selectbox("选择要分享的个人路线", list(labels), format_func=labels.get, key="awj_share_trip")
        trip = next(t for t in trips if t["id"] == tid)
        choices = {p["id"]: f"个人照片 {i + 1}" for i, p in enumerate(store.photos(token)) if p["scope"] == "share_allowed"}
        with st.form("awj_share_form"):
            title = st.text_input("公开标题", value="东京巡礼路线", max_chars=120, key="awj_public_title")
            text = st.text_area("公开短文（默认空白，不复制私人笔记）", max_chars=1200, key="awj_public_text")
            selected = st.multiselect("明确选择公开照片", list(choices), format_func=choices.get, key="awj_public_photos")
            preview = st.form_submit_button("生成发布预览")
        if preview:
            public = _attempt(lambda: store.preview_share(token, tid, catalog, title=title, text=text, photo_ids=selected))
            if public:
                st.session_state["awj_share_preview"] = {"trip_id": tid, "revision": trip["revision"], "public": public}
        draft = st.session_state.get("awj_share_preview")
        if draft and draft["trip_id"] == tid:
            public = draft["public"]
            st.subheader("即将公开的副本")
            st.text(public["title"])
            st.text(public["text"])
            for day in public["days"]:
                st.write(f"第 {day['day']} 天：" + " → ".join(s["name"] for s in day["stops"]))
            for photo in store.photos(token):
                if photo["id"] in public["photo_ids"]:
                    photo_inline(photo["image"], label="即将分享的本人照片")
            confirm = st.checkbox("已检查标题、短文和照片中的隐私，确认发布此预览", key="awj_publish_confirm")
            if st.button("发布公开路线副本", key="awj_publish", disabled=not confirm):
                sid = _attempt(lambda: store.publish_share(token, tid, draft["revision"], public, catalog))
                if sid:
                    st.session_state.pop("awj_share_preview", None)
                    st.success("已生成可撤下的分享链接")
    for shared in store.shares(token):
        with st.container(border=True):
            st.write(shared["title"])
            if shared["active"]:
                relative = f"?share={shared['id']}"
                st.link_button("打开公开副本", relative)
                base = os.getenv("ANIMEWAY_PUBLIC_URL", "").rstrip("/")
                st.code(f"{base}/{relative}" if base else relative, language=None)
                st.caption("未配置公开站点地址时显示相对链接；可打开后复制浏览器地址。公开站点请配置 ANIMEWAY_PUBLIC_URL。")
                public = store.public_share(shared["id"], catalog)
                if public:
                    st.download_button("下载不含原作图的文字分享卡 SVG", share_card_svg(public), file_name="animeway-route-card.svg", mime="image/svg+xml", key=f"awj_card_{shared['id']}")
                if st.button("撤下此分享", key=f"awj_revoke_{shared['id']}"):
                    _attempt(lambda s=shared: store.revoke_share(token, s["id"]))
                    st.rerun()
            else:
                st.caption("已撤下，链接不再提供路线和照片。外部已保存副本无法远程收回。")


def render_public_share(store, token, catalog, share_id):
    st.title("AnimeWay · 公开路线副本")
    public = store.public_share(share_id, catalog) if store else None
    if not public:
        st.warning("此分享不存在或已撤下")
        return
    st.text(public["title"])
    st.text(public["text"])
    st.caption(public["warning"])
    places = _place_names(catalog)
    for day in public["days"]:
        st.subheader(f"第 {day['day']} 天")
        for stop in day["stops"]:
            st.write(f"{places.get(stop['location_id'], stop['name'])} · {'核心' if stop['required'] else '可选'} · 停留建议 {stop['stay_min']} 分钟")
    for data in public["photos"]:
        photo_inline(data, label="分享者明确公开的本人照片")
    from core.place_links import places as current_places
    copy_places = current_places(catalog)
    rows = [{'id': s['location_id'], 'name': copy_places.get(s['location_id'], {}).get('name', s['name']),
             'status': 'missing' if s['location_id'] not in copy_places else 'withdrawn' if copy_places[s['location_id']].get('withdrawn') else copy_places[s['location_id']].get('access', {}).get('status', 'unknown')}
            for day in public['days'] for s in day['stops']]
    st.subheader("复制预览：地点与访问状态")
    st.dataframe(rows, hide_index=True, width="stretch")
    start = st.date_input("复制后我的开始日期（日本时间）", value=today(), key="awj_copy_date")
    st.caption("复制仅得到路线选择，起终点需你补全；不获取原用户日期、住宿、照片原档或私有记录。")
    copy_preview = _attempt(lambda: store.preview_copy_share(share_id, start.isoformat(), catalog))
    if copy_preview:
        st.caption(copy_preview['check']['promise'])
        for issue in copy_preview['check']['issues']:
            st.warning(issue['message'])

    if st.button("复制为我的个人 Trip", disabled=not token or copy_preview is None, key="awj_copy_share"):
        trip = _attempt(lambda: store.copy_share(token, share_id, start.isoformat(), catalog))
        if trip:
            st.query_params.clear()
            st.session_state.update(aw_page="personal", awp_mode="detail", awp_selected=trip["id"],
                                    aw_my_view="personal", aw_pending_tab="trips")
            st.rerun()


def render_contributions(store, token, catalog):
    names = _place_names(catalog)
    st.caption(f"重点问题目标 7 天内更新处理状态；不是保证完成事实核查。新增点位采用邀请制，队列达到 {c.capacity()} 条暂停扩投稿。原有纠错仍在「备份与反馈」查看。")
    with st.expander("兑换新增地点邀请"):
        invitation = st.text_input("维护者邀请码", type="password", key="awj_invitation")
        if st.button("兑换邀请", key="awj_redeem"):
            _attempt(lambda: c.redeem_invite(store, token, invitation))
    with st.form("awj_contribution_form"):
        kind = st.selectbox("投稿类型", ["correction", "new_location"], format_func={"correction": "现有地点纠错", "new_location": "邀请制新增地点"}.get)
        lid = st.selectbox("纠错关联地点", list(names), format_func=names.get, key="awj_contribution_location")
        description = st.text_area("问题、现场变化与证据说明", max_chars=3000)
        evidence = st.text_input("证据来源链接（不自动抓取）", max_chars=2048)
        observed = st.date_input("观察／查证日期", max_value=today(), value=today())
        with st.expander("新增地点资料（仅新增时填写）"):
            name = st.text_input("当地名称", max_chars=300)
            lat = st.number_input("候选纬度", 35.4, 35.9, 35.68, format="%.6f")
            lon = st.number_input("候选经度", 139.3, 139.95, 139.70, format="%.6f")
            work = st.selectbox("关联作品", [a["id"] for a in catalog["anime"]], format_func={a["id"]: a["cn"] for a in catalog["anime"]}.get)
            region = st.selectbox("东京片区", [d["id"] for d in catalog["destinations"]], format_func={d["id"]: d["name"] for d in catalog["destinations"]}.get)
        submitted = st.form_submit_button("提交供人工核验")
    if submitted:
        proposal = {"name": name, "lat": lat, "lon": lon, "anime_id": work, "destination_id": region} if kind == "new_location" else None
        if _attempt(lambda: c.submission(store, token, kind=kind, location_id=lid if kind == "correction" else "",
                description=description, evidence_url=evidence, observed_on=observed.isoformat(), proposal=proposal, catalog=catalog)):
            st.success("已提交，公共地点资料未被自动覆盖")
    labels = {"pending": "待审核", "needs_info": "待补充", "accepted": "已采纳", "rejected": "已拒绝", "withdrawn": "已回撤"}
    for item in c.own_submissions(store, token):
        with st.expander(f"{labels[item['status']]} · {item['created_at'][:10]} · {item['body']['description'][:40]}"):
            st.text(item["body"]["review_note"] or "等待维护者核查")
            if item["status"] == "needs_info":
                with st.form(f"awj_supplement_{item['id']}"):
                    description = st.text_area("补充说明", value=item["body"]["description"])
                    evidence = st.text_input("更新证据链接", value=item["body"]["evidence_url"])
                    submitted = st.form_submit_button("补充后重新提交")
                if submitted:
                    _attempt(lambda i=item: c.supplement(store, token, i["id"], description, evidence))
                    st.rerun()


def _backup(store, token, catalog):
    st.caption("记录备份包含足迹、私人短文、压缩照片、配对与授权、关注及不感兴趣。Trip／收藏仍在「备份与反馈」单独备份。恢复照片默认私密，不恢复公开链接或统计同意。")
    raw = store.export_journal(token)
    st.download_button("下载记录与照片备份", raw.encode(), file_name="animeway-journal.json", mime="application/json", key="awj_backup")
    upload = st.file_uploader("恢复记录备份（最多 16 MiB）", type=["json"], key="awj_restore_file")
    from components.import_review import render_import_review
    approved = render_import_review(store, token, upload, catalog, journal=True)
    if st.button("合并恢复记录与照片", key="awj_restore", disabled=approved is None):
        count = _attempt(lambda: store.import_journal(token, approved))
        if count is not None:
            st.success(f"新增 {count} 条记录；相同文件重复恢复不会重复添加")


def render_rediscovery(store, token, catalog, api_key=""):
    st.title("下一次巡礼")
    st.caption("从关注、愿望和确认到访继续；跳过不等于不喜欢。这里不发送站外通知。")
    if not token:
        st.info("匿名身份连接后可关注与保存")
        return
    prefs = store.preferences(token)
    works = {a["id"]: a["cn"] for a in catalog["anime"]}
    regions = {d["id"]: d["name"] for d in catalog["destinations"]}
    with st.expander("作品／目的地关注与订阅设置"):
        with st.form("awj_follows"):
            followed_works = st.multiselect("关注作品", list(works), default=[f["id"] for f in prefs["follows"] if f["kind"] == "anime" and f["id"] in works], format_func=works.get)
            followed_regions = st.multiselect("关注目的地", list(regions), default=[f["id"] for f in prefs["follows"] if f["kind"] == "destination" and f["id"] in regions], format_func=regions.get)
            consent = st.checkbox("允许记录最小采用／主动回访事件，用于评估产品；取消时删除此身份的这类统计", value=prefs["measure_consent"])
            submit = st.form_submit_button("保存关注设置")
        if submit:
            old = {(f["kind"], f["id"]): f for f in prefs["follows"]}
            prefs["follows"] = [old.get((kind, i), {"kind": kind, "id": i, "since": _now()}) for kind, ids in (("anime", followed_works), ("destination", followed_regions)) for i in ids]
            prefs["measure_consent"] = consent
            if _attempt(lambda: store.save_preferences(token, prefs, catalog)):
                st.rerun()
    if st.button("我又有一次出行机会，开始筹备", key="awj_return_intent"):
        _attempt(lambda: store.record_intent(token))
        st.session_state.update(aw_page="personal", awp_mode="new", aw_pending_tab="planning")
        st.rerun()
    st.subheader("相关内容更新")
    updates = c.follow_updates(store, token, catalog)
    if not updates:
        st.caption("关注后暂无相关资料变化；不会用泛化提醒填充。")
    for update in updates:
        st.text(f"{update['created_at'][:10]} · {update['body']['summary']}")
        if update["kind"] == "location" and update["object_id"] in _place_names(catalog):
            if st.button("查看最新地点资料", key=f"awj_update_{update['id']}"):
                store.record_journey_event(token, "update_opened", update["object_id"], "update")
                st.session_state["awj_origin"] = {"location_id": update["object_id"], "at": time.time()}
                st.session_state.update(aw_page="location", aw_selected_location=update["object_id"],
                                        aw_explore_view="手册与地点", aw_pending_tab="explore")
                st.rerun()
    st.subheader("尚未确认到访的相关场景")
    suggestions = store.recommend(token, catalog)
    if not suggestions:
        st.caption("先关注作品、目的地或收藏场景；没有明确兴趣时不会补入无关热门点。")
    for suggestion in suggestions:
        point = suggestion["location"]
        with st.container(border=True):
            st.write(point["name"])
            st.caption(suggestion["reason"])
            st.caption("基础资料仍需核查，不是已验证路线推荐。" if point["content_level"] == "basic" else "已具备初步选择资料，出发前仍需核查。")
            if st.button("查看场景与访问说明", key=f"awj_recommend_open_{point['id']}"):
                st.session_state.update(aw_page="location", aw_selected_location=point["id"],
                                        aw_explore_view="手册与地点", aw_pending_tab="explore")
                st.rerun()
            if st.button("保存到想去清单", key=f"awj_recommend_save_{point['id']}"):
                _attempt(lambda p=point: store.save_recommendation(token, p["id"], catalog))
                st.success("已保存")
            if st.button("不感兴趣", key=f"awj_dismiss_{point['id']}"):
                prefs["dismissed"] = list(dict.fromkeys(prefs["dismissed"] + [point["id"]]))
                _attempt(lambda: store.save_preferences(token, prefs, catalog))
                st.rerun()
    with st.expander("恢复不感兴趣的地点"):
        if st.button("清空不感兴趣设置", key="awj_reset_dismiss"):
            prefs["dismissed"] = []
            _attempt(lambda: store.save_preferences(token, prefs, catalog))
            st.rerun()
    with st.expander("愿望清单整理预览（不自动修改收藏）"):
        wanted = store.list_wishlist(token)
        visited = {e["location_id"] for e in store.entries(token) if e["confirmed"]}
        completed = [p for p in wanted if p["id"] in visited]
        st.write(f"想去 {len(wanted)} 个，其中 {len(completed)} 个已经确认到访。")
        chosen = st.multiselect("选择从想去清单移除的已到访地点", [p["id"] for p in completed], format_func={p["id"]: p["name"] for p in completed}.get)
        confirm = st.checkbox("确认仅移除上述收藏，保留到访记录")
        if st.button("应用整理", disabled=not confirm or not chosen):
            for lid in chosen:
                _attempt(lambda i=lid: store.remove_wishlist(token, i))
            st.rerun()
    from core import journal_ai, trip_ai
    with st.expander("下一次轻量出行建议预览"):
        _ai_budget(store, token)
        suggested = {r["location"]["id"]: r for r in suggestions}
        selected = st.multiselect("人工选择至多三个候选", list(suggested), format_func=lambda i: suggested[i]["location"]["name"], key="awj_next_ids")
        st.caption("默认人工选择；AI 仅从当前候选选择同片区地点，不改收藏。与 Trip AI 共用服务额度，未配置预算时关闭。")
        if st.button("可选 AI 选择候选", disabled=not trip_ai.enabled(api_key), key="awj_next_ai"):
            result = _attempt(lambda: journal_ai.recommend_choices(store, token, catalog, api_key))
            if result:
                st.session_state["awj_next_preview"] = [r["location"]["id"] for r in result]
        if st.button("预览我的选择", key="awj_next_preview_button"):
            st.session_state["awj_next_preview"] = selected
        preview = st.session_state.get("awj_next_preview", [])
        for lid in preview:
            st.write(suggested[lid]["location"]["name"] + "：" + suggested[lid]["reason"] if lid in suggested else "此候选已失效，请重新选择")
        when = st.date_input("新草案开始日期", value=today(), key="awj_next_date")
        if st.button("确认建立独立 Trip 草案", disabled=not preview, key="awj_next_apply"):
            trip = _attempt(lambda: store.create_recommended_trip(token, preview, when.isoformat(), catalog))
            if trip:
                st.session_state.update(aw_page="personal", awp_mode="detail", awp_selected=trip["id"],
                                        aw_my_view="personal", aw_pending_tab="trips")
                st.rerun()
    st.subheader("旅行日期相关活动")
    start = st.date_input("活动筛选开始", value=today(), key="awj_activity_start")
    end = st.date_input("活动筛选结束", value=start, min_value=start, key="awj_activity_end")
    activities = c.activities(catalog, start=start.isoformat(), end=end.isoformat())
    if not activities:
        st.caption("这个日期范围暂无经维护者确认且仍有效的官方活动，不用过期活动补位。")
    for activity in activities:
        st.write(activity["title"])
        st.caption(f"{activity['start_date']}—{activity['end_date']} · 最近核查 {activity['checked_at']}")
        st.text(activity["summary"])
        st.link_button("活动官方来源", activity["source_url"])
