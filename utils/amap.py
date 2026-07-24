import requests
from typing import Any
from urllib.parse import urlencode


PROVIDER = "amap"
API_VERSION = "v3"
REQUEST_TIMEOUT_SECONDS = 5


def _parse_polyline(value: Any) -> list[list[float]]:
    coordinates: list[list[float]] = []
    if not isinstance(value, str):
        return coordinates
    for pair in value.split(";"):
        try:
            lon, lat = pair.split(",", 1)
            coordinate = [float(lon), float(lat)]
        except (TypeError, ValueError):
            continue
        if not coordinates or coordinate != coordinates[-1]:
            coordinates.append(coordinate)
    return coordinates


def _collect_polylines(value: Any) -> list[list[float]]:
    coordinates: list[list[float]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_coordinates = (
                _parse_polyline(child)
                if key == "polyline"
                else _collect_polylines(child)
            )
            for coordinate in child_coordinates:
                if not coordinates or coordinate != coordinates[-1]:
                    coordinates.append(coordinate)
    elif isinstance(value, list):
        for child in value:
            for coordinate in _collect_polylines(child):
                if not coordinates or coordinate != coordinates[-1]:
                    coordinates.append(coordinate)
    return coordinates


def get_static_map_url(points, key, zoom=10, size="750*300"):
    """
    Generate Amap Static Map URL.
    points: list of (lon, lat) tuples.
    """
    if not points:
        return ""
    
    # 1. Markers: start, mid, end
    locations = [f"{p[0]},{p[1]}" for p in points]
    markers = f"mid,,A:{';'.join(locations)}" # Simple same style for all
    
    # 2. Path: Connect them
    paths = f"5,0x0000FF,1,,:{';'.join(locations)}"
    
    params = {"zoom": zoom, "size": size, "markers": markers, "paths": paths, "key": key}
    return f"https://restapi.amap.com/v3/staticmap?{urlencode(params)}"

def get_navigation_url(lon, lat):
    """
    Generate Amap Navigation URL (Web).
    """
    return f"https://uri.amap.com/navigation?to={lon},{lat}&mode=walk&coordinate=gaode"

def get_location_coords(address, key, city=None):
    """
    Geocode an address or city name to (lon, lat).
    """
    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {"address": address, "key": key}
    if city:
        params["city"] = city
    
    try:
        res = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS).json()
        if res['status'] == '1' and res['geocodes']:
            location = res['geocodes'][0]['location']
            lon, lat = location.split(',')
            return float(lon), float(lat)
    except Exception as e:
        print(f"Geocode Error: {e}")
    
    return None, None

def get_address_from_coords(lon, lat, key):
    """
    Reverse Geocode: (lon, lat) -> Formatted Address.
    """
    if not key:
        return f"{lat:.5f}, {lon:.5f}"
    
    location = f"{lon},{lat}"
    url = "https://restapi.amap.com/v3/geocode/regeo"
    params = {"location": location, "key": key, "radius": 100, "extensions": "base"}
    
    try:
        res = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS).json()
        if res['status'] == '1':
            return res['regeocode']['formatted_address']
    except Exception as e:
        print(f"Regeo Error: {e}")
    
    return f"{lat:.5f}, {lon:.5f}"

def get_walking_route(origin_lon, origin_lat, dest_lon, dest_lat, key):
    """
    Get Walking steps from Amap Web API v3.
    """
    origin = f"{origin_lon},{origin_lat}"
    destination = f"{dest_lon},{dest_lat}"
    url = "https://restapi.amap.com/v3/direction/walking"
    params = {
        "origin": origin,
        "destination": destination,
        "key": key,
        "extensions": "all",
    }
    
    try:
        res = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS).json()
        if res['status'] == '1' and res['route']['paths']:
            path = res['route']['paths'][0]
            distance = path['distance']
            duration = int(path['duration']) // 60 # minutes
            
            steps = []
            for step in path['steps']:
                steps.append(step['instruction'])
            
            return {
                "type": "walking",
                "distance_m": distance,
                "duration_min": duration,
                "steps": steps,
                "polyline": _collect_polylines(path.get("steps", [])),
                "raw": path
            }
    except Exception as e:
        print(f"Walking Route Error: {e}")
    return None

