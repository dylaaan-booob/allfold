"""Isolated native-save, request-authority and settlement safety checks."""
from concurrent.futures import Future
import threading
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from allfold.application.batch_import import BatchImportService
from allfold.application.batch_import import BatchPhase
from allfold.application.export_attempts import (
    _reserve_export_attempt_locked, complete_electron_import, ExportCompletionOutcome,
)
from allfold.persistence.safe_write import workspace_operation_lock
from allfold.application.browser_runtime import BrowserTaskLock
from allfold.web.electron_bridge import ElectronBridge, ElectronDisconnected
from electron_test_helpers import paper, state, edit


def confirmed():
    return {"settled": True, "parent": {"outcome": "confirmed", "status": 201,
        "requested_id": "native-parent", "accepted_id": "native-parent", "empty_response": False},
        "pdf": {"outcome": "unverified"}}


class Bridge:
    connected = True
    def __init__(self):
        self.future = Future()
        self.dispatched = threading.Event()
        self.calls = []
        self.cancels = 0
    def execute(self, action, data, progress=None):
        self.calls.append((action, data))
        self.dispatched.set()
        return self.future

    def cancel_current(self):
        self.cancels += 1


@pytest.mark.parametrize("result,outcome", [(confirmed(), "EXPORTED"),
    ({"settled": True,"parent":{"outcome":"uncertain"}}, "UNCERTAIN"),
    ({"settled": True,"parent":{"outcome":"no_effect"}}, "NO_EFFECT")])
def test_parent_acceptance_and_cas(tmp_path, result, outcome):
    value, path = paper(tmp_path, "fixture")
    original = path.read_text()
    with workspace_operation_lock(tmp_path) as lock:
        reservation = _reserve_export_attempt_locked(lock, value.id)
        completed = complete_electron_import(reservation, result, operation_lock=lock)
    assert completed.outcome.value == outcome
    if outcome == "EXPORTED":
        assert state(path).status.value == "exported"
        assert state(path).body == state_from_text(path, original).body
    else:
        assert path.read_text() == original


def state_from_text(path, text):
    from allfold.persistence.markdown_state import parse_paper_state
    return parse_paper_state(path, text)


def test_accepted_parent_cannot_overwrite_a_changed_paper(tmp_path):
    value, path = paper(tmp_path, "fixture")
    with workspace_operation_lock(tmp_path) as lock:
        reservation = _reserve_export_attempt_locked(lock, value.id)
        edit(path, title="Human edit")
        edited = path.read_bytes()
        result = complete_electron_import(reservation, confirmed(), operation_lock=lock)
    assert result.outcome is ExportCompletionOutcome.FAILED
    assert path.read_bytes() == edited


def test_cancel_retains_workspace_and_browser_owner_until_current_save_settles(tmp_path):
    _, path = paper(tmp_path, "a")
    paper(tmp_path, "b")
    lock = BrowserTaskLock()
    owner = lock.acquire("kept")
    bridge = Bridge()
    batch = BatchImportService(bridge, lock)
    batch.start(tmp_path, browser_owner=owner)
    assert bridge.dispatched.wait(2)
    batch.stop()
    assert bridge.cancels == 1
    assert batch.running and lock.owner is owner
    with pytest.raises(RuntimeError):
        with workspace_operation_lock(tmp_path):
            pass
    bridge.future.set_result(confirmed())
    batch.join()
    assert state(path).status.value == "exported"
    assert batch.snapshot().phase is BatchPhase.STOPPED
    assert len(bridge.calls) == 1
    action, data = bridge.calls[0]
    assert action == "import_paper"
    assert data["metadata"]["doi"] == data["doi"]
    assert data["metadata"]["title"] == state(path).title
    assert set(data["metadata"]) <= {"doi", "title", "journal", "abstract", "publication_date", "authors", "journal_issns"}
    assert lock.owner is owner  # Only the top-level workflow releases it.
    lock.release(owner)


