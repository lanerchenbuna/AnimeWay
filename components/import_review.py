"""Explicit review before restoring a private backup; no preview writes."""
import hashlib
import json
import streamlit as st
from core.import_review import review_backup
from components.trip_planner import _attempt


def render_import_review(store, token, upload, catalog, *, journal=False):
    prefix = 'awj_review' if journal else 'aw_review'
    if not token or upload is None:
        return None
    limit = 16 if journal else 5
    if upload.size > limit * 1024 * 1024:
        st.error(f'备份不得超过 {limit} MiB')
        return None
    try:
        raw = upload.getvalue().decode('utf-8')
    except UnicodeError:
        st.error('备份不是有效 UTF-8 JSON')
        return None
    from components.map_runtime import map_resource
    service, *_ = map_resource(store, catalog)
    def inspect():
        return review_backup(store, token, raw, catalog, journal=journal, resolver=service.get_place)
    if st.button('预览恢复内容与地点冲突', key=prefix+'_preview'):
        result = _attempt(inspect)
        if result is not None:
            st.session_state[prefix] = result
    preview = st.session_state.get(prefix)
    if not preview:
        return None
    current = _attempt(inspect)
    if current is None or current != preview:
        st.warning('文件、地点资料或现有收藏已变化，请重新预览。')
        return None
    st.caption('最终写入时还会核对身份、容量与重复导入。恢复为独立副本，不覆盖现有 Trip 或记录。相同地点收藏有冲突时保留现有收藏；历史缺失 ID 不猜测迁移，导航需当前资料解析。')
    st.write(f"Trip 副本 {preview['copies']}；记录 {preview['entries']}；照片 {preview['photos']}（恢复后私密）。")
    if preview['already_imported']:
        st.info('此备份已恢复过，再次确认不会重复新增。')
    if preview['locations']:
        st.dataframe(preview['locations'], hide_index=True, width="stretch")
    if preview['wishlist_conflicts_preserved']:
        st.warning('保留现有收藏：' + '、'.join(preview['wishlist_conflicts_preserved']))
    if preview['scene_pairs_unresolved']:
        st.warning('部分照片的场景归属当前无法确认，恢复后仅保留私密历史配对。')
    if st.checkbox('已阅读缺失地点和冲突，确认恢复为独立副本', key=prefix+'_confirm_'+hashlib.sha256(json.dumps(preview, sort_keys=True).encode()).hexdigest()):
        return raw
    return None
