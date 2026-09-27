import hashlib
import json
import os
from datetime import datetime
from data_factory.normalization import normalize_spot, stable_spot_id, extract_lat_lon  # noqa: F401
from typing import Any, Dict, List

try:
    from data_factory.schema import AnimeItem, Spot
except ImportError:
    from schema import AnimeItem, Spot


BANGUMI_FILE = "knowledge_base/raw/bangumi_knowledge.json"
MANUAL_FILE = "knowledge_base/raw/manual_seeds.json"
ANITABI_FILE = "knowledge_base/raw/anitabi_crawl.json"
INDEX_FILE = "knowledge_base/index.json"
RUNTIME_INDEX_FILE = "knowledge_base/animeway.sqlite3"


def load_json(filepath: str, default: Any) -> Any:
    if not os.path.exists(filepath):
        return default
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def file_checksum(filepath: str) -> str | None:
    if not os.path.exists(filepath):
        return None
    digest = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def build_rag_content(meta: Dict[str, Any], spots: List[Spot]) -> str:
    titles = meta.get("titles", {})
    parts = [
        titles.get("cn", ""),
        titles.get("jp", ""),
        meta.get("description", ""),
        " ".join(meta.get("tags", [])),
    ]
    for spot in spots:
        parts.extend([spot.name, spot.city or "", spot.description or "", spot.scene or "", " ".join(spot.tags)])
    return " ".join(str(part) for part in parts if part).lower()


def build_knowledge_base(write: bool = True, *, raw_spots: list | None = None) -> Dict[str, Any]:
    raw_meta = []
    raw_meta.extend(load_json(MANUAL_FILE, []))
    raw_meta.extend(load_json(BANGUMI_FILE, []))
    raw_spots = load_json(ANITABI_FILE, []) if raw_spots is None else raw_spots

    spots_map: Dict[int, List[Spot]] = {}
    skipped_spots = 0
    duplicate_spots = 0
    legacy_conflicts = 0
    canonical_spots: dict[tuple[int, str], Spot] = {}
    seen_spot_ids: set[tuple[int, str]] = set()
    seen_records: dict[tuple[int, str], dict] = {}
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
        id_key = (anime_id, spot.id)
        record = spot.model_dump(mode="json", exclude_none=True)
        if id_key in seen_spot_ids:
            if seen_records[id_key] != record:
                if spot.identity_kind != "legacy_derived":
                    raise ValueError(f"Conflicting source point: {id_key}")
                # Old snapshots lack source IDs. Keep the existing canonical ID
                # and every conflicting variant for explicit later reconciliation.
                canonical = canonical_spots[id_key]
                if record not in canonical.legacy_variants:
                    canonical.legacy_variants.append(record)
                canonical.normalization_issues = sorted(set(canonical.normalization_issues + ["legacy_identity_conflict"]))
                legacy_conflicts += 1
            duplicate_spots += 1
            continue
        seen_spot_ids.add(id_key)
        seen_records[id_key] = record
        canonical_spots[id_key] = spot
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
            rag_content=None,
        )
        items.append(kb_item.model_dump(mode="json", exclude_none=True))

    spot_count = sum(len(item["spots"]) for item in items)
    missing_city = sum(1 for item in items for spot in item["spots"] if not spot.get("city"))
    missing_image = sum(1 for item in items for spot in item["spots"] if not spot.get("image"))
    source_metadata = {
        "bangumi": {
            "path": BANGUMI_FILE,
            "source_url": "https://bgm.tv",
            "license": "unknown",
            "checksum_sha256": file_checksum(BANGUMI_FILE),
        },
        "anitabi": {
            "path": ANITABI_FILE,
            "source_url": "https://anitabi.cn",
            "license": "unknown",
            "checksum_sha256": file_checksum(ANITABI_FILE),
        },
        "manual": {
            "path": MANUAL_FILE if os.path.exists(MANUAL_FILE) else None,
            "source_url": None,
            "license": "project-provided",
            "checksum_sha256": file_checksum(MANUAL_FILE),
        },
    }
    stats = {
        "schema_version": "3",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "anime_count": len(items),
        "anime_with_spots": sum(1 for item in items if item["spots"]),
        "spot_count": spot_count,
        "missing_city": missing_city,
        "missing_image": missing_image,
        "skipped_anime": skipped_anime,
        "skipped_spots": skipped_spots,
        "duplicate_spots": duplicate_spots,
        "legacy_identity_conflicts": legacy_conflicts,
        "source_files": {
            "bangumi": BANGUMI_FILE,
            "manual": MANUAL_FILE if os.path.exists(MANUAL_FILE) else None,
            "anitabi": ANITABI_FILE,
        },
        "source_metadata": source_metadata,
    }
    payload = {"stats": stats, "items": items}

    if write:
        from data_factory.release import publish_offline

        selected = publish_offline(payload=payload, raw=raw_spots)
        stats["runtime_index"] = {"path": selected["db_path"], "version": selected["version"]}

    return payload


def main() -> None:
    payload = build_knowledge_base(write=True)
    stats = payload["stats"]
    print("✅ Knowledge base built")
    print(f"   Snapshot: {stats['runtime_index']['version']}")
    print(f"   Anime: {stats['anime_count']} ({stats['anime_with_spots']} with spots)")
    print(f"   Spots: {stats['spot_count']}")
    print(f"   Missing city: {stats['missing_city']}")
    print(f"   Missing image: {stats['missing_image']}")
    print(f"   Skipped anime: {stats['skipped_anime']}")
    print(f"   Skipped spots: {stats['skipped_spots']}")
    print(f"   Duplicate spots removed: {stats['duplicate_spots']}")
    print(f"   Runtime index: {stats['runtime_index']['path']}")


if __name__ == "__main__":
    main()
