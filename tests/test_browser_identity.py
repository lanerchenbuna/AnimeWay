"""Storage handshakes are security and persistence behavior, not visual tests."""
import subprocess
from pathlib import Path

import pytest

from components import identity
from core.private_store import PrivateStore


@pytest.fixture
def identity_context(tmp_path, monkeypatch):
    store = PrivateStore(tmp_path / "private.sqlite3")
    state = {"locale": "zh_CN"}
    notices = []
    monkeypatch.setattr(identity.st, "session_state", state)
    monkeypatch.setattr(identity.st, "caption", notices.append)
    monkeypatch.setattr(identity.st, "warning", notices.append)
    return store, state, notices


def test_identity_is_not_ready_until_browser_answers(identity_context, monkeypatch):
    store, state, _ = identity_context
    monkeypatch.setattr(identity, "_identity_component", lambda **kwargs: None)
    assert identity.private_identity(store) is None
    assert store.has_identity(state["_aw_identity_candidate"])
    assert "aw_identity_token" not in state


def test_new_session_recovers_existing_browser_not_new_candidate(identity_context, monkeypatch):
    store, state, _ = identity_context
    existing = store.new_identity()
    monkeypatch.setattr(identity, "_identity_component", lambda **kwargs: {"token": existing, "persistent": True})
    assert identity.private_identity(store) == existing
    assert existing != state["_aw_identity_candidate"]
    assert state["aw_identity_persistent"] is True


def test_unavailable_browser_storage_is_disclosed(identity_context, monkeypatch):
    store, _, notices = identity_context
    monkeypatch.setattr(identity, "_identity_component", lambda **kwargs: {"token": kwargs["candidate"], "persistent": False})
    assert identity.private_identity(store)
    assert any("未允许" in item for item in notices)


def test_unknown_browser_token_is_not_accepted(identity_context, monkeypatch):
    store, state, _ = identity_context
    state.update(awj_private_note="private", awj_share_preview={"private": True}, awp_title="hotel")
    monkeypatch.setattr(identity, "_identity_component", lambda **kwargs: {"token": "A" * 43, "persistent": True})
    monkeypatch.setattr(identity.st, "rerun", lambda: (_ for _ in ()).throw(RuntimeError("rerun")))
    with pytest.raises(RuntimeError, match="rerun"):
        identity.private_identity(store)
    assert "aw_identity_token" not in state
    assert state["aw_identity_missing"] is True
    assert not any(key.startswith(("awj_", "awp_")) for key in state)


def test_switching_browser_identity_clears_private_navigation(identity_context, monkeypatch):
    store, state, _ = identity_context
    first, second = store.new_identity(), store.new_identity()
    state.update(aw_identity_token=first, aw_selected_trip="private-trip", aw_page="trip")
    monkeypatch.setattr(identity, "_identity_component", lambda **kwargs: {"token": second, "persistent": True})
    assert identity.private_identity(store) == second
    assert "aw_selected_trip" not in state
    assert state["aw_page"] == "discover"


def test_first_party_component_protocol():
    """Exercise the actual JS against a browser API double, not real storage."""
    import shutil

    if not shutil.which("node"):
        pytest.skip("Node is optional; browser validation exercises this component too")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", str(root / "scripts" / "test_identity_component.cjs")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
