import json
import sqlite3
from contextlib import closing

from core.sqlite_retrieval import SQLiteRetriever
from data_factory.build_kb import normalize_spot
from data_factory import crawler
from data_factory.enrich_cities import build_report
from data_factory.sqlite_index import SCHEMA_VERSION, build_runtime_index


def _payload():
    return {
        "stats": {
            "generated_at": "2026-07-24T00:00:00",
            "source_metadata": {
                "test": {
                    "source_url": "https://example.com",
                    "license": "test-license",
                }
            },
        },
        "items": [
            {
                "anime_id": 1,
                "meta": {
                    "id": 1,
                    "titles": {"cn": "孤独摇滚！", "jp": "ぼっち・ざ・ろっく！"},
                    "cover": None,
                    "type": "TV",
                    "score": 8.8,
                    "tags": ["乐队"],
                    "description": "少女乐队故事",
                },
                "spots": [
                    {
                        "id": "spot-1",
                        "name": "下北沢SHELTER",
                        "city": "东京都",
                        "image": None,
                        "lat": 35.6615,
                        "lon": 139.6694,
                        "description": None,
                        "tags": ["live"],
                        "source_url": "https://example.com/spot",
                        "episode": "8",
                        "scene": "演出场景",
                        "verified_at": "2026-07-24",
                    }
                ],
            }
        ],
    }


def test_runtime_index_is_versioned_and_loaded_lazily(tmp_path):
    db_path = tmp_path / "animeway.sqlite3"
    result = build_runtime_index(_payload(), db_path=str(db_path))
    retriever = SQLiteRetriever(str(db_path))

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["data_checksum"]
    assert retriever.anime_count == 1
    assert retriever.spot_count == 1
    assert retriever.search_anime("孤独摇滚")[0]["id"] == 1
    assert retriever.search_spots("量子香蕉飞船") == []
    assert retriever.get_anime_item(1)["spots"][0]["episode"] == "8"

    with closing(sqlite3.connect(db_path)) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    assert json.loads(metadata["schema_version"]) == SCHEMA_VERSION
    assert json.loads(metadata["source_metadata"])["test"]["license"] == "test-license"


def test_coordinate_validation_rejects_out_of_range_values():
    assert normalize_spot({"name": "bad", "lat": 91, "lon": 139}, anime_id=1) is None
    assert normalize_spot({"name": "bad", "lat": 35, "lon": 181}, anime_id=1) is None


def test_city_enrichment_report_is_reviewable_and_does_not_mutate_input():
    points = [
        {"id": "known", "name": "A", "lat": 35.0, "lon": 139.0, "city": "测试市"},
        {"id": "missing", "name": "B", "lat": 35.001, "lon": 139.001, "city": ""},
    ]

    report = build_report(points, max_distance_km=5)

    assert report["suggestion_count"] == 1
    assert report["suggestions"][0]["city"] == "测试市"
    assert report["suggestions"][0]["source"] == "nearest_known_spot"
    assert points[1]["city"] == ""


def test_crawler_retries_transient_http_errors_with_backoff(monkeypatch):
    statuses = iter([503, 200])
    sleeps = []

    class Response:
        def __init__(self, status_code):
            self.status_code = status_code

    monkeypatch.setattr(
        crawler.requests,
        "get",
        lambda *args, **kwargs: Response(next(statuses)),
    )
    monkeypatch.setattr(crawler.time, "sleep", lambda seconds: sleeps.append(seconds))

    response, error = crawler.request_with_backoff("https://example.com")

    assert response.status_code == 200
    assert error == ""
    assert sleeps == [crawler.DELAY_SECONDS]


def test_shipped_crawl_state_tracks_every_bangumi_subject():
    with open("knowledge_base/raw/bangumi_knowledge.json", encoding="utf-8") as source:
        subjects = json.load(source)
    with open("knowledge_base/raw/crawl_state.json", encoding="utf-8") as source:
        state = json.load(source)

    subject_ids = {
        str(item.get("subject") or item.get("id"))
        for item in subjects
        if item.get("subject") or item.get("id")
    }
    assert subject_ids <= set(state)
    assert {entry["status"] for entry in state.values()} <= {
        "pending",
        "success",
        "no_spots",
        "not_found",
        "failed",
    }
