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
import os
import json
from datetime import datetime

import streamlit as st
import pydeck as pdk
from geopy.distance import geodesic

# ================= Configuration & State =================
st.set_page_config(
    page_title="AnimeWay | 圣地巡礼助手", 
    layout="wide", 
    page_icon="⛩️",
    initial_sidebar_state="expanded"
)

# Local modules
from utils import amap, ali_ai, optimization
from core.retrieval import HybridRetriever
from components.ui import render_hero, render_anime_card, render_agent_status

# Load Knowledge Base
# Load Knowledge Base via Agent (Runtime Join)
@st.cache_resource
def load_agent_resources():
    from core.agent import AnimeRagAgent
    # Initialize Agent (loads data from Raw JSONs)
    agent = AnimeRagAgent()
    return agent, agent.retriever

# Global Instance
rag_agent, retriever = load_agent_resources()
if 'rag_agent' not in st.session_state:
    st.session_state['rag_agent'] = rag_agent

# ================= 🎨 Anime Style UI 2.0 =================
def load_css():
    with open("assets/style.css", "r") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

load_css()

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

ITEMS_PER_PAGE = 24  # Increased to show more spots

def clean_markdown_output(text):
    if not text: return ""
    pattern = r"^```(?:markdown)?\s*([\s\S]*?)\s*```$"
    match = re.match(pattern, text, re.IGNORECASE)
    if match: return match.group(1).strip()
    return text.strip()

