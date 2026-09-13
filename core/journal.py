"""Private travel records and explicit projections, independent of planning events."""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import date, datetime
from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from core.private_store import _identifier, _text, _url
from core.trip import TOKYO, _keys, _int

MAX_PHOTO_BYTES = 600_000
MAX_JOURNAL_BACKUP = 16 * 1024 * 1024


def today():
    return datetime.now(TOKYO).date()


def day_value(value, *, past=False):
    if not isinstance(value, str):
        raise ValueError("日期格式应为 YYYY-MM-DD")
    day = date.fromisoformat(value)
    if past and day > today():
        raise ValueError("不能把未来计划确认为实际到访或拍摄")
    return day.isoformat()


def clean_photo(raw):
    """Decode user images, correct orientation, then re-encode without EXIF/GPS."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 8 * 1024 * 1024:
        raise ValueError("请选择不超过 8 MiB 的 JPEG／PNG／WebP 照片")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as img:
                if img.format not in {"JPEG", "PNG", "WEBP"} or img.width * img.height > 20_000_000:
                    raise ValueError("仅支持至多 2000 万像素的 JPEG／PNG／WebP")
                img = ImageOps.exif_transpose(img).convert("RGB")
                img.thumbnail((1600, 1600))
                for quality in (85, 70, 50):
                    out = BytesIO()
                    img.save(out, format="JPEG", quality=quality, optimize=True)
                    if out.tell() <= MAX_PHOTO_BYTES:
                        return out.getvalue()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("无法读取照片，请使用有效的 JPEG／PNG／WebP") from exc
    raise ValueError("压缩后照片仍过大，请先缩小图片")


def validate_entry(raw):
    _keys(raw, {"id", "revision", "location_id", "trip_id", "date", "stay_min", "confirmed",
                "note", "short_text", "source_key", "created_at", "updated_at"},
          {"id", "revision", "location_id", "trip_id", "date", "stay_min", "confirmed",
           "note", "short_text", "source_key", "created_at", "updated_at"})
    if type(raw["confirmed"]) is not bool:
        raise ValueError("需明确确认是否到访")
    result = {**raw, "id": _identifier(raw["id"]), "location_id": _identifier(raw["location_id"]),
              "revision": _int(raw["revision"], 1, 1_000_000), "date": day_value(raw["date"], past=True),
              "note": _text(raw["note"], "private note", 3000),
              "short_text": _text(raw["short_text"], "editable short text", 2000),
              "trip_id": _identifier(raw["trip_id"]) if raw["trip_id"] else "",
              "source_key": _text(raw["source_key"], "source key", 400)}
    if result["stay_min"] is not None:
        _int(result["stay_min"], 1, 1440)
    for field in ("created_at", "updated_at"):
        if datetime.fromisoformat(raw[field]).tzinfo is None:
            raise ValueError("记录时间需要时区")
    return result


def validate_photo(raw):
    _keys(raw, {"id", "entry_id", "scene_id", "taken_on", "rights", "scope", "caption"},
          {"id", "entry_id", "scene_id", "taken_on", "rights", "scope", "caption"})
    if raw["rights"] not in {"own", "private_only"} or raw["scope"] not in {"private", "share_allowed"}:
        raise ValueError("照片使用范围无效")
    if raw["scope"] == "share_allowed" and raw["rights"] != "own":
        raise ValueError("未确认公开使用权的照片只能私密保存")
    return {**raw, "id": _identifier(raw["id"]), "entry_id": _identifier(raw["entry_id"]),
            "scene_id": _identifier(raw["scene_id"]) if raw["scene_id"] else "",
            "taken_on": day_value(raw["taken_on"], past=True), "caption": _text(raw["caption"], "caption", 500)}


def validate_preferences(raw):
    _keys(raw, {"follows", "dismissed", "measure_consent"}, {"follows", "dismissed", "measure_consent"})
    if type(raw["measure_consent"]) is not bool or not isinstance(raw["follows"], list) or len(raw["follows"]) > 100:
        raise ValueError("订阅设置无效")
    seen = set()
    for follow in raw["follows"]:
        _keys(follow, {"kind", "id", "since"}, {"kind", "id", "since"})
        if follow["kind"] not in {"anime", "destination"}:
            raise ValueError("不支持的关注类型")
        _identifier(follow["id"])
        if datetime.fromisoformat(follow["since"]).tzinfo is None or (follow["kind"], follow["id"]) in seen:
            raise ValueError("关注时间或重复关注无效")
        seen.add((follow["kind"], follow["id"]))
    if not isinstance(raw["dismissed"], list) or len(raw["dismissed"]) > 500:
        raise ValueError("不感兴趣列表过长")
    for item in raw["dismissed"]:
        _identifier(item)
    return deepcopy(raw)


def region_ids(point, catalog):
    regions = {d["id"]: d.get("parent_id") for d in catalog["destinations"]}
    result, current = set(), point["destination_id"]
    while current and current not in result:
        result.add(current)
        current = regions.get(current)
    return result


def recommendations(catalog, preferences, wishlist, entries, *, limit=8):
    follows = preferences["follows"]
    works = {f["id"] for f in follows if f["kind"] == "anime"}
    regions = {f["id"] for f in follows if f["kind"] == "destination"}
    saved = {p["id"] for p in wishlist}
    visited = {e["location_id"] for e in entries if e["confirmed"]}
    places = {p["id"]: p for p in catalog["locations"]}
    experienced = {a for loc in visited for a in places.get(loc, {}).get("anime_ids", [])}
    wanted = works | {a for p in wishlist for a in p.get("anime_ids", [])} | experienced
    result = []
    for point in catalog["locations"]:
        if point["id"] in visited | set(preferences["dismissed"]) or point.get("withdrawn") or point["access"]["status"] in {"closed", "prohibited"}:
            continue
        reason, score = [], 0
        if point["id"] in saved:
            reason.append("你收藏过，尚未确认到访")
            score += 6
        if wanted.intersection(point["anime_ids"]):
            reason.append("关联你关注、收藏或到访过的作品")
            score += 3
        if regions.intersection(region_ids(point, catalog)):
            reason.append("位于你明确关注的目的地")
            score += 2
        if reason:
            result.append({"location": point, "reason": "；".join(reason), "score": score})
    return sorted(result, key=lambda r: (-r["score"], r["location"]["id"]))[:limit]


def public_projection(plan, catalog, *, title, text, photo_ids):
    """Allowlist only; hotel, concrete dates, notes, history and owner never enter."""
    places = {p["id"]: p for p in catalog["locations"]}
    days = []
    for index, day in enumerate(plan["days"], 1):
        stops = []
        for stop in day["stops"]:
            point = places.get(stop["location_id"])
            if not point or point.get("withdrawn") or point["access"]["status"] in {"closed", "prohibited"}:
                raise ValueError("路线中有已撤下或不宜访问的地点，请先编辑个人 Trip")
            stops.append({"location_id": point["id"], "name": point["name"], "stay_min": stop["stay_min"],
                          "required": stop["priority"] == "required"})
        days.append({"day": index, "stops": stops})
    if not any(day["stops"] for day in days):
        raise ValueError("至少选择一个路线站点")
    return {"title": _text(title, "public title", 120, empty=False), "text": _text(text, "public text", 1200),
            "destination_id": "tokyo", "days": days, "photo_ids": list(photo_ids),
            "warning": "用户分享的筹备路线，不是现场或交通已核实保证。复制后请填写自己的日期与起终点。"}


def share_card_svg(public):
    from html import escape
    count = sum(len(d["stops"]) for d in public["days"])
    title = escape(public["title"])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">'
            '<rect width="960" height="540" rx="32" fill="#111630"/>'
            '<text x="64" y="92" font-family="sans-serif" font-size="26" fill="#68e1fd">AnimeWay · TOKYO</text>'
            f'<foreignObject x="64" y="145" width="820" height="200"><div xmlns="http://www.w3.org/1999/xhtml" '
            f'style="font-family:sans-serif;font-size:42px;color:#f5f7ff;overflow-wrap:anywhere">{title}</div></foreignObject>'
            f'<text x="64" y="410" font-family="sans-serif" font-size="28" fill="#f5f7ff">{len(public["days"])} DAYS · {count} STOPS</text>'
            '<text x="64" y="480" font-family="sans-serif" font-size="22" fill="#aab4d6">Shared route draft · Check current access and transport</text></svg>').encode()


def encode_photo(data):
    return base64.b64encode(data).decode("ascii")


def source_url(raw):
    value = _url(raw)
    if not value:
        raise ValueError("必须提供可核查的来源链接")
    return value
