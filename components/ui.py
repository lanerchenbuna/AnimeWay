from __future__ import annotations

import base64
import html
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

from components.i18n import tr


@lru_cache(maxsize=4)
def _asset_data_uri(path: str) -> str:
    asset = Path(path)
    if not asset.exists():
        return ""
    mime = "image/webp" if asset.suffix.lower() == ".webp" else "image/png"
    payload = base64.b64encode(asset.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def render_hero(locale: str = "zh_CN") -> str:
    hero_uri = _asset_data_uri("assets/images/animeway-hero.webp")
    safe_uri = html.escape(hero_uri, quote=True)
    return f"""
<section class="hero-container aw-reveal" style="--hero-image: url('{safe_uri}')">
    <div class="hero-grid" aria-hidden="true"></div>
    <div class="hero-orbit hero-orbit--one" aria-hidden="true"></div>
    <div class="hero-orbit hero-orbit--two" aria-hidden="true"></div>
    <div class="hero-content">
        <div class="hero-eyebrow"><span class="signal-dot"></span>{tr("hero_eyebrow", locale=locale)}</div>
        <div class="hero-title">{tr("hero_title", locale=locale)}</div>
        <p class="hero-subtitle">{tr("hero_subtitle", locale=locale)}</p>
        <div class="hero-trilingual">
            <span>{tr("hero_en", locale=locale)}</span>
            <span>{tr("hero_jp", locale=locale)}</span>
        </div>
        <div class="hero-stats">
            <div class="hero-stat">
                <span class="hero-stat__value">{tr("hero_local_value", locale=locale)}</span>
                <span class="hero-stat__label">{tr("hero_local", locale=locale)}</span>
            </div>
            <div class="hero-stat">
                <span class="hero-stat__value">{tr("hero_points_value", locale=locale)}</span>
                <span class="hero-stat__label">{tr("hero_points", locale=locale)}</span>
            </div>
            <div class="hero-stat">
                <span class="hero-stat__value">{tr("hero_route_value", locale=locale)}</span>
                <span class="hero-stat__label">{tr("hero_route", locale=locale)}</span>
            </div>
        </div>
    </div>
    <div class="hero-coordinate" aria-hidden="true">
        <span>35.6812° N</span><span>139.7671° E</span>
    </div>
    <div class="hero-scroll" aria-hidden="true"><span></span>SCROLL TO DEPART</div>
</section>
"""


def render_section_header(title: str, kicker: str, description: str) -> str:
    return f"""
<header class="section-heading aw-reveal">
    <div class="section-heading__kicker">{html.escape(kicker)}</div>
    <h2>{html.escape(title)}</h2>
    <p>{html.escape(description)}</p>
</header>
"""


def render_anime_card(spot: dict, locale: str = "zh_CN") -> str:
    """Render an escaped pilgrimage spot card."""
    raw_img = spot.get("image") or spot.get("img")
    img_src = str(raw_img or "")
    if "plan=h" in img_src:
        img_src = img_src.replace("plan=h160", "plan=h360")

    name = spot.get("spot_name") or spot.get("name") or tr("unknown_location", locale=locale)
    anime = spot.get("anime_name") or spot.get("_anime_name") or tr("unknown_anime", locale=locale)
    city = spot.get("_city") or spot.get("city") or tr("unknown_city", locale=locale)
    try:
        lat, lon = float(spot.get("lat", 0)), float(spot.get("lon", 0))
    except (TypeError, ValueError):
        lat, lon = 0.0, 0.0

    map_url = "https://www.google.com/maps/search/?" + urlencode(
        {"api": "1", "query": f"{lat},{lon}"}
    )
    description = spot.get("description") or spot.get("content") or tr(
        "spot_fallback", locale=locale, city=city
    )

    safe_name = html.escape(str(name), quote=True)
    safe_anime = html.escape(str(anime), quote=True)
    safe_city = html.escape(str(city), quote=True)
    safe_description = html.escape(str(description), quote=True)
    safe_map_url = html.escape(map_url, quote=True)
    if img_src:
        media = (
            f'<img src="{html.escape(img_src, quote=True)}" alt="{safe_name}" '
            'loading="lazy" decoding="async">'
        )
    else:
        media = """
<div class="spot-card__fallback" aria-hidden="true">
    <span class="spot-card__fallback-ring"></span>
    <span>NO VISUAL<br>COORDINATE</span>
</div>
"""

    return f"""
<article class="spot-card aw-reveal">
    <div class="spot-card__media">
        {media}
        <div class="spot-card__index">WAYPOINT</div>
    </div>
    <div class="spot-card__body">
        <div class="spot-card__topline">
            <div class="spot-card__title">{safe_name}</div>
            <div class="location-badge">⌖ {safe_city}</div>
        </div>
        <div class="spot-card__tags">
            <span class="anime-tag">PLAY · {safe_anime}</span>
            <span class="anime-tag anime-tag--coord">{lat:.4f} / {lon:.4f}</span>
        </div>
        <p class="spot-card__description">{safe_description}</p>
        <a href="{safe_map_url}" target="_blank" rel="noopener noreferrer" class="nav-btn">
            <span>↗</span> {tr("navigate", locale=locale)}
        </a>
    </div>
</article>
"""


def render_agent_status(stage: str, message: str) -> str:
    icons = {
        "thinking": "◌",
        "searching": "⌕",
        "done": "✓",
        "error": "△",
        "writing": "✎",
    }
    icon = icons.get(stage, "◇")
    safe_message = html.escape(str(message), quote=True)
    return f"""
<div class="agent-box aw-reveal">
    <div class="agent-box__icon">{icon}</div>
    <div>
        <div class="agent-box__label">ANIMEWAY SIGNAL</div>
        <div class="agent-box__message">{safe_message}</div>
    </div>
</div>
"""
