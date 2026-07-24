import json
import math
import os
import sqlite3
from contextlib import closing, contextmanager
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Dict, List

from core.retrieval import HybridRetriever
from data_factory.sqlite_index import SCHEMA_VERSION


class SQLiteKnowledgeView(Sequence):
    """Compatibility view that only materializes anime records when accessed."""

    def __init__(self, retriever: "SQLiteRetriever"):
        self.retriever = retriever

    def __len__(self) -> int:
        return self.retriever.anime_count

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            return [self.retriever.get_anime_item(anime_id) for anime_id in self.retriever.anime_ids(start, stop, step)]
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        anime_ids = self.retriever.anime_ids(index, index + 1, 1)
        if not anime_ids:
            raise IndexError(index)
        anime_id = anime_ids[0]
        return self.retriever.get_anime_item(anime_id)

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        for anime_id in self.retriever.anime_ids():
            item = self.retriever.get_anime_item(anime_id)
            if item:
                yield item


class SQLiteRetriever(HybridRetriever):
    """Read-only SQLite/FTS retriever with lazy presentation-data loading."""

    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(self.db_path)
        self.metadata = self._load_metadata()
        if str(self.metadata.get("schema_version")) != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported runtime index schema: {self.metadata.get('schema_version')} "
                f"(expected {SCHEMA_VERSION})"
            )
        self.anime_count = int(self.metadata.get("anime_count", 0))
        self.spot_count = int(self.metadata.get("spot_count", 0))
        self._location_aliases = self._load_location_aliases()
        self.knowledge_base = SQLiteKnowledgeView(self)

    @contextmanager
    def _connect(self):
        uri = Path(self.db_path).as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA cache_size = -8192")
        connection.execute("PRAGMA mmap_size = 67108864")
        try:
            yield connection
        finally:
            connection.close()

    def _load_metadata(self) -> Dict[str, Any]:
        with closing(sqlite3.connect(self.db_path)) as connection:
            rows = connection.execute("SELECT key, value FROM metadata").fetchall()
        metadata: Dict[str, Any] = {}
        for key, value in rows:
            try:
                metadata[key] = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                metadata[key] = value
        return metadata

    def _load_location_aliases(self) -> Dict[str, List[str]]:
        aliases: Dict[str, List[str]] = {}
        with self._connect() as connection:
            for row in connection.execute("SELECT alias_norm, city_norm FROM city_aliases"):
                aliases.setdefault(row["alias_norm"], []).append(row["city_norm"])
        return aliases

    @classmethod
    def _query_tokens(cls, query: str) -> List[str]:
        cleaned = cls.clean_query(query) or cls.normalize_text(query)
        if not cleaned:
            return []
        chunks = cls.tokenize(cleaned)
        tokens: list[str] = []
        for chunk in chunks:
            normalized = cls.normalize_text(chunk)
            if not normalized:
                continue
            if normalized.isascii() or len(normalized) <= 2:
                tokens.append(normalized)
            elif len(normalized) == 3:
                tokens.extend(normalized[index : index + 2] for index in range(2))
            elif len(normalized) == len(cleaned):
                tokens.extend(normalized[index : index + 2] for index in range(len(normalized) - 1))
        return list(dict.fromkeys(tokens))

    @staticmethod
    def _match_expression(tokens: List[str], operator: str = "AND") -> str:
        safe = [token.replace('"', '""') for token in tokens if token]
        return f" {operator} ".join(f'"{token}"' for token in safe)

    def _anime_rows(self, expression: str, limit: int) -> List[sqlite3.Row]:
        if not expression:
            return []
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT a.*, -bm25(anime_fts) AS lexical_rank
                FROM anime_fts
                JOIN anime AS a ON a.anime_id = anime_fts.rowid
                WHERE anime_fts MATCH ?
                ORDER BY bm25(anime_fts)
                LIMIT ?
                """,
                (expression, limit),
            ).fetchall()

    def _spot_rows(self, expression: str, limit: int) -> List[sqlite3.Row]:
        if not expression:
            return []
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT
                    s.*, a.cn AS anime_cn, a.jp AS anime_jp,
                    -bm25(spot_fts) AS lexical_rank
                FROM spot_fts
                JOIN spots AS s ON s.row_id = spot_fts.rowid
                JOIN anime AS a ON a.anime_id = s.anime_id
                WHERE spot_fts MATCH ?
                ORDER BY bm25(spot_fts)
                LIMIT ?
                """,
                (expression, limit),
            ).fetchall()

    def _spot_rows_for_cities(self, city_terms: List[str], limit: int) -> List[sqlite3.Row]:
        normalized_terms = list(dict.fromkeys(self.normalize_text(term) for term in city_terms if term))
        if not normalized_terms:
            return []
        conditions = " OR ".join("s.city_norm = ? OR s.city_norm LIKE ?" for _ in normalized_terms)
        params: list[Any] = []
        for term in normalized_terms:
            params.extend([term, f"{term}%"])
        params.append(limit)
        with self._connect() as connection:
            return connection.execute(
                f"""
                SELECT
                    s.*, a.cn AS anime_cn, a.jp AS anime_jp,
                    0.0 AS lexical_rank
                FROM spots AS s
                JOIN anime AS a ON a.anime_id = s.anime_id
                WHERE {conditions}
                LIMIT ?
                """,
                params,
            ).fetchall()

    def _fuzzy_anime_rows(self, tokens: List[str], limit: int) -> List[sqlite3.Row]:
        expression = self._match_expression(tokens, operator="OR")
        return self._anime_rows(expression, limit)

    @staticmethod
    def _title_score(query_norm: str, title_norms: List[str]) -> float:
        score = 0.0
        for title_norm in title_norms:
            if not title_norm or not query_norm:
                continue
            if query_norm == title_norm:
                score = max(score, 140)
            elif title_norm.startswith(query_norm):
                score = max(score, 95)
            elif query_norm in title_norm:
                score = max(score, 70)
            elif len(title_norm) >= 3 and title_norm in query_norm:
                score = max(score, 55)
        return score

    def search_anime(self, query: str, k: int = 20) -> List[Dict]:
        query_tokens = self._query_tokens(query)
        if not query_tokens:
            return []
        q_norm = self.clean_query(query) or self.normalize_text(query)
        rows = self._anime_rows(
            self._match_expression(query_tokens),
            limit=min(600, max(120, k * 30)),
        )
        fuzzy_only = False
        if not rows:
            rows = self._fuzzy_anime_rows(query_tokens, limit=600)
            fuzzy_only = True

        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            title_norms = [row["cn_norm"], row["jp_norm"]]
            title_score = self._title_score(q_norm, title_norms)
            if fuzzy_only and not title_score:
                if not any(
                    len(q_norm) <= len(title_norm) + 2
                    and self._is_fuzzy_match(q_norm, title_norm)
                    for title_norm in title_norms
                ):
                    continue
                title_score = 45

            lexical = max(0.0, float(row["lexical_rank"] or 0.0)) * 8
            score = 12 + lexical + title_score
            if row["spots_count"]:
                score += min(28, math.log1p(row["spots_count"]) * 7)
            if score >= self.ANIME_MIN_SCORE:
                scored.append((score, row))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        if not self._passes_confidence(scored, self.ANIME_MIN_SCORE):
            return []
        return [self._format_anime_row(row, score) for score, row in scored[:k]]

    def _extract_location_terms(self, query_norm: str) -> List[str]:
        terms: list[str] = []
        for alias_norm, city_norms in self._location_aliases.items():
            if alias_norm and alias_norm in query_norm:
                terms.extend(city_norms)
                terms.append(alias_norm)
        return list(dict.fromkeys(terms))

    def _location_score(self, row: sqlite3.Row, location_terms: List[str]) -> float:
        if not location_terms:
            return 0.0
        fields = [row["city_norm"] or "", row["name_norm"] or ""]
        score = 0.0
        for term in location_terms:
            if term == "京都":
                matched = any(
                    "京都" in field and "東京都" not in field and "东京都" not in field
                    for field in fields
                )
            else:
                matched = any(term in field or field in term for field in fields if field)
            if matched:
                score = max(score, 130 if term in (row["city_norm"] or "") else 95)
        return score

    def _theme_score(self, row: sqlite3.Row, theme_terms: List[str]) -> float:
        if not theme_terms:
            return 0.0
        text = self.normalize_text(
            " ".join(
                [
                    row["name"] or "",
                    row["city"] or "",
                    row["description"] or "",
                    row["tags_json"] or "",
                ]
            )
        )
        score = 0.0
        for term in theme_terms:
            term_norm = self.normalize_text(term)
            if term_norm and term_norm in text:
                score = max(score, 90 if term_norm in (row["name_norm"] or "") else 60)
        return score

    def search_spots(self, query: str, k: int = 20) -> List[Dict]:
        query_tokens = self._query_tokens(query)
        if not query_tokens:
            return []
        q_norm = self.normalize_text(query)
        q_clean = self.clean_query(query) or q_norm
        location_terms = self._extract_location_terms(q_norm)
        theme_terms = self._extract_theme_terms(q_norm)
        row_limit = min(1200, max(250, k * 40))
        rows = self._spot_rows_for_cities(location_terms, row_limit) if location_terms else []
        if not rows:
            rows = self._spot_rows(self._match_expression(query_tokens), limit=row_limit)
        anime_candidates = self.search_anime(query, k=5)
        anime_boosts = {
            candidate["id"]: max(0, 85 - rank * 12)
            for rank, candidate in enumerate(anime_candidates)
        }
        if not rows and anime_boosts:
            placeholders = ",".join("?" for _ in anime_boosts)
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT
                        s.*, a.cn AS anime_cn, a.jp AS anime_jp,
                        0.0 AS lexical_rank
                    FROM spots AS s
                    JOIN anime AS a ON a.anime_id = s.anime_id
                    WHERE s.anime_id IN ({placeholders})
                    LIMIT 1200
                    """,
                    tuple(anime_boosts),
                ).fetchall()

        scored: list[tuple[float, float, float, sqlite3.Row]] = []
        for row in rows:
            location_score = self._location_score(row, location_terms)
            theme_score = self._theme_score(row, theme_terms)
            direct_score = 0.0
            if q_clean and q_clean in (row["name_norm"] or ""):
                direct_score = max(direct_score, 80)
            if q_clean and q_clean in (row["city_norm"] or ""):
                direct_score = max(direct_score, 90)
            if q_clean and (
                q_clean in self.normalize_text(row["anime_cn"])
                or q_clean in self.normalize_text(row["anime_jp"])
            ):
                direct_score = max(direct_score, 55)

            if location_terms and location_score <= 0:
                continue
            if theme_terms and theme_score <= 0:
                continue
            lexical = max(0.0, float(row["lexical_rank"] or 0.0)) * 8
            score = 12 + lexical + direct_score + location_score + theme_score
            score += anime_boosts.get(row["anime_id"], 0)
            if score >= self.SPOT_MIN_SCORE:
                scored.append((score, location_score, theme_score, row))

        if location_terms and any(location_score >= 130 for _, location_score, _, _ in scored):
            scored = [item for item in scored if item[1] >= 130]
        scored.sort(key=lambda item: item[0], reverse=True)
        if not self._passes_confidence(scored, self.SPOT_MIN_SCORE):
            return []
        return [self._format_spot_row(row, score) for score, _, _, row in scored[:k]]

    @staticmethod
    def _format_anime_row(row: sqlite3.Row, score: float | None = None) -> Dict:
        candidate = {
            "id": row["anime_id"],
            "cn": row["cn"],
            "jp": row["jp"],
            "image": row["cover"],
            "summary": f"{row['spots_count']} 圣地 | {row['score'] if row['score'] is not None else 'N/A'} 分",
        }
        if score is not None:
            candidate["_score"] = round(score, 4)
        return candidate

    @staticmethod
    def _format_spot_row(row: sqlite3.Row, score: float | None = None) -> Dict:
        result = {
            "id": row["spot_id"],
            "name": row["name"],
            "image": row["image"],
            "lat": row["lat"],
            "lon": row["lon"],
            "description": row["description"],
            "city": row["city"],
            "tags": json.loads(row["tags_json"] or "[]"),
            "source_url": row["source_url"],
            "episode": row["episode"],
            "scene": row["scene"],
            "verified_at": row["verified_at"],
            "anime_id": row["anime_id"],
            "_anime_name": row["anime_cn"] or row["anime_jp"] or "未知动画",
            "_city": row["city"] or "Unknown",
        }
        if score is not None:
            result["_score"] = round(score, 4)
        return result

    def anime_ids(self, start: int = 0, stop: int | None = None, step: int = 1) -> List[int]:
        limit = -1 if stop is None else max(0, stop - start)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT anime_id FROM anime ORDER BY anime_id LIMIT ? OFFSET ?",
                (limit, max(0, start)),
            ).fetchall()
        return [row["anime_id"] for row in rows][::step]

    def get_anime_item(self, anime_id: int) -> Dict[str, Any] | None:
        with self._connect() as connection:
            anime = connection.execute(
                "SELECT * FROM anime WHERE anime_id = ?",
                (int(anime_id),),
            ).fetchone()
            if not anime:
                return None
            spot_rows = connection.execute(
                """
                SELECT s.*, a.cn AS anime_cn, a.jp AS anime_jp
                FROM spots AS s
                JOIN anime AS a ON a.anime_id = s.anime_id
                WHERE s.anime_id = ?
                ORDER BY s.row_id
                """,
                (int(anime_id),),
            ).fetchall()
        spots = [self._format_spot_row(row) for row in spot_rows]
        tags = json.loads(anime["tags_json"] or "[]")
        rag_content = " ".join(
            str(value)
            for value in [
                anime["cn"],
                anime["jp"],
                anime["description"] or "",
                *tags,
                *[
                    part
                    for spot in spots
                    for part in [
                        spot.get("name") or "",
                        spot.get("city") or "",
                        spot.get("description") or "",
                        spot.get("scene") or "",
                    ]
                ],
            ]
            if value
        ).lower()
        return {
            "anime_id": anime["anime_id"],
            "meta": {
                "id": anime["anime_id"],
                "titles": {"cn": anime["cn"], "jp": anime["jp"]},
                "cover": anime["cover"],
                "type": anime["media_type"],
                "score": anime["score"],
                "tags": tags,
                "description": anime["description"] or "",
            },
            "spots": spots,
            "rag_content": rag_content,
        }

    def retrieve_keyword(self, query: str, k: int = 10) -> List[Dict]:
        return self.retrieve_knowledge(query, k=k)

    def retrieve_vector_simulated(self, query: str, k: int = 10) -> List[Dict]:
        return self.retrieve_knowledge(query, k=k)

    def retrieve_knowledge(self, query: str, k: int = 5) -> List[Dict]:
        return [
            item
            for candidate in self.search_anime(query, k=k)
            if (item := self.get_anime_item(candidate["id"])) is not None
        ]

    def get_anime_candidates(self, query: str) -> List[Dict]:
        return self.search_anime(query, k=20)

    def retrieve_spots(self, query: str, k: int = 5):
        return self.search_spots(query, k=k)

    def get_spots_by_anime_id(self, anime_id: int) -> List[Dict]:
        item = self.get_anime_item(anime_id)
        return item.get("spots", []) if item else []
