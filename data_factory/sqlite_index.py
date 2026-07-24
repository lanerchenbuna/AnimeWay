import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable

from core.retrieval import HybridRetriever


SCHEMA_VERSION = "2"
DEFAULT_DB_PATH = "knowledge_base/animeway.sqlite3"


def normalize_text(value: Any) -> str:
    return HybridRetriever.normalize_text(str(value or ""))


def fts_tokens(values: Iterable[Any]) -> str:
    tokens: set[str] = set()
    for value in values:
        chunks = re.findall(
            r"[a-z0-9]+|[\u4e00-\u9fff]+|[\u3040-\u30ffー]+",
            str(value or "").lower(),
        )
        for chunk in chunks:
            if re.fullmatch(r"[a-z0-9]+", chunk):
                tokens.add(chunk)
                continue
            if len(chunk) == 1:
                tokens.add(chunk)
                continue
            if len(chunk) == 2:
                tokens.add(chunk)
            elif len(chunk) > 2:
                tokens.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return " ".join(sorted(tokens))


def _alias_terms(values: Iterable[Any]) -> list[str]:
    normalized = normalize_text(" ".join(str(value or "") for value in values))
    aliases: list[str] = []
    for variants in HybridRetriever.THEME_ALIASES.values():
        if any(normalize_text(variant) in normalized for variant in variants):
            aliases.extend(variants)
    for variants in HybridRetriever.LOCATION_ALIASES.values():
        if any(normalize_text(variant) in normalized for variant in variants):
            aliases.extend(variants)
    return list(dict.fromkeys(aliases))


