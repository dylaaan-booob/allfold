"""One authenticated Electron connection and one in-flight browser operation.

No operation is replayed on disconnection. In particular a native save with a
lost result is uncertain, even if the remote operation happened to finish.
"""
from __future__ import annotations
import asyncio
import hmac
import threading
from collections.abc import Callable
from uuid import uuid4
from concurrent.futures import Future
from fastapi import WebSocket, WebSocketDisconnect
from allfold.integrations.cloudflare_solver import solve_cloudflare
from allfold.application.browser_runtime import ElectronDisconnected


class ElectronBridge:
    def __init__(self, token: str, authority: str, *, cdp_url: str = ""):
        self._token = token
        self._authority = authority
        self._cdp_url = cdp_url
        self._socket: WebSocket | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: tuple[str, str, asyncio.Future, Callable | None] | None = None
        self._challenge_stop: tuple[tuple, str, threading.Event] | None = None
        self.closing = False
        self.shutdown = None

    @property
    def connected(self) -> bool:
        return self._socket is not None and not self.closing

    async def connect(self, socket: WebSocket) -> None:
        if (self._socket is not None or self._pending is not None or self.closing
                or socket.headers.get("host") != self._authority
                or socket.headers.get("origin") is not None):
            await socket.close(code=1008)
            return
        await socket.accept()
        task = None
        challenge_task = None
        try:
            hello = await asyncio.wait_for(socket.receive_json(), timeout=5)
            token = hello.get("token") if isinstance(hello, dict) else None
            if not isinstance(token, str) or not hmac.compare_digest(token, self._token):
                await socket.close(code=1008)
                return
            # Recheck after handshake to avoid two simultaneous clients winning.
            if self._socket is not None:
                await socket.close(code=1008)
                return
            self._socket, self._loop = socket, asyncio.get_running_loop()
            await socket.send_json({"type": "ready"})
            while True:
                message = await socket.receive_json()
                if not isinstance(message, dict):
                    raise ValueError("Invalid Electron message")
                if message.get("type") == "shutdown":
                    if self._challenge_stop is not None:
                        self._challenge_stop[2].set()
                    if not self.closing:
                        self.closing = True
                        task = asyncio.create_task(self._drain(socket))
                    continue
                if message.get("type") == "cancel_cloudflare":
                    challenge = self._challenge_stop
                    if (challenge is not None and message.get("id") == challenge[0][0]
                            and message.get("action") == challenge[0][1]
                            and message.get("challenge_id") == challenge[1]):
                        challenge[2].set()
                    continue
                pending = self._pending
                if (pending is None or message.get("id") != pending[0]
                        or message.get("action") != pending[1]):
                    raise ValueError("Stale Electron result")
                data = message.get("data")
                if not isinstance(data, dict):
                    raise ValueError("Invalid Electron data")
                if message.get("type") == "solve_cloudflare":
                    challenge_id = message.get("challenge_id")
                    url = data.get("url")
                    if (not isinstance(challenge_id, str) or not challenge_id
                            or not isinstance(url, str) or not url):
                        raise ValueError("Invalid challenge request")
                    if challenge_task is not None and not challenge_task.done():
                        if self._challenge_stop is not None and not self._challenge_stop[2].is_set():
                            raise ValueError("Concurrent challenge request")
                    stop = threading.Event()
                    self._challenge_stop = pending, challenge_id, stop
                    if challenge_task is not None and not challenge_task.done():
                        # Await the actual worker, including cleanup; canceling to_thread is insufficient.
                        await challenge_task
                    if self._pending is not pending or pending[2].done() or self.closing or stop.is_set():
                        stop.set()
                        if self._challenge_stop is not None and self._challenge_stop[2] is stop:
                            self._challenge_stop = None
                        continue
                    challenge_task = asyncio.create_task(
                        self._solve_cloudflare(socket, pending, challenge_id, url, stop))
                elif message.get("type") == "progress":
                    if pending[3]:
                        pending[3](data)
                elif message.get("type") == "result" and not pending[2].done():
                    pending[2].set_result(data)
                else:
                    raise ValueError("Unexpected Electron message")
        except (WebSocketDisconnect, ValueError, TimeoutError, RuntimeError):
            pass
        finally:
            if self._challenge_stop is not None:
                self._challenge_stop[2].set()
            if self._socket is socket:
                self._socket = None
                if self._pending is not None and self._pending[3]:
                    self._pending[3]({"message": "Electron disconnected; waiting for application shutdown, no replay"})
            try:
                await socket.close()
            except (WebSocketDisconnect, RuntimeError):
                pass
            if challenge_task is not None:
                await challenge_task
            if task is not None:
                await task

    async def _solve_cloudflare(self, socket: WebSocket, pending: tuple,
                                challenge_id: str, url: str, stop: threading.Event) -> None:
        # Keep receiving cancel/shutdown messages while the synchronous driver runs.
        data = await asyncio.to_thread(solve_cloudflare, self._cdp_url, url, stop)
        # The worker is settled before its result is sent; a subsequent request may now wait for this send.
        if self._challenge_stop is not None and self._challenge_stop[2] is stop:
            self._challenge_stop = None
        if (not stop.is_set() and self._socket is socket
                and self._pending is pending and not pending[2].done()):
            try:
                await socket.send_json({"type": "solve_cloudflare_result", "id": pending[0],
                    "action": pending[1], "challenge_id": challenge_id, "data": data})
            except (WebSocketDisconnect, OSError, RuntimeError):
                pass

    def finish_disconnected(self):
        """Called only by process teardown after Main has waited for local ItemSaver.

        A dropped transport cannot prove a native operation settled. Keep the
        pending worker (and its Workspace lock) until controlled shutdown.
        """
        if self._socket is None and self._pending is not None and not self._pending[2].done():
            self._pending[2].set_exception(ElectronDisconnected("Electron disconnected; inspect Zotero before retry"))

    async def _drain(self, socket: WebSocket):
        if self.shutdown:
            await self.shutdown()
        try:
            await socket.send_json({"type": "shutdown_ready"})
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def _execute(self, action: str, data: dict, progress: Callable | None) -> dict:
        if not self.connected:
            raise ElectronDisconnected("Electron runtime is unavailable")
        if self._pending is not None:
            raise RuntimeError("A browser request is already in flight")
        request_id = uuid4().hex
        result = asyncio.get_running_loop().create_future()
        self._pending = request_id, action, result, progress
        try:
            await self._socket.send_json({"type": "execute", "id": request_id, "action": action, "data": data})
            # An active ItemSaver must settle. Timeout must not release Workspace ownership.
            return await result
        except (WebSocketDisconnect, OSError, RuntimeError) as error:
            raise ElectronDisconnected("Electron result unavailable; no automatic replay") from error
        finally:
            if self._challenge_stop is not None and self._challenge_stop[0] is self._pending:
                self._challenge_stop[2].set()
            self._pending = None

    def execute(self, action: str, data: dict, progress: Callable | None = None) -> Future[dict]:
        """Register from a business worker; await the returned Future outside its stop mutex."""
        if self._loop is None:
            raise ElectronDisconnected("Electron has not connected")
        return asyncio.run_coroutine_threadsafe(self._execute(action, data, progress), self._loop)

    async def _cancel_current(self) -> bool:
        pending = self._pending
        if pending is None or self._socket is None:
            return False
        try:
            await self._socket.send_json({"type": "cancel", "id": pending[0], "action": pending[1]})
        except (WebSocketDisconnect, OSError, RuntimeError):
            return False
        return True

    def cancel_current(self):
        """Stop pre-save work; Main never aborts an escaped native ItemSaver."""
        challenge = self._challenge_stop
        if challenge is not None and challenge[0] is self._pending:
            challenge[2].set()
        if self._loop is not None:
            return asyncio.run_coroutine_threadsafe(self._cancel_current(), self._loop)
