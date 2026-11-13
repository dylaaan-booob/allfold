"""Collection admission and captured writes against disposable real SQLite libraries."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import sqlite3
from uuid import uuid4

import pytest

from allfold.models import ExternalIds
from allfold.persistence.paper_repository import (
    BodyReference, InvalidPaperState, LibraryError, MetadataDelta, PaperMetadata, PaperRepository, StaleWriteError,
)


def admit(repository, lifecycle_id, *, pmid="123", branches=("api", "preprint")):
    return repository.admit_collection(
        repository.workspace_id, lifecycle_id=lifecycle_id, branches=branches,
        direct_ids=ExternalIds(pmid=pmid), metadata=PaperMetadata(title="Article"))


def test_concurrent_admission_commits_one_paper_and_one_queued_attempt(tmp_path):
    lifecycle_id = uuid4()
    with PaperRepository.create(tmp_path) as repository:
        workspace_id = repository.workspace_id
    barrier = Barrier(4)

    def worker(_):
        with PaperRepository.open(tmp_path, expected_workspace_id=workspace_id) as repository:
            barrier.wait(timeout=5)
            return admit(repository, lifecycle_id)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = tuple(pool.map(worker, range(4)))
    assert len({result.paper.id for result in results}) == 1
    assert len({result.token for result in results}) == 1
    assert sum(result.created for result in results) == 1
    assert sum(result.admitted for result in results) == 1
    with PaperRepository.open(tmp_path) as repository:
        paper = repository.get(results[0].paper.id)
        assert paper.collection.status == "queued"
        assert paper.collection.attempt == 1
        assert paper.collection.lifecycle_id == lifecycle_id
        assert tuple(branch.name for branch in paper.collection.branches) == ("api", "preprint")
        assert len(repository.list_papers()) == 1


def test_captured_branch_increments_and_completion_are_idempotent_and_persist(tmp_path):
    with PaperRepository.create(tmp_path) as repository:
        admission = admit(repository, uuid4())
        token = admission.token
        running = repository.mark_collection_running(token)
        assert running.collection_status == "running"
        first = repository.commit_collection_branch(
            token, "api", sequence=1,
            delta=MetadataDelta(abstract="First result", ordinary_dates=("2026-11",)), outcome="completed")
        assert first.metadata.abstract == "First result"
        # A later manual clear must survive the duplicate success message.
        edited = repository.edit_metadata(first.token, {"abstract": None, "notes": "Human notes"})
        repeated = repository.commit_collection_branch(
            token, "api", sequence=1, delta=MetadataDelta(abstract="First result"), outcome="completed")
        assert repeated == edited
        with pytest.raises(InvalidPaperState):
            repository.finish_collection(token)
        repository.commit_collection_branch(token, "preprint", sequence=1, outcome="skipped", reason="Not applicable")
        completed = repository.finish_collection(token)
        assert completed.collection_status == "completed"
        assert completed.metadata.abstract is None
        assert completed.metadata.ordinary_dates == ("2026-11",)
        assert completed.metadata.notes == "Human notes"
        assert repository.finish_collection(token) == completed
        assert repository.commit_collection_branch(
            token, "api", sequence=1, delta=MetadataDelta(abstract="Duplicate after terminal"), outcome="completed") == completed
        revision = repository.revision
        assert admit(repository, uuid4()).token is None
        assert repository.revision == revision
    with PaperRepository.open(tmp_path) as reopened:
        assert reopened.get(completed.id) == completed
        assert admit(reopened, uuid4()).paper.collection_status == "completed"


def test_cancel_waits_for_settlement_then_retry_preserves_success_and_refuses_old_results(tmp_path):
    with PaperRepository.create(tmp_path) as repository:
        first = admit(repository, uuid4())
        repository.commit_collection_branch(first.token, "api", sequence=1,
                                           delta=MetadataDelta(ordinary_dates=("2026-11-01",)), outcome="completed")
        cancelled = repository.request_collection_cancel(first.token, reason="User cancelled")
        assert cancelled.collection.active and cancelled.collection.cancel_requested
        with pytest.raises(StaleWriteError):
            repository.require_collection(first.token)
        with pytest.raises(StaleWriteError):
            repository.commit_collection_branch(first.token, "preprint", sequence=1,
                                               delta=MetadataDelta(abstract="Late result"), outcome="completed")
        with pytest.raises(InvalidPaperState):
            repository.retry_collection(cancelled.token, lifecycle_id=uuid4(), branches=("api", "preprint"))
        # Cleanup may record its captured terminal fact after execution was revoked.
        repository.commit_collection_branch(first.token, "preprint", sequence=1, outcome="cancelled")
        finished = repository.finish_collection(first.token)
        assert finished.collection_status == "cancelled"
        assert not admit(repository, uuid4()).admitted  # Failed/cancelled never auto-retry.
        retried = repository.retry_collection(finished.token, lifecycle_id=uuid4(), branches=("api", "preprint"))
        assert retried.token.attempt == first.token.attempt + 1
        assert [branch.state for branch in retried.paper.collection.branches] == ["completed", "queued"]
        for action in (
            lambda: repository.commit_collection_branch(first.token, "preprint", sequence=2, outcome="cancelled"),
            lambda: repository.finish_collection(first.token),
            lambda: repository.request_collection_cancel(first.token),
        ):
            with pytest.raises(StaleWriteError):
                action()
        repository.commit_collection_branch(retried.token, "preprint", sequence=1, outcome="completed")
        completed = repository.finish_collection(retried.token)
        assert completed.collection_status == "completed"
        assert completed.metadata.ordinary_dates == ("2026-11-01",)
        with pytest.raises(InvalidPaperState):
            repository.retry_collection(completed.token, lifecycle_id=uuid4(), branches=("api", "preprint"))


def test_restart_interruption_is_explicit_and_preserves_successful_branch_facts(tmp_path):
    lifecycle_id = uuid4()
    with PaperRepository.create(tmp_path) as repository:
        first = admit(repository, lifecycle_id)
        repository.mark_collection_running(first.token)
        saved = repository.commit_collection_branch(first.token, "api", sequence=1,
                                                   delta=MetadataDelta(abstract="Saved before crash"), outcome="completed")
    # Worker/reader opens must not change a currently owned attempt.
    with PaperRepository.open(tmp_path) as repository:
        assert repository.get(saved.id) == saved
        assert repository.interrupt_collections(lifecycle_id) == ()
        next_lifecycle = uuid4()
        assert repository.interrupt_collections(next_lifecycle) == (saved.id,)
        interrupted = repository.get(saved.id)
        assert interrupted.collection_status == "failed"
        assert interrupted.collection.reason == "interrupted"
        assert interrupted.metadata.abstract == "Saved before crash"
        assert [branch.state for branch in interrupted.collection.branches] == ["completed", "failed"]
        revision = repository.revision
        assert repository.interrupt_collections(next_lifecycle) == ()
        assert repository.revision == revision
        with pytest.raises(StaleWriteError):
            repository.commit_collection_branch(first.token, "preprint", sequence=1,
                                               delta=MetadataDelta(abstract="Late"), outcome="completed")
        retry = repository.retry_collection(interrupted.token, lifecycle_id=next_lifecycle, branches=("api", "preprint"))
        assert retry.paper.collection.branches[0].state == "completed"


def test_reject_restore_never_renews_capture_and_clearing_waits_for_cleanup(tmp_path):
    with PaperRepository.create(tmp_path) as repository:
        admission = admit(repository, uuid4())
        token = admission.token
        rejected = repository.exclude(admission.paper.token)
        with pytest.raises(InvalidPaperState):
            repository.clear_metadata(rejected.token)
        restored = repository.restore(rejected.token)
        assert admit(repository, uuid4()).token == token
        with pytest.raises(StaleWriteError):
            repository.require_collection(token)
        with pytest.raises(InvalidPaperState):
            repository.complete_body(restored.token, BodyReference(relative_path="Documents/late.pdf"))
        for branch in ("api", "preprint"):
            repository.commit_collection_branch(token, branch, sequence=1, outcome="cancelled")
        settled = repository.finish_collection(token)
        assert settled.collection_status == "cancelled"
        body = repository.complete_body(settled.token, BodyReference(relative_path="Documents/original.pdf"))
        cleared = repository.clear_metadata(repository.exclude(body.token).token)
        assert cleared.collection_status == "not_started"
        assert cleared.body == body.body
        repository.unexclude(cleared.token)
        rebuilt = admit(repository, uuid4())
        assert rebuilt.admitted and not rebuilt.created
        assert rebuilt.paper.id == admission.paper.id
        assert rebuilt.paper.metadata_generation > admission.paper.metadata_generation
        assert rebuilt.paper.body == body.body
        assert rebuilt.token.attempt == 1
        with pytest.raises(StaleWriteError):
            repository.finish_collection(token)


def test_admission_and_branch_commit_failures_roll_back_all_related_facts(tmp_path):
    with PaperRepository.create(tmp_path) as repository:
        with sqlite3.connect(tmp_path / "papers.sqlite") as injector:
            injector.execute("""CREATE TRIGGER fail_admission BEFORE INSERT ON paper_collection
                BEGIN SELECT RAISE(ABORT, 'admission fault'); END""")
        with pytest.raises(LibraryError, match="admission fault"):
            admit(repository, uuid4())
        assert repository.list_papers() == ()
        assert repository.revision == 0
        with sqlite3.connect(tmp_path / "papers.sqlite") as injector:
            injector.execute("DROP TRIGGER fail_admission")
        admission = admit(repository, uuid4())
        with sqlite3.connect(tmp_path / "papers.sqlite") as injector:
            injector.execute("""CREATE TRIGGER fail_result BEFORE UPDATE ON paper_collection_branch
                BEGIN SELECT RAISE(ABORT, 'result fault'); END""")
        with pytest.raises(LibraryError, match="result fault"):
            repository.commit_collection_branch(admission.token, "api", sequence=1, outcome="completed",
                                               delta=MetadataDelta(abstract="Must roll back"),
                                               direct_ids=ExternalIds(pmcid="PMC999"))
        assert repository.get(admission.paper.id) == admission.paper
        assert repository.match(ExternalIds(pmcid="PMC999")) is None


def test_cleanup_failure_retains_success_but_group_fails_until_explicit_retry(tmp_path):
    with PaperRepository.create(tmp_path) as repository:
        admission = admit(repository, uuid4(), branches=("api",))
        repository.commit_collection_branch(admission.token, "api", sequence=1, outcome="completed")
        failed = repository.finish_collection(admission.token, failed=True, reason="cleanup_failed")
        assert failed.collection_status == "failed"
        assert failed.collection.branches[0].state == "completed"
        retry = repository.retry_collection(failed.token, lifecycle_id=uuid4(), branches=("api",))
        assert retry.paper.collection.branches[0].state == "completed"
        assert repository.finish_collection(retry.token).collection_status == "completed"
