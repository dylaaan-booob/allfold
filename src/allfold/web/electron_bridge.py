"""Multiplex independent native operations over one authenticated connection.

A lost result does not establish native settlement. Pending saves are never replayed.
"""
from __future__ import annotations

import asyncio
import hmac
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect

from allfold.application.browser_runtime import ElectronDisconnected
from allfold.application.history import observe
from allfold.browser_diagnostics import normalize_browser_diagnostic
from allfold.recovery_diagnostics import normalize_recovery, normalize_recovery_action
from allfold.integrations.cloudflare_solver import solve_cloudflare


_CONTROL_ACTIONS = {"diagnostics_reset", "cas_credentials"}
_RESOURCE_ACTIONS = {"invalidate_access", "release_workflow_pages"}
_BUSINESS_ACTIONS = {"login_carsi", "prepare_service", "visit_manual_service", "search_journal_cover", "wos_query", "wos_export", "invalidate_access", "release_workflow_pages", "extract_paper_metadata", "extract_paper_pdf_clues"}
_RECOVERY_ACTIONS = {"prepare_service", "extract_paper_metadata", "extract_paper_pdf_clues"}
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
    verify_recovery: Callable[[], None] | None
    stop: threading.Event = field(default_factory=threading.Event)
    challenges: dict[str, threading.Event] = field(default_factory=dict)
    recovery_check: asyncio.Task | None = None

    def stop_callbacks(self) -> None:
        self.stop.set()
        for stop in self.challenges.values():
            stop.set()

    def envelope(self, message_type, **fields) -> dict:
        return {"type": message_type, "id": self.id, "action": self.action, **fields}


