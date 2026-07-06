from typing import Any, Dict, List
import re


class SearchService:
    def __init__(self, knowledge_base: List[Dict], retriever):
        self.knowledge_base = knowledge_base
        self.retriever = retriever
        self._anime_by_id = {
            int(item.get("anime_id")): item
            for item in knowledge_base
            if item.get("anime_id") is not None
        }

    def anime_item(self, anime_id: int) -> Dict | None:
        return self._anime_by_id.get(int(anime_id))

    def search_anime(self, query: str, k: int = 20) -> List[Dict]:
        return self.retriever.search_anime(query, k=k)

    def search_spots(self, query: str, k: int = 50) -> List[Dict]:
        return self.retriever.search_spots(query, k=k)

    def search_for_query(self, query: str, anime_name: str | None = None) -> Dict[str, Any]:
        search_term = anime_name or query
        if not anime_name and self._looks_like_spot_query(query):
            spots = self.search_spots(query, k=50)
            if spots:
                return {
                    "mode": "search_spots",
                    "query": query,
                    "candidates": [],
                    "spots": spots,
                    "context": [],
                }

        candidates = self.search_anime(search_term, k=20)
        if candidates:
            return {
                "mode": "search_candidates",
                "query": search_term,
                "candidates": candidates,
                "spots": [],
                "context": [],
            }

        spots = self.search_spots(query, k=50)
        return {
            "mode": "search_spots" if spots else "empty",
            "query": query,
            "candidates": [],
            "spots": spots,
            "context": [],
        }

    @staticmethod
    def _looks_like_spot_query(query: str) -> bool:
        return bool(
            re.search(
                r"京都|东京|東京|大阪|镰仓|鎌倉|下北|咖啡|cafe|coffee|喫茶|カフェ|学校|高校|神社|寺|车站|駅",
                query,
                re.IGNORECASE,
            )
        )

    def guide_context(self, query: str, anime_name: str | None = None, limit: int = 3) -> List[Dict]:
        search_term = anime_name or query
        candidates = self.search_anime(search_term, k=limit)
        context = []
        for candidate in candidates:
            item = self.anime_item(candidate["id"])
            if item:
                context.append(item)
        if context:
            return context[:limit]

        spot_results = self.search_spots(query, k=limit * 5)
        seen = set()
        for spot in spot_results:
            anime_id = spot.get("anime_id")
            if anime_id in seen:
                continue
            item = self.anime_item(anime_id)
            if item:
                context.append(item)
                seen.add(anime_id)
            if len(context) >= limit:
                break
        return context

    def candidates_for_names(self, names: List[str], limit: int = 10) -> List[Dict]:
        candidates = []
        seen = set()
        for name in names:
            for candidate in self.search_anime(name, k=3):
                if candidate["id"] in seen:
                    continue
                candidates.append(candidate)
                seen.add(candidate["id"])
                break
            if len(candidates) >= limit:
                break
        return candidates
