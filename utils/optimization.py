from geopy.distance import geodesic
import copy

def calculate_distance_matrix(points):
    """
    Calculate N*N distance matrix (km) for points.
    """
    n = len(points)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j: continue
            coords_i = (points[i]['geo'][0], points[i]['geo'][1])
            coords_j = (points[j]['geo'][0], points[j]['geo'][1])
            try:
                # geodesic expects (lat, lon)
                matrix[i][j] = geodesic(coords_i, coords_j).km
            except:
                matrix[i][j] = 99999.0
    return matrix

def solve_tsp_greedy(points, start_index=0):
    """
    Solve TSP using Nearest Neighbor heuristic.
    Returns: Optimized list of points.
    """
    if not points: return []
    if len(points) <= 2: return points # No optimization needed
    
    n = len(points)
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
            break # Should not happen if graph is complete
            
    # Reconstruct list
    input_copy = copy.deepcopy(points)
    optimized_points = [input_copy[i] for i in path_indices]
    
    return optimized_points
