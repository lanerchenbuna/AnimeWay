from core.agent import AnimeRagAgent
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
