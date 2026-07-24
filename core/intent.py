import json
import re
from typing import Any, Callable, Dict, List

from core.prompts import INTENT_PROMPT_TEMPLATE


VALID_INTENTS = {"SEARCH", "RECOMMEND", "GUIDE", "CHAT"}


def extract_json_object(text: str) -> Dict[str, Any] | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    candidates = [cleaned]
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        candidates.append(match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def normalize_intent_payload(payload: Dict[str, Any], query: str, fallback_reason: str = "") -> Dict[str, Any]:
    intent = str(payload.get("intent") or "").upper()
    if intent not in VALID_INTENTS:
        intent = heuristic_intent(query)["intent"]

    keywords = payload.get("keywords")
    if not isinstance(keywords, str) or not keywords.strip():
        keywords = query

    anime_name = payload.get("anime_name")
    if anime_name in ("", "null", "None"):
        anime_name = None
    if anime_name is not None and not isinstance(anime_name, str):
        anime_name = str(anime_name)

    reasoning = payload.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        reasoning = fallback_reason or "Intent parsed with schema fallback."

    return {
        "intent": intent,
        "keywords": keywords.strip(),
        "anime_name": anime_name.strip() if isinstance(anime_name, str) else None,
        "reasoning": reasoning,
    }


def heuristic_intent(query: str) -> Dict[str, Any]:
    q = query.strip()
    if re.search(r"推荐|适合|想看|治愈|机甲|类型|风格", q):
        intent = "RECOMMEND"
    elif re.search(r"指南|攻略|值得去|怎么逛|行程|路线", q):
        intent = "GUIDE"
    elif re.search(r"圣地|巡礼|取景|在哪|哪里|地点|位置|京都|东京|東京|咖啡|cafe|喫茶", q, re.IGNORECASE):
        intent = "SEARCH"
    elif re.search(r"你好|您好|你是谁|闲聊|聊聊天|谢谢|再见|帮助", q):
        intent = "CHAT"
    else:
        # The primary no-key surface is a relevance-gated local search box.
        # Unknown terms should therefore be allowed to return a trustworthy
        # empty result instead of being forced through an unavailable LLM.
        intent = "SEARCH"
    return {
        "intent": intent,
        "keywords": q,
        "anime_name": None,
        "reasoning": "Heuristic fallback without valid LLM JSON.",
    }


class IntentService:
    def __init__(self, llm_call: Callable[[str, List[Dict] | None, str], str]):
        self.llm_call = llm_call

    @staticmethod
    def format_history(history: List[Dict] | None) -> str:
        if not history:
            return ""
        lines = ["Conversation History:"]
        for msg in history[-3:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def classify(self, query: str, history: List[Dict] | None = None, api_key: str = "") -> Dict[str, Any]:
        if not api_key:
            return heuristic_intent(query)
        history_context = self.format_history(history)
        prompt_query = f"{history_context}\nCurrent Query: {query}" if history_context else query
        prompt = INTENT_PROMPT_TEMPLATE.replace("{user_query}", prompt_query)
        raw = self.llm_call(prompt, None, api_key)
        parsed = extract_json_object(raw)
        if parsed is None:
            return heuristic_intent(query)
        return normalize_intent_payload(parsed, query)
