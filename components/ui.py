from __future__ import annotations

import base64
import html
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

from components.i18n import tr
from data_factory.normalization import safe_url


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


def render_agent_intro(*, qwen_ready: bool, amap_ready: bool, locale: str = "zh_CN") -> str:
    """A compact first screen that explains the routebook workflow and service state."""
    copy = {
        "zh_CN": (
            "东京精选 · 智能巡礼", "从喜欢的动画，走进真实的街道。",
            "说出作品、日期和旅行节奏。AnimeWay 会找到有来源的圣地，安排每天的顺序，并给出可核查的路书。",
            "提出想法", "查看地点与路线", "保存个人 Trip", "已连接", "未配置", "Qwen 用于可选 AI 路书；高德只补充地点地址。东京公共交通仍需外部核查。",
        ),
        "en_US": (
            "Tokyo pilot · Anime pilgrimage", "From a favorite story to a real journey.",
            "Tell us the title, date and pace. AnimeWay finds sourced places and creates a routebook you can review.",
            "Describe your trip", "Review places and routes", "Save your Trip", "Connected", "Not configured", "Qwen is optional for AI routebooks; AMap only supplements place addresses. Check Tokyo transit externally.",
        ),
        "ja_JP": (
            "東京の聖地 · 巡礼プラン", "好きな物語から、実際の街へ。",
            "作品、日付、旅のペースを伝えると、出典のある場所を探して確認できる旅程を作ります。",
            "希望を伝える", "場所と経路を確認", "旅程を保存", "接続済み", "未設定", "Qwen は任意の AI 旅程、高徳地図は住所補完用です。東京の公共交通は外部で確認してください。",
        ),
    }
    hero_uri = html.escape(_asset_data_uri("assets/images/animeway-hero.webp"), quote=True)
    eyebrow, title, description, step_one, step_two, step_three, connected, missing, hint = copy.get(locale, copy["zh_CN"])
    qwen_status = connected if qwen_ready else missing
    amap_status = connected if amap_ready else missing
    return f"""
<section class="agent-intro" style="--agent-image: url('{hero_uri}')">
  <div class="agent-intro__content">
    <span class="agent-intro__eyebrow">ANIMEWAY / {html.escape(eyebrow)}</span>
    <h1>{html.escape(title)}</h1>
    <p>{html.escape(description)}</p>
    <div class="agent-intro__services" aria-label="API 状态">
      <span class="{'is-ready' if qwen_ready else 'is-pending'}">Qwen · {qwen_status}</span>
      <span class="{'is-ready' if amap_ready else 'is-pending'}">高德地点补充 · {amap_status}</span>
    </div>
  </div>
</section>
<div class="agent-steps" aria-label="巡礼流程">
  <div><b>01</b><span>{html.escape(step_one)}</span></div>
  <div><b>02</b><span>{html.escape(step_two)}</span></div>
  <div><b>03</b><span>{html.escape(step_three)}</span></div>
</div>
<p class="agent-key-hint">{html.escape(hint)}</p>
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
    img_src = safe_url(raw_img) or ""
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
        background_url = quote(img_src, safe=":/?&=%#;,@+-._~")
        media = (
            f'<div class="spot-card__preview" role="img" aria-label="{safe_name} 场景预览" '
            f'style="background-image:url({background_url})">'
            '<span>上游场景图 · 无法加载时请查看来源</span></div>'
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
        {f'<a href="https://anitabi.cn/map?bangumiId={html.escape(str(spot.get("anime_id")), quote=True)}" target="_blank" rel="noopener noreferrer" class="spot-card__source">Anitabi 来源 ↗</a>' if img_src and urlsplit(img_src).hostname == "image.anitabi.cn" and str(spot.get("anime_id", "")).isdigit() else ""}
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
