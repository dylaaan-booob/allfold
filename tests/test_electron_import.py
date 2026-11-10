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
    return {"settled": True, "parent": {"outcome": "confirmed", "status": 200, "protocol": "local-api-v3",
        "requested_id": "ABCDEFGH", "accepted_id": "ABCDEFGH", "empty_response": False},
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


def test_latest_batch_observations_are_memory_only_and_recovered_pdf_has_no_final_failure(tmp_path):
    value, path = paper(tmp_path, "fixture")
    lock = BrowserTaskLock()
    bridge = Bridge()
    batch = BatchImportService(bridge, lock)
    batch.start(tmp_path, browser_owner=lock.acquire("kept"))
    assert bridge.dispatched.wait(2)
    result = {**confirmed(), "last_import": {"item_exists":True, "pdf_attached":True, "pdf_source":"openalex", "fallback_used":True, "query_diagnostic":None},
              "pdf":{"outcome":"unverified", "registered":True, "source":"openalex", "failures":[{"phase":"initial_fetch", "code":"http_error", "status":403}]},
              "zotero":{"parent_key":"ABCDEFGH"}}
    bridge.future.set_result(result)
    batch.join()
    observed = batch.snapshot().results[0]
    assert observed.item_exists is True and observed.pdf_attached is True
    assert observed.pdf_source == "openalex" and observed.fallback_used is True
    assert observed.diagnostic is None
    assert "ABCDEFGH" not in path.read_text() and "pdf_source" not in path.read_text()
    from allfold.application.history import batch_history
    assert "pdf_source" not in str(batch_history(batch.snapshot()))


def test_terminal_zotero_upload_failure_takes_priority_over_recovered_download_failure(tmp_path):
    from allfold.diagnostics import DiagnosticStore
    paper(tmp_path, 'fixture')
    lock, bridge = BrowserTaskLock(), Bridge()
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs')
    batch = BatchImportService(bridge, lock, diagnostics=store)
    owner = lock.acquire('kept')
    batch.start(tmp_path, browser_owner=owner)
    assert bridge.dispatched.wait(2)
    bridge.future.set_result({**confirmed(), 'stop_batch': True,
        'pdf': {'registered': False, 'failures': [
            {'phase': 'initial_fetch', 'code': 'http_error', 'status': 404},
            {'phase': 'attachment_save', 'code': 'authorization_required', 'status': 401}]},
        'last_import': {'item_exists': True, 'pdf_attached': False, 'pdf_source': 'none', 'fallback_used': False}})
    batch.join()
    observed = batch.snapshot().results[0]
    assert batch.snapshot().phase is BatchPhase.PAUSED
    assert observed.item_exists is True and observed.pdf_attached is False
    assert observed.diagnostic == {'stage': 'attachment', 'step': 'attachment_save',
        'code': 'authorization_required', 'status': 401}
    assert 'Zotero' in observed.reason and '401' in observed.reason and '404' not in observed.reason
    recorded = store.history()['records'][0]['details']['results'][0]
    assert recorded['diagnostic'] == observed.diagnostic
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


def test_openalex_subrequest_is_on_demand_and_bound_to_exact_import():
    calls = []
    target = {"server_id":"SERVERFIXTUR", "library_type":"user", "library_id":"0", "collection_key":None}
    bridge = ElectronBridge("secret", "testserver", openalex_pdf=lambda doi: calls.append(doi) or {"candidates":["https://oa.example/paper.pdf"]})
    app = FastAPI()
    app.websocket("/ws")(bridge.connect)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"token":"secret"})
            socket.receive_json()
            pending = bridge.execute("import_paper", {"doi":"10.5555/test", "zotero_target":target})
            request = socket.receive_json()
            assert calls == []
            socket.send_json({"type":"openalex_pdf", "id":request["id"], "action":"import_paper", "lookup_id":"lookup1",
                              "data":{"doi":"10.5555/test", "target":target, "parent_key":"ABCDEFGH"}})
            assert socket.receive_json() == {"type":"openalex_pdf_result", "id":request["id"], "action":"import_paper",
                "lookup_id":"lookup1", "data":{"candidates":["https://oa.example/paper.pdf"]}}
            socket.send_json({"type":"result", "id":request["id"], "action":"import_paper", "data":confirmed()})
            pending.result(timeout=2)
    assert calls == ["10.5555/test"]


