from components import state


def test_append_message_uses_stable_structured_schema(monkeypatch):
    session_state = {"messages": []}
    monkeypatch.setattr(state.st, "session_state", session_state)

    message = state.append_message(
        "assistant",
        "找到结果",
        structured_result={"mode": "search_spots"},
        retrieval_context=[{"anime": "孤独摇滚！", "spots_count": 10}],
    )

    assert message["message_id"]
    assert message["role"] == "assistant"
    assert message["structured_result"]["mode"] == "search_spots"
    assert message["retrieval_context"][0]["anime"] == "孤独摇滚！"
    assert message["created_at"]
    assert message["feedback"] is None


def test_itinerary_limit_prevents_unbounded_tsp_input(monkeypatch):
    itinerary = [
        {"_local_id": f"{index}_old", "id": str(index), "name": "old"}
        for index in range(state.MAX_ITINERARY_ITEMS)
    ]
    session_state = {
        "itinerary": itinerary,
        "planned_routes": None,
        "optimized_points": [],
    }
    messages = []
    monkeypatch.setattr(state.st, "session_state", session_state)
    monkeypatch.setattr(state.st, "toast", messages.append)
    monkeypatch.setattr(
        state.st,
        "rerun",
        lambda: (_ for _ in ()).throw(AssertionError("full backpack must not rerun")),
    )

    state.add_to_itinerary({"id": "new", "name": "new"}, "test")

    assert len(session_state["itinerary"]) == state.MAX_ITINERARY_ITEMS
    assert "最多保存" in messages[0]
