"""Small deterministic reproducer for title relevance scoring."""

from core.retrieval import HybridRetriever


def main() -> None:
    retriever = HybridRetriever(
        [
            {
                "anime_id": 294135,
                "meta": {
                    "titles": {
                        "cn": "剧场版 少女☆歌剧 Revue Starlight",
                        "jp": "劇場版 少女☆歌劇 レヴュースタァライト",
                    },
                    "tags": ["少女歌剧", "百合"],
                },
                "spots": [],
            }
        ]
    )
    candidates = retriever.get_anime_candidates("少女歌剧")
    if not candidates or candidates[0]["id"] != 294135:
        raise SystemExit("Retrieval reproducer failed")
    print(candidates[0])


if __name__ == "__main__":
    main()
