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
    def cancel_workflow(self, workflow_id):
        pass
    def cancel_task(self, workflow_id, task_id):
        return self.cancel_workflow(workflow_id)
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
        self.cancelled_tasks = []
        self.cancelled_workflows = []
    def execute(self, action, data, progress=None, *, verify_recovery=None):
        if action == 'release_workflow_pages':
            self.calls.append((action, data))
            settled = Future()
            settled.set_result({'released': True})
            return settled
        self.future = Future()
        self.calls.append((action, data))
        self.progress = progress
        self.dispatched.set()
        return self.future
    def cancel_workflow(self, workflow_id):
        self.cancels += 1
        self.cancelled_workflows.append(workflow_id)
    def cancel_task(self, workflow_id, task_id):
        self.cancelled_tasks.append((workflow_id, task_id))
        self.cancels += 1
    def finish_disconnected(self):
        self.closing = True
        if self.future is not None and not self.future.done():
            self.future.set_result({})
