from evaluation.run_eval import evaluate, threshold_failures


class FakeRetriever:
    def search_anime(self, query, k=10):
        if query == "hit":
            return [{"id": 2}, {"id": 1}]
        return []

    def search_spots(self, query, k=10):
        if query == "city":
            return [{"name": "京都站", "city": "京都市"}]
        if query == "false-positive":
            return [{"name": "不应出现"}]
        return []


def test_golden_metrics_compute_recall_mrr_and_false_positive_rate():
    cases = [
        {
            "id": "anime",
            "target": "anime",
            "query": "hit",
            "relevance": {"anime_ids": [1]},
        },
        {
            "id": "city",
            "target": "city",
            "query": "city",
            "relevance": {"contains_any": ["京都"]},
        },
        {
            "id": "negative-clean",
            "target": "negative",
            "query": "clean",
            "relevance": {},
        },
        {
            "id": "negative-hit",
            "target": "negative",
            "query": "false-positive",
            "relevance": {},
        },
    ]

    metrics = evaluate(FakeRetriever(), cases, k=10)

    assert metrics["recall_at_k"] == 1.0
    assert metrics["mrr"] == 0.75
    assert metrics["false_positive_rate"] == 0.5
    assert metrics["false_hit_ids"] == ["negative-hit"]


def test_golden_thresholds_fail_closed():
    failures = threshold_failures(
        {
            "recall_at_k": 0.89,
            "mrr": 0.84,
            "false_positive_rate": 0.05,
        },
        recall_threshold=0.90,
        mrr_threshold=0.85,
        false_positive_threshold=0.05,
    )

    assert set(failures) == {"recall_at_k", "mrr", "false_positive_rate"}
