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
        lambda query, history=None, api_key="": {
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
        lambda query, history=None, api_key="": {
            "intent": "RECOMMEND",
            "keywords": "乐队番",
            "anime_name": None,
            "reasoning": "test",
        },
    )
    monkeypatch.setattr(
        agent.guide_service,
        "recommend_names",
        lambda query, count=10, api_key="": ["孤独摇滚！", "轻音少女"],
    )

    result = agent.run("推荐几部乐队番", api_key="test-key")

    assert result["mode"] == "recommendation"
    assert result["recommendations"] == ["孤独摇滚！", "轻音少女"]
    assert result["candidates"]


def test_agent_run_guide_uses_unified_entrypoint(agent, monkeypatch):
    monkeypatch.setattr(
        agent.intent_service,
        "classify",
        lambda query, history=None, api_key="": {
            "intent": "GUIDE",
            "keywords": "孤独摇滚巡礼指南",
            "anime_name": "孤独摇滚",
            "reasoning": "test",
        },
    )
    monkeypatch.setattr(
        agent.guide_service,
        "generate_response",
        lambda query, context, history=None, api_key="": "guide ok",
    )

    result = agent.run("孤独摇滚巡礼指南", api_key="test-key")

    assert result["mode"] == "answer"
    assert result["response"] == "guide ok"
    assert result["context"]


def test_offline_search_does_not_require_dashscope_key(agent):
    result = agent.run("横滨有什么动画圣地", api_key="")

    assert result["mode"] == "search_spots"
    assert result["spots"]
    assert "横滨" in result["spots"][0].get("city", "")


@pytest.mark.parametrize("query", ["少女歌剧", "少钕歌剧"])
def test_offline_plain_title_search_does_not_require_dashscope_key(agent, query):
    result = agent.run(query, api_key="")

    assert result["mode"] == "search_candidates"
    assert result["candidates"]
    assert result.get("requires_api_key") is not True


def test_offline_long_tail_city_search_does_not_require_dashscope_key(agent):
    result = agent.run("南砺市", api_key="")

    assert result["mode"] == "search_spots"
    assert result["spots"]
    assert all("南砺" in (spot.get("city") or "") for spot in result["spots"])


def test_offline_irrelevant_query_reaches_empty_mode(agent):
    result = agent.run("量子香蕉飞船", api_key="")

    assert result["mode"] == "empty"
    assert result["candidates"] == []
    assert result["spots"] == []


def test_offline_explicit_chat_explains_key_requirement(agent):
    result = agent.run("你好，你是谁", api_key="")

    assert result["mode"] == "answer"
    assert result["requires_api_key"] is True


def test_offline_recommendation_explains_key_requirement(agent):
    result = agent.run("推荐几部乐队番", api_key="")

    assert result["mode"] == "answer"
    assert result["requires_api_key"] is True
    assert "DashScope Key" in result["response"]
