"""Map actions into existing private Trip and journal workflows."""
import streamlit as st

from core.place_links import blocked, map_trip_plan, trip_eligible
from core.trip import evaluate
from core.journal import today
from components.trip_planner import _attempt


def open_map(location_id):
    from core.map_explore import initial_state, navigate
    state = st.session_state.setdefault('awmap_state', initial_state())
    navigate(state, 'place', location_id=location_id)
    st.session_state['aw_pending_tab'] = 'map'
    st.rerun()


def open_handbook(page, **state):
    st.session_state.update(state)
    st.session_state.update(aw_page=page, awmap_return=True, aw_pending_tab='handbook')
    st.rerun()


def render_place_actions(store, token, detail, catalog):
    if not store or not token or not hasattr(store, 'list_personal_trips'):
        return
    place = detail['place']
    lid = place['id']
    # Only this selected full-library place is needed for private journal writes.
    local = {**catalog, 'resolved_locations': {**catalog.get('resolved_locations', {}), lid: place},
             'scenes': list({s['id']: s for s in catalog['scenes'] + detail['scenes']}.values())}
    st.subheader('旅行与记录')
    if trip_eligible(place, catalog):
        with st.expander('加入东京个人 Trip'):
            trips = [t for t in store.list_personal_trips(token) if t['state'] != 'ended']
            labels = {'': '新建 1—3 日草案', **{t['id']: t['plan']['requirements']['title'] for t in trips}}
            target = st.selectbox('选择 Trip', list(labels), format_func=labels.get, key='awmap_trip_target')
            if target:
                trip = next(t for t in trips if t['id'] == target)
                days = [d['date'] for d in trip['plan']['days']]
                day = st.selectbox('加入哪一天', days, key='awmap_trip_day')
                existing = any(s['location_id'] == lid for d in trip['plan']['days'] for s in d['stops'])
                if existing:
                    st.info('此地点已在 Trip 中，多个场景共用一次停靠。')
                if st.button('加入当天末尾', key='awmap_trip_add', disabled=existing):
                    saved = _attempt(lambda: store.edit_personal_trip(token, target, trip['revision'],
                                     {'kind': 'add', 'date': day, 'replacement_id': lid}, catalog))
                    if saved:
                        st.session_state['awmap_last_trip'] = saved['id']
                        st.rerun()
                if st.button('查看每日顺序与访问状态', key='awmap_trip_view'):
                    open_handbook('personal', awp_mode='detail', awp_selected=target)
            else:
                start = st.date_input('开始日期（日本时间）', value=today(), key='awmap_trip_date')
                count = st.selectbox('天数', [1, 2, 3], key='awmap_trip_days')
                if st.button('创建含此地点的 Trip 草案', key='awmap_trip_create'):
                    plan = _attempt(lambda: map_trip_plan(lid, start.isoformat(), count, local))
                    if plan:
                        saved = _attempt(lambda: store.create_personal_trip(token, plan))
                        if saved:
                            open_handbook('personal', awp_mode='detail', awp_selected=saved['id'])
            if target:
                check = evaluate(trip['plan'], catalog, trip['events'])
                st.caption(check['promise'])
                for day in trip['plan']['days']:
                    st.write(day['date'] + '：' + ' → '.join(next((p['name'] for p in catalog['locations'] if p['id'] == s['location_id']), s['location_id']) for s in day['stops']))
    else:
        st.info('当前仅东京试点地点可加入 Trip；其他地点仍可收藏。关闭或撤下地点不新增旅行安排。')
    with st.expander('补记此地点的到访'):
        st.caption('收藏、地图点选和计划不会自动生成到访。历史记录可以保留；当前无法访问不代表从未到访。')
        with st.form('awmap_visit_form_' + lid, clear_on_submit=True):
            when = st.date_input('实际到访日期', value=today(), max_value=today(), key='awmap_visit_date')
            note = st.text_area('私人笔记', max_chars=3000, key='awmap_visit_note')
            confirmed = st.checkbox('我确认实际到访了该地点', key='awmap_visit_confirm_' + lid)
            submit = st.form_submit_button('保存此地点的私密到访')
        if submit:
            if not confirmed:
                st.error('尚未确认到访，未生成足迹')
            elif not place.get('withdrawn'):
                entry = _attempt(lambda: store.save_entry(token, location_id=lid, visited_on=when.isoformat(), confirmed=True, note=note, catalog=local))
                if entry:
                    st.session_state['awmap_last_entry'] = entry['id']
                    st.success('到访已保存，可继续管理私密照片。')
            else:
                st.info('地点已撤下，请在原有记录中维护历史事实。')
        entries = [e for e in store.entries(token) if e['location_id'] == lid]
        if entries and st.button('管理此地点的记录与照片', key='awmap_visit_photos'):
            recent = st.session_state.get('awmap_last_entry')
            selected = next((e for e in entries if e['id'] == recent), max(entries, key=lambda e: e['created_at']))
            open_handbook('journal', awj_pending_entry=selected['id'])
    if blocked(place):
        st.caption('当前访问受限；已有记录不会被自动删除或改写。')
