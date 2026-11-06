from datetime import datetime, timezone

import httpx
import pytest

from allfold.application.decisions import reject_paper
from allfold.application.workspace import load_workspace
from allfold.models import ExternalIds, MetadataSource, ProviderRecordRef, ProviderWorkEvidence, WorkflowStatus
from allfold.persistence.discovery_evidence import append_discovery_evidence
from allfold.persistence.safe_write import workspace_operation_lock
from allfold.providers.supplemental import SupplementalClient
from test_paper_enrichment import missing
from test_web_app import write_valid_config


def test_saved_unkept_paper_completes_after_restart_and_rejected_paper_is_excluded(tmp_path):
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [arxiv]\n')
    paper_id, path = missing(workspace)
    rejected_id, rejected = missing(workspace)
    # The helper uses one filename; give each saved Paper its own stable file.
    # Recreate the first with its original UUID before preparing evidence.
    from test_application_decisions import write_paper
    rejected.rename(workspace / 'Papers' / 'rejected.md')
    rejected = workspace / 'Papers' / 'rejected.md'
    rejected.write_text(rejected.read_text().replace('10.5555/decision', '10.5555/rejected').replace('12345678', '7654321'))
    path = write_paper(workspace, paper_id, status=WorkflowStatus.CANDIDATE)
    from allfold.persistence.markdown_state import MISSING_ABSTRACT
    path.write_text(path.read_text().replace('Decision abstract.', MISSING_ABSTRACT) + '\nHuman notes.\n')
    reject_paper(workspace, rejected_id, WorkflowStatus.CANDIDATE)
    rejected = workspace / 'Papers' / 'rejected.md'
    original_rejected = rejected.read_bytes()
    with workspace_operation_lock(workspace) as lock:
        append_discovery_evidence(lock, paper_id, (ProviderWorkEvidence(
            provenance=MetadataSource(provider='openalex', record_id='W42', retrieved_at=datetime.now(timezone.utc)),
            external_ids=ExternalIds(doi='10.5555/decision'),
            related_ids=(ProviderRecordRef(provider='arxiv', record_id='2201.12345'),)),))
    calls = []
    def response(request):
        calls.append(request)
        assert request.url.params['id_list'] == '2201.12345'
        return httpx.Response(200, text='''<feed xmlns="http://www.w3.org/2005/Atom">
          <entry><id>https://arxiv.org/abs/2201.12345v3</id><title>Preprint title</title>
          <published>2022-01-04T00:00:00Z</published><summary>New abstract</summary>
          <author><name>New author</name></author></entry></feed>''')
    def factory(provider, **kwargs):
        assert provider == 'arxiv'
        return SupplementalClient(provider, transport=httpx.MockTransport(response), interval=0, **kwargs)
    service = ApiCompletion(config, BrowserTaskLock(), client_factory=factory)
    service.start((paper_id, rejected_id))
    service.join()
    state = service.state()
    assert state['phase'] == 'Completed'
    assert {r['paper_id']: r['status'] for r in state['results']} == {str(paper_id): 'updated', str(rejected_id): 'excluded'}
    paper, = load_workspace(workspace).inbox
    assert paper.first_public_at == '2022-01-04' and paper.abstract == 'New abstract'
    assert paper.status is WorkflowStatus.CANDIDATE and paper.external_ids.doi == '10.5555/decision'
    assert paper.authors == ('Ada Author',) and 'Human notes.' in path.read_text()
    assert rejected.read_bytes() == original_rejected and len(calls) == 1
    restarted = ApiCompletion(config, BrowserTaskLock(), client_factory=factory)
    restarted.start((paper_id,))
    restarted.join()
    assert restarted.state()['results'][0]['status'] == 'unchanged'
    assert len(calls) == 1  # saved first-version evidence answers the native gap


@pytest.mark.parametrize('change', ['reject', 'content', 'directory', 'file', 'configuration', 'cancel'])
def test_api_completion_refuses_changes_and_cancellation_during_lookup(tmp_path, change):
    from threading import Event
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [crossref]\n')
    paper_id, path = missing(workspace)
    waiting, release = Event(), Event()
    def response(request):
        waiting.set()
        assert release.wait(3)
        return httpx.Response(200, json={'message': {'DOI': '10.5555/decision', 'type': 'journal-article',
            'abstract': 'New abstract', 'accepted': {'date-parts': [[2025, 12, 1]]}}})
    def factory(provider, **kwargs):
        return SupplementalClient(provider, interval=0, transport=httpx.MockTransport(response), **kwargs)
    service = ApiCompletion(config, BrowserTaskLock(), client_factory=factory)
    task = service.start((paper_id,))
    assert waiting.wait(3)
    if change == 'reject':
        reject_paper(workspace, paper_id, WorkflowStatus.CANDIDATE)
    elif change == 'content':
        path.write_text(path.read_text() + 'Human edit\n')
    elif change == 'directory':
        old = workspace / 'OldPapers'
        path.parent.rename(old)
        path.parent.mkdir()
        path.write_bytes((old / path.name).read_bytes())
    elif change == 'file':
        old = path.with_suffix('.old')
        path.rename(old)
        path.write_bytes(old.read_bytes())
    elif change == 'configuration':
        config.write_text(config.read_text() + '\n# changed configuration\n')
    else:
        assert service.cancel(task['request_id'])
    before = path.read_bytes()
    release.set()
    service.join()
    assert path.read_bytes() == before
    assert service.state()['results'][0]['status'] == ('cancelled' if change == 'cancel' else 'failed')


