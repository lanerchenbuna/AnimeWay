import html
from urllib.parse import urlencode


def render_hero():
    return """
<div class="hero-container fade-in">
    <div class="hero-background-shape"></div>
    <div class="hero-content">
        <div class="hero-title">⛩️ AnimeWay</div>
        <div class="hero-subtitle">✨ Break the Dimensional Wall | 突破次元壁的圣地巡礼 ✨</div>
    </div>
</div>
"""

def render_anime_card(spot):
    """
    Renders a premium glassmorphism card for an anime spot.
    """
    img_src = str(spot.get('image') or spot.get('img') or "https://via.placeholder.com/400x225.png?text=No+Signal")
    # Basic quality enhancement for some sources
    if "plan=h" in img_src: img_src = img_src.replace("plan=h160", "plan=h360")
    
    name = spot.get('spot_name') or spot.get('name') or "Unknown Location"
    anime = spot.get('anime_name') or spot.get('_anime_name') or "Unknown Anime"
    city = spot.get('_city') or spot.get('city') or "Coordinates"
    try:
        lat, lon = float(spot.get('lat', 0)), float(spot.get('lon', 0))
    except (TypeError, ValueError):
        lat, lon = 0.0, 0.0
    
    # Generate map link
    map_url = "https://www.amap.com/search?" + urlencode({"query": f"{lat},{lon}"})
    
    # Flattened HTML to avoid Markdown indentation issues
    description = spot.get('description') or spot.get('content') or f"位于 {city} 的巡礼圣地。"
    safe_img_src = html.escape(img_src, quote=True)
    safe_name = html.escape(str(name), quote=True)
    safe_anime = html.escape(str(anime), quote=True)
    safe_city = html.escape(str(city), quote=True)
    safe_description = html.escape(str(description), quote=True)
    safe_map_url = html.escape(map_url, quote=True)
    
    return f"""
<div class="anime-card fade-in">
    <div style="display: flex; gap: 24px; align-items: stretch;">
        <div style="flex: 2; min-width: 200px;" class="card-image-container">
            <img src="{safe_img_src}" style="width: 100%; height: 100%; object-fit: cover; min-height: 160px; transition: transform 0.5s;">
        </div>
        <div style="flex: 3; display: flex; flex-direction: column; justify-content: space-between; padding-top: 5px; padding-bottom: 5px;">
            <div>
                 <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div class="card-title">{safe_name}</div>
                    <div class="location-badge">📍 {safe_city}</div>
                 </div>
                 <div style="margin-top: 8px; margin-bottom: 8px; display: flex; flex-wrap: wrap; gap: 8px;">
                    <span class="anime-tag">📺 {safe_anime}</span>
                    <span class="anime-tag">🧭 {lat:.4f}, {lon:.4f}</span>
                 </div>
                 <div style="font-size: 0.9rem; color: #555; margin-bottom: 12px; line-height: 1.4;">
                    {safe_description}
                 </div>
            </div>
            <div style="display: flex; gap: 12px; align-items: center; margin-top: auto;">
                <a href="{safe_map_url}" target="_blank" class="nav-btn">
                    🗺️ 导航
                </a>
            </div>
        </div>
    </div>
</div>
"""

def render_agent_status(stage, message):
    icons = {
        "thinking": "🧠",
        "searching": "🔍",
        "done": "✅",
        "error": "⚠️",
        "writing": "✍️"
    }
    icon = icons.get(stage, "🤖")
    safe_message = html.escape(str(message), quote=True)
    
    return f"""
<div class="agent-box fade-in">
    <div style="font-size: 1.5rem;">{icon}</div>
    <div style="flex-grow: 1;">
        <div style="font-weight: 700; color: #7AF; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 1px;">状态</div>
        <div style="color: #2D3436;">{safe_message}</div>
    </div>
</div>
"""
