#!/usr/bin/env python3
"""Run the 30 Tokyo transport boundary samples; this does not certify coverage."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.pilot import load_pilot
from core.trip import TOKYO, validate_anchor
from core.trip_transport import connection, resolve_anchor


def run_samples(catalog=None, sample_path=None):
    catalog = catalog or load_pilot()
    path = sample_path or Path(__file__).resolve().parents[1] / "evaluation" / "tokyo_transport.json"
    payload = json.loads(path.read_text())
    places = {p["id"]: p for p in catalog["locations"]}
    results = []
    for sample in payload["samples"]:
        if sample["kind"] == "geocoding":
            try:
                anchor = validate_anchor(sample["anchor"])
                resolved = resolve_anchor(anchor, catalog)
                status = "catalog_or_user_confirmed" if resolved else "unresolved"
            except ValueError:
                status = "invalid_scope"
            passed = status == sample["expected"]
        else:
            origin, destination = places.get(sample.get("from_id")), places.get(sample.get("to_id"))
            result = connection(origin, destination, sample["mode"], catalog)
            status = result["status"]
            passed = status in sample["expected"] and result["mode"] == sample["mode"] and status != "verified"
            if sample["mode"] == "transit" and status != "same_location":
                passed = passed and result["move_min"] is None and result["fare_jpy"] is None
        results.append({"id": sample["id"], "scenario": sample["scenario"], "result": status,
                        "policy_passed": passed, "live_provider_verified": False})
    return {"measured_at": datetime.now(TOKYO).isoformat(), "sample_version": payload["version"],
            "policy_cases": len(results), "policy_passed": sum(r["policy_passed"] for r in results),
            "live_provider_queries": 0, "provider_coverage_verified": False, "field_walks": 0,
            "release_scope": "v0.9 editable drafts; no verified Japan transit promise", "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_samples()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    if result["policy_passed"] != result["policy_cases"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
