from typing import Any, Dict, List


class AgentPlanner:
    def __init__(self, search_service, guide_service):
        self.search = search_service
        self.guide = guide_service

    def run(
        self,
        query: str,
        intent_data: Dict[str, Any],
        history: List[Dict] | None = None,
        api_key: str = "",
    ) -> Dict[str, Any]:
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
            if not api_key:
                return self._llm_key_required(intent_type, keywords, intent_data, thought)
            names = self.guide.recommend_names(keywords, count=10, api_key=api_key)
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
            if not api_key:
                return self._llm_key_required(intent_type, keywords, intent_data, thought)
            context = self.search.guide_context(keywords, anime_name=anime_name)
            response = self.guide.generate_response(query, context, history=history, api_key=api_key)
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

        if not api_key:
            return self._llm_key_required(intent_type, keywords, intent_data, thought)
        context = self.search.guide_context(keywords, anime_name=anime_name)
        response = self.guide.generate_response(query, context, history=history, api_key=api_key)
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

    @staticmethod
    def _llm_key_required(intent_type: str, query: str, intent_data: Dict[str, Any], thought: str) -> Dict[str, Any]:
        return {
            "intent": intent_type,
            "mode": "answer",
            "query": query,
            "candidates": [],
            "spots": [],
            "context": [],
            "response": "本地作品与地点检索无需密钥；推荐、攻略和自然语言回答需要先配置 DashScope Key。",
            "thought": f"{thought} -> LLM key required; no external request was made.",
            "meta": intent_data,
            "requires_api_key": True,
        }
