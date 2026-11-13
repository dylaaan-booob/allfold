"""Production Run identity classification and SQLite writes, without Paper Markdown."""
from dataclasses import replace
from datetime import datetime, timezone

from allfold.models import ExternalIds
from allfold.persistence.paper_repository import PaperMetadata, PaperRepository
from integrated_run_helpers import EmptyCompletion, run_integrated
from test_integrated_run import config, evidence, client_for


def configured(tmp_path):
    path, _ = config(tmp_path)
    path.write_text(path.read_text() + 'enabled_providers: [pubmed]\n')
    return path


def test_run_uses_repository_uuid_and_keeps_complete_records_unchanged(tmp_path):
    path = configured(tmp_path)
    rows = (evidence(),)
    first = run_integrated(path, client_factory=client_for(rows))
    workspace = tmp_path / 'workspace'
    with PaperRepository.open(workspace) as repository:
        saved, = repository.list_papers()
    assert saved.id != __import__('uuid').UUID(int=0)
    assert first.facts.details['paper_ids'] == [str(saved.id)]
    assert not (workspace / 'Papers').exists() and not (workspace / 'Inbox.base').exists()
    helper_calls = []
    class Completion(EmptyCompletion):
        def lookup_many(self, namespace, ids, **kwargs):
            helper_calls.extend(ids)
            return super().lookup_many(namespace, ids, **kwargs)
    second = run_integrated(path, client_factory=client_for((evidence(title='Replacement'),)), completion_factory=Completion)
    assert second.facts.created_papers == 0 and second.facts.existing_papers == 1
    assert helper_calls == []
    with PaperRepository.open(workspace) as repository:
        assert repository.get(saved.id) == saved


def test_excluded_and_released_placeholder_have_distinct_early_run_classification(tmp_path):
    path = configured(tmp_path)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        saved = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/formal'),
            metadata=PaperMetadata(title='Old title', notes='Deleted notes')).paper
        excluded = repository.exclude(saved.token)
    result = run_integrated(path, client_factory=client_for((evidence(),)))
    assert result.facts.created_papers == result.facts.existing_papers == 0
    assert result.facts.statistics['completion_targets'] == 0
    with PaperRepository.open(workspace) as repository:
        released = repository.unexclude(repository.clear_metadata(excluded.token).token)
    result = run_integrated(path, client_factory=client_for((evidence(),)))
    assert result.facts.statistics['completion_targets'] == 1
    assert result.facts.statistics['rebuilt_papers'] == 1
    with PaperRepository.open(workspace) as repository:
        rebuilt = repository.get(saved.id)
        assert rebuilt.id == released.id and rebuilt.metadata.title == 'Native hit'
        assert rebuilt.metadata.notes == ''


def test_reject_restore_during_completion_cannot_renew_placeholder_authority(tmp_path):
    path = configured(tmp_path)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        saved = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/formal'),
            metadata=PaperMetadata(title='Old title')).paper
        placeholder = repository.unexclude(repository.clear_metadata(repository.exclude(saved.token).token).token)
    changed = []
    class Completion(EmptyCompletion):
        def lookup_many(self, namespace, ids, **kwargs):
            if not changed:
                with PaperRepository.open(workspace) as repository:
                    current = repository.get(placeholder.id)
                    changed.append(repository.unexclude(repository.exclude(current.token).token))
            return super().lookup_many(namespace, ids, **kwargs)
    run_integrated(path, client_factory=client_for((evidence(),)), completion_factory=Completion)
    assert changed
    with PaperRepository.open(workspace) as repository:
        assert repository.get(placeholder.id).metadata is None
