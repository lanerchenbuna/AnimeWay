import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable


DEFAULT_INPUT = "knowledge_base/raw/anitabi_crawl.json"
DEFAULT_REPORT = "knowledge_base/city_enrichment_report.json"
GRID_SIZE_DEGREES = 0.25


def _bucket(lat: float, lon: float) -> tuple[int, int]:
    return int(math.floor(lat / GRID_SIZE_DEGREES)), int(math.floor(lon / GRID_SIZE_DEGREES))


def _distance_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, first)
    lat2, lon2 = map(math.radians, second)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(value)))


def _coordinates(point: Dict[str, Any]) -> tuple[float, float] | None:
    try:
        return float(point["lat"]), float(point["lon"])
    except (KeyError, TypeError, ValueError):
        geo = point.get("geo")
        if not isinstance(geo, list) or len(geo) != 2:
            return None
        try:
            return float(geo[0]), float(geo[1])
        except (TypeError, ValueError):
            return None


def build_city_grid(points: Iterable[Dict[str, Any]]) -> Dict[tuple[int, int], list[Dict[str, Any]]]:
    grid: Dict[tuple[int, int], list[Dict[str, Any]]] = defaultdict(list)
    for point in points:
        city = str(point.get("city") or "").strip()
        coords = _coordinates(point)
        if city and coords:
            grid[_bucket(*coords)].append({"city": city, "lat": coords[0], "lon": coords[1]})
    return grid


def suggest_city(
    point: Dict[str, Any],
    grid: Dict[tuple[int, int], list[Dict[str, Any]]],
    max_distance_km: float = 25.0,
) -> Dict[str, Any] | None:
    coords = _coordinates(point)
    if not coords:
        return None
    center = _bucket(*coords)
    candidates = [
        candidate
        for lat_offset in range(-2, 3)
        for lon_offset in range(-2, 3)
        for candidate in grid.get((center[0] + lat_offset, center[1] + lon_offset), [])
    ]
    if not candidates:
        return None
    nearest = min(
        candidates,
        key=lambda candidate: _distance_km(coords, (candidate["lat"], candidate["lon"])),
    )
    distance = _distance_km(coords, (nearest["lat"], nearest["lon"]))
    if distance > max_distance_km:
        return None
    return {
        "city": nearest["city"],
        "distance_km": round(distance, 2),
        "confidence": "high" if distance <= 5 else "medium",
        "source": "nearest_known_spot",
    }


def build_report(points: list[Dict[str, Any]], max_distance_km: float = 25.0) -> Dict[str, Any]:
    grid = build_city_grid(points)
    suggestions = []
    unresolved = 0
    for index, point in enumerate(points):
        if point.get("city"):
            continue
        suggestion = suggest_city(point, grid, max_distance_km=max_distance_km)
        if not suggestion:
            unresolved += 1
            continue
        suggestions.append(
            {
                "raw_index": index,
                "spot_id": point.get("id"),
                "anime_id": point.get("anime_id"),
                "name": point.get("name") or point.get("cn"),
                "lat": _coordinates(point)[0],
                "lon": _coordinates(point)[1],
                **suggestion,
            }
        )
    return {
        "method": "nearest known spot city; review before applying",
        "max_distance_km": max_distance_km,
        "missing_city_count": sum(1 for point in points if not point.get("city")),
        "suggestion_count": len(suggestions),
        "unresolved_count": unresolved,
        "suggestions": suggestions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate reviewable city-completion suggestions.")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--max-distance-km", type=float, default=25.0)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as source:
        points = json.load(source)
    report = build_report(points, max_distance_km=args.max_distance_km)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = report_path.with_suffix(report_path.suffix + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
    temp_path.replace(report_path)
    print(
        f"City report: {report['suggestion_count']} suggestions, "
        f"{report['unresolved_count']} unresolved -> {report_path}"
    )


if __name__ == "__main__":
    main()
