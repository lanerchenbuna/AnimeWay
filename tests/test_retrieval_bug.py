from core.retrieval import HybridRetriever
import json

# Mock Data
mock_data = [
    {
        "anime_id": 294135,
        "meta": {
            "titles": {"cn": "剧场版 少女☆歌剧 Revue Starlight", "jp": "劇場版 少女☆歌劇 レヴュースタァライト"},
            "tags": ["少女歌剧", "百合"]
        },
        "spots": []
    }
]

retriever = HybridRetriever(mock_data)
candidates = retriever.get_anime_candidates("少女歌剧")
print(f"Found: {len(candidates)}")
if candidates:
    print(candidates[0]['cn'])
