"""Trash operations exercise the production application seam with real SQLite."""
import pytest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, current_thread

from allfold.application.collection_runtime import WorkspaceRegistry
from allfold.application.decisions import apply_paper_action
from allfold.application.workspace import load_workspace
from allfold.persistence.library_models import BodyReference, MetadataDelta
from allfold.persistence.paper_repository import PaperRepository, StaleWriteError
from allfold.persistence.safe_write import workspace_operation_lock
from library_application_helpers import create_paper, read_paper


def test_reject_restore_clear_and_unexclude_preserve_uuid_identities_and_pdf(tmp_path):
    _, workspace, paper = create_paper(tmp_path, abstract='Human abstract', notes='Private note')
    body = workspace / 'Documents' / 'retained.pdf'
    body.parent.mkdir()
    body.write_bytes(b'%PDF-isolated-body')
    with PaperRepository.open(workspace) as repository:
        paper = repository.complete_body(paper.token, BodyReference(relative_path='Documents/retained.pdf'))
    original_token = paper.token
    rejected = apply_paper_action(workspace, paper.workspace_id, paper.id, 'reject')
    assert load_workspace(workspace).trash[0].paper_id == paper.id
    restored = apply_paper_action(workspace, paper.workspace_id, paper.id, 'restore')
    assert load_workspace(workspace).downloaded[0].abstract == 'Human abstract'
    with PaperRepository.open(workspace) as repository:
        with pytest.raises(StaleWriteError):
            repository.merge_metadata(original_token, {'abstract': 'Late worker'})
    apply_paper_action(workspace, paper.workspace_id, paper.id, 'reject')
    cleared = apply_paper_action(workspace, paper.workspace_id, paper.id, 'clear-metadata')
    assert cleared.paper.metadata is None and cleared.paper.excluded
    assert cleared.paper.id == paper.id and cleared.paper.identities == paper.identities
    assert body.read_bytes() == b'%PDF-isolated-body'
    apply_paper_action(workspace, paper.workspace_id, paper.id, 'unexclude')
    snapshot = load_workspace(workspace)
    assert len(snapshot.downloaded) == 1 and snapshot.downloaded[0].title is None
    assert not snapshot.inbox and not snapshot.trash
    assert rejected.revision < restored.revision < cleared.revision < snapshot.revision


def test_cleared_released_identity_without_body_is_hidden_not_deleted(tmp_path):
    _, workspace, paper = create_paper(tmp_path)
    for action in ('reject', 'clear-metadata', 'unexclude'):
        apply_paper_action(workspace, paper.workspace_id, paper.id, action)
    snapshot = load_workspace(workspace)
    assert not snapshot.inbox and not snapshot.downloaded and not snapshot.trash
    assert read_paper(workspace, paper.id).metadata is None


@pytest.mark.parametrize('kind', ['download', 'legacy'])
@pytest.mark.parametrize('previous_owner', [False, True])
def test_delayed_reject_signals_only_its_captured_reservation(tmp_path, monkeypatch, kind, previous_owner):
    _, workspace, paper = create_paper(tmp_path)
    registry = WorkspaceRegistry(workspace, factory=None)
    rejected, resume_reject, work_started, finish_work = (Event() for _ in range(4))
    previous_cancel, replacement_cancel = Event(), Event()
    gate = registry.paper_gate

    def cancel_previous():
        def check_write_locks_released():
            lock = gate()
            assert lock.acquire(timeout=1)
            lock.release()
            with workspace_operation_lock(workspace, create=False):
                with PaperRepository.open(workspace) as repository:
                    repository.touch_projection(paper.id)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(check_write_locks_released).result(2)
        previous_cancel.set()

    old = registry.reserve(paper.id, kind=kind, cancel=cancel_previous) if previous_owner else None

    @contextmanager
    def pause_after_gate():
        with gate():
            yield
        if current_thread().name.startswith('delayed-reject'):
            rejected.set()
            assert resume_reject.wait(5)

    monkeypatch.setattr(registry, 'paper_gate', pause_after_gate)
    replacement = None
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='delayed-reject') as reject_pool:
            delayed = reject_pool.submit(apply_paper_action, workspace, paper.workspace_id, paper.id, 'reject',
                workspace_registry=registry)
            try:
                assert rejected.wait(2)
                assert read_paper(workspace, paper.id).excluded
                if old is not None:
                    registry.release(old)
                apply_paper_action(workspace, paper.workspace_id, paper.id, 'restore', workspace_registry=registry)
                replacement = registry.reserve(paper.id, kind=kind, cancel=replacement_cancel.set)

                def controlled_work():
                    work_started.set()
                    assert finish_work.wait(5)
                    if replacement.cancel_event.is_set() or replacement_cancel.is_set():
                        raise RuntimeError('Replacement was cancelled by the old Reject')
                    with PaperRepository.open(workspace) as repository:
                        return repository.merge_metadata(replacement.token, MetadataDelta(abstract='Replacement work completed'))

                with ThreadPoolExecutor(max_workers=1) as work_pool:
                    work = work_pool.submit(controlled_work)
                    try:
                        assert work_started.wait(2)
                        resume_reject.set()
                        assert delayed.result(3).paper.excluded
                        assert not replacement.cancel_event.is_set() and not replacement_cancel.is_set()
                    finally:
                        finish_work.set()
                    assert work.result(3).metadata.abstract == 'Replacement work completed'
                assert previous_cancel.is_set() is previous_owner
            finally:
                resume_reject.set()
    finally:
        resume_reject.set(); finish_work.set()
        if old is not None:
            registry.release(old)
        if replacement is not None:
            registry.release(replacement)
        registry.shutdown(); registry.join()
