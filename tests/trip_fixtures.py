"""Small Tokyo-like catalog and Trip plan shared by acceptance tests."""

from core.trip import empty_plan, new_requirements, stop_spec, validate_plan


CATALOG = {
    "anime": [{"id": "work", "name": "Test work"}],
    "locations": [
        {"id": "a", "name": "A", "lat": 35.66, "lon": 139.70, "anime_ids": ["work"],
         "destination_id": "tokyo", "scene_ids": [],
         "access": {"status": "public", "checked_at": "2026-09-29"}},
        {"id": "b", "name": "B", "lat": 35.661, "lon": 139.701, "anime_ids": ["work"],
         "destination_id": "tokyo", "scene_ids": [],
         "access": {"status": "public", "checked_at": "2026-09-29"}},
        {"id": "c", "name": "C", "lat": 35.662, "lon": 139.702, "anime_ids": ["work"],
         "destination_id": "tokyo", "scene_ids": [],
         "access": {"status": "public", "checked_at": "2026-09-29"}},
    ],
    "scenes": [], "routes": [],
}


def plan_for(mode="walk", *, anchored=True):
    req = new_requirements("2026-10-01", 1, anime_ids=["work"])
    req["mode"] = mode
    plan = empty_plan(req)
    day = plan["days"][0]
    if anchored:
        anchor = {"name": "A", "location_id": "a", "lat": None, "lon": None, "confirmed": True}
        day["start"] = dict(anchor)
        day["end"] = dict(anchor)
    day["stops"] = [stop_spec("b"), stop_spec("c")]
    return validate_plan(plan)
