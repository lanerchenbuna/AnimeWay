from core.agent import AnimeRagAgent
from core.retrieval import HybridRetriever
import pytest


@pytest.fixture(scope="module")
def retriever():
    return AnimeRagAgent().retriever


def test_bocchi_spot_search_returns_shimokitazawa(retriever):
    spots = retriever.search_spots("孤独摇滚圣地", k=10)

    assert spots
    assert any("下北" in spot["name"] or "shelter" in spot["name"].lower() for spot in spots)


def test_kyoto_spot_search_returns_kyoto_not_tokyo(retriever):
    spots = retriever.search_spots("京都有什么动画圣地", k=10)

    assert spots
    top_text = f"{spots[0].get('name', '')} {spots[0].get('city', '')} {spots[0].get('_city', '')}"
    assert "京都" in top_text
    assert "東京都" not in top_text


def test_cafe_spot_search_returns_cafe_like_places(retriever):
    spots = retriever.search_spots("咖啡店巡礼", k=10)

    assert spots
    cafe_terms = ("cafe", "咖啡", "喫茶", "カフェ")
    assert any(
        any(term in f"{spot.get('name', '')} {spot.get('description', '')}".lower() for term in cafe_terms)
        for spot in spots
    )


def test_starlight_search_prefers_tv_series_with_spots(retriever):
    candidates = retriever.search_anime("少女歌剧", k=3)

    assert candidates
    assert candidates[0]["id"] == 214265
    assert "96 圣地" in candidates[0]["summary"]


def test_irrelevant_query_does_not_receive_popularity_boost(retriever):
    query = "量子香蕉飞船"

    assert retriever.search_anime(query, k=5) == []
    assert retriever.search_spots(query, k=5) == []


def test_dynamic_city_lexicon_routes_yokohama_query_to_yokohama(retriever):
    spots = retriever.search_spots("横滨有什么动画圣地", k=10)

    assert spots
    assert all("横滨" in (spot.get("city") or "") for spot in spots)


def test_title_typo_can_still_match_anime(retriever):
    candidates = retriever.search_anime("少钕歌剧", k=3)

    assert candidates
    assert "少女" in candidates[0]["cn"]


def test_legacy_retrieval_cache_can_be_reloaded(tmp_path):
    knowledge_base = [
        {
            "anime_id": 1,
            "meta": {
                "titles": {"cn": "缓存测试作品", "jp": ""},
                "tags": [],
                "score": 8,
            },
            "spots": [
                {
                    "id": "spot-1",
                    "name": "缓存测试地点",
                    "city": "测试市",
                    "lat": 35,
                    "lon": 139,
                    "tags": [],
                }
            ],
        }
    ]

    first = HybridRetriever(knowledge_base, cache_dir=str(tmp_path))
    second = HybridRetriever(knowledge_base, cache_dir=str(tmp_path))

    assert first.search_anime("缓存测试作品")
    assert second.search_anime("缓存测试作品")
    assert second.search_spots("缓存测试地点")