@pytest.mark.parametrize("changed", [{"doi":"10.5555/other"}, {"parent_key":"../../file"}, {"target":{}}])
def test_openalex_rejects_wrong_doi_target_or_parent_without_query(changed):
    from starlette.websockets import WebSocketDisconnect
    calls = []
    target = {"server_id":"SERVERFIXTUR", "library_type":"user", "library_id":"0"}
    bridge = ElectronBridge("secret", "testserver", openalex_pdf=lambda doi: calls.append(doi) or {})
    app = FastAPI()
    app.websocket("/ws")(bridge.connect)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"token":"secret"}); socket.receive_json()
            bridge.execute("import_paper", {"doi":"10.5555/test", "zotero_target":target})
            request = socket.receive_json()
            socket.send_json({"type":"openalex_pdf", "id":request["id"], "action":"import_paper", "lookup_id":"one",
                "data":{"doi":"10.5555/test", "target":target, "parent_key":"ABCDEFGH", **changed}})
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
        client.portal.call(bridge.finish_disconnected)
    assert calls == []


@pytest.mark.parametrize("disconnect", [False, True])
def test_openalex_lookup_cannot_deliver_candidates_after_cancel_or_disconnect(disconnect):
    started, release = threading.Event(), threading.Event()
    def lookup(doi):
        started.set()
        assert release.wait(2)
        return {"candidates":["https://oa.example/private.pdf"]}
    target = {"server_id":"SERVERFIXTUR", "library_type":"user", "library_id":"0", "collection_key":None}
    bridge = ElectronBridge("secret", "testserver", openalex_pdf=lookup)
    app = FastAPI()
    app.websocket("/ws")(bridge.connect)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"token":"secret"}); socket.receive_json()
            pending = bridge.execute("import_paper", {"doi":"10.5555/test", "zotero_target":target})
            request = socket.receive_json()
            socket.send_json({"type":"openalex_pdf", "id":request["id"], "action":"import_paper", "lookup_id":"one",
                "data":{"doi":"10.5555/test", "target":target, "parent_key":"ABCDEFGH"}})
            assert started.wait(2)
            if disconnect:
                release.set()
                socket.close()
            else:
                bridge.cancel_current().result(timeout=2)
                assert socket.receive_json()["type"] == "cancel"
                release.set()
                socket.send_json({"type":"progress", "id":request["id"], "action":"import_paper", "data":{}})
                socket.send_json({"type":"result", "id":request["id"], "action":"import_paper", "data":confirmed()})
                assert pending.result(timeout=2) == confirmed()
        if disconnect:
            client.portal.call(bridge.finish_disconnected)
            with pytest.raises(ElectronDisconnected):
                pending.result(timeout=2)


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




def test_parallel_native_requests_route_progress_cancellation_and_settlement_independently():
    bridge = ElectronBridge("secret", "testserver")
    app = FastAPI()
    app.websocket("/ws")(bridge.connect)
    first_progress, second_progress = [], []
    with TestClient(app) as client, client.websocket_connect("/ws") as socket:
        socket.send_json({"token": "secret"})
        assert socket.receive_json()["type"] == "ready"
        first = bridge.execute("import_paper", {"workflow_id": "batch", "task_id": "first"}, first_progress.append)
        a = socket.receive_json()
        second = bridge.execute("import_paper", {"workflow_id": "batch", "task_id": "second"}, second_progress.append)
        bridge.cancel_task("batch", "first")
        b = socket.receive_json()
        assert b["type"] == "execute" and a["id"] != b["id"]
        assert socket.receive_json() == {"type": "cancel", "id": a["id"], "action": "import_paper"}
        for message, progress in ((b, "second saving"), (a, "first settling")):
            socket.send_json({"type": "progress", "id": message["id"], "action": message["action"],
                              "data": {"message": progress}})
        socket.send_json({"type": "result", "id": b["id"], "action": b["action"], "data": confirmed()})
        assert second.result(timeout=2) == confirmed()
        assert not first.done()
        assert first_progress == [{"message": "first settling"}]
        assert second_progress == [{"message": "second saving"}]
        socket.send_json({"type": "result", "id": a["id"], "action": a["action"],
                          "data": {"settled": True, "parent": {"outcome": "no_effect"}}})
        assert first.result(timeout=2)["parent"]["outcome"] == "no_effect"


