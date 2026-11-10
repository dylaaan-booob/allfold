"""Multiplex independent native operations over one authenticated connection.

A lost result does not establish native settlement. Pending saves are never replayed.
"""
from __future__ import annotations

import asyncio
import hmac
import re
import threading
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect

from allfold.application.browser_runtime import ElectronDisconnected
from allfold.application.history import observe
from allfold.browser_diagnostics import normalize_browser_diagnostic
from allfold.identifiers import valid_doi
from allfold.integrations.cloudflare_solver import solve_cloudflare


_CONTROL_ACTIONS = {"diagnostics_reset", "cas_credentials", "zotero_local"}
_CONTEXT_FIELDS = ("workflow_id", "task_id", "parent_task_id", "service_id", "paper_id")
_SOCKET_ERRORS = (WebSocketDisconnect, OSError, RuntimeError)
_RECEIVE_ERRORS = (*_SOCKET_ERRORS, ValueError, TimeoutError)


@dataclass
class _Operation:
    id: str
    action: str
    result: asyncio.Future[dict]
    progress: Callable | None
    context: dict
    import_identity: dict | None
    stop: threading.Event = field(default_factory=threading.Event)
    challenges: dict[str, threading.Event] = field(default_factory=dict)
    lookup_requested: bool = False

    def stop_callbacks(self) -> None:
        self.stop.set()
        for stop in self.challenges.values():
            stop.set()

    def envelope(self, message_type, **fields) -> dict:
        return {"type": message_type, "id": self.id, "action": self.action, **fields}


