import hashlib
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Tuple

try:
    from data_factory.schema import AnimeItem, Spot
except ImportError:
    from schema import AnimeItem, Spot


BANGUMI_FILE = "knowledge_base/raw/bangumi_knowledge.json"
MANUAL_FILE = "knowledge_base/raw/manual_seeds.json"
ANITABI_FILE = "knowledge_base/raw/anitabi_crawl.json"
INDEX_FILE = "knowledge_base/index.json"


def load_json(filepath: str, default: Any) -> Any:
    if not os.path.exists(filepath):
        return default
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_tags(tags: Any) -> List[str]:
    if not tags:
        return []
    if isinstance(tags, list):
        return [str(tag).strip() for tag in tags if str(tag).strip()]
    if isinstance(tags, str):
        return [tag.strip() for tag in tags.split() if tag.strip()]
    return [str(tags).strip()]


def parse_score(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def stable_spot_id(anime_id: int, name: str, lat: float, lon: float) -> str:
    source = f"{anime_id}:{name}:{lat:.6f}:{lon:.6f}"
    return hashlib.sha1(source.encode("utf-8")).hexdigest()


def extract_lat_lon(raw_spot: Dict[str, Any]) -> Tuple[float | None, float | None]:
    geo = raw_spot.get("geo")
    if isinstance(geo, list) and len(geo) == 2:
        try:
            return float(geo[0]), float(geo[1])
        except (TypeError, ValueError):
            return None, None

    try:
        lat = float(raw_spot.get("lat"))
        lon = float(raw_spot.get("lon"))
        return lat, lon
    except (TypeError, ValueError):
        return None, None


def normalize_spot(raw_spot: Dict[str, Any], anime_id: int) -> Spot | None:
    name = str(raw_spot.get("name") or raw_spot.get("cn") or "").strip()
    lat, lon = extract_lat_lon(raw_spot)
    if not name or lat is None or lon is None:
        return None

    spot_id = raw_spot.get("id") or stable_spot_id(anime_id, name, lat, lon)
    return Spot(
        id=str(spot_id),
        name=name,
        image=raw_spot.get("image") or raw_spot.get("img"),
        lat=lat,
        lon=lon,
        description=raw_spot.get("description") or raw_spot.get("content"),
        city=raw_spot.get("city") or raw_spot.get("_city"),
        tags=normalize_tags(raw_spot.get("tags")),
    )


def build_rag_content(meta: Dict[str, Any], spots: List[Spot]) -> str:
    titles = meta.get("titles", {})
    parts = [
        titles.get("cn", ""),
        titles.get("jp", ""),
        meta.get("description", ""),
        " ".join(meta.get("tags", [])),
    ]
    for spot in spots:
        parts.extend([spot.name, spot.city or "", spot.description or "", " ".join(spot.tags)])
    return " ".join(str(part) for part in parts if part).lower()


def build_knowledge_base(write: bool = True) -> Dict[str, Any]:
    raw_meta = []
    raw_meta.extend(load_json(MANUAL_FILE, []))
    raw_meta.extend(load_json(BANGUMI_FILE, []))
    raw_spots = load_json(ANITABI_FILE, [])

    spots_map: Dict[int, List[Spot]] = {}
    skipped_spots = 0
    for raw_spot in raw_spots:
        try:
            anime_id = int(raw_spot.get("anime_id"))
        except (TypeError, ValueError):
            skipped_spots += 1
            continue

        spot = normalize_spot(raw_spot, anime_id)
        if spot is None:
            skipped_spots += 1
            continue
        spots_map.setdefault(anime_id, []).append(spot)

    items: List[Dict[str, Any]] = []
    seen_anime_ids = set()
    skipped_anime = 0

    for raw_item in raw_meta:
        try:
            anime_id = int(raw_item.get("subject") or raw_item.get("id"))
        except (TypeError, ValueError):
            skipped_anime += 1
            continue
        if anime_id in seen_anime_ids:
            continue
        seen_anime_ids.add(anime_id)

        titles = {
            "cn": raw_item.get("中文名") or raw_item.get("name_cn") or "",
            "jp": raw_item.get("原名") or raw_item.get("name_jp") or "",
        }
        if not titles["cn"] and titles["jp"]:
            titles["cn"] = titles["jp"]

        meta = {
            "id": anime_id,
            "titles": titles,
            "cover": raw_item.get("cover") or raw_item.get("image") or raw_item.get("封面"),
            "type": raw_item.get("类型") or raw_item.get("type"),
            "score": parse_score(raw_item.get("score") or raw_item.get("rating")),
            "tags": normalize_tags(raw_item.get("tags")),
            "description": raw_item.get("description") or raw_item.get("简介") or "",
        }
        spots = spots_map.get(anime_id, [])
        kb_item = AnimeItem(
            anime_id=anime_id,
            meta=meta,
            spots=spots,
            rag_content=build_rag_content(meta, spots),
        )
        items.append(kb_item.model_dump(mode="json"))

    spot_count = sum(len(item["spots"]) for item in items)
    missing_city = sum(1 for item in items for spot in item["spots"] if not spot.get("city"))
    missing_image = sum(1 for item in items for spot in item["spots"] if not spot.get("image"))
    stats = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "anime_count": len(items),
        "anime_with_spots": sum(1 for item in items if item["spots"]),
        "spot_count": spot_count,
        "missing_city": missing_city,
        "missing_image": missing_image,
        "skipped_anime": skipped_anime,
        "skipped_spots": skipped_spots,
        "source_files": {
            "bangumi": BANGUMI_FILE,
            "manual": MANUAL_FILE if os.path.exists(MANUAL_FILE) else None,
            "anitabi": ANITABI_FILE,
        },
    }
    payload = {"stats": stats, "items": items}

    if write:
        os.makedirs(os.path.dirname(INDEX_FILE), exist_ok=True)
        tmp_path = f"{INDEX_FILE}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, INDEX_FILE)

    return payload


def main() -> None:
    payload = build_knowledge_base(write=True)
    stats = payload["stats"]
    print("✅ Knowledge base built")
    print(f"   Index: {INDEX_FILE}")
    print(f"   Anime: {stats['anime_count']} ({stats['anime_with_spots']} with spots)")
    print(f"   Spots: {stats['spot_count']}")
    print(f"   Missing city: {stats['missing_city']}")
    print(f"   Missing image: {stats['missing_image']}")
    print(f"   Skipped anime: {stats['skipped_anime']}")
    print(f"   Skipped spots: {stats['skipped_spots']}")


if __name__ == "__main__":
    main()