def save_feedback(query, response, is_positive):
    """
    Data Flywheel: Save user feedback to a local JSONL file.
    If Negative (Thumbs Down), it becomes a 'Bad Case' for future tuning.
    """
    feedback_file = "evaluation/feedback_log.jsonl"
    bad_case_file = "evaluation/bad_cases.log"
    
    timestamp = datetime.now().isoformat()
    record = {
        "timestamp": timestamp,
        "query": query,
        "response": response,
        "is_positive": is_positive
    }
    
    # Ensure directory exists
    os.makedirs("evaluation", exist_ok=True)
    
    # 1. Append to General Log
    with open(feedback_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        
    # 2. If Negative, valid Date Recipe optimization source
    if not is_positive:
        bad_cases = []
        if os.path.exists(bad_case_file):
            try:
                with open(bad_case_file, "r", encoding="utf-8") as f:
                    bad_cases = json.load(f)
            except: pass
            
        bad_cases.append(record)
        
        with open(bad_case_file, "w", encoding="utf-8") as f:
            json.dump(bad_cases, f, indent=2, ensure_ascii=False)
    
    st.toast("Feedback Received! (Data Flywheel Updated)", icon="🧬")

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
    
    # Force sidebar update correctly
    if 'render_sidebar_itinerary' in globals():
        render_sidebar_itinerary()
    
    # Restore Rerun to ensure other tabs (Plan) and button states update
    st.rerun()

def remove_from_itinerary(idx):
    if 0 <= idx < len(st.session_state['itinerary']):
        item = st.session_state['itinerary'].pop(idx)
        st.toast(f"🗑️ 已移除: {item.get('name')}")
        
        # Force sidebar update
        if 'render_sidebar_itinerary' in globals():
            render_sidebar_itinerary()
        
        # Restore Rerun
        st.rerun()

# ================= Sidebar =================
with st.sidebar:
    st.markdown("## 🎒 巡礼背包 <br><small>Adventure Bag</small>", unsafe_allow_html=True)
    
    with st.expander("⚙️ 魔法设定 (Settings)", expanded=True):
        amap_key = st.text_input("GaoDe Key (Map)", type="password", key="amap_key")
        dashscope_key = st.text_input("DashScope Key (AI)", type="password", key="dashscope_key")
        
        # Auto-sanitize keys to prevent 'latin-1' header errors
        if amap_key: amap_key = amap_key.strip()
        if dashscope_key: dashscope_key = str(dashscope_key).strip()

            
    st.markdown("---")
    st.markdown("---")
    
    # Dynamic Sidebar Container
    sidebar_placeholder = st.empty()
    
    def render_sidebar_itinerary():
        with sidebar_placeholder.container():
            st.markdown(f"#### 🗺️ 待攻略副本 ({len(st.session_state['itinerary'])})")
            if st.session_state['itinerary']:
                for i, item in enumerate(st.session_state['itinerary']):
                    st.markdown(f"**{i+1}. {item.get('cn') or item.get('name')}**")
                    st.caption(f"📺 {item.get('_anime_name')}")
                st.markdown("---")
                st.success("Ready! 前往生成路书 👉")
            else: 
                st.markdown("*背包是空的... (´；ω；`)*")
                st.markdown("*快去寻找心动的圣地吧！*")
                st.markdown("---")

    render_sidebar_itinerary()

# ================= Main UI =================
# Hero Section
st.markdown(render_hero(), unsafe_allow_html=True)

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
                 candidates = retriever.get_anime_candidates(name)
                 if candidates:
                     info = candidates[0]
                     rec_candidates.append(info)
                 else:
                     # Attempt fallback or skip
                     pass
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
                 st.warning("未能获取完整番剧详情。")
                 return False

    # === Chat History Init ===
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    # Display History
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Unified Input
    prompt = st.chat_input("输入指令... (Enter command)")

    if prompt:
        if not dashscope_key:
             st.error("需要 DashScope Key 才能启动观测者。")
        else:
             # Display and Save User Message
             with st.chat_message("user"):
                 st.write(prompt)
             st.session_state["messages"].append({"role": "user", "content": prompt})
                 
             ali_ai.dashscope.api_key = dashscope_key 
             
             # Initialize Agent with existing retriever
             from core.agent import AnimeRagAgent
             if 'rag_agent' not in st.session_state:
                 st.session_state['rag_agent'] = AnimeRagAgent(retriever=retriever)
             
             # Analyze Intent with History
             intent_data = st.session_state['rag_agent'].analyze_intent(prompt, history=st.session_state["messages"])
             intent_type = intent_data.get('intent', 'CHAT')
             intent_query = intent_data.get('keywords', prompt)
             
             with st.chat_message("assistant"):
                 
                 # === CASE 1: RECOMMENDATION ===
                 if intent_type == 'RECOMMEND':
                    st.markdown(render_agent_status("thinking", f"Creating recommendations for: {intent_query}"), unsafe_allow_html=True)
                    if run_recommendation(intent_query):
                         st.success(f"已为您准备好推荐作品，请点击卡片查看圣地。")

                 # === CASE 2: SEARCH ===
                 elif intent_type == 'SEARCH':
                      st.markdown(render_agent_status("searching", f"Searching for: {intent_query}"), unsafe_allow_html=True)
                      with st.spinner("Searching knowledge base..."):
                          candidates = retriever.get_anime_candidates(intent_query)
                          st.session_state['search_candidates'] = candidates
                          st.session_state['search_results'] = []
                          st.session_state['current_anime'] = None
                          st.session_state['is_rec_result'] = False # Not a rec
                          
                          if candidates:
                             st.success(f"✅ Found {len(candidates)} potential matches.")
                          else:
                             st.warning("⚠️ No matches found in the knowledge base.")

                 # === CASE 3: CHAT (RAG Enchanced) ===
                 else:
                     st.markdown(render_agent_status("thinking", "Agent Activation (RAG Protocol)..."), unsafe_allow_html=True)
                     
                     from core.agent import AnimeRagAgent
                     # Initialize RAG Agent (Lazy Load)
                     if 'rag_agent' not in st.session_state:
                         st.session_state['rag_agent'] = AnimeRagAgent()
                     
                     result = st.session_state['rag_agent'].generate_response(prompt, dashscope_key)
                     
                     if isinstance(result, dict):
                         # RAG Structure
                         response = result.get('response', 'Error')
                         thought = result.get('thought', 'Direct Search')
                         context = result.get('context', [])
                         
                         with st.expander("🧠 Agent Thought Trace", expanded=False):
                             st.markdown(f"**Intent**: {thought}")
                             # Fix: Handle both old (flat) and new (hierarchical) context structures
                             debug_view = []
                             for c in context[:5]:
                                 if 'meta' in c: # New AnimeItem
                                     debug_view.append({
                                         "anime": c.get('meta', {}).get('titles', {}).get('cn'),
                                         "spots_count": len(c.get('spots', []))
                                     })
                                 else: # Old Spot Item
                                     debug_view.append({
                                         "an": c.get('anime_name') or c.get('name'), 
                                         "spot": c.get('spot_name')
                                     })
                             st.json(debug_view)
                         
                         st.markdown("### 💡 Agent Response")
                         st.markdown(response)
                     else:
                         # Fallback string
                         st.markdown(result)
                         response = result # For feedback structure
                     
                     # === Data Flywheel: User Feedback ===
                     col_fb_1, col_fb_2, _ = st.columns([1, 1, 8])
                     with col_fb_1:
                         if st.button("👍", key=f"fb_up_{int(time.time())}"):
                             save_feedback(prompt, response, True)
                     with col_fb_2:
                         if st.button("👎", key=f"fb_down_{int(time.time())}"):
                             save_feedback(prompt, response, False)

    
    # Render Search Candidates (Grid Layout)
    if st.session_state.get('search_candidates') and not st.session_state.get('search_results'):
        st.markdown("### 🤔 Target Verification")
        
        candidates = st.session_state['search_candidates'][:20]
        # Masonry-like Grid
        cols = st.columns(3)
        for i, cand in enumerate(candidates):
            with cols[i % 3]:
                # Use standard container for selection to keep button interactive
                with st.container():
                     # Cover Image
                     img = cand.get('image') or "https://via.placeholder.com/300x160.png?text=No+Cover"
                     st.image(img, use_container_width=True)
                     
                     st.markdown(f"**{cand['cn']}**")
                     st.caption(cand['summary'])
                     
                     # Primary Action Button
                     if st.button(f"🚀 Deploy", key=f"sel_{cand['id']}_{i}", help=f"Explore spots for {cand['cn']}"):
                         with st.status("🚀 Deploying Scanners..."):
                             st.write(f"📡 Scanning spots for {cand['cn']}...")
                             st.write(f"📡 Scanning spots for {cand['cn']}...")
                             
                             raw_pts = retriever.get_spots_by_anime_id(cand['id'])
                             
                             if raw_pts:
                                 new_pts = []
                                 for p in raw_pts:
                                     np = dict(p)
                                     # Inject Context for UI
                                     np['_anime_name'] = cand['cn']
                                     # Use city from ETL (now available), fallback to Unknown
                                     np['_city'] = p.get('city') or "Unknown" 
                                     new_pts.append(np)
                                 st.session_state['search_results'] = new_pts
                                 st.session_state['current_anime'] = cand['cn']
                                 st.session_state['page'] = 0
                                 st.session_state['search_candidates'] = [] # Clear candidates to show results
                                 st.rerun()
                             else: st.error("No data found.")

    # === Result List Display (Common) ===
    if st.session_state['search_results']:
        st.markdown("---")
        c_back, c_title = st.columns([1, 4])
        with c_back:
            if st.button("🔙 返回/清空", type="secondary"):
                st.session_state['search_results'] = []
                st.session_state['current_anime'] = None
                st.rerun()
        
        total_items = len(st.session_state['search_results'])
             
        with c_title:
            if st.session_state['current_anime'] == "AI 精选推荐":
                st.markdown(f"### ✨ 此刻的命运之选 ({total_items})")
            else:
                st.markdown(f"### 📍 {st.session_state['current_anime']} 圣地列表 (共 {total_items} 个)")
                
        start_idx = st.session_state['page'] * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        items = st.session_state['search_results'][start_idx:end_idx]
        
        for pt in items:
            with st.container():
                # Enrich Data: City & Description
                if not pt.get('_city') or pt.get('_city') in ['Unknown', 'Unknown City', ""]:
                   # Try to get city from coordinates on the fly
                   if st.session_state.get('amap_key'):
                        c_code = amap.get_regeo_city(pt['lon'], pt['lat'], st.session_state['amap_key'])
                        if c_code:
                             # Since get_regeo_city return adcode mostly, let's try to get address for better display
                             addr = amap.get_address_from_coords(pt['lon'], pt['lat'], st.session_state['amap_key'])
                             # Extract city from address roughly or just use address
                             pt['_city'] = addr.split('市')[0] + '市' if '市' in addr else "Unknown City"
                   else:
                        pt['_city'] = "Unknown City"
                
                # Render HTML Card
                card_html = render_anime_card(pt)
                st.markdown(card_html, unsafe_allow_html=True)
                
                # Action Buttons (Native Streamlit) aligned with card
                col_spacer, col_btn = st.columns([4, 1])
                with col_btn:
                    if st.button("➕ Collect", key=f"add_{pt['id']}_p{st.session_state['page']}"): 
                        add_to_itinerary(pt, pt.get('_anime_name'))
         
        if total_items > ITEMS_PER_PAGE:
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
                    st.markdown(f"**{item.get('spot_name') or item.get('name') or '未知地点'}**")
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
                                "lat": slat, 
                                "lon": slon
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
                       try: city = amap.get_regeo_city(s['lon'], s['lat'], amap_key)
                       except: pass
                   
                   route = None
                   # 1. Try Transit (Recommended Strategy 0)
                   try:
                       route = amap.get_transit_route(s['lon'], s['lat'], e['lon'], e['lat'], city, amap_key, strategy=0)
                   except Exception as e:
                       print(f"Plan Route Error: {e}")
                   
                   if not route:
                       # 2. Fallback: Walking
                       try:
                           route = amap.get_walking_route(s['lon'], s['lat'], e['lon'], e['lat'], amap_key)
                       except Exception as e: print(f"Walking Error: {e}")
                   
                   if not route:
                       # 3. Fallback: Driving
                       try:
                           route = amap.get_driving_route(s['lon'], s['lat'], e['lon'], e['lat'], amap_key)
                       except Exception as e: print(f"Driving Error: {e}")
                       
                   if not route:
                        # 4. Fallback: Straight Line (Geodesic)
                        try:
                            dist_km = geodesic((s['lat'], s['lon']), (e['lat'], e['lon'])).km
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
                   map_points.append((float(p['lon']), float(p['lat']))) # lon, lat
                   # Try to find image (anitabi might have 'image' field)
                   img = p.get('image') or p.get('img')
                   if img: spot_images.append({'name': p.get('cn') or p.get('name', '圣地'), 'src': img})
               
               # === Render Visuals (Dashboard Reborn) ===
               st.balloons()
               st.divider()
               
               # 1. Interactive Map (PyDeck for Global Support)
               if map_points:
                   # Center map
                   mid_lat = sum(p[1] for p in map_points) / len(map_points)
                   mid_lon = sum(p[0] for p in map_points) / len(map_points)
                   
                   # Data for Layers
                   # 1. Path Layer
                   path_data = [{"path": [[p[0], p[1]] for p in map_points], "color": [255, 126, 179]}]
                   
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
                               get_color=[122, 175, 255],
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
