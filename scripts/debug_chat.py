"""Manual Agent entrypoint diagnostic; requires no key for local search."""

import argparse
import json
import os

from core.agent import AnimeRagAgent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="少女歌剧")
    args = parser.parse_args()

    result = AnimeRagAgent().run(
        args.query,
        api_key=os.getenv("DASHSCOPE_API_KEY", ""),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