def test_parallel_cloudflare_requests_keep_receiving_results_and_cancel_only_their_target(monkeypatch):
    first_started = threading.Event()
    first_stopped = threading.Event()
    targets = ("a" * 32, "b" * 32)
    calls = []

    def solve(_endpoint, url, stop, *, target_id):
        calls.append((url, target_id))
        if target_id == targets[0]:
            first_started.set()
            if stop.wait(2):
                first_stopped.set()
        return {"outcome": "clicked", "reason": "checkbox_clicked"}

    monkeypatch.setattr("allfold.web.electron_bridge.solve_cloudflare", solve)
    bridge = ElectronBridge("secret", "testserver")
    app = FastAPI()
    app.websocket("/ws")(bridge.connect)
    url = "https://fixture.example/challenge"
    with TestClient(app) as client, client.websocket_connect("/ws") as socket:
        socket.send_json({"token": "secret"})
        socket.receive_json()
        results, requests = [], []
        for task, target in zip(("first", "second"), targets):
            results.append(bridge.execute("prepare_service", {"workflow_id": "login", "task_id": task}))
            request = socket.receive_json()
            challenge = {"id": request["id"], "action": request["action"], "challenge_id": target}
            requests.append(challenge)
            socket.send_json({**challenge, "type": "solve_cloudflare", "data": {"url": url, "target_id": target}})
            assert first_started.wait(2)
        other = bridge.execute("prepare_service", {"workflow_id": "login", "task_id": "third"})
        other_request = socket.receive_json()
        socket.send_json({"type": "result", "id": other_request["id"], "action": other_request["action"],
                          "data": {"outcome": "Opened"}})
        assert other.result(timeout=2) == {"outcome": "Opened"}
        assert calls == [(url, targets[0])]
        assert bridge.cancel_task("login", "first").result(timeout=2)
        assert socket.receive_json() == {"type": "cancel", "id": requests[0]["id"], "action": "prepare_service"}
        assert first_stopped.wait(2)
        assert socket.receive_json() == {**requests[1], "type": "solve_cloudflare_result",
            "data": {"outcome": "clicked", "reason": "checkbox_clicked"}}
        assert calls == [(url, target) for target in targets]
        for result, request in zip(results, requests):
            socket.send_json({"type": "result", "id": request["id"], "action": request["action"],
                              "data": {"outcome": "Opened"}})
            assert result.result(timeout=2) == {"outcome": "Opened"}


def test_disconnect_holds_all_pending_native_saves_until_teardown():
    bridge = ElectronBridge("secret", "testserver")
    app = FastAPI()
    app.websocket("/ws")(bridge.connect)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"token": "secret"})
            socket.receive_json()
            results = []
            for task in ("first", "second"):
                results.append(bridge.execute("import_paper", {"workflow_id": "batch", "task_id": task}))
                assert socket.receive_json()["type"] == "execute"
        assert all(not result.done() for result in results)
        client.portal.call(bridge.finish_disconnected)
        for result in results:
            with pytest.raises(ElectronDisconnected):
                result.result(timeout=2)


@pytest.mark.parametrize('signal_before_disconnect', [False, True])
def test_disconnect_during_drain_settles_only_after_main_confirms_native_drain(signal_before_disconnect):
    import asyncio
    from fastapi import WebSocketDisconnect

    async def scenario():
        bridge = ElectronBridge("secret", "testserver")
        incoming, outgoing = asyncio.Queue(), asyncio.Queue()
        draining = asyncio.Event()

        class Socket:
            headers = {"host": "testserver"}

            async def accept(self):
                pass

            async def receive_json(self):
                message = await incoming.get()
                if message is None:
                    raise WebSocketDisconnect()
                return message

            async def send_json(self, message):
                await outgoing.put(message)

            async def close(self, code=1000):
                pass

        async def drain():
            draining.set()
            # A normal drain waits for the native result. Once transport is
            # lost, process teardown must own the remaining settlement.
            await asyncio.shield(asyncio.wrap_future(result))

        await incoming.put({"token": "secret"})
        bridge.shutdown = drain
        connection = asyncio.create_task(bridge.connect(Socket()))
        assert (await asyncio.wait_for(outgoing.get(), 1))["type"] == "ready"
        result = bridge.execute("import_paper", {"workflow_id": "batch", "task_id": "paper"})
        assert (await asyncio.wait_for(outgoing.get(), 1))["type"] == "execute"
        await incoming.put({"type": "shutdown"})
        await asyncio.wait_for(draining.wait(), 1)
        if signal_before_disconnect:
            bridge.native_drained()
            await asyncio.sleep(0)
            assert not result.done()
        await incoming.put(None)
        await asyncio.wait_for(connection, 1)
        if not signal_before_disconnect:
            assert not result.done()
            bridge.native_drained()
        with pytest.raises(ElectronDisconnected):
            await asyncio.wait_for(asyncio.wrap_future(result), 1)

    asyncio.run(scenario())
