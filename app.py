"""
AnimeWay - AI-Powered Anime Pilgrimage Planner
==============================================
A Streamlit application that uses Aliyun DashScope LLM, Amap (GaoDe) API, 
and Bangumi/Anitabi data to plan anime pilgrimage itineraries.

Author: Antigravity Agent
License: MIT
"""

import time
import re

import streamlit as st
import pydeck as pdk
from geopy.distance import geodesic

from utils import bangumi, anitabi, amap, ali_ai, optimization

# ================= Configuration & State =================
st.set_page_config(
    page_title="AnimeWay | 圣地巡礼助手", 
    layout="wide", 
    page_icon="⛩️",
    initial_sidebar_state="expanded"
)

# ================= 🎨 Anime Style CSS =================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Zcool+KuaiLe&family=Noto+Sans+SC:wght@400;700&display=swap');
    
    /* Global Background */
    .stApp {
        background-color: #FAFAFA;
        background-image: radial-gradient(#FFB7C5 1px, transparent 1px), radial-gradient(#A0C4FF 1px, transparent 1px);
        background-size: 20px 20px;
        background-position: 0 0, 10px 10px;
    }

    /* Typography */
    html, body, [class*="css"] {
        font-family: 'Noto Sans SC', sans-serif;
        color: #4A4A4A;
    }
    h1, h2, h3 {
        font-family: 'Zcool KuaiLe', sans-serif !important; /* Playful Title Font */
        background: linear-gradient(120deg, #FF9A9E 0%, #FECFEF 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
    }
    
    /* Sidebar - Glassmorphism */
    section[data-testid="stSidebar"] {
        background: rgba(255, 255, 255, 0.65);
        backdrop-filter: blur(12px);
        border-right: 1px solid rgba(255,255,255,0.5);
    }
    
    /* Cards (Container) */
    .stContainer {
        background: rgba(255, 255, 255, 0.9);
        border-radius: 16px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        padding: 10px;
        border: 1px solid #FFF;
    }
    
    /* Buttons - Anime Game Style */
    .stButton>button {
        border-radius: 50px !important;
        background: linear-gradient(90deg, #FF9A9E 0%, #FECFEF 100%) !important;
        color: white !important;
        border: none !important;
        box-shadow: 0 4px 10px rgba(255, 154, 158, 0.3) !important;
        transition: all 0.3s ease !important;
        font-weight: bold !important;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 15px rgba(255, 154, 158, 0.5) !important;
    }
    /* Secondary Button (Gray/Blue) */
    button[kind="secondary"] {
        background: #F0F2F6 !important;
        color: #555 !important;
        box-shadow: none !important;
    }
    
    /* Inputs */
    .stTextInput>div>div>input {
        border-radius: 20px;
        border: 2px solid #E0E0E0;
        padding-left: 15px;
    }
    .stTextInput>div>div>input:focus {
        border-color: #FF9A9E;
        box-shadow: 0 0 5px rgba(255, 154, 158, 0.5);
    }

    /* Badges */
    .anime-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 0.8em;
        font-weight: bold;
        color: #FFF;
        background: #A0C4FF;
        box-shadow: 0 2px 5px rgba(160, 196, 255, 0.4);
    }
    .location-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 8px;
        font-size: 0.8em;
        color: #666;
        background: #F0F2F6;
        border: 1px solid #DDD;
    }
    
    /* Tab Bar */
    .stTabs [data-baseweb="tab-list"] {
        gap: 20px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 20px;
        background-color: white;
        padding: 5px 20px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    .stTabs [aria-selected="true"] {
        background-color: #FF9A9E !important;
        color: white !important;
    }
    
</style>
""", unsafe_allow_html=True)

# Initialize Session State
if 'itinerary' not in st.session_state:
    st.session_state['itinerary'] = [] 
if 'search_results' not in st.session_state:
    st.session_state['search_results'] = []
if 'current_anime' not in st.session_state:
    st.session_state['current_anime'] = None
if 'page' not in st.session_state:
    st.session_state['page'] = 0
if 'search_candidates' not in st.session_state:
    st.session_state['search_candidates'] = [] 

ITEMS_PER_PAGE = 10

def clean_markdown_output(text):
    if not text: return ""
    pattern = r"^```(?:markdown)?\s*([\s\S]*?)\s*```$"
    match = re.match(pattern, text, re.IGNORECASE)
    if match: return match.group(1).strip()
    return text.strip()

def add_to_itinerary(point, anime_name):
    point_copy = dict(point)
    if point.get('_anime_name'):
        anime_name = point.get('_anime_name')
    point_copy['_anime_name'] = anime_name or "未知动画"
    
    p_id = f"{point_copy.get('id')}_{point_copy.get('cn')}"
    for item in st.session_state['itinerary']:
        if item.get('_local_id') == p_id:
            st.toast("OwO 已经添加过啦！", icon="🍥")
            return
    
    point_copy['_local_id'] = p_id
    st.session_state['itinerary'].append(point_copy)
    st.toast(f"Get!! 捕获圣地: {point_copy.get('cn') or point_copy.get('name')}", icon="✨")
    st.rerun()

def remove_from_itinerary(idx):
    if 0 <= idx < len(st.session_state['itinerary']):
        st.session_state['itinerary'].pop(idx)
        st.rerun()

# ================= Sidebar =================
with st.sidebar:
    st.markdown("## 🎒 巡礼背包 <br><small>Adventure Bag</small>", unsafe_allow_html=True)
    
    with st.expander("⚙️ 魔法设定 (Settings)", expanded=True):
        amap_key = st.text_input("GaoDe Key (Map)", type="password")
        dashscope_key = st.text_input("DashScope Key (AI)", type="password")

            
    st.markdown("---")
    st.markdown(f"#### 🗺️ 待攻略副本 ({len(st.session_state['itinerary'])})")
    
    if st.session_state['itinerary']:
        for i, item in enumerate(st.session_state['itinerary']):
            st.markdown(f"**{i+1}. {item.get('cn') or item.get('name')}**")
            st.caption(f"📺 {item.get('_anime_name')}")
    else: 
        st.markdown("*背包是空的... (´；ω；`)*")
        st.markdown("*快去寻找心动的圣地吧！*")
    
    st.markdown("---")
    if st.session_state['itinerary']: 
        st.success("Ready! 前往生成路书 👉")

# ================= Main UI =================
st.markdown("# ⛩️ AnimeWay <br><small style='font-size: 0.4em; color: #888;'>Breaking the Dimensional Wall...</small>", unsafe_allow_html=True)

tab_discover, tab_plan = st.tabs(["🏘️ 圣地观测 (Discover)", "📅 冒险之书 (Plan)"])

# --- Tab 1: Discovery ---
with tab_discover:
    st.markdown("### 💬 召唤次元观测者 (Agent)")
    st.info("💡 告诉我你想找什么？例如：“想看点治愈的番”、“推荐几部机甲类”、“寻找莉可丽丝的圣地”")

    # === Helper: Run Recommendation ===
    def run_recommendation(query_text):
         with st.spinner("🤖 正在连接阿卡夏记录..."):
             # Count = 10
             rec_names = ali_ai.recommend_anime_list(count=10, context_query=query_text)
             st.write(f"✨ 为您推荐: {', '.join(rec_names)}")
             
             rec_candidates = []
             progress_bar = st.progress(0)
             
             for i, name in enumerate(rec_names):
                 candidates = bangumi.search_candidates(name, use_llm=False)
                 if candidates:
                     info = candidates[0]
                     rec_candidates.append(info)
                 else:
                     rec_candidates.append({
                         'id': 0, 'cn': name, 'jp': name, 'image': None, 'summary': '暂无简介'
                     })
                 progress_bar.progress((i + 1) / len(rec_names))
             
             progress_bar.empty()
             
             if rec_candidates:
                 st.session_state['search_candidates'] = rec_candidates
                 st.session_state['search_results'] = []
                 st.session_state['current_anime'] = None
                 st.session_state['is_rec_result'] = True # Flag for Reroll
                 st.session_state['last_rec_query'] = query_text # Save for Reroll
                 return True
             else:
                 st.warning("未能获取番剧详情。")
                 return False

    # Unified Input
    prompt = st.chat_input("输入指令... (Enter command)")

    if prompt:
        if not dashscope_key:
             st.error("需要 DashScope Key 才能启动观测者。")
        else:
             with st.chat_message("user"):
                 st.write(prompt)
                 
             ali_ai.dashscope.api_key = dashscope_key 
             
             from utils import agent
             intent = agent.parse_intent(prompt)
             
             with st.chat_message("assistant"):
                 st.write(f"🧠 分析意图: **{intent['type']}** (关键词: {intent['query']})")
                 
                 # === CASE 1: RECOMMENDATION ===
                 if intent['type'] == 'RECOMMEND':
                     if run_recommendation(intent.get('query', '')):
                         st.success(f"已为您准备好 10 部作品，请点击卡片查看圣地。")

                 # === CASE 2: SEARCH ===
                 elif intent['type'] == 'SEARCH':
                      with st.spinner(f"正在检索《{intent['query']}》..."):
                          candidates = bangumi.search_candidates(intent['query'], use_llm=True)
                          st.session_state['search_candidates'] = candidates
                          st.session_state['search_results'] = []
                          st.session_state['current_anime'] = None
                          st.session_state['is_rec_result'] = False # Not a rec
                          
                          if candidates:
                              st.success(f"找到 {len(candidates)} 个结果")
                          else:
                              st.warning("未找到匹配的番剧。")

                 # === CASE 3: CHAT ===
                 else:
                     st.write("我是您的圣地巡礼向导。请告诉我您想去的番剧圣地，或者想看的番剧类型！")
    
    # Render Search Candidates (if any)
    if st.session_state.get('search_candidates') and not st.session_state.get('search_results'):
        c_head_1, c_head_2 = st.columns([4, 1])
        with c_head_1:
            st.markdown(f"##### 🤔 请确认目标:")
        with c_head_2:
            # Show Reroll Button if result is from Recommendation
            if st.session_state.get('is_rec_result'):
                if st.button("🎲 换一批", help="重新生成推荐"):
                     if run_recommendation(st.session_state.get('last_rec_query', '')):
                         st.rerun()

        candidates = st.session_state['search_candidates'][:20]
        for i in range(0, len(candidates), 3):
            cols = st.columns(3)
            for j in range(3):
                if i + j < len(candidates):
                    cand = candidates[i+j]
                    with cols[j]:
                        with st.container(border=True):
                            if cand.get('image'): st.image(cand['image'], use_container_width=True)
                            stay_label = f"展开结界 ➡️"
                            st.markdown(f"**{cand['cn']}**")
                            if st.button(stay_label, key=f"sel_{cand['id']}"):
                                with st.spinner(f"正在加载《{cand['cn']}》的圣地..."):
                                    lite_info = anitabi.get_subject_lite(cand['id'])
                                    city_name = lite_info.get('city') if lite_info else ""
                                    raw_pts = anitabi.get_points(cand['id'])
                                    if raw_pts:
                                        new_pts = []
                                        for p in raw_pts:
                                            np = dict(p)
                                            np['_anime_name'] = cand['cn']
                                            np['_city'] = city_name
                                            new_pts.append(np)
                                        st.session_state['search_results'] = new_pts
                                        st.session_state['current_anime'] = cand['cn']
                                        st.session_state['page'] = 0
                                        st.rerun()
                                    else: st.error("该番剧暂无收录数据。")

    # === Result List Display (Common) ===
    if st.session_state['search_results'] and (st.session_state['current_anime'] is not None):
         st.markdown("---")
         c_back, c_title = st.columns([1, 4])
         with c_back:
             if st.button("🔙 返回/清空", type="secondary"):
                 st.session_state['search_results'] = []
                 st.session_state['current_anime'] = None
                 st.rerun()
         with c_title:
             if st.session_state['current_anime'] == "AI 精选推荐":
                  st.markdown("### ✨ 此刻的命运之选")
             else:
                  st.markdown(f"### 📍 {st.session_state['current_anime']} 圣地列表")
             
         total_items = len(st.session_state['search_results'])
         start_idx = st.session_state['page'] * ITEMS_PER_PAGE
         end_idx = start_idx + ITEMS_PER_PAGE
         items = st.session_state['search_results'][start_idx:end_idx]
         
         for pt in items:
            with st.container():
                c_img, c_info, c_action = st.columns([1.5, 3, 1])
                with c_img:
                    img = pt.get('image', '').replace('plan=h160', 'plan=h360')
                    st.image(img or "https://via.placeholder.com/300x160.png?text=No+Image", use_container_width=True)
                with c_info:
                    st.markdown(f"#### {pt.get('cn') or pt.get('name')}")
                    
                    loc_str = ""
                    if pt.get('_city'): loc_str += f"{pt.get('_city')} "
                    loc_str += f"({pt['geo'][0]:.4f}, {pt['geo'][1]:.4f})"
                    
                    st.markdown(f"<span class='location-badge'>📍 {loc_str}</span>", unsafe_allow_html=True)
                    st.markdown(f"<span class='anime-badge'>📺 {pt.get('_anime_name')}</span>", unsafe_allow_html=True)
                    
                    st.markdown(f"<br><a href='{amap.get_navigation_url(pt['geo'][1], pt['geo'][0])}' target='_blank'>🗺️ 打开地图观测</a>", unsafe_allow_html=True)
                    
                with c_action:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("➕ 收藏", key=f"add_{pt['id']}_p{st.session_state['page']}"): 
                        add_to_itinerary(pt, pt.get('_anime_name'))
        
         st.markdown("---")
         c_p, c_c, c_n = st.columns([1, 2, 1])
         with c_p:
             if st.session_state['page'] > 0:
                 if st.button("⬅️ 上一页", key="pg_prev"): st.session_state['page'] -= 1; st.rerun()
         with c_c:
              st.markdown(f"<center>页码 {st.session_state['page']+1} / {((total_items-1)//ITEMS_PER_PAGE)+1}</center>", unsafe_allow_html=True)
         with c_n:
             if end_idx < total_items:
                 if st.button("下一页 ➡️", key="pg_next"): st.session_state['page'] += 1; st.rerun()

# --- Tab 2: Planning ---
with tab_plan:
    st.markdown("## ✨ 冒险之书 <small>(Itinerary)</small>", unsafe_allow_html=True)
    
    c_opts, _ = st.columns([2, 1])
    with c_opts:
        enable_tsp = st.checkbox("🔄 开启时空折叠 (智能路线优化 TSP)", value=True)
    
    if not st.session_state['itinerary']:
        st.info("🎒 还没有收集任何圣地碎片哦...")
    else:
        for i, item in enumerate(st.session_state['itinerary']):
            with st.container():
                c1, c2, c3 = st.columns([0.5, 3, 1])
                with c1: st.markdown(f"### {i+1}")
                with c2: 
                    st.markdown(f"**{item.get('cn') or item.get('name')}**")
                    st.caption(f"📺 {item.get('_anime_name')}")
                with c3:
                    if st.button("❌ 移除", key=f"del_{i}"): remove_from_itinerary(i)
                st.markdown("---")
        
        # New Flow: 1. Plan Routes (Select Scheme) 2. Generate Guide (LLM)
        if 'planned_routes' not in st.session_state:
            st.session_state['planned_routes'] = None
        
        # Action: Plan Routes
        # Input for Start Location
        start_addr = st.text_input("🏁 设定出发地 (Start Location)", placeholder="如果不填，默认从第一个景点开始 (或尝试定位)")
        
        # Action: Generate Adventure Book (Single Step)
        if st.button("🔮 生成圣地巡礼路书 (Generate Adventure Book)", type="primary", use_container_width=True):
            if not amap_key: 
                st.error("❌ 缺少地图卷轴 (Amap Key)")
            elif not dashscope_key:
                st.error("❌ 缺少魔力源 (DashScope Key)")
            else:
               ali_ai.dashscope.api_key = dashscope_key
               
               points_to_route = list(st.session_state['itinerary'])
               
               # Handle Start Point
               if start_addr:
                   try:
                       slon, slat = amap.get_location_coords(start_addr, amap_key)
                       if slon and slat:
                           start_pt = {
                               "name": f"出发地: {start_addr}",
                               "cn": f"出发地: {start_addr}",
                               "_anime_name": "起点",
                                "geo": [slat, slon], # lat, lon format
                            }
                           points_to_route.insert(0, start_pt)
                           st.toast(f"✅ 起点已设定: {start_addr}")
                   except Exception as e:
                       print(f"Start Point Error: {e}")
               
               if enable_tsp:
                   with st.spinner("🧠 正在计算最优路径 (TSP)..."):
                       points_to_route = optimization.solve_tsp_greedy(points_to_route)
                       st.toast("✅ 路径优化完毕")
               
               st.session_state['optimized_points'] = points_to_route
               
               # Use Strategy 0 (Recommended) for all segments
               final_routes = []
               
               progress_bar = st.progress(0)
               status_text = st.empty()
               
               total_segments = len(points_to_route) - 1
               
               for i in range(total_segments):
                   status_text.text(f"正在分析第 {i+1}/{total_segments} 段行程...")
                   s, e = points_to_route[i], points_to_route[i+1]
                   
                   # Ensure we have a valid city for Transit API
                   city = s.get('_city') or e.get('_city')
                   if not city:
                       try: city = amap.get_regeo_city(s['geo'][1], s['geo'][0], amap_key)
                       except: pass
                   
                   route = None
                   # 1. Try Transit (Recommended Strategy 0)
                   try:
                       route = amap.get_transit_route(s['geo'][1], s['geo'][0], e['geo'][1], e['geo'][0], city, amap_key, strategy=0)
                   except Exception as e:
                       print(f"Plan Route Error: {e}")
                   
                   if not route:
                       # 2. Fallback: Walking
                       try:
                           route = amap.get_walking_route(s['geo'][1], s['geo'][0], e['geo'][1], e['geo'][0], amap_key)
                       except Exception as e: print(f"Walking Error: {e}")
                   
                   if not route:
                       # 3. Fallback: Driving
                       try:
                           route = amap.get_driving_route(s['geo'][1], s['geo'][0], e['geo'][1], e['geo'][0], amap_key)
                       except Exception as e: print(f"Driving Error: {e}")
                       
                   if not route:
                        # 4. Fallback: Straight Line (Geodesic)
                        try:
                            dist_km = geodesic((s['geo'][0], s['geo'][1]), (e['geo'][0], e['geo'][1])).km
                            dist_m = int(dist_km * 1000)
                            duration_min = int(dist_km / 50 * 60) # Assume 50km/h speed
                            route = {
                                "type": "flying", # Direct line
                                "distance_m": dist_m,
                                "duration_min": duration_min,
                                "cost": 0,
                                "steps": [f"直线距离 {dist_km:.1f}km (无法规划路径，建议查看地图)"]
                            }
                        except: pass

                   if route:
                       final_routes.append(route)
                   else:
                       final_routes.append(None)
                       
                   time.sleep(0.1) 
                   progress_bar.progress((i + 1) / total_segments)
               
               status_text.empty()
               progress_bar.empty()
               
               status_text.empty()
               progress_bar.empty()
               
               # === Visualization Data Prep ===
               total_time = 0
               total_dist_km = 0
               total_cost = 0.0
               map_points = []
               
               # Collect Points & Images
               spot_images = []
               
               for p in points_to_route:
                   # Ensure float for map
                   map_points.append((float(p['geo'][1]), float(p['geo'][0]))) # lon, lat
                   # Try to find image (anitabi might have 'image' field)
                   img = p.get('image') or p.get('img')
                   if img: spot_images.append({'name': p.get('cn') or p.get('name', '圣地'), 'src': img})
                   
               timeline_data = [] # Keep timeline simple for LLM, but calc totals here
               
               for i, r in enumerate(final_routes):
                   if r:
                       dur = r.get('duration_min', 0)
                       dist = r.get('distance_m', 0)
                       c = r.get('cost', 0)
                       total_time += dur
                       total_dist_km += dist / 1000
                       total_cost += c

               # === Render Visuals (Dashboard Reborn) ===
               st.balloons()
               st.divider()
               
               # 1. Interactive Map (PyDeck for Global Support)
               # AMap Static API has poor coverage outside China (e.g. Japan), appearing blank.
               # Switching to PyDeck + OSM/Carto tiles for global rendering.
               import pydeck as pdk
               
               if map_points:
                   # Center map
                   mid_lat = sum(p[1] for p in map_points) / len(map_points)
                   mid_lon = sum(p[0] for p in map_points) / len(map_points)
                   
                   # Data for Layers
                   # 1. Path Layer
                   path_data = [{"path": [[p[0], p[1]] for p in map_points], "color": [255, 0, 128]}]
                   
                   # 2. Scatter Layer (Points)
                   scatter_data = [{"position": [p[0], p[1]], "name": points_to_route[i].get('cn') or points_to_route[i].get('name', '圣地')} for i, p in enumerate(map_points)]

                   st.pydeck_chart(pdk.Deck(
                       map_style=None, # Use default light style
                       initial_view_state=pdk.ViewState(
                           latitude=mid_lat,
                           longitude=mid_lon,
                           zoom=11,
                           pitch=0,
                       ),
                       layers=[
                           pdk.Layer(
                               "PathLayer",
                               data=path_data,
                               pickable=True,
                               get_path="path",
                               get_color="color",
                               width_scale=20,
                               width_min_pixels=2,
                           ),
                           pdk.Layer(
                               "ScatterplotLayer",
                               data=scatter_data,
                               get_position="position",
                               get_color=[0, 0, 255],
                               get_radius=200,
                           ),
                       ],
                       tooltip={"text": "{name}"}
                   ))

               # 2. Visual Album
               if spot_images:
                   st.markdown("##### 📸 巡礼相册")
                   cols = st.columns(len(spot_images) if len(spot_images) <= 4 else 4)
                   for i, img in enumerate(spot_images[:4]): # Show max 4 preview
                       with cols[i]:
                           st.image(img['src'], caption=img['name'], use_container_width=True)
               
               st.divider()
               
               # Trigger LLM Generation
               with st.spinner("✍️ AI 导游正在为您撰写《圣地巡礼·终极奥义书》..."):
                    txt = clean_markdown_output(ali_ai.generate_tour_guide_text(points_to_route, final_routes))
               
               st.markdown("### 📖 您的冒险之书")
               st.markdown(txt, unsafe_allow_html=True)