def get_transit_route(
    origin_lon,
    origin_lat,
    dest_lon,
    dest_lat,
    city,
    key,
    strategy=0,
    destination_city=None,
):
    """
    Get Transit steps from Amap Web API v3 (Integrated).
    Strategies:
    0: Recommended (Fastest/Best)
    2: Least Transfers
    3: Least Walking
    5: No Subway
    """
    origin = f"{origin_lon},{origin_lat}"
    destination = f"{dest_lon},{dest_lat}"
    # city can be city code or name.
    if not city:
        city = "此地"
    
    url = "https://restapi.amap.com/v3/direction/transit/integrated"
    params = {
        "origin": origin,
        "destination": destination,
        "city": city,
        "key": key,
        "strategy": strategy,
        "extensions": "all",
    }
    if destination_city and destination_city != city:
        params["cityd"] = destination_city
    
    try:
        res = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS).json()
        if res['status'] == '1' and res['route']['transits']:
            # Pick the first route
            route = res['route']['transits'][0]
            
            # Safe Parsing
            try:
                distance = float(route.get('distance', 0))
            except (TypeError, ValueError):
                distance = 0.0
            
            try:
                duration = int(route.get('duration', 0)) // 60
            except (TypeError, ValueError):
                duration = 0
            
            # Cost handling: sometimes it's a list or string
            raw_cost = route.get('cost')
            cost = 0.0
            if isinstance(raw_cost, list) and raw_cost:
                try:
                    cost = float(raw_cost[0].get('cost', 0))
                except (AttributeError, TypeError, ValueError):
                    pass
            elif isinstance(raw_cost, str) and raw_cost:
                try:
                    cost = float(raw_cost)
                except ValueError:
                    pass
            elif isinstance(raw_cost, (int, float)):
                cost = float(raw_cost)

            segments_desc = []
            has_railway = False
            for seg in route['segments']:
                # Walking part
                if seg.get('walking') and seg['walking']['steps']:
                    try:
                        dist = seg['walking']['distance']
                        segments_desc.append(f"步行 {dist}米")
                    except (KeyError, TypeError):
                        pass
                
                # Bus/Subway part
                if seg.get('bus') and seg['bus']['buslines']:
                    try:
                        line = seg['bus']['buslines'][0]
                        name = line['name'].split('(')[0]
                        stations = line.get('num_stops', '?')
                        segments_desc.append(f"乘坐 [{name}] ({stations}站)")
                    except (AttributeError, IndexError, KeyError, TypeError):
                        pass
                
                # Railway part (sometimes appears for intercity)
                if seg.get('railway') and seg['railway']['name']:
                    has_railway = True
                    try:
                        r_name = seg['railway']['name']
                        segments_desc.append(f"乘坐 [{r_name}]")
                    except (KeyError, TypeError):
                        pass
            
            return {
                "type": "rail" if has_railway else "transit",
                "distance_m": distance,
                "duration_min": duration,
                "cost": cost,
                "steps": segments_desc,
                "polyline": _collect_polylines(route.get("segments", [])),
                "raw": route
            }
    except Exception as e:
        print(f"Transit Route Error: {e}")
        
    return None

def get_driving_route(origin_lon, origin_lat, dest_lon, dest_lat, key):
    """
    Get Driving steps from Amap Web API v3.
    Use as fallback for long distances where walking is impossible and transit fails.
    """
    origin = f"{origin_lon},{origin_lat}"
    destination = f"{dest_lon},{dest_lat}"
    url = "https://restapi.amap.com/v3/direction/driving"
    params = {
        "origin": origin,
        "destination": destination,
        "key": key,
        "strategy": 0,
        "extensions": "all",
    }
    
    try:
        res = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS).json()
        if res['status'] == '1' and res['route']['paths']:
            path = res['route']['paths'][0]
            distance = int(path['distance'])
            duration = int(path['duration']) // 60
            
            steps = []
            for step in path['steps']:
                steps.append(f"驾驶: {step['instruction']}")
            
            return {
                "type": "driving",
                "distance_m": distance,
                "duration_min": duration,
                "cost": 0, # Driving usually has no ticket cost (except tolls, but simplified here)
                "steps": steps,
                "polyline": _collect_polylines(path.get("steps", [])),
                "raw": path
            }
    except Exception as e:
        print(f"Driving Route Error: {e}")
    return None

def get_regeo_city(lon, lat, key):
    """
    Get city code from coordinates (Regeo).
    Critical for Transit API which requires an origin city.
    """
    location = f"{lon},{lat}"
    url = "https://restapi.amap.com/v3/geocode/regeo"
    params = {"location": location, "key": key, "radius": 100, "extensions": "base"}
    try:
        res = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS).json()
        if res['status'] == '1':
            component = res["regeocode"]["addressComponent"]
            return (
                component.get("citycode")
                or component.get("adcode")
                or component.get("city")
                or ""
            )
    except Exception as e:
        print(f"Get City Code Error: {e}")
    return ""
