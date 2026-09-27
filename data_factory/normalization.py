"""Anitabi boundary normalization shared by crawler and offline builds."""
import hashlib
import math
import re
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

from data_factory.schema import Spot

# Persist only these additional fields in the runtime index.
SPOT_DETAIL_FIELDS = (
    "identity_kind", "source_point_id", "timecode_seconds", "origin", "origin_url",
    "group", "source_raw", "normalization_issues", "legacy_variants",
)

# Upstream serves each point image as .../points/<pointId>-<stamp>.jpg or
# .../points/<bangumiId>/<pointId>_<stamp>.jpg. The point ID is upstream-provided
# evidence, not a name or distance guess, but callers must still confirm it against a
# refreshed record before treating it as an identity mapping. Short tokens are real
# (the saved snapshot contains a.jpg and c.jpg), and a wrong guess only fails to match.
_IMAGE_PATH = re.compile(
    r"/points/(?:[A-Za-z0-9]+/)?([A-Za-z0-9]{1,40}?)(?:[-_][^/]*)?\.(?:jpe?g|png|webp)$",
    re.IGNORECASE,
)


def image_point_id(image_url: Any) -> str | None:
    """Recover the upstream point ID embedded in an upstream image URL."""
    value = safe_url(image_url)
    if not value:
        return None
    parts = urlsplit(value)
    match = _IMAGE_PATH.search(parts.path)
    return match.group(1) if match else None


def stable_spot_id(anime_id: int, name: str, lat: float, lon: float) -> str:
    """Keep the pre-map fallback exactly: saved references depend on this hash."""
    source = f"{anime_id}:{name}:{lat:.6f}:{lon:.6f}"
    return hashlib.sha1(source.encode("utf-8")).hexdigest()


def extract_lat_lon(point: dict) -> tuple[float | None, float | None]:
    geo = point.get("geo")
    values = geo if isinstance(geo, list) and len(geo) == 2 else [point.get("lat"), point.get("lon")]
    try:
        if any(isinstance(value, bool) for value in values):
            return None, None
        lat, lon = map(float, values)
        if not (math.isfinite(lat) and math.isfinite(lon)):
            return None, None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            return None, None
        return lat, lon
    except (TypeError, ValueError, OverflowError):
        return None, None


def text_value(value: Any) -> str | None:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return str(value).strip() or None
    return None


def safe_url(value: Any) -> str | None:
    value = text_value(value)
    if not value:
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme in {"http", "https"} and parts.hostname and not parts.username and not parts.password:
            return value
    except ValueError:
        pass
    return None


def _evidence(raw: dict) -> dict:
    evidence = deepcopy(raw.get("source_raw")) if isinstance(raw.get("source_raw"), dict) else {}
    for key in ("ep", "s", "origin", "originURL", "originLink", "folder", "group", "episode",
                "timecode_seconds", "source_url"):
        if "source_raw" not in raw and key in raw:
            evidence[key] = deepcopy(raw[key])
    return evidence


def _episode(raw: dict, issues: list) -> str | None:
    episode_raw = raw.get("episode") if raw.get("episode") is not None else raw.get("ep")
    episode = text_value(episode_raw)
    if episode_raw is not None and episode is None:
        issues.append("invalid_episode")
    return episode


def _timecode(raw: dict, issues: list) -> float | None:
    seconds_raw = raw.get("timecode_seconds") if raw.get("timecode_seconds") is not None else raw.get("s")
    if seconds_raw is None:
        return None
    try:
        seconds = float(seconds_raw)
        if isinstance(seconds_raw, bool) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        issues.append("invalid_timecode")
        return None
    return seconds


def _origin_url(raw: dict, issues: list) -> str | None:
    # Upstream sends the source link as originURL on most rows and originLink on others
    # (observed on work 328609, 2026-09-27).
    origin_raw = raw.get("origin_url") or raw.get("originURL") or raw.get("originLink")
    origin_url = safe_url(origin_raw)
    if origin_raw and not origin_url:
        issues.append("invalid_origin_url")
    return origin_url


def normalize_point_metadata(raw: dict) -> dict | None:
    """Validate an upstream point row that carries no coordinates.

    Current ``/points/detail`` rows no longer include ``geo``/``city``; they still carry
    the upstream point ID plus episode, timecode, origin and image facts. This returns
    exactly those facts without inventing coordinates, so a refresh can enrich existing
    points while geography stays with the audited snapshot. A row is usable when it has
    an upstream ID, even if its name is blank.
    """
    name = text_value(raw.get("name")) or text_value(raw.get("cn"))
    image = safe_url(raw.get("image") or raw.get("img"))
    point_id = text_value(raw.get("id")) or image_point_id(image)
    if not name and not point_id:
        return None
    issues = list(raw.get("normalization_issues") or [])
    return {
        "name": name,
        "point_id": point_id,
        "image": image,
        "description": text_value(raw.get("description") or raw.get("content")),
        "episode": _episode(raw, issues),
        "timecode_seconds": _timecode(raw, issues),
        "origin": text_value(raw.get("origin")),
        "origin_url": _origin_url(raw, issues),
        "group": text_value(raw.get("group") or raw.get("folder")),
        "source_raw": _evidence(raw),
        "normalization_issues": sorted(set(issues)),
    }


def normalize_spot(raw: dict, anime_id: int) -> Spot | None:
    name = text_value(raw.get("name")) or text_value(raw.get("cn"))
    lat, lon = extract_lat_lon(raw)
    if not name or lat is None or lon is None:
        return None
    legacy_id = stable_spot_id(anime_id, name, lat, lon)
    spot_id = text_value(raw.get("id")) or legacy_id
    identity = raw.get("identity_kind")
    if identity not in {"upstream", "legacy_derived"}:
        identity = "legacy_derived" if spot_id == legacy_id else "upstream"
    evidence = _evidence(raw)
    issues = list(raw.get("normalization_issues") or [])
    episode = _episode(raw, issues)
    seconds = _timecode(raw, issues)
    origin_url = _origin_url(raw, issues)
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = tags.split()
    elif not isinstance(tags, list):
        tags = [tags]
    return Spot(
        id=spot_id, name=name, lat=lat, lon=lon,
        image=safe_url(raw.get("image") or raw.get("img")),
        description=text_value(raw.get("description") or raw.get("content")),
        city=text_value(raw.get("city") or raw.get("_city")),
        tags=[text for tag in tags if (text := text_value(tag))],
        source_url=safe_url(raw.get("source_url")), episode=episode,
        scene=text_value(raw.get("scene")), verified_at=text_value(raw.get("verified_at")),
        identity_kind=identity,
        source_point_id=spot_id if identity == "upstream" else None,
        timecode_seconds=seconds, origin=text_value(raw.get("origin")), origin_url=origin_url,
        group=text_value(raw.get("group") or raw.get("folder")),
        legacy_variants=deepcopy(raw.get("legacy_variants") or []),
        source_raw=evidence, normalization_issues=sorted(set(issues)),
    )