def test_disconnect_stops_batch_without_replaying_or_changing_papers(tmp_path):
    _, a = paper(tmp_path, "a")
    _, b = paper(tmp_path, "b")
    before = [a.read_bytes(), b.read_bytes()]
    lock = BrowserTaskLock()
    bridge = Bridge()
    batch = BatchImportService(bridge, lock)
    batch.start(tmp_path, browser_owner=lock.acquire("kept"))
    assert bridge.dispatched.wait(2)
    bridge.future.set_exception(ElectronDisconnected("lost"))
    batch.join()
    assert batch.snapshot().phase is BatchPhase.PAUSED
    assert len(bridge.calls) == 1
    assert [a.read_bytes(), b.read_bytes()] == before


def test_one_authenticated_socket_matches_a_single_request():
    bridge = ElectronBridge("secret", "testserver")
    app = FastAPI()
    app.websocket("/ws")(bridge.connect)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"token": "secret"})
            assert socket.receive_json()["type"] == "ready"
            pending = bridge.execute("import_paper", {"doi": "10.5555/test"})
            request = socket.receive_json()
            socket.send_json({"type": "progress", "id": request["id"], "action": request["action"], "data": {"message": "saving"}})
            socket.send_json({"type": "result", "id": request["id"], "action": request["action"], "data": confirmed()})
            assert pending.result(timeout=2) == confirmed()


def test_cancel_message_is_bound_to_pending_request_and_keeps_ownership_until_result():
    bridge = ElectronBridge("secret", "testserver")
    app = FastAPI()
    app.websocket("/ws")(bridge.connect)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"token": "secret"})
            assert socket.receive_json()["type"] == "ready"
            pending = bridge.execute("import_paper", {"doi": "10.5555/test"})
            request = socket.receive_json()
            cancellation = bridge.cancel_current()
            assert socket.receive_json() == {"type": "cancel", "id": request["id"], "action": request["action"]}
            assert cancellation.result(timeout=2) is True
            assert not pending.done()
            result = {"settled": True, "parent": {"outcome": "no_effect"},
                      "diagnostic": {"stage": "navigation", "code": "canceled"}}
            socket.send_json({"type": "result", "id": request["id"], "action": request["action"], "data": result})
            assert pending.result(timeout=2) == result
            assert bridge.cancel_current().result(timeout=2) is False


def test_socket_disconnect_makes_the_current_save_uncertain():
    bridge = ElectronBridge("secret", "testserver")
    app = FastAPI()
    app.websocket("/ws")(bridge.connect)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"token": "secret"})
            socket.receive_json()
            pending = bridge.execute("import_paper", {"doi": "10.5555/test"})
            socket.receive_json()
        assert not pending.done()  # A lost socket cannot prove native settlement.
        client.portal.call(bridge.finish_disconnected)
        with pytest.raises(ElectronDisconnected):
            pending.result(timeout=2)


def test_socket_refuses_a_web_origin_and_wrong_bootstrap_token():
    from starlette.websockets import WebSocketDisconnect
    bridge = ElectronBridge("secret", "testserver")
    app = FastAPI()
    app.websocket("/ws")(bridge.connect)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws", headers={"origin":"https://example.org"}):
                pass
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"token":"wrong"})
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()


@pytest.mark.parametrize("first,expected_calls,phase", [
    ({"settled": True, "parent": {"outcome": "no_effect"},
      "diagnostic": {"stage": "translation", "code": "http_error", "status": 403}}, 2, BatchPhase.COMPLETED),
    ({"settled": True, "parent": {"outcome": "uncertain"}}, 1, BatchPhase.PAUSED),
])
def test_batch_continues_only_after_known_no_effect(tmp_path, first, expected_calls, phase):
    paper(tmp_path, "a")
    paper(tmp_path, "b")
    class ImmediateBridge:
        connected = True
        calls = 0
        def execute(self, *args):
            self.calls += 1
            result = Future()
            result.set_result(first if self.calls == 1 else confirmed())
            return result
    bridge = ImmediateBridge()
    lock = BrowserTaskLock()
    batch = BatchImportService(bridge, lock)
    batch.start(tmp_path, browser_owner=lock.acquire("kept"))
    batch.join()
    assert bridge.calls == expected_calls
    assert batch.snapshot().phase is phase
    if phase is BatchPhase.COMPLETED:
        assert "1 imported, 1 not imported" in batch.snapshot().message
        assert "Official Translator: HTTP request failed (HTTP 403)" in batch.snapshot().results[0].reason
        batch.clear_terminal()
        assert batch.snapshot().phase is BatchPhase.IDLE
        assert not batch.snapshot().results


