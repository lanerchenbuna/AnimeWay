"""Read-only destination staging. A candidate cannot become a live destination."""
import json
from pathlib import Path


def expansion_status(path):
    """Validate an explicitly supplied candidate; no local planning file is required."""
    raw = json.loads(Path(path).read_text())
    if raw.get("schema_version") != 1:
        raise ValueError("不支持的目的地试点格式")
    missing = [name for name, passed in raw["release_gates"].items() if passed is not True]
    if not raw.get("content_owner"):
        missing.append("content_owner")
    if any(value is None for value in raw["cost_observations"].values()):
        missing.append("cost_observations")
    if (raw.get("public_enabled") or raw.get("planner_enabled")) and missing:
        raise ValueError("未完成真实验收，不能启用新目的地")
    return {"destination": raw["name"], "status": raw["status"], "missing": missing,
            "public_enabled": raw["public_enabled"], "planner_enabled": raw["planner_enabled"]}
