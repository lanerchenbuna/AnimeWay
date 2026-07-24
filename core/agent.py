import json
import os
from typing import List, Dict, Any
from dashscope import Generation
from core.guide import GuideService
from core.intent import IntentService
from core.planner import AgentPlanner
from core.retrieval import HybridRetriever
from core.search import SearchService

class AnimeRagAgent:
    def __init__(self, kb_data: List[Dict] | None = None, retriever=None):
        if retriever is not None:
            self.retriever = retriever
            self.knowledge_base = (
                kb_data
                if kb_data is not None
                else getattr(retriever, "knowledge_base", [])
            )
        elif kb_data is not None:
            self.knowledge_base = kb_data
            cache_dir = os.getenv("ANIMEWAY_RETRIEVAL_CACHE_DIR")
            self.retriever = HybridRetriever(self.knowledge_base, cache_dir=cache_dir)
        else:
            runtime_index = os.getenv("ANIMEWAY_INDEX_DB", "knowledge_base/animeway.sqlite3")
            if os.path.exists(runtime_index):
                from core.sqlite_retrieval import SQLiteRetriever

                self.retriever = SQLiteRetriever(runtime_index)
                self.knowledge_base = self.retriever.knowledge_base
                print(
                    f"✅ [Runtime] Loaded SQLite index: {self.retriever.anime_count} anime, "
                    f"{self.retriever.spot_count} spots."
                )
            else:
                self.knowledge_base = self._load_kb()
                cache_dir = os.getenv("ANIMEWAY_RETRIEVAL_CACHE_DIR")
                self.retriever = HybridRetriever(self.knowledge_base, cache_dir=cache_dir)

        self.intent_service = IntentService(self._call_llm)
        list_knowledge = self.knowledge_base if isinstance(self.knowledge_base, list) else None
        self.search_service = SearchService(list_knowledge, self.retriever)
        self.guide_service = GuideService(self._call_llm)
        self.planner = AgentPlanner(self.search_service, self.guide_service)
        
    def _load_kb(self) -> List[Dict]:
        """
        Loads the pre-built knowledge index.
        Falls back to the builder so local development still works before the
        first explicit `python -m data_factory.build_kb` run.
        """
        index_path = "knowledge_base/index.json"

        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                items = payload.get("items", [])
                stats = payload.get("stats", {})
                print(
                    f"✅ [Runtime] Loaded index: {len(items)} anime, "
                    f"{stats.get('spot_count', 'unknown')} spots."
                )
                return items
            if isinstance(payload, list):
                print(f"✅ [Runtime] Loaded legacy index: {len(payload)} anime.")
                return payload

        from data_factory.build_kb import build_knowledge_base

        payload = build_knowledge_base(write=False)
        items = payload.get("items", [])
        stats = payload.get("stats", {})
        print(
            f"⚡ [Runtime] Built transient index: {len(items)} anime, "
            f"{stats.get('spot_count', 0)} spots."
        )
        return items

    @staticmethod
    def sanitize_api_key(api_key: str | None) -> str:
        if not api_key:
            return ""
        api_key = str(api_key).strip()
        try:
            api_key.encode("ascii")
            return api_key
        except UnicodeEncodeError:
            import re

            return re.sub(r"[^\x00-\x7F]+", "", api_key)

    def _call_llm(self, prompt: str, history: List = None, api_key: str = "") -> str:
        """Helper to call DashScope safely"""
        safe_key = self.sanitize_api_key(api_key)
        if not safe_key:
            return ""
        try:
            messages = [{'role': 'user', 'content': prompt}]
            if history:
                safe_history = [
                    {"role": msg.get("role", "user"), "content": str(msg.get("content", ""))}
                    for msg in history[-6:]
                    if msg.get("role") in {"user", "assistant"} and msg.get("content")
                ]
                messages = safe_history + messages
            
            resp = Generation.call(model="qwen-turbo", messages=messages, api_key=safe_key)
            if resp.status_code == 200:
                return resp.output.text
            else:
                return f"⚠️ DashScope 调用失败（错误码：{getattr(resp, 'code', 'unknown')}）。"
        except Exception:
            return "⚠️ DashScope 网络调用失败，请稍后重试。"

    def run(self, user_query: str, api_key: str = "", history: List[Dict] = None) -> Dict[str, Any]:
        """
        Unified Agent entrypoint for UI, CLI, and tests.
        """
        safe_key = self.sanitize_api_key(api_key)
        intent_data = self.intent_service.classify(user_query, history=history, api_key=safe_key)
        return self.planner.run(user_query, intent_data, history=history, api_key=safe_key)

    def analyze_intent(self, query: str, history: List[Dict] = None, api_key: str = "") -> Dict[str, Any]:
        """
        Backward-compatible wrapper. Prefer `run()`.
        """
        return self.intent_service.classify(query, history=history, api_key=self.sanitize_api_key(api_key))

    def generate_response(self, user_query: str, api_key: str, history: List[Dict] = None) -> Dict[str, Any]:
        """
        Backward-compatible wrapper. Prefer `run()`.
        """
        return self.run(user_query, api_key=api_key, history=history)

if __name__ == "__main__":
    # Test
    agent = AnimeRagAgent()
    # You would need to set env var for API key to run this test
    print("Agent Initialized.")
