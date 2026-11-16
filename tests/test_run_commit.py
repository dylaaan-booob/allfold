"""Run retrieval never retains write exclusion or resurrects a reset Workspace."""
from threading import Event

import pytest

from allfold.application.run_commit import capture_run_workspace, commit_run_workspace
from allfold.application.workspace_reset import execute_reset, preview_reset
from allfold.config import JournalConfig, render_settings_list_text
from allfold.models import CanonicalMetadata, CanonicalPaper, ExternalIds
from allfold.persistence.paper_repository import PaperRepository, PaperMetadata
from allfold.persistence.safe_write import ContentChangedError, workspace_operation_lock


@pytest.fixture
def configuration(tmp_path):
    path = tmp_path / "monitor.yaml"
    path.write_text("name: Test\nvenue_whitelist: list.md\nkeyword_expression: causal\n"
                    "output_dir: workspace\nfrom_month: 2026-01\nto_month: 2026-12\n")
    scope = tmp_path / "list.md"
    scope.write_text(render_settings_list_text(
        None, (JournalConfig(name="Biometrics", issn="0006-341X"),),
        path=scope, groups=(), custom_labels=(), access_services=(),
    ))
    return path


def paper():
    return CanonicalPaper(metadata=CanonicalMetadata(title="Causal inference", journal="Biometrics"),
                          external_ids=ExternalIds(doi="10.5555/snapshot"))


def test_network_snapshot_releases_exclusion_and_reset_prevents_late_write(configuration):
    with capture_run_workspace(configuration) as snapshot:
        with workspace_operation_lock(snapshot.config.output_dir):
            pass
        assert execute_reset(configuration, preview_reset(configuration)).success
        with pytest.raises(ContentChangedError):
            with commit_run_workspace(snapshot) as lock:
                PaperRepository.open(snapshot.config.output_dir, expected_workspace_id=snapshot.workspace_id)
        assert not snapshot.config.output_dir.exists()


@pytest.mark.parametrize("replacement", ["directory", "symlink", "database", "configuration"])
def test_retrieval_snapshot_cannot_write_to_replaced_objects(configuration, replacement):
    with capture_run_workspace(configuration) as snapshot:
        workspace = snapshot.config.output_dir
        outside = configuration.parent / "replacement"
        outside.mkdir()
        if replacement == "configuration":
            configuration.write_text(configuration.read_text().replace("causal", "inference"))
        elif replacement == "database":
            (workspace / "papers.sqlite").rename(workspace / "old.sqlite")
            with PaperRepository.create(workspace):
                pass
        else:
            workspace.rename(configuration.parent / "original")
            if replacement == "directory":
                workspace.mkdir()
            else:
                workspace.symlink_to(outside, target_is_directory=True)
        with pytest.raises(ContentChangedError):
            with commit_run_workspace(snapshot) as lock:
                PaperRepository.open(workspace, expected_workspace_id=snapshot.workspace_id)
        assert not tuple(outside.iterdir())
        if replacement == "directory":
            assert not tuple(workspace.iterdir())


def test_cancellation_prevents_any_commit(configuration):
    cancelled = Event()
    with capture_run_workspace(configuration) as snapshot:
        cancelled.set()
        with pytest.raises(ContentChangedError, match="cancelled"):
            with commit_run_workspace(snapshot, cancel_event=cancelled):
                pytest.fail("cancelled Run entered commit scope")
        with PaperRepository.open(snapshot.config.output_dir) as repository:
            assert repository.list_papers() == ()


def _commit_process(snapshot, started, release, result):
    try:
        with commit_run_workspace(snapshot) as lock:
            started.set()
            assert release.wait(5)
            with PaperRepository.open(snapshot.config.output_dir, expected_workspace_id=snapshot.workspace_id) as repository:
                saved = repository.create_or_match(snapshot.workspace_id,
                    direct_ids=paper().external_ids, metadata=PaperMetadata(title='Causal inference'))
                result.put((int(saved.created), int(not saved.created), False))
    except Exception as error:
        result.put(str(error))


def test_two_processes_rescan_shared_identity_inside_commit_lock(configuration):
    import multiprocessing
    context = multiprocessing.get_context("fork")
    result = context.Queue()
    first_started, second_started, release = (context.Event() for _ in range(3))
    with capture_run_workspace(configuration) as first, capture_run_workspace(configuration) as second:
        workers = [context.Process(target=_commit_process, args=(snapshot, started, release, result))
                   for snapshot, started in ((first, first_started), (second, second_started))]
        workers[0].start()
        assert first_started.wait(5)
        workers[1].start()
        assert not second_started.wait(0.1)
        release.set()
        for worker in workers:
            worker.join(5)
            assert worker.exitcode == 0
        outcomes = [result.get(timeout=1) for _ in workers]
        assert all(isinstance(item, tuple) for item in outcomes), outcomes
        assert sorted(outcomes) == [(0, 1, False), (1, 0, False)]
        with PaperRepository.open(first.config.output_dir) as repository:
            assert len(repository.list_papers()) == 1


def test_reset_while_real_http_adapter_waits_cannot_restore_old_run(configuration):
    import httpx
    from integrated_run_helpers import run_integrated
    from allfold.providers.integrated import DiscoveryClient

    def response(request):
        assert execute_reset(configuration, preview_reset(configuration)).success
        return httpx.Response(200, json={"results": [{"id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.5555/late", "title": "Causal inference", "publication_date": "2026-01-01"}],
            "meta": {"count": 1, "next_cursor": None}})

    def client(provider, **kwargs):
        return DiscoveryClient(provider, transport=httpx.MockTransport(response), interval=0, **kwargs)

    with pytest.raises(ContentChangedError):
        run_integrated(configuration, client_factory=client)
    assert not (configuration.parent / "workspace").exists()


