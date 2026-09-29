"""Optional address enrichment for the legacy discovery search.

Personal Trip transport is evaluated in core.trip_transport, not by AMap.
"""

import requests

REQUEST_TIMEOUT_SECONDS = 5
REGEOCODE_URL = "https://restapi.amap.com/v3/geocode/regeo"


def get_address_from_coords(lon, lat, key):
    """Return a formatted address when available, otherwise the source coordinates."""
    fallback = f"{lat:.5f}, {lon:.5f}"
    if not key:
        return fallback
    try:
        result = requests.get(
            REGEOCODE_URL,
            params={"location": f"{lon},{lat}", "key": key,
                    "radius": 100, "extensions": "base"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        ).json()
        if result.get("status") == "1":
            return result["regeocode"]["formatted_address"]
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        pass
    return fallback


def get_regeo_city(lon, lat, key):
    """Return a city code used to describe a search result, if available."""
    if not key:
        return ""
    try:
        result = requests.get(
            REGEOCODE_URL,
            params={"location": f"{lon},{lat}", "key": key,
                    "radius": 100, "extensions": "base"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        ).json()
        if result.get("status") == "1":
            component = result["regeocode"]["addressComponent"]
            return (component.get("citycode") or component.get("adcode")
                    or component.get("city") or "")
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        pass
    return ""