class ElectronBridge:
    def __init__(self, token: str, authority: str, *, cdp_url: str = "", diagnostics=None):
        self.diagnostics = diagnostics
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
        self._native_drained = False
        self.shutdown = None
        self.access_pages_closed = None
        self.page_limits = None

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
            return task

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
            limits = self.page_limits() if self.page_limits else None
            await self._send(socket, {"type": "ready", "log_level": getattr(self.diagnostics, "level", "info"),
                **({'page_limits': limits} if limits is not None else {})})
            while True:
                message = await socket.receive_json()
                if not isinstance(message, dict):
                    raise ValueError("Invalid Electron message")
                kind = message.get("type")
                if kind == 'access_pages_closed':
                    pages = message.get('page_ids')
                    if (set(message) != {'type', 'page_ids'} or not isinstance(pages, list)
                            or not 1 <= len(pages) <= 256
                            or any(type(page) is not int or page <= 0 for page in pages)
                            or len(pages) != len(set(pages))):
                        raise ValueError('Invalid access Page closure')
                    if self.access_pages_closed:
                        self.access_pages_closed(pages)
                    continue
                if kind == "shutdown":
                    if not self.closing:
                        self.closing = True
                        for pending in self._pending.values():
                            pending.stop_callbacks()
                        drain = asyncio.create_task(self._drain(socket, workers))
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
                if kind == "solve_cloudflare":
                    challenge_id = message.get("challenge_id")
                    url = data.get("url")
                    target_id = data.get("target_id")
                    deadline_ms = data.get("deadline_ms")
                    if (not isinstance(challenge_id, str) or not re.fullmatch(r"[a-f0-9]{32}", challenge_id)
                            or not isinstance(url, str) or not url.startswith(("https://", "http://"))
                            or not isinstance(target_id, str) or not re.fullmatch(r"[A-Fa-f0-9]{32}", target_id)
                            or type(deadline_ms) is not int or deadline_ms <= 0
                            or challenge_id in pending.challenges or pending.action in _CONTROL_ACTIONS):
                        raise ValueError("Invalid challenge request")
                    if not self.closing and not pending.stop.is_set():
                        stop = pending.challenges[challenge_id] = threading.Event()
                        start_worker(self._solve_cloudflare(socket, pending, challenge_id, url, target_id, stop, deadline_ms))
                elif kind == "verify_recovery_authority":
                    check_id = message.get("check_id")
                    if (pending.action not in _RECOVERY_ACTIONS or data
                            or not isinstance(check_id, str) or not re.fullmatch(r"[a-f0-9]{32}", check_id)):
                        raise ValueError("Invalid recovery authority request")
                    if not pending.stop.is_set():
                        if pending.recovery_check and not pending.recovery_check.done():
                            await self._callback(socket, pending, pending.stop, pending.envelope(
                                "verify_recovery_authority_result", check_id=check_id, data={"allowed": False}))
                        else:
                            pending.recovery_check = start_worker(self._verify_recovery(socket, pending, check_id))
                elif kind == "progress":
                    if pending.progress:
                        if "recovery_action" in data:
                            data = {**data, "recovery_action": normalize_recovery_action(data["recovery_action"])}
                        pending.progress(data)
                elif kind == "result":
                    if 'recovery' in data:
                        data = {**data, 'recovery': normalize_recovery(data['recovery'])}
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
                if self._native_drained:
                    self.finish_disconnected()
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

    async def _verify_recovery(self, socket, pending: _Operation, check_id: str) -> None:
        allowed = False
        try:
            if pending.verify_recovery is not None and not pending.stop.is_set():
                await asyncio.to_thread(pending.verify_recovery)
                allowed = True
        except Exception:
            pass
        pending.recovery_check = None
        await self._callback(socket, pending, pending.stop, pending.envelope(
            "verify_recovery_authority_result", check_id=check_id, data={"allowed": allowed}))

    async def _solve_cloudflare(self, socket, pending: _Operation, challenge_id: str,
                                url: str, target_id: str, stop: threading.Event, deadline_ms: int) -> None:
        timer = asyncio.get_running_loop().call_later(max(0, deadline_ms / 1000 - time.time()), stop.set)
        try:
            # Wait off the receive loop. Holding the slot until the worker returns
            # prevents cleanup or logger restoration from crossing another solve.
            async with self._solver_slot:
                if stop.is_set() or pending.stop.is_set() or time.time() * 1000 >= deadline_ms:
                    return
                worker = asyncio.create_task(asyncio.to_thread(solve_cloudflare, self._cdp_url, url, stop, target_id=target_id))
                try:
                    data = await asyncio.shield(worker)
                except asyncio.CancelledError:
                    stop.set()
                    await worker  # The application slot belongs to the actual thread until cleanup ends.
                    raise
            await self._callback(socket, pending, stop, pending.envelope(
                "solve_cloudflare_result", challenge_id=challenge_id, data=data))
        finally:
            timer.cancel()
            pending.challenges.pop(challenge_id, None)

    def native_drained(self):
        """Main's fallback shutdown confirms that no issued native write is still active."""
        def confirm():
            self.closing = True
            self._native_drained = True
            self.finish_disconnected()

        if self._loop is not None:
            self._loop.call_soon_threadsafe(confirm)

    def finish_disconnected(self):
        """Process teardown calls this after Main has waited for native saves."""
        if self._socket is None:
            for pending in self._pending.values():
                if not pending.result.done():
                    pending.result.set_exception(ElectronDisconnected(
                        "Electron disconnected; operation result is unconfirmed"))

    async def _drain(self, socket: WebSocket, workers: set[asyncio.Task]):
        if self.shutdown:
            await self.shutdown()
        if workers:
            await asyncio.gather(*workers)
        try:
            await self._send(socket, {"type": "shutdown_ready"})
        except _SOCKET_ERRORS:
            pass

    async def _execute(self, action: str, data: dict, progress: Callable | None, verify_recovery: Callable | None) -> dict:
        if action not in _CONTROL_ACTIONS | _BUSINESS_ACTIONS:
            raise ValueError('Unsupported native operation')
        if action in {'extract_paper_metadata', 'extract_paper_pdf_clues'} and (
                not isinstance(data, dict) or action == 'extract_paper_metadata' and type(data.get('wantAbstract')) is not bool
                or action == 'extract_paper_pdf_clues' and 'wantAbstract' in data
                or type(data.get('deadline_ms')) is not int or data['deadline_ms'] <= 0):
            raise ValueError('Invalid native extraction parameters')
        socket = self._socket
        # Normal exit closes execution admission first. Captured owners still
        # need this same authenticated receive loop to settle their resources.
        if socket is None or self.closing and action not in _RESOURCE_ACTIONS:
            raise ElectronDisconnected("Electron runtime is unavailable")
        request_id = uuid4().hex
        result = asyncio.get_running_loop().create_future()
        context = {key: data[key] for key in _CONTEXT_FIELDS if key in data}
        scope = data.get("service_scope")
        if isinstance(scope, dict):
            context.update({key: scope[key] for key in ("config_revision", "user_state_revision") if key in scope})
        context.update(request_id=request_id, action=action)
        pending = self._pending[request_id] = _Operation(request_id, action, result, progress, context, verify_recovery)
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
            if pending.recovery_check is not None:
                # Its read may still use the Coordinator's held Workspace descriptor.
                await pending.recovery_check
            self._pending.pop(request_id, None)

    def execute(self, action: str, data: dict, progress: Callable | None = None, *,
                verify_recovery: Callable[[], None] | None = None) -> Future[dict]:
        """Register from a business worker; await the result outside its stop mutex."""
        if self._loop is None:
            raise ElectronDisconnected("Electron has not connected")
        return asyncio.run_coroutine_threadsafe(self._execute(action, data, progress, verify_recovery), self._loop)

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

    def _schedule_cancel(self, workflow_id: str, task_id: str | None = None) -> Future[bool] | None:
        if self._loop is not None:
            return asyncio.run_coroutine_threadsafe(self._cancel(workflow_id, task_id), self._loop)
        return None

    def cancel_workflow(self, workflow_id: str) -> Future[bool] | None:
        return self._schedule_cancel(workflow_id)

    def cancel_task(self, workflow_id: str, task_id: str) -> Future[bool] | None:
        return self._schedule_cancel(workflow_id, task_id)

    def refresh_page_limits(self) -> Future[None] | None:
        async def refresh():
            socket = self._socket
            if socket is not None and not self.closing and self.page_limits:
                await self._send(socket, {'type': 'page_limits', 'page_limits': self.page_limits()})
        if self._loop is not None:
            return asyncio.run_coroutine_threadsafe(refresh(), self._loop)
        return None