def test_api_admission_csrf_progress_reset_and_settings_ownership(tmp_path):
    from threading import Event
    from fastapi.testclient import TestClient
    from electron_test_helpers import OfflineBridge
    from allfold.web.app import create_app
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [crossref]\n')
    paper_id, path = missing(workspace)
    app = create_app(config, electron_bridge=OfflineBridge())
    waiting, release = Event(), Event()
    def response(request):
        waiting.set()
        assert release.wait(3)
        return httpx.Response(404, json={})
    app.state.api_completion.client_factory = lambda provider, **kwargs: SupplementalClient(
        provider, interval=0, transport=httpx.MockTransport(response), **kwargs)
    with TestClient(app, base_url='http://localhost') as client:
        prefix = '/api/papers/api-completion'
        assert client.post(prefix + '/start', json={'csrf_token': 'bad', 'paper_ids': [str(paper_id)]}).status_code == 403
        settings = client.get('/api/ui-next/settings').json()
        csrf = settings['csrf_token']
        start = client.post(prefix + '/start', json={'csrf_token': csrf, 'paper_ids': [str(paper_id)]})
        assert start.status_code == 200 and waiting.wait(3)
        assert client.get(prefix + '/state').json()['phase'] == 'Running'
        assert client.post(prefix + '/start', json={'csrf_token': csrf, 'paper_ids': [str(paper_id)]}).status_code == 409
        from allfold.web.settings_guard import settings_task_active
        assert settings_task_active(app)
        assert app.state.browser_task_lock.owner.kind == 'api-completion'
        base = {key: settings['values'][key] for key in ('monitor_revision_exists', 'monitor_revision_digest', 'journal_revision_exists', 'journal_revision_digest')}
        saved = client.post('/api/ui-next/settings/autosave', json={
            'csrf_token': csrf, 'base': base, 'changes': {'completion_providers': ['arxiv']}}).json()
        assert saved['outcome'] == 'TASK_ACTIVE'
        preview = client.get('/api/ui-next/settings/reset-preview').json()
        reset = client.post('/settings/workspace-reset', data={'csrf_token': csrf, 'reset_token': preview['reset_token']})
        assert reset.status_code == 409 and path.exists()
        assert client.post(prefix + '/cancel', json={'csrf_token': csrf, 'request_id': 'stale'}).status_code == 409
        release.set()
        app.state.api_completion.join()
        result = client.get(prefix + '/state').json()
        assert result['phase'] == 'Completed' and result['results'][0]['status'] == 'unchanged'
        assert result['results'][0]['lookups'][0]['status'] == 'no_match'
        assert not settings_task_active(app)
        history = app.state.diagnostics.history()['records']
        assert any(record['kind'] == 'api_completion' and record['outcome'] == 'completed' for record in history)


def test_repeated_api_completion_appends_facts_without_overwriting_first_public_or_notes(tmp_path):
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    from test_application_decisions import replace_frontmatter
    from allfold.persistence.markdown_state import parse_paper_state
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [crossref]\n')
    paper_id, path = missing(workspace)
    replace_frontmatter(path, first_public_at='2022-01', authors=['Human Author'])
    path.write_text(path.read_text() + '\n## Human Section\nDo not edit.\n')
    def response(request):
        return httpx.Response(200, json={'message': {'DOI': '10.5555/decision', 'type': 'journal-article',
            'author': [{'given': 'Other', 'family': 'Author'}], 'accepted': {'date-parts': [[2025, 12]]},
            'published-online': {'date-parts': [[2025, 12]]}, 'published-print': {'date-parts': [[2026]]}}})
    def factory(provider, **kwargs):
        return SupplementalClient(provider, interval=0, transport=httpx.MockTransport(response), **kwargs)
    for attempt in range(2):
        service = ApiCompletion(config, BrowserTaskLock(), client_factory=factory)
        service.start((paper_id,))
        service.join()
        assert service.state()['phase'] == 'Completed'
        if not attempt:
            first = path.read_bytes()
    assert path.read_bytes() == first
    paper = parse_paper_state(path, path.read_text())
    assert paper.first_public_at == '2022-01' and paper.authors == ('Human Author',)
    assert len(paper.date_evidence) == 3
    assert '## Human Section\nDo not edit.' in path.read_text()


