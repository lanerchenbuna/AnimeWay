import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from core.agent import AnimeRagAgent
from core.retrieval import HybridRetriever


DEFAULT_DATASET = Path("evaluation/golden_retrieval.json")
DEFAULT_RECALL_THRESHOLD = 0.90
DEFAULT_MRR_THRESHOLD = 0.85
DEFAULT_FALSE_POSITIVE_THRESHOLD = 0.05


def load_dataset(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        payload = json.load(source)
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError(f"Invalid evaluation dataset: {path}")
    if not payload["cases"]:
        raise ValueError(f"Evaluation dataset contains no cases: {path}")
    return payload


def _search(retriever: Any, case: dict[str, Any], k: int) -> list[dict[str, Any]]:
    target = case.get("target")
    if target == "anime":
        return retriever.search_anime(case["query"], k=k)
    if target in {"city", "theme", "spot", "negative"}:
        return retriever.search_spots(case["query"], k=k)
    raise ValueError(f"Unsupported evaluation target: {target}")


def _result_text(result: dict[str, Any]) -> str:
    return HybridRetriever.normalize_text(
        " ".join(
            [
                str(result.get("name") or ""),
                str(result.get("city") or result.get("_city") or ""),
                str(result.get("_anime_name") or result.get("cn") or ""),
                str(result.get("description") or ""),
                " ".join(str(tag) for tag in result.get("tags", [])),
            ]
        )
    )


def is_relevant(case: dict[str, Any], result: dict[str, Any]) -> bool:
    relevance = case.get("relevance") or {}
    anime_ids = {int(value) for value in relevance.get("anime_ids", [])}
    if anime_ids:
        candidate_id = result.get("anime_id") or result.get("id")
        if candidate_id is None:
            return False
        try:
            return int(candidate_id) in anime_ids
        except (TypeError, ValueError):
            return False

    result_text = _result_text(result)
    expected_values = relevance.get("contains_any", [])
    return bool(
        expected_values
        and any(
            HybridRetriever.normalize_text(str(value)) in result_text
            for value in expected_values
        )
    )


def evaluate(
    retriever: Any,
    cases: list[dict[str, Any]],
    k: int = 10,
) -> dict[str, Any]:
    positive_cases = [case for case in cases if case.get("target") != "negative"]
    negative_cases = [case for case in cases if case.get("target") == "negative"]
    positive_hits = 0
    reciprocal_rank_sum = 0.0
    false_hits: list[str] = []
    case_results: list[dict[str, Any]] = []
    latencies_ms: list[float] = []

    for case in cases:
        started_at = time.perf_counter()
        results = _search(retriever, case, k)
        latency_ms = (time.perf_counter() - started_at) * 1000
        latencies_ms.append(latency_ms)

        if case.get("target") == "negative":
            if results:
                false_hits.append(case["id"])
            rank = None
        else:
            rank = next(
                (
                    index
                    for index, result in enumerate(results, start=1)
                    if is_relevant(case, result)
                ),
                None,
            )
            if rank is not None:
                positive_hits += 1
                reciprocal_rank_sum += 1 / rank

        case_results.append(
            {
                "id": case["id"],
                "query": case["query"],
                "target": case["target"],
                "rank": rank,
                "result_count": len(results),
                "latency_ms": round(latency_ms, 3),
            }
        )

    positive_count = len(positive_cases)
    negative_count = len(negative_cases)
    return {
        "case_count": len(cases),
        "positive_count": positive_count,
        "negative_count": negative_count,
        "recall_at_k": positive_hits / positive_count if positive_count else 1.0,
        "mrr": reciprocal_rank_sum / positive_count if positive_count else 1.0,
        "false_positive_rate": len(false_hits) / negative_count if negative_count else 0.0,
        "false_hit_ids": false_hits,
        "max_latency_ms": round(max(latencies_ms, default=0.0), 3),
        "cases": case_results,
    }


def threshold_failures(
    metrics: dict[str, Any],
    recall_threshold: float,
    mrr_threshold: float,
    false_positive_threshold: float,
) -> dict[str, str]:
    failures = {}
    if metrics["recall_at_k"] < recall_threshold:
        failures["recall_at_k"] = (
            f"{metrics['recall_at_k']:.3f} < {recall_threshold:.3f}"
        )
    if metrics["mrr"] < mrr_threshold:
        failures["mrr"] = f"{metrics['mrr']:.3f} < {mrr_threshold:.3f}"
    if metrics["false_positive_rate"] >= false_positive_threshold:
        failures["false_positive_rate"] = (
            f"{metrics['false_positive_rate']:.3f} >= "
            f"{false_positive_threshold:.3f}"
        )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the versioned Chinese retrieval golden set.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--min-recall", type=float, default=DEFAULT_RECALL_THRESHOLD)
    parser.add_argument("--min-mrr", type=float, default=DEFAULT_MRR_THRESHOLD)
    parser.add_argument(
        "--max-false-positive-rate",
        type=float,
        default=DEFAULT_FALSE_POSITIVE_THRESHOLD,
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = load_dataset(args.dataset)
    retriever = AnimeRagAgent().retriever
    metrics = evaluate(retriever, payload["cases"], k=max(1, args.k))
    failures = threshold_failures(
        metrics,
        recall_threshold=args.min_recall,
        mrr_threshold=args.min_mrr,
        false_positive_threshold=args.max_false_positive_rate,
    )
    report = {
        "dataset": str(args.dataset),
        "dataset_version": payload.get("version"),
        "metrics": metrics,
        "thresholds": {
            "min_recall": args.min_recall,
            "min_mrr": args.min_mrr,
            "max_false_positive_rate": args.max_false_positive_rate,
        },
        "failures": failures,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
