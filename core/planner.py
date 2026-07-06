from typing import Any, Dict, List


class AgentPlanner:
    def __init__(self, search_service, guide_service):
        self.search = search_service
        self.guide = guide_service

    def run(self, query: str, intent_data: Dict[str, Any], history: List[Dict] | None = None) -> Dict[str, Any]:
        intent_type = intent_data.get("intent", "CHAT")
        keywords = intent_data.get("keywords") or query
        anime_name = intent_data.get("anime_name")
        thought = f"Detected Intent: {intent_type} | Focus: {keywords}"

        if intent_type == "SEARCH":
            result = self.search.search_for_query(keywords, anime_name=anime_name)
            result.update(
                {
                    "intent": intent_type,
                    "response": "",
                    "thought": self._search_thought(thought, result),
                    "context": result.get("context", []),
                    "meta": intent_data,
                }
            )
            return result

        if intent_type == "RECOMMEND":
            names = self.guide.recommend_names(keywords, count=10)
            candidates = self.search.candidates_for_names(names, limit=10)
            return {
                "intent": intent_type,
                "mode": "recommendation",
                "query": keywords,
                "recommendations": names,
                "candidates": candidates,
                "spots": [],
                "context": [],
                "response": "",
                "thought": f"{thought} -> Recommended {len(candidates)} matched anime candidates.",
                "meta": intent_data,
            }

        if intent_type == "GUIDE":
            context = self.search.guide_context(keywords, anime_name=anime_name)
            response = self.guide.generate_response(query, context, history=history)
            return {
                "intent": intent_type,
                "mode": "answer",
                "query": keywords,
                "candidates": [],
                "spots": [],
                "context": context,
                "response": response,
                "thought": f"{thought} -> Guide context: {len(context)} anime items.",
                "meta": intent_data,
            }

        context = self.search.guide_context(keywords, anime_name=anime_name)
        response = self.guide.generate_response(query, context, history=history)
        return {
            "intent": intent_type,
            "mode": "answer",
            "query": keywords,
            "candidates": [],
            "spots": [],
            "context": context,
            "response": response,
            "thought": f"{thought} -> Chat/RAG context: {len(context)} anime items.",
            "meta": intent_data,
        }

    @staticmethod
    def _search_thought(base: str, result: Dict[str, Any]) -> str:
        if result.get("mode") == "search_candidates":
            return f"{base} -> Found {len(result.get('candidates', []))} anime candidates."
        if result.get("mode") == "search_spots":
            return f"{base} -> Found {len(result.get('spots', []))} spot matches."
        return f"{base} -> No matching anime or spot data."
