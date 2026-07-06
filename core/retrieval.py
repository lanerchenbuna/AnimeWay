import hashlib
import math
import os
import pickle
import re
from collections import Counter
from typing import Dict, List


class HybridRetriever:
    """
    Local lexical retriever for anime and pilgrimage spots.

    The index is intentionally lightweight: BM25 over normalized text plus
    deterministic boosts for exact titles, cities, themes, and spot counts.
    """

    STOPWORDS = {
        "的",
        "了",
        "和",
        "与",
        "在",
        "有",
        "什么",
        "哪里",
        "哪",
        "怎么",
        "动画",
        "动漫",
        "番",
        "圣地",
        "巡礼",
        "取景",
        "取景地",
        "地点",
        "地方",
        "推荐",
        "想去",
        "看看",
    }
    SUFFIXES = ["的圣地", "圣地巡礼", "圣地", "巡礼", "取景地", "取景", "在哪里", "在哪", "原型", "位置"]
    THEME_ALIASES = {
        "咖啡": ["咖啡", "咖啡店", "cafe", "coffee", "喫茶", "カフェ"],
        "咖啡店": ["咖啡", "咖啡店", "cafe", "coffee", "喫茶", "カフェ"],
        "cafe": ["咖啡", "咖啡店", "cafe", "coffee", "喫茶", "カフェ"],
        "喫茶": ["咖啡", "咖啡店", "cafe", "coffee", "喫茶", "カフェ"],
        "学校": ["学校", "高校", "学園", "school", "highschool"],
        "神社": ["神社", "寺", "temple", "shrine"],
        "音乐": ["音乐", "乐队", "吉他", "live", "ライブ", "band"],
        "乐队": ["音乐", "乐队", "吉他", "live", "ライブ", "band"],
    }
    LOCATION_ALIASES = {
        "京都": ["京都", "京都市", "京都府"],
        "东京": ["东京", "東京", "东京都", "東京都"],
        "東京": ["东京", "東京", "东京都", "東京都"],
        "大阪": ["大阪", "大阪市", "大阪府"],
        "镰仓": ["镰仓", "鎌倉"],
        "鎌倉": ["镰仓", "鎌倉"],
        "下北泽": ["下北泽", "下北沢"],
        "下北沢": ["下北泽", "下北沢"],
    }
    ICONIC_SPOT_TERMS = {
        "shelter": 35,
        "下北": 30,
        "神社": 16,
        "階段": 14,
        "坂": 12,
        "学校": 12,
        "高校": 12,
        "喫茶": 10,
        "cafe": 10,
        "カフェ": 10,
        "駅": 4,
    }

    def __init__(self, knowledge_base: List[Dict], cache_dir: str | None = None):
        self.knowledge_base = knowledge_base
        self.cache_dir = cache_dir
        self._anime_by_id = {int(item.get("anime_id")): item for item in knowledge_base if item.get("anime_id") is not None}
        self._anime_docs = []
        self._spot_docs = []
        self._anime_idf = {}
        self._spot_idf = {}
        self._anime_avgdl = 1.0
        self._spot_avgdl = 1.0
        self._build_indexes()

    @staticmethod
    def normalize_text(text: str) -> str:
        return re.sub(r"[^\w\u4e00-\u9fff\u3040-\u30ffー]+", "", str(text).lower())

    @classmethod
    def clean_query(cls, query: str) -> str:
        query_norm = cls.normalize_text(query)
        for suffix in cls.SUFFIXES:
            query_norm = query_norm.replace(cls.normalize_text(suffix), "")
        return query_norm.strip()

    @classmethod
    def tokenize(cls, text: str) -> List[str]:
        chunks = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+|[\u3040-\u30ffー]+", str(text).lower())
        tokens = []
        for chunk in chunks:
            if re.fullmatch(r"[a-z0-9]+", chunk):
                if chunk not in cls.STOPWORDS:
                    tokens.append(chunk)
                continue

            if len(chunk) <= 1:
                if chunk not in cls.STOPWORDS:
                    tokens.append(chunk)
                continue

            tokens.append(chunk)
            max_n = min(4, len(chunk))
            for n in range(2, max_n + 1):
                tokens.extend(chunk[i : i + n] for i in range(len(chunk) - n + 1))

        return [token for token in tokens if token and token not in cls.STOPWORDS]

    @classmethod
    def expand_query_tokens(cls, query: str) -> List[str]:
        tokens = cls.tokenize(query)
        compact = cls.normalize_text(query)
        expanded = list(tokens)
        for key, aliases in cls.THEME_ALIASES.items():
            if cls.normalize_text(key) in compact or any(cls.normalize_text(alias) in compact for alias in aliases):
                expanded.extend(cls.tokenize(" ".join(aliases)))
        for key, aliases in cls.LOCATION_ALIASES.items():
            if cls.normalize_text(key) in compact:
                expanded.extend(cls.tokenize(" ".join(aliases)))
        return list(dict.fromkeys(expanded))

    @staticmethod
    def _join_parts(parts: List[str]) -> str:
        return " ".join(str(part) for part in parts if part)

    def _build_indexes(self) -> None:
        fingerprint = self._fingerprint()
        if self.cache_dir:
            cached = self._load_cache(fingerprint)
            if cached:
                (
                    self._anime_docs,
                    self._spot_docs,
                    self._anime_idf,
                    self._spot_idf,
                    self._anime_avgdl,
                    self._spot_avgdl,
                ) = cached
                return

        self._anime_docs = [self._build_anime_doc(item) for item in self.knowledge_base]
        self._spot_docs = []
        for item in self.knowledge_base:
            self._spot_docs.extend(self._build_spot_doc(item, spot) for spot in item.get("spots", []))

        self._anime_idf, self._anime_avgdl = self._build_bm25_stats(self._anime_docs)
        self._spot_idf, self._spot_avgdl = self._build_bm25_stats(self._spot_docs)

        if self.cache_dir:
            self._save_cache(
                fingerprint,
                (
                    self._anime_docs,
                    self._spot_docs,
                    self._anime_idf,
                    self._spot_idf,
                    self._anime_avgdl,
                    self._spot_avgdl,
                ),
            )

    def _fingerprint(self) -> str:
        digest = hashlib.sha1()
        digest.update(str(len(self.knowledge_base)).encode("utf-8"))
        for item in self.knowledge_base:
            digest.update(str(item.get("anime_id", "")).encode("utf-8"))
            digest.update(str(item.get("rag_content", "")).encode("utf-8"))
            for spot in item.get("spots", []):
                digest.update(str(spot.get("id", "")).encode("utf-8"))
                digest.update(str(spot.get("name", "")).encode("utf-8"))
                digest.update(str(spot.get("city", "")).encode("utf-8"))
        return digest.hexdigest()

    def _cache_path(self) -> str:
        return os.path.join(self.cache_dir or "", "bm25_cache.pkl")

    def _load_cache(self, fingerprint: str):
        path = self._cache_path()
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                payload = pickle.load(f)
            if payload.get("fingerprint") == fingerprint:
                return payload.get("data")
        except (OSError, pickle.PickleError, EOFError):
            return None
        return None

    def _save_cache(self, fingerprint: str, data) -> None:
        os.makedirs(self.cache_dir or "", exist_ok=True)
        with open(self._cache_path(), "wb") as f:
            pickle.dump({"fingerprint": fingerprint, "data": data}, f)

    def _build_anime_doc(self, item: Dict) -> Dict:
        meta = item.get("meta", {})
        titles = meta.get("titles", {})
        spots = item.get("spots", [])
        text = self._join_parts(
            [
                titles.get("cn", ""),
                titles.get("jp", ""),
                meta.get("description", ""),
                " ".join(meta.get("tags", [])),
                item.get("rag_content", ""),
                " ".join(self._spot_text_parts(spot) for spot in spots),
            ]
        )
        tokens = self.tokenize(text)
        return {
            "item": item,
            "tokens": tokens,
            "tf": Counter(tokens),
            "length": max(len(tokens), 1),
            "norm_text": self.normalize_text(text),
            "title_norms": [self.normalize_text(titles.get("cn", "")), self.normalize_text(titles.get("jp", ""))],
            "spots_count": len(spots),
        }

    def _build_spot_doc(self, item: Dict, spot: Dict) -> Dict:
        meta = item.get("meta", {})
        titles = meta.get("titles", {})
        text = self._join_parts(
            [
                self._spot_text_parts(spot),
                titles.get("cn", ""),
                titles.get("jp", ""),
                " ".join(meta.get("tags", [])),
            ]
        )
        tokens = self.tokenize(text)
        city = spot.get("city") or spot.get("_city") or ""
        name = spot.get("name") or spot.get("cn") or ""
        return {
            "item": item,
            "spot": spot,
            "tokens": tokens,
            "tf": Counter(tokens),
            "length": max(len(tokens), 1),
            "norm_text": self.normalize_text(text),
            "name_norm": self.normalize_text(name),
            "city_norm": self.normalize_text(city),
            "anime_title_norms": [self.normalize_text(titles.get("cn", "")), self.normalize_text(titles.get("jp", ""))],
        }

    def _spot_text_parts(self, spot: Dict) -> str:
        return self._join_parts(
            [
                spot.get("name") or spot.get("cn") or "",
                spot.get("city") or spot.get("_city") or "",
                spot.get("description") or spot.get("content") or "",
                " ".join(spot.get("tags", [])),
            ]
        )

    @staticmethod
    def _build_bm25_stats(docs: List[Dict]) -> tuple[Dict[str, float], float]:
        if not docs:
            return {}, 1.0
        doc_count = len(docs)
        df = Counter()
        total_len = 0
        for doc in docs:
            total_len += doc["length"]
            df.update(doc["tf"].keys())
        idf = {
            token: math.log(1 + (doc_count - freq + 0.5) / (freq + 0.5))
            for token, freq in df.items()
        }
        return idf, max(total_len / doc_count, 1.0)

    @staticmethod
    def _bm25_score(doc: Dict, query_tokens: List[str], idf: Dict[str, float], avgdl: float) -> float:
        k1 = 1.5
        b = 0.75
        score = 0.0
        for token in query_tokens:
            tf = doc["tf"].get(token, 0)
            if not tf:
                continue
            denom = tf + k1 * (1 - b + b * doc["length"] / avgdl)
            score += idf.get(token, 0.0) * (tf * (k1 + 1) / denom)
        return score

    def search_anime(self, query: str, k: int = 20) -> List[Dict]:
        """
        Search anime titles/metadata and return UI-friendly candidates.
        """
        query_tokens = self.expand_query_tokens(query)
        q_norm = self.normalize_text(query)
        q_clean = self.clean_query(query) or q_norm
        scored = []

        for doc in self._anime_docs:
            item = doc["item"]
            score = self._bm25_score(doc, query_tokens, self._anime_idf, self._anime_avgdl)

            title_score = 0.0
            for title_norm in doc["title_norms"]:
                if not title_norm or not q_clean:
                    continue
                if q_clean == title_norm:
                    title_score = max(title_score, 140)
                elif title_norm.startswith(q_clean):
                    title_score = max(title_score, 95)
                elif q_clean in title_norm:
                    title_score = max(title_score, 70)
                elif title_norm in q_clean:
                    title_score = max(title_score, 55)

            if q_clean and q_clean in doc["norm_text"]:
                score += 12
            score += title_score
            if doc["spots_count"]:
                score += min(28, math.log1p(doc["spots_count"]) * 7)

            if score > 0:
                scored.append((score, item))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [self._format_anime_candidate(item, score) for score, item in scored[:k]]

    def search_spots(self, query: str, k: int = 20) -> List[Dict]:
        """
        Search individual pilgrimage spots by anime title, city, place name, or theme.
        """
        query_tokens = self.expand_query_tokens(query)
        q_norm = self.normalize_text(query)
        q_clean = self.clean_query(query) or q_norm
        location_terms = self._extract_location_terms(q_norm)
        theme_terms = self._extract_theme_terms(q_norm)
        anime_candidates = self.search_anime(query, k=5)
        anime_boosts = {cand["id"]: max(0, 85 - rank * 12) for rank, cand in enumerate(anime_candidates)}

        scored = []
        for doc in self._spot_docs:
            item = doc["item"]
            spot = doc["spot"]
            anime_id = int(item.get("anime_id"))
            score = self._bm25_score(doc, query_tokens, self._spot_idf, self._spot_avgdl)
            location_match = self._location_match_score(doc, location_terms)
            theme_match = self._theme_match_score(doc, theme_terms)

            if q_clean and q_clean in doc["name_norm"]:
                score += 80
            if q_clean and q_clean in doc["city_norm"]:
                score += 90
            if q_clean and any(q_clean in title_norm for title_norm in doc["anime_title_norms"]):
                score += 55

            score += location_match
            score += theme_match
            score += anime_boosts.get(anime_id, 0)
            score += self._iconic_spot_bonus(doc)

            if score > 0:
                scored.append((score, location_match, theme_match, item, spot))

        if location_terms and any(location_score > 0 for _, location_score, _, _, _ in scored):
            scored = [row for row in scored if row[1] > 0]
        if theme_terms and any(theme_score > 0 for _, _, theme_score, _, _ in scored):
            scored = [row for row in scored if row[2] > 0]

        scored.sort(key=lambda row: row[0], reverse=True)
        return [self._format_spot_result(item, spot, score) for score, _, _, item, spot in scored[:k]]

    def _extract_location_terms(self, query_norm: str) -> List[str]:
        terms = []
        for key, aliases in self.LOCATION_ALIASES.items():
            if self.normalize_text(key) in query_norm or any(self.normalize_text(alias) in query_norm for alias in aliases):
                terms.extend(aliases)
        return list(dict.fromkeys(terms))

    def _extract_theme_terms(self, query_norm: str) -> List[str]:
        terms = []
        for key, aliases in self.THEME_ALIASES.items():
            if self.normalize_text(key) in query_norm or any(self.normalize_text(alias) in query_norm for alias in aliases):
                terms.extend(aliases)
        return list(dict.fromkeys(terms))

    def _location_match_score(self, doc: Dict, location_terms: List[str]) -> float:
        if not location_terms:
            return 0.0
        score = 0.0
        fields = [doc["city_norm"], doc["name_norm"], doc["norm_text"]]
        for term in location_terms:
            term_norm = self.normalize_text(term)
            if not term_norm:
                continue
            if term_norm == "京都":
                matched = any("京都" in field and "東京都" not in field for field in fields)
            else:
                matched = any(term_norm in field for field in fields)
            if matched:
                score = max(score, 130 if term_norm in doc["city_norm"] else 95)
        return score

    def _theme_match_score(self, doc: Dict, theme_terms: List[str]) -> float:
        if not theme_terms:
            return 0.0
        score = 0.0
        for term in theme_terms:
            term_norm = self.normalize_text(term)
            if term_norm and term_norm in doc["norm_text"]:
                score = max(score, 90 if term_norm in doc["name_norm"] else 60)
        return score

    def _iconic_spot_bonus(self, doc: Dict) -> float:
        text = doc["norm_text"]
        return sum(weight for term, weight in self.ICONIC_SPOT_TERMS.items() if self.normalize_text(term) in text)

    @staticmethod
    def _format_anime_candidate(item: Dict, score: float | None = None) -> Dict:
        meta = item.get("meta", {})
        titles = meta.get("titles", {})
        candidate = {
            "id": item["anime_id"],
            "cn": titles.get("cn", ""),
            "jp": titles.get("jp", ""),
            "image": meta.get("cover"),
            "summary": f"{len(item.get('spots', []))} 圣地 | {meta.get('score', 'N/A')} 分",
        }
        if score is not None:
            candidate["_score"] = round(score, 4)
        return candidate

    @staticmethod
    def _format_spot_result(item: Dict, spot: Dict, score: float | None = None) -> Dict:
        meta = item.get("meta", {})
        titles = meta.get("titles", {})
        result = dict(spot)
        result["anime_id"] = item.get("anime_id")
        result["_anime_name"] = titles.get("cn") or titles.get("jp") or "未知动画"
        result["_city"] = result.get("city") or "Unknown"
        if score is not None:
            result["_score"] = round(score, 4)
        return result

    def retrieve_keyword(self, query: str, k: int = 10) -> List[Dict]:
        candidates = self.search_anime(query, k=k)
        return [self._anime_by_id[candidate["id"]] for candidate in candidates if candidate["id"] in self._anime_by_id]

    def retrieve_vector_simulated(self, query: str, k: int = 10) -> List[Dict]:
        return self.retrieve_keyword(query, k=k)

    def rank_fusion(self, list_a: List[Dict], list_b: List[Dict], k: int = 60) -> List[Dict]:
        rrf_map = {}
        for lst in (list_a, list_b):
            for rank, item in enumerate(lst):
                key = item.get("anime_id")
                if key is None:
                    continue
                rrf_map.setdefault(key, {"item": item, "score": 0.0})
                rrf_map[key]["score"] += 1 / (k + rank + 1)
        return [row["item"] for row in sorted(rrf_map.values(), key=lambda row: row["score"], reverse=True)]

    def retrieve_knowledge(self, query: str, k: int = 5) -> List[Dict]:
        candidates = self.search_anime(query, k=k)
        return [self._anime_by_id[candidate["id"]] for candidate in candidates if candidate["id"] in self._anime_by_id]

    def get_anime_candidates(self, query: str) -> List[Dict]:
        return self.search_anime(query, k=20)

    def retrieve_spots(self, query: str, k: int = 5):
        return self.search_spots(query, k=k)

    def get_spots_by_anime_id(self, anime_id: int) -> List[Dict]:
        item = self._anime_by_id.get(int(anime_id))
        return item.get("spots", []) if item else []
