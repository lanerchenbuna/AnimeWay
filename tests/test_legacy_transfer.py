"""Existing backpack users can retain their places without the route-size limit."""
from copy import deepcopy

from components.legacy_transfer import transfer_backpack, wishlist_point
from core.private_store import PrivateStore


def test_transfer_keeps_backpack_deduplicates_and_preserves_more_than_twelve(tmp_path):
    store = PrivateStore(tmp_path / "private.db")
    token, other = store.new_identity(), store.new_identity()
    initial = [{"id": f"prior-{i}", "name": f"Prior {i}", "lat": 35.6, "lon": 139.7} for i in range(13)]
    for point in initial:
        store.add_wishlist(token, point)
    points = [{"id": "a592d0d101934baa3379a97ff7ca667adf546961", "name": "新宿駅南口", "lat": 35.69, "lon": 139.7, "_city": "高山市"},
              {"name": "自选地点", "lat": 35.65, "lon": 139.68, "source_url": None},
              {"name": "坏坐标", "lat": None, "lon": 139.7}]
    before = deepcopy(points)
    assert transfer_backpack(store, token, points) == (2, 1)
    assert transfer_backpack(store, token, points) == (0, 1)
    assert points == before
    saved = store.list_wishlist(token)
    assert len(saved) == 15
    assert next(item for item in saved if item["id"] == "loc-tokyo-shinjuku-south")["city"] == "东京都"
    assert not store.list_wishlist(other)


def test_custom_places_receive_stable_identity_without_exposing_keys():
    point = {"name": "自选地点", "lat": 35.65, "lon": 139.68}
    assert wishlist_point(point)["id"] == wishlist_point(deepcopy(point))["id"]
    assert wishlist_point({**point, "lon": 139.69})["id"] != wishlist_point(point)["id"]