def test_last_run_write_uses_same_bound_workspace_as_paper_commit(configuration):
    from allfold.application.run_state import (
        INTEGRATED_RUN_SCHEMA_VERSION, LastRunSnapshot, LastRunSnapshotWriteError,
        RecordedRunOutcome, RunFacts, RunProvider, write_last_run_snapshot,
    )
    from allfold.config import resolve_runtime_date
    from datetime import date, datetime, timezone
    with capture_run_workspace(configuration) as snapshot:
        workspace = snapshot.config.output_dir
        with commit_run_workspace(snapshot) as lock:
            workspace.rename(configuration.parent / "original")
            workspace.mkdir()
            facts = LastRunSnapshot(INTEGRATED_RUN_SCHEMA_VERSION, RunProvider.INTEGRATED,
                resolve_runtime_date(snapshot.config, today=date(2026, 11, 5)),
                RecordedRunOutcome.COMPLETED, RunFacts(finished_at=datetime.now(timezone.utc),
                    created_papers=0, existing_papers=0))
            with pytest.raises(LastRunSnapshotWriteError):
                write_last_run_snapshot(workspace, facts, operation_lock=lock)
            assert not tuple(workspace.iterdir())


@pytest.mark.parametrize('edit', ['comment', 'logging', 'workflow', 'display', 'keyword_format', 'journal_display', 'unused_service'])
def test_run_snapshot_keeps_captured_inputs_after_unrelated_edits(configuration, edit):
    from dataclasses import replace
    from allfold.config import AccessService, load_config
    from allfold.persistence.user_state import read_user_state, compare_write_user_state

    original = load_config(configuration)
    with capture_run_workspace(configuration, original) as snapshot:
        if edit in {'journal_display', 'unused_service'}:
            saved = read_user_state(configuration)
            if edit == 'journal_display':
                state = replace(saved.state, journals=tuple(j.model_copy(update={'name': 'Display alias',
                    'group': 'Display group', 'labels': ('Display label',)}) for j in saved.state.journals),
                    groups=('Display group',), custom_labels=('Display label',))
            else:
                state = replace(saved.state, access_services=(AccessService.create('Unused Service', 'https://unused.example/'),))
            compare_write_user_state(configuration, state, saved.revision)
        else:
            text = configuration.read_text()
            if edit == 'keyword_format':
                text = text.replace('keyword_expression: causal', 'keyword_expression: ( causal )')
            else:
                text += {'comment': '\n# a new comment\n', 'logging': '\nlog_level: DEBUG\n',
                    'workflow': '\nworkflow:\n  managed_page_global_limit: 8\n  pdf_concurrency: 4\n',
                    'display': '\nprovider_aliases:\n  pubmed: Display alias\nname: Renamed monitor\n'}[edit]
            configuration.write_text(text)
        with commit_run_workspace(snapshot) as lock:
            with PaperRepository.open(lock.path, expected_workspace_id=snapshot.workspace_id) as repository:
                repository.create_or_match(snapshot.workspace_id, direct_ids=paper().external_ids,
                    metadata=PaperMetadata(title='Original result'))
        assert snapshot.config is original
        with PaperRepository.open(original.output_dir) as repository:
            assert repository.list_papers()[0].metadata.title == 'Original result'


@pytest.mark.parametrize('edit', ['keyword', 'date', 'source_order', 'journal_scope', 'allocation', 'mailto'])
def test_run_snapshot_refuses_changed_consumed_inputs(configuration, edit):
    from dataclasses import replace
    from allfold.config import AccessService
    from allfold.persistence.user_state import read_user_state, compare_write_user_state

    with capture_run_workspace(configuration) as snapshot:
        if edit in {'journal_scope', 'allocation'}:
            saved = read_user_state(configuration)
            service = AccessService.create('Assigned', 'https://assigned.example/')
            update = {'issn': '0090-5364'} if edit == 'journal_scope' else {'access_service_id': service.id}
            state = replace(saved.state, journals=tuple(j.model_copy(update=update) for j in saved.state.journals),
                access_services=(service,))
            compare_write_user_state(configuration, state, saved.revision)
        else:
            text = configuration.read_text()
            if edit == 'keyword':
                text = text.replace('keyword_expression: causal', 'keyword_expression: inference')
            elif edit == 'date':
                text = text.replace('to_month: 2026-12', 'to_month: 2026-11')
            elif edit == 'source_order':
                text += '\nenabled_providers: [openalex, pubmed]\n'
            else:
                text += '\ncrossref_mailto: reader@example.org\n'
            configuration.write_text(text)
        with pytest.raises(ContentChangedError):
            with commit_run_workspace(snapshot):
                pytest.fail('changed Run inputs reached its write phase')
        with PaperRepository.open(snapshot.config.output_dir) as repository:
            assert not repository.list_papers()


def test_wos_snapshot_admits_loaded_scope_after_unrelated_user_state_revision(configuration):
    from dataclasses import replace
    from allfold.config import AccessService, load_config
    from allfold.persistence.user_state import read_user_state, compare_write_user_state

    configuration.write_text(configuration.read_text() + '\nenabled_providers: [wos]\n')
    load_config(configuration)
    saved = read_user_state(configuration)
    wos = AccessService.create('Web of Science', 'https://www.webofscience.com/')
    compare_write_user_state(configuration, replace(saved.state,
        access_services=(wos,)), saved.revision)
    original = load_config(configuration)
    saved = read_user_state(configuration)
    compare_write_user_state(configuration, replace(saved.state, groups=('Unrelated',)), saved.revision)
    with capture_run_workspace(configuration, original) as snapshot:
        with commit_run_workspace(snapshot):
            pass
        assert snapshot.config is original
        assert snapshot.wos_access.services == (wos,)
