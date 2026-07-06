import json
import re
from typing import Callable, Dict, List

from core.prompts import RAG_RESPONSE_TEMPLATE, SYSTEM_PERSONA


def extract_json_list(text: str) -> List[str] | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    candidates = [cleaned]
    match = re.search(r"\[[\s\S]*\]", cleaned)
    if match:
        candidates.append(match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return None


class GuideService:
    FALLBACK_RECOMMENDATIONS = ["你的名字。", "孤独摇滚！", "轻音少女", "摇曳露营△", "冰菓"]

    def __init__(self, llm_call: Callable[[str, List[Dict] | None], str]):
        self.llm_call = llm_call

    @staticmethod
    def summarize_context(context_results: List[Dict]) -> str:
        if not context_results:
            return "No specific data found in Knowledge Base."

        simplified_ctx = []
        for item in context_results[:3]:
            meta = item.get("meta", {})
            spots = item.get("spots", [])
            simplified_ctx.append(
                {
                    "anime": meta.get("titles", {}).get("cn"),
                    "intro": (meta.get("description", "") or "")[:200],
                    "score": float(meta.get("score", 0) or 0),
                    "key_spots": [
                        {
                            "name": str(spot.get("name")),
                            "city": spot.get("city"),
                        }
                        for spot in spots[:10]
                    ],
                    "total_spots": len(spots),
                }
            )

        try:
            return json.dumps(simplified_ctx, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return "Context Serialization Error"

    def generate_response(self, user_query: str, context_results: List[Dict], history: List[Dict] | None = None) -> str:
        final_prompt = RAG_RESPONSE_TEMPLATE.format(
            system_persona=SYSTEM_PERSONA,
            context_str=self.summarize_context(context_results),
            user_query=user_query,
        )
        return self.llm_call(final_prompt, history)

    def recommend_names(self, query: str, count: int = 10) -> List[str]:
        prompt = (
            f"用户想要关于“{query}”的{count}部圣地巡礼动画推荐。\n"
            "要求：\n"
            "1. 必须是真实的、有明确取景地的动画。\n"
            "2. 尽量覆盖不同风格。\n"
            "3. 只输出动画的官方中文名称，用JSON列表格式。\n"
            "4. 不要包含任何Markdown标记或解释。\n\n"
            "示例格式: [\"动画A\", \"动画B\"]"
        )
        raw = self.llm_call(prompt, None)
        names = extract_json_list(raw)
        if names:
            return names[:count]
        return self.FALLBACK_RECOMMENDATIONS[:count]