def _data_checksum(items: list[Dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in items:
        digest.update(str(item.get("anime_id", "")).encode("utf-8"))
        meta = item.get("meta", {})
        digest.update(json.dumps(meta, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        for spot in item.get("spots", []):
            digest.update(json.dumps(spot, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE anime (
            anime_id INTEGER PRIMARY KEY,
            cn TEXT NOT NULL,
            jp TEXT NOT NULL,
            cn_norm TEXT NOT NULL,
            jp_norm TEXT NOT NULL,
            cover TEXT,
            media_type TEXT,
            score REAL,
            tags_json TEXT NOT NULL,
            description TEXT,
            spots_count INTEGER NOT NULL
        );

        CREATE TABLE spots (
            row_id INTEGER PRIMARY KEY,
            spot_id TEXT NOT NULL,
            anime_id INTEGER NOT NULL REFERENCES anime(anime_id),
            name TEXT NOT NULL,
            name_norm TEXT NOT NULL,
            city TEXT,
            city_norm TEXT NOT NULL,
            image TEXT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            description TEXT,
            tags_json TEXT NOT NULL,
            source_url TEXT,
            episode TEXT,
            scene TEXT,
            verified_at TEXT,
            UNIQUE(anime_id, spot_id)
        );

        CREATE INDEX spots_anime_id_idx ON spots(anime_id);
        CREATE INDEX spots_city_norm_idx ON spots(city_norm);

        CREATE VIRTUAL TABLE anime_fts USING fts5(
            search_tokens,
            content = '',
            detail = 'none',
            columnsize = 0,
            tokenize = 'unicode61'
        );

        CREATE VIRTUAL TABLE spot_fts USING fts5(
            search_tokens,
            content = '',
            detail = 'none',
            columnsize = 0,
            tokenize = 'unicode61'
        );

        CREATE TABLE city_aliases (
            alias_norm TEXT NOT NULL,
            city_norm TEXT NOT NULL,
            PRIMARY KEY(alias_norm, city_norm)
        );
        CREATE INDEX city_aliases_alias_idx ON city_aliases(alias_norm);
        """
    )


def build_runtime_index(
    payload: Dict[str, Any],
    db_path: str = DEFAULT_DB_PATH,
    source_metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    items = payload.get("items", [])
    output = Path(db_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output.with_suffix(output.suffix + ".tmp")
    if temp_path.exists():
        temp_path.unlink()

    connection = sqlite3.connect(temp_path)
    try:
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute("PRAGMA temp_store = MEMORY")
        _create_schema(connection)

        metadata = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": payload.get("stats", {}).get("generated_at", ""),
            "data_checksum": _data_checksum(items),
            "source_metadata": source_metadata or payload.get("stats", {}).get("source_metadata", {}),
            "anime_count": len(items),
            "spot_count": sum(len(item.get("spots", [])) for item in items),
        }
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            [
                (key, json.dumps(value, ensure_ascii=False, separators=(",", ":")))
                for key, value in metadata.items()
            ],
        )

        spot_row_id = 0
        seen_spot_ids: set[tuple[int, str]] = set()
        seen_spot_semantics: set[tuple[int, str, float, float]] = set()
        city_alias_pairs: set[tuple[str, str]] = set()
        for item in items:
            anime_id = int(item["anime_id"])
            meta = item.get("meta", {})
            titles = meta.get("titles", {})
            cn = str(titles.get("cn") or "")
            jp = str(titles.get("jp") or "")
            spots = item.get("spots", [])
            tags = [str(tag) for tag in meta.get("tags", [])]
            connection.execute(
                """
                INSERT INTO anime(
                    anime_id, cn, jp, cn_norm, jp_norm, cover, media_type,
                    score, tags_json, description, spots_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    anime_id,
                    cn,
                    jp,
                    normalize_text(cn),
                    normalize_text(jp),
                    meta.get("cover"),
                    meta.get("type"),
                    meta.get("score"),
                    json.dumps(tags, ensure_ascii=False, separators=(",", ":")),
                    meta.get("description") or "",
                    len(spots),
                ),
            )

            anime_search_values: list[Any] = [
                cn,
                jp,
                meta.get("description") or "",
                *tags,
            ]
            for spot in spots:
                anime_search_values.extend(
                    [
                        spot.get("name") or "",
                        spot.get("city") or "",
                        spot.get("description") or "",
                        spot.get("scene") or "",
                        *spot.get("tags", []),
                    ]
                )
            anime_search_values.extend(_alias_terms(anime_search_values))
            connection.execute(
                "INSERT INTO anime_fts(rowid, search_tokens) VALUES (?, ?)",
                (anime_id, fts_tokens(anime_search_values)),
            )

            for spot in spots:
                spot_id = str(spot.get("id") or "")
                semantic_key = (
                    anime_id,
                    normalize_text(spot.get("name")),
                    round(float(spot["lat"]), 6),
                    round(float(spot["lon"]), 6),
                )
                if (anime_id, spot_id) in seen_spot_ids or semantic_key in seen_spot_semantics:
                    continue
                seen_spot_ids.add((anime_id, spot_id))
                seen_spot_semantics.add(semantic_key)
                spot_row_id += 1
                city = str(spot.get("city") or "")
                city_norm = normalize_text(city)
                spot_tags = [str(tag) for tag in spot.get("tags", [])]
                connection.execute(
                    """
                    INSERT INTO spots(
                        row_id, spot_id, anime_id, name, name_norm, city, city_norm,
                        image, lat, lon, description, tags_json, source_url,
                        episode, scene, verified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        spot_row_id,
                        spot_id or str(spot_row_id),
                        anime_id,
                        str(spot.get("name") or ""),
                        normalize_text(spot.get("name")),
                        city or None,
                        city_norm,
                        spot.get("image"),
                        float(spot["lat"]),
                        float(spot["lon"]),
                        spot.get("description"),
                        json.dumps(spot_tags, ensure_ascii=False, separators=(",", ":")),
                        spot.get("source_url"),
                        spot.get("episode"),
                        spot.get("scene"),
                        spot.get("verified_at"),
                    ),
                )
                spot_search_values: list[Any] = [
                    spot.get("name") or "",
                    city,
                    spot.get("description") or "",
                    spot.get("scene") or "",
                    cn,
                    jp,
                    *spot_tags,
                    *tags,
                ]
                spot_search_values.extend(_alias_terms(spot_search_values))
                if city:
                    city_variants = {city}
                    if len(city) > 2 and city[-1] in {"市", "县", "県", "府", "区", "州", "都"}:
                        city_variants.add(city[:-1])
                    spot_search_values.extend(city_variants)
                    for alias in city_variants:
                        city_alias_pairs.add((normalize_text(alias), city_norm))
                connection.execute(
                    "INSERT INTO spot_fts(rowid, search_tokens) VALUES (?, ?)",
                    (spot_row_id, fts_tokens(spot_search_values)),
                )

        metadata["spot_count"] = spot_row_id
        connection.execute(
            "UPDATE metadata SET value = ? WHERE key = 'spot_count'",
            (json.dumps(spot_row_id),),
        )

        for key, variants in HybridRetriever.LOCATION_ALIASES.items():
            canonical_values = {normalize_text(value) for value in variants}
            for alias in {key, *variants}:
                alias_norm = normalize_text(alias)
                for city_norm in canonical_values:
                    if alias_norm and city_norm:
                        city_alias_pairs.add((alias_norm, city_norm))
        connection.executemany(
            "INSERT OR IGNORE INTO city_aliases(alias_norm, city_norm) VALUES (?, ?)",
            sorted(city_alias_pairs),
        )
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()

    os.replace(temp_path, output)
    return {
        "path": str(output),
        "schema_version": SCHEMA_VERSION,
        "data_checksum": metadata["data_checksum"],
        "anime_count": metadata["anime_count"],
        "spot_count": metadata["spot_count"],
        "size_bytes": output.stat().st_size,
    }
