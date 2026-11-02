"""Isolated Paper fixtures and explicit in-memory Electron transport doubles."""
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import threading
from allfold.persistence.markdown_state import parse_paper_state, serialize_document
from allfold.persistence.materialize import render_paper_markdown
from allfold.models import Author, CanonicalMetadata, CanonicalPaper, ExternalIds, Workflow, WorkflowStatus

class OfflineBridge:
    connected = False
    closing = False
    async def connect(self, socket):
        await socket.close(code=1008)
    def execute(self, *args):
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
    def execute(self, action, data, progress=None):
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

def paper(root, name, *, status=WorkflowStatus.KEPT, doi=None, paper_id=None, days=0):
    value = CanonicalPaper(id=paper_id or uuid4(), metadata=CanonicalMetadata(title=name, journal="Test Journal"),
        external_ids=ExternalIds(doi=doi or f"10.5555/{name}"), authors=(Author(name="Ada"),),
        workflow=Workflow(status=status, discovered_at=datetime(2026, 10, 8, tzinfo=timezone.utc) - timedelta(days=days)))
    path = root / "Papers" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_paper_markdown(value))
    return value, path


def state(path):
    return parse_paper_state(path, path.read_bytes().decode())


def edit(path, **changes):
    value = state(path)
    frontmatter = dict(value.frontmatter)
    frontmatter.update(changes)
    path.write_text(serialize_document(frontmatter, value.body))
