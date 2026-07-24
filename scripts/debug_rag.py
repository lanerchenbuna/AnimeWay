"""Manual local retrieval diagnostic; not part of the pytest suite."""

import argparse

from core.agent import AnimeRagAgent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="轻音少女")
    args = parser.parse_args()

    agent = AnimeRagAgent()
    results = agent.retriever.retrieve_knowledge(args.query)
    candidates = agent.retriever.get_anime_candidates(args.query)
    if not candidates:
        raise SystemExit(f"No candidates found for: {args.query}")

    print(f"Candidates: {len(candidates)}")
    print(f"Top candidate: {candidates[0]['cn']}")
    print(f"Knowledge records: {len(results)}")
    if results:
        print(f"Spots: {len(results[0].get('spots', []))}")


if __name__ == "__main__":
    main()