class ElectronBridge:
    def __init__(self, token: str, authority: str, *, cdp_url: str = "", diagnostics=None, openalex_pdf=None):
        self.diagnostics = diagnostics
        self.openalex_pdf = openalex_pdf
        self._token = token
        self._authority = authority
        self._cdp_url = cdp_url
        self._socket: WebSocket | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: dict[str, _Operation] = {}
        # The Pydoll adapter temporarily suppresses its process-wide raw logging.
        self._solver_slot = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self.closing = False
        self.shutdown = None

    @property
    def connected(self) -> bool:
        return self._socket is not None and not self.closing

    async def _send(self, socket: WebSocket, message: dict) -> None:
        async with self._send_lock:
            await socket.send_json(message)

    async def connect(self, socket: WebSocket) -> None:
        if (self._socket is not None or self._pending or self.closing
                or socket.headers.get("host") != self._authority
                or socket.headers.get("origin") is not None):
            await socket.close(code=1008)
            return
        await socket.accept()
        drain = None
        workers: set[asyncio.Task] = set()

        def start_worker(coroutine):
            task = asyncio.create_task(coroutine)
            workers.add(task)
            task.add_done_callback(workers.discard)

        try:
            hello = await asyncio.wait_for(socket.receive_json(), timeout=5)
            token = hello.get("token") if isinstance(hello, dict) else None
            if not isinstance(token, str) or not hmac.compare_digest(token, self._token):
                await socket.close(code=1008)
                return
            if self._socket is not None or self._pending or self.closing:
                await socket.close(code=1008)
                return
            self._socket, self._loop = socket, asyncio.get_running_loop()
            observe(self.diagnostics, "native_status", hello.get("diagnostics_status"))
            await self._send(socket, {"type": "ready", "log_level": getattr(self.diagnostics, "level", "info")})
            while True:
                message = await socket.receive_json()
                if not isinstance(message, dict):
                    raise ValueError("Invalid Electron message")
                kind = message.get("type")
                if kind == "shutdown":
                    if not self.closing:
                        self.closing = True
                        for pending in self._pending.values():
                            pending.stop_callbacks()
                        drain = asyncio.create_task(self._drain(socket))
                    continue
                request_id = message.get("id")
                pending = self._pending.get(request_id) if isinstance(request_id, str) else None
                if kind == "cancel_cloudflare":
                    challenge_id = message.get("challenge_id")
                    if (pending is not None and message.get("action") == pending.action
                            and isinstance(challenge_id, str)):
                        stop = pending.challenges.get(challenge_id)
                        if stop is not None:
                            stop.set()
                    continue
                if pending is None or message.get("action") != pending.action or pending.result.done():
                    raise ValueError("Stale Electron result")
                data = message.get("data")
                if not isinstance(data, dict):
                    raise ValueError("Invalid Electron data")
                if kind == "openalex_pdf":
                    expected = pending.import_identity
                    lookup_id = message.get("lookup_id")
                    if (self.openalex_pdf is None or expected is None or pending.lookup_requested
                            or not isinstance(lookup_id, str) or not re.fullmatch(r"[A-Za-z0-9]{1,64}", lookup_id)
                            or valid_doi(data.get("doi")) != expected["doi"]
                            or data.get("target") != expected["target"]
                            or not isinstance(data.get("parent_key"), str)
                            or not re.fullmatch(r"[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}", data["parent_key"])):
                        raise ValueError("Invalid OpenAlex Import request")
                    if not pending.stop.is_set():
                        pending.lookup_requested = True
                        start_worker(self._lookup_pdf(socket, pending, lookup_id, expected["doi"]))
                elif kind == "solve_cloudflare":
                    challenge_id = message.get("challenge_id")
                    url = data.get("url")
                    target_id = data.get("target_id")
                    if (not isinstance(challenge_id, str) or not re.fullmatch(r"[a-f0-9]{32}", challenge_id)
                            or not isinstance(url, str) or not url.startswith(("https://", "http://"))
                            or not isinstance(target_id, str) or not re.fullmatch(r"[A-Fa-f0-9]{32}", target_id)
                            or challenge_id in pending.challenges or pending.action in _CONTROL_ACTIONS):
                        raise ValueError("Invalid challenge request")
                    if not pending.stop.is_set():
                        stop = pending.challenges[challenge_id] = threading.Event()
                        start_worker(self._solve_cloudflare(socket, pending, challenge_id, url, target_id, stop))
                elif kind == "progress":
                    if pending.progress:
                        pending.progress(data)
                elif kind == "result":
                    self._observe_result(pending, data)
                    pending.stop_callbacks()
                    pending.result.set_result(data)
                else:
                    raise ValueError("Unexpected Electron message")
        except _RECEIVE_ERRORS:
            pass
        finally:
            if self._socket is socket:
                self._socket = None
                for pending in self._pending.values():
                    pending.stop_callbacks()
                    if pending.result.done():
                        continue
                    if pending.action not in _CONTROL_ACTIONS:
                        observe(self.diagnostics, "event", "bridge_disconnected", {
                            **pending.context, "code": "bridge_disconnected", "outcome": "uncertain"})
                        observe(self.diagnostics, "native_status", {"available": False, "incomplete": True})
                    if pending.progress:
                        pending.progress({"message": "Electron disconnected; waiting for application shutdown, no replay"})
            try:
                await socket.close()
            except _SOCKET_ERRORS:
                pass
            if workers:
                await asyncio.gather(*workers)
            if drain is not None:
                # Uvicorn waits for this socket handler before lifespan teardown.
                # Leave pending native results for teardown to mark uncertain once
                # Main has finished its escaped saves and stopped this process.
                if drain.cancel():
                    await asyncio.gather(drain, return_exceptions=True)
                else:
                    await drain

    def _observe_result(self, pending: _Operation, data: dict) -> None:
        if pending.action in _CONTROL_ACTIONS:
            return
        observe(self.diagnostics, "native_status", data.get("diagnostics_status"))
        diagnostic = normalize_browser_diagnostic(data.get("diagnostic")) or {}
        parent = data.get("parent")
        outcome = parent.get("outcome") if isinstance(parent, dict) else data.get("outcome")
        if outcome is None:
            outcome = ("failed" if diagnostic else "retrieved" if data.get("item") or data.get("image_base64")
                       else "downloaded" if data.get("filename") else "queried" if type(data.get("total")) is int
                       else "no_result")
        observe(self.diagnostics, "event", "task_finished", {**pending.context, **diagnostic, "outcome": outcome})

    async def _callback(self, socket, pending: _Operation, stop: threading.Event, message: dict) -> None:
        try:
            async with self._send_lock:
                if (not stop.is_set() and not pending.stop.is_set() and self._socket is socket
                        and self._pending.get(pending.id) is pending and not pending.result.done()):
                    await socket.send_json(message)
        except _SOCKET_ERRORS:
            pass

    async def _lookup_pdf(self, socket, pending: _Operation, lookup_id: str, doi: str) -> None:
        if pending.stop.is_set():
            return
        try:
            data = await asyncio.to_thread(self.openalex_pdf, doi)
        except Exception:
            data = {"candidates": [], "diagnostic": {"code": "openalex_lookup_failed"}}
        await self._callback(socket, pending, pending.stop, pending.envelope(
            "openalex_pdf_result", lookup_id=lookup_id, data=data))

    async def _solve_cloudflare(self, socket, pending: _Operation, challenge_id: str,
                                url: str, target_id: str, stop: threading.Event) -> None:
        try:
            # Wait off the receive loop. Holding the slot until the worker returns
            # prevents cleanup or logger restoration from crossing another solve.
            async with self._solver_slot:
                if stop.is_set():
                    return
                data = await asyncio.to_thread(solve_cloudflare, self._cdp_url, url, stop, target_id=target_id)
            await self._callback(socket, pending, stop, pending.envelope(
                "solve_cloudflare_result", challenge_id=challenge_id, data=data))
        finally:
            pending.challenges.pop(challenge_id, None)

    def finish_disconnected(self):
        """Process teardown calls this after Main has waited for native saves."""
        if self._socket is None:
            for pending in self._pending.values():
                if not pending.result.done():
                    pending.result.set_exception(ElectronDisconnected(
                        "Electron disconnected; inspect Zotero before retry"))

    async def _drain(self, socket: WebSocket):
        if self.shutdown:
            await self.shutdown()
        try:
            await self._send(socket, {"type": "shutdown_ready"})
        except _SOCKET_ERRORS:
            pass

    async def _execute(self, action: str, data: dict, progress: Callable | None) -> dict:
        socket = self._socket
        if socket is None or self.closing:
            raise ElectronDisconnected("Electron runtime is unavailable")
        request_id = uuid4().hex
        result = asyncio.get_running_loop().create_future()
        target = data.get("zotero_target")
        import_identity = ({"doi": valid_doi(data.get("doi")), "target": {
            key: target.get(key) for key in ("server_id", "library_type", "library_id", "collection_key")}}
            if action == "import_paper" and isinstance(target, dict) else None)
        context = {key: data[key] for key in _CONTEXT_FIELDS if key in data}
        scope = data.get("service_scope")
        if isinstance(scope, dict):
            context.update({key: scope[key] for key in ("config_revision", "user_state_revision") if key in scope})
        context.update(request_id=request_id, action=action)
        pending = self._pending[request_id] = _Operation(request_id, action, result, progress, context, import_identity)
        if action not in _CONTROL_ACTIONS:
            data = {**data, "log_level": getattr(self.diagnostics, "level", "info")}
            observe(self.diagnostics, "event", "task_started", context)
        try:
            try:
                await self._send(socket, pending.envelope("execute", data=data))
            except _SOCKET_ERRORS:
                # Dispatch may have reached Main. Trigger controlled teardown and
                # leave this request pending until native writes have drained.
                try:
                    await socket.close()
                except _SOCKET_ERRORS:
                    pass
            return await result
        finally:
            pending.stop_callbacks()
            self._pending.pop(request_id, None)

    def execute(self, action: str, data: dict, progress: Callable | None = None) -> Future[dict]:
        """Register from a business worker; await the result outside its stop mutex."""
        if self._loop is None:
            raise ElectronDisconnected("Electron has not connected")
        return asyncio.run_coroutine_threadsafe(self._execute(action, data, progress), self._loop)

    async def _cancel(self, workflow_id: str | None, task_id: str | None) -> bool:
        pending = [operation for operation in self._pending.values() if not operation.result.done()
                   and (workflow_id is None or operation.context.get("workflow_id") == workflow_id)
                   and (task_id is None or operation.context.get("task_id") == task_id)]
        for operation in pending:
            operation.stop_callbacks()
        socket = self._socket
        if socket is None:
            return False
        sent = False
        for operation in pending:
            if operation.result.done():
                continue
            try:
                await self._send(socket, operation.envelope("cancel"))
                sent = True
            except _SOCKET_ERRORS:
                break
        return sent

    def _schedule_cancel(self, workflow_id: str | None = None, task_id: str | None = None) -> Future[bool] | None:
        if self._loop is not None:
            return asyncio.run_coroutine_threadsafe(self._cancel(workflow_id, task_id), self._loop)
        return None

    def cancel_current(self) -> Future[bool] | None:
        """Stop every active request under the current Browser workflow owner."""
        return self._schedule_cancel()

    def cancel_workflow(self, workflow_id: str) -> Future[bool] | None:
        return self._schedule_cancel(workflow_id)

    def cancel_task(self, workflow_id: str, task_id: str) -> Future[bool] | None:
        return self._schedule_cancel(workflow_id, task_id)
