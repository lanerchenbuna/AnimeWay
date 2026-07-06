import pytest

from core.agent import AnimeRagAgent
from core.intent import extract_json_object, heuristic_intent, normalize_intent_payload


@pytest.fixture(scope="module")
def agent():
    return AnimeRagAgent()


def test_intent_json_schema_parser_handles_fenced_json():
    raw = """```json
    {"intent":"search","keywords":"孤独摇滚圣地","anime_name":"孤独摇滚","reasoning":"ok"}
    ```"""

    parsed = extract_json_object(raw)
    normalized = normalize_intent_payload(parsed, "孤独摇滚圣地")

    assert normalized["intent"] == "SEARCH"
    assert normalized["keywords"] == "孤独摇滚圣地"
    assert normalized["anime_name"] == "孤独摇滚"


def test_intent_heuristic_fallback_for_location_query():
    result = heuristic_intent("京都有什么动画圣地")

    assert result["intent"] == "SEARCH"
    assert result["keywords"] == "京都有什么动画圣地"


def test_agent_run_search_uses_unified_entrypoint(agent, monkeypatch):
    monkeypatch.setattr(
        agent.intent_service,
        "classify",
        lambda query, history=None: {
            "intent": "SEARCH",
            "keywords": "京都有什么动画圣地",
            "anime_name": None,
            "reasoning": "test",
        },
    )

    result = agent.run("京都有什么动画圣地")

    assert result["mode"] == "search_spots"
    assert result["spots"]
    assert "京都" in result["spots"][0].get("city", "")


def test_agent_run_recommend_uses_unified_entrypoint(agent, monkeypatch):
    monkeypatch.setattr(
        agent.intent_service,
        "classify",
        lambda query, history=None: {
            "intent": "RECOMMEND",
            "keywords": "乐队番",
            "anime_name": None,
            "reasoning": "test",
        },
    )
    monkeypatch.setattr(agent.guide_service, "recommend_names", lambda query, count=10: ["孤独摇滚！", "轻音少女"])

    result = agent.run("推荐几部乐队番")

    assert result["mode"] == "recommendation"
    assert result["recommendations"] == ["孤独摇滚！", "轻音少女"]
    assert result["candidates"]


def test_agent_run_guide_uses_unified_entrypoint(agent, monkeypatch):
    monkeypatch.setattr(
        agent.intent_service,
        "classify",
        lambda query, history=None: {
            "intent": "GUIDE",
            "keywords": "孤独摇滚巡礼指南",
            "anime_name": "孤独摇滚",
            "reasoning": "test",
        },
    )
    monkeypatch.setattr(agent.guide_service, "generate_response", lambda query, context, history=None: "guide ok")

    result = agent.run("孤独摇滚巡礼指南")

    assert result["mode"] == "answer"
    assert result["response"] == "guide ok"
    assert result["context"]