def test_operation_deduplicates_linked_lookups_without_merging_saved_papers(tmp_path):
    from uuid import uuid4
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    from test_application_decisions import write_paper, replace_frontmatter
    from allfold.persistence.markdown_state import parse_paper_state
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [crossref]\n')
    first_id, first = missing(workspace)
    second_id = uuid4()
    second = write_paper(workspace, second_id, filename='second.md')
    replace_frontmatter(second, doi='10.5555/second', external_ids={'doi': '10.5555/second'})
    calls = []
    def response(request):
        doi = request.url.path.removeprefix('/works/')
        calls.append(doi)
        other = '10.5555/second' if doi == '10.5555/decision' else '10.5555/decision'
        return httpx.Response(200, json={'message': {'DOI': doi, 'type': 'journal-article', 'abstract': 'API abstract',
            'relation': {'is-version-of': [{'id-type': 'doi', 'id': other}]}}})
    service = ApiCompletion(config, BrowserTaskLock(), client_factory=lambda provider, **kwargs:
        SupplementalClient(provider, interval=0, transport=httpx.MockTransport(response), **kwargs))
    service.start((first_id, second_id))
    service.join()
    assert calls == ['10.5555/decision', '10.5555/second']
    assert len(load_workspace(workspace).papers) == 2
    for path, paper_id, doi in ((first, first_id, '10.5555/decision'), (second, second_id, '10.5555/second')):
        state = parse_paper_state(path, path.read_text())
        assert state.paper_id == paper_id and state.external_ids.doi == doi
        assert state.title == 'Decision Paper' and state.status is WorkflowStatus.CANDIDATE


def test_cancellation_retains_previous_commit_and_stops_later_papers(tmp_path):
    from uuid import uuid4
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    from test_application_decisions import write_paper, replace_frontmatter
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [crossref]\n')
    ids, paths = [], []
    for index in range(3):
        paper_id = uuid4()
        path = write_paper(workspace, paper_id, filename=f'paper{index}.md')
        replace_frontmatter(path, doi=f'10.5555/{index}', external_ids={'doi': f'10.5555/{index}'})
        ids.append(paper_id)
        paths.append(path)
    before = [path.read_bytes() for path in paths]
    calls = []
    def response(request):
        doi = request.url.path.removeprefix('/works/')
        calls.append(doi)
        if len(calls) == 2:
            assert service.cancel(service.state()['request_id'])
        return httpx.Response(200, json={'message': {'DOI': doi, 'type': 'journal-article', 'accepted': {'date-parts': [[2025, 12, 1]]}}})
    service = ApiCompletion(config, BrowserTaskLock(), client_factory=lambda provider, **kwargs:
        SupplementalClient(provider, interval=0, transport=httpx.MockTransport(response), **kwargs))
    service.start(ids)
    service.join()
    assert service.state()['phase'] == 'Cancelled'
    assert [result['status'] for result in service.state()['results']] == ['updated', 'cancelled', 'cancelled']
    assert paths[0].read_bytes() != before[0]
    assert [path.read_bytes() for path in paths[1:]] == before[1:]
    assert calls == ['10.5555/0', '10.5555/1']


def test_evidence_write_failure_reports_the_paper_update_that_was_committed(tmp_path):
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.diagnostics import DiagnosticStore
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [crossref]\n')
    paper_id, path = missing(workspace)
    store = DiagnosticStore(config, root=tmp_path / 'logs')
    def response(request):
        (workspace / 'Evidence' / f'{paper_id}.json').mkdir(parents=True)
        return httpx.Response(200, json={'message': {'DOI': '10.5555/decision', 'type': 'journal-article', 'abstract': 'Committed abstract'}})
    service = ApiCompletion(config, BrowserTaskLock(), diagnostics=store, client_factory=lambda provider, **kwargs:
        SupplementalClient(provider, interval=0, transport=httpx.MockTransport(response), **kwargs))
    service.start((paper_id,))
    service.join()
    result = service.state()
    assert load_workspace(workspace).inbox[0].abstract == 'Committed abstract'
    assert result['phase'] == 'Partial' and result['results'][0]['status'] == 'updated'
    assert result['results'][0]['warning'] and 'abstract' in result['results'][0]['saved_fields']
    assert store.history()['records'][0]['statistics']['updated'] == 1


def test_api_completion_uses_saved_identity_alias_without_a_handoff(tmp_path):
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    from test_application_decisions import replace_frontmatter
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [arxiv]\n')
    paper_id, path = missing(workspace)
    replace_frontmatter(path, doi=None, external_ids={}, identity_aliases=[{'provider': 'arxiv', 'record_id': '2201.12345'}])
    calls = []
    def response(request):
        calls.append(request)
        return httpx.Response(200, text='''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
            <id>https://arxiv.org/abs/2201.12345v2</id><title>Title</title><summary>Alias abstract</summary>
            <published>2022-01-02T00:00:00Z</published></entry></feed>''')
    service = ApiCompletion(config, BrowserTaskLock(), client_factory=lambda provider, **kwargs:
        SupplementalClient(provider, interval=0, transport=httpx.MockTransport(response), **kwargs))
    service.start((paper_id,))
    service.join()
    paper, = load_workspace(workspace).inbox
    assert len(calls) == 1 and paper.abstract == 'Alias abstract'
    assert paper.external_ids.doi is None and paper.first_public_at == '2022-01-02'
