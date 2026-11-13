"""Isolated Paper fixtures and explicit in-memory Electron transport doubles."""
from concurrent.futures import Future
import threading

class OfflineBridge:
    connected = False
    closing = False
    async def connect(self, socket):
        await socket.close(code=1008)
    def execute(self, *args, **kwargs):
        raise AssertionError('Offline fixture must not dispatch browser work')
    def cancel_current(self):
        pass
    def finish_disconnected(self):
        pass

class PendingBridge:
    connected = True
    closing = False
    def __init__(self):
        self.future = None
        self.dispatched = threading.Event()
        self.calls = []
        self.progress = None
        self.cancels = 0
    def execute(self, action, data, progress=None, *, verify_recovery=None):
        self.future = Future()
        self.calls.append((action, data))
        self.progress = progress
        self.dispatched.set()
        return self.future
    def cancel_current(self):
        self.cancels += 1
    def finish_disconnected(self):
        self.closing = True
        if self.future is not None and not self.future.done():
            self.future.set_result({})
