import copy
import re
from collections import OrderedDict
from typing import Any

from geopy.distance import geodesic


UNKNOWN_CITIES = {"", "unknown", "unknowncity", "未知", "未知城市"}


def calculate_distance_matrix(points: list[dict[str, Any]]) -> list[list[float]]:
    """
    Calculate N*N distance matrix (km) for points.

    Distances are symmetric, so each geodesic pair is calculated once.
    """
    n = len(points)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            coords_i = (points[i]["lat"], points[i]["lon"])
            coords_j = (points[j]["lat"], points[j]["lon"])
            try:
                distance = geodesic(coords_i, coords_j).km
            except (TypeError, ValueError):
                distance = 99999.0
            matrix[i][j] = distance
            matrix[j][i] = distance
    return matrix


def solve_tsp_greedy(
    points: list[dict[str, Any]],
    start_index: int = 0,
) -> list[dict[str, Any]]:
    """
    Solve TSP using Nearest Neighbor heuristic.
    Returns: Optimized list of points.
    """
    if not points:
        return []
    if len(points) <= 2:
        return copy.deepcopy(points)
    
    n = len(points)
    if not 0 <= start_index < n:
        raise IndexError(start_index)
    dist_matrix = calculate_distance_matrix(points)
    
    visited = [False] * n
    path_indices = []
    
    # Start at user-defined start point (usually 0, the first added point)
    current = start_index
    path_indices.append(current)
    visited[current] = True
    
    for _ in range(n - 1):
        nearest_dist = float('inf')
        nearest_idx = -1
        
        for next_idx in range(n):
            if not visited[next_idx]:
                d = dist_matrix[current][next_idx]
                if d < nearest_dist:
                    nearest_dist = d
                    nearest_idx = next_idx
        
        if nearest_idx != -1:
            visited[nearest_idx] = True
            path_indices.append(nearest_idx)
            current = nearest_idx
        else:
            break
            
    # Reconstruct list
    input_copy = copy.deepcopy(points)
    optimized_points = [input_copy[i] for i in path_indices]
    
    return optimized_points


def normalize_city(point: dict[str, Any]) -> str:
    value = str(point.get("_city") or point.get("city") or "").strip().lower()
    return re.sub(r"[^\w\u4e00-\u9fff\u3040-\u30ffー]+", "", value)


def solve_tsp_by_city(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Preserve first-seen city order and run nearest-neighbour only inside each city.

    Unknown-city points remain independent groups, preventing an accidental
    cross-country greedy route when city metadata is missing.
    """
    if not points:
        return []

    groups: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for index, point in enumerate(points):
        city = normalize_city(point)
        group_key = city if city not in UNKNOWN_CITIES else f"__unknown_{index}"
        groups.setdefault(group_key, []).append(point)

    optimized: list[dict[str, Any]] = []
    for group in groups.values():
        optimized.extend(solve_tsp_greedy(group, start_index=0))
    return optimized
