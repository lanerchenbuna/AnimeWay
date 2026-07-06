import streamlit as st


def render_sidebar() -> tuple[str, str]:
    with st.sidebar:
        st.markdown("## 巡礼背包")

        with st.expander("服务密钥", expanded=True):
            amap_key = st.text_input("高德地图 Key", type="password", key="amap_key")
            dashscope_key = st.text_input("DashScope Key", type="password", key="dashscope_key")

        amap_key = amap_key.strip() if amap_key else ""
        dashscope_key = str(dashscope_key).strip() if dashscope_key else ""

        st.divider()
        st.markdown(f"#### 待规划地点（{len(st.session_state['itinerary'])}）")
        if st.session_state["itinerary"]:
            for idx, item in enumerate(st.session_state["itinerary"], start=1):
                st.markdown(f"**{idx}. {item.get('cn') or item.get('name')}**")
                st.caption(item.get("_anime_name") or "未知动画")
            st.success("可前往「冒险之书」生成路线。")
        else:
            st.caption("背包为空。先去发现页收集圣地。")

    return amap_key, dashscope_key
