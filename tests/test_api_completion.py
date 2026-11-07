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


@pytest.mark.parametrize('provider', ('biorxiv', 'medrxiv'))
def test_known_preprint_is_queried_before_redundant_formal_reverse_lookup(tmp_path, provider):
    from uuid import uuid4
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    from test_application_decisions import write_paper, replace_frontmatter
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + f'\ncompletion_providers: [crossref, {provider}]\n')
    paper_id = uuid4()
    path = write_paper(workspace, paper_id)
    formal, preprint = '10.1093/bioinformatics/btaf638', '10.1101/2022.02.01.123456'
    replace_frontmatter(path, doi=formal, external_ids={'doi': formal}, first_public_at=None)
    calls = []
    def response(request):
        calls.append(request.url.path)
        if request.url.host == 'api.crossref.org':
            is_formal = request.url.path.endswith(formal)
            item = {'DOI': formal if is_formal else preprint, 'title': ['Formal' if is_formal else 'Preprint'],
                    'type': 'journal-article' if is_formal else 'posted-content', 'publisher': provider if not is_formal else 'Journal publisher'}
            if is_formal:
                item['relation'] = {'has-preprint': [{'id-type': 'doi', 'id': preprint}]}
            return httpx.Response(200, json={'message': item})
        if request.url.path.startswith('/pubs/'):
            return httpx.Response(200, json={'messages': [{'status': 'service unavailable'}], 'collection': []})
        return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': [{
            'doi': preprint, 'published': formal, 'server': provider, 'version': '1', 'date': '2022-02-03'}]})
    service = ApiCompletion(config, BrowserTaskLock(), client_factory=lambda selected, **kwargs:
        SupplementalClient(selected, interval=0, transport=httpx.MockTransport(response), **kwargs))
    service.start((paper_id,))
    service.join()
    assert load_workspace(workspace).inbox[0].first_public_at == '2022-02-03'
    assert service.state()['phase'] == 'Completed'
    assert f'/details/{provider}/{preprint}/na/json' in calls
    assert not any(path.startswith('/pubs/') for path in calls)


@pytest.mark.parametrize('recorded', (False, True))
def test_partial_completion_reports_whether_first_public_is_recorded(tmp_path, recorded):
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    from test_application_decisions import replace_frontmatter
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [crossref]\n')
    paper_id, path = missing(workspace)
    if recorded:
        replace_frontmatter(path, first_public_at='2022-02-03')
    service = ApiCompletion(config, BrowserTaskLock(), client_factory=lambda provider, **kwargs:
        SupplementalClient(provider, interval=0, transport=httpx.MockTransport(lambda request:
            httpx.Response(200, json={'message': {}})), **kwargs))
    service.start((paper_id,))
    service.join()
    result = service.state()
    assert result['phase'] == 'Partial'
    assert result['results'][0]['first_public_status'] == 'failed'
    assert result['results'][0]['first_public_recorded'] is recorded
    assert result['results'][0]['lookups'][0]['status'] == 'identity_mismatch'


@pytest.mark.parametrize('provider', ('biorxiv', 'medrxiv'))
def test_native_publication_not_found_is_completed_no_match(tmp_path, provider):
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + f'\ncompletion_providers: [{provider}]\n')
    paper_id, path = missing(workspace)
    path.write_text(path.read_text().replace('10.5555/decision', '10.1186/s13059-025-03880-4'))
    before = path.read_bytes()
    service = ApiCompletion(config, BrowserTaskLock(), client_factory=lambda selected, **kwargs:
        SupplementalClient(selected, interval=0, transport=httpx.MockTransport(lambda request:
            httpx.Response(200, json={'messages': [{'status':
                'Preprint for DOI 10.1186/s13059-025-03880-4 not found'}], 'collection': []})), **kwargs))
    service.start((paper_id,))
    service.join()
    result = service.state()
    assert result['phase'] == 'Completed'
    assert result['results'][0]['status'] == 'unchanged'
    assert result['results'][0]['lookups'][0]['status'] == 'no_match'
    assert path.read_bytes() == before


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


@pytest.mark.parametrize('related', [False, True])
def test_arxiv_doi_identity_survives_completion_writeback_without_atom_doi(tmp_path, related):
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    from test_application_decisions import replace_frontmatter
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [arxiv]\n')
    paper_id, path = missing(workspace)
    arxiv_doi = '10.48550/arxiv.2201.12345'
    primary = '10.5555/formal' if related else arxiv_doi
    replace_frontmatter(path, doi=primary, external_ids={'doi': primary}, related_dois=[arxiv_doi] if related else [])
    service = ApiCompletion(config, BrowserTaskLock(), client_factory=lambda provider, **kwargs:
        SupplementalClient(provider, interval=0, transport=httpx.MockTransport(lambda _: httpx.Response(200, text='''
          <feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <id>https://arxiv.org/abs/2201.12345v3</id><title>Preprint</title><summary>Native abstract</summary>
          <published>2022-01-02T00:00:00Z</published></entry></feed>''')), **kwargs))
    service.start((paper_id,))
    service.join()
    assert service.state()['results'][0]['status'] == 'updated'
    paper, = load_workspace(workspace).inbox
    assert paper.abstract == 'Native abstract' and paper.first_public_at == '2022-01-02'
    assert paper.external_ids.doi == primary and paper.paper_id == paper_id


@pytest.mark.parametrize('provider', ['biorxiv', 'medrxiv'])
def test_batch_native_reverse_lookup_reuses_details_for_separately_saved_preprint(tmp_path, provider):
    from uuid import uuid4
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    from test_application_decisions import write_paper, replace_frontmatter
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + f'\ncompletion_providers: [{provider}]\n')
    formal_id, _ = missing(workspace)
    preprint_id = uuid4()
    preprint = write_paper(workspace, preprint_id, filename='preprint.md')
    replace_frontmatter(preprint, doi='10.1101/123456', external_ids={'doi': '10.1101/123456'},
                        publication_date=None, publication_type='preprint', authors=[])
    calls = []
    def response(request):
        calls.append(request.url.path)
        rows = [{'preprint_doi': '10.1101/123456', 'published_doi': '10.5555/decision'}] if '/pubs/' in request.url.path else [
            {'doi': '10.1101/123456', 'published': '10.5555/decision', 'version': '1', 'date': '2022-01-02'}]
        return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': rows})
    service = ApiCompletion(config, BrowserTaskLock(), client_factory=lambda selected, **kwargs:
        SupplementalClient(selected, interval=0, transport=httpx.MockTransport(response), **kwargs))
    service.start((formal_id, preprint_id))
    service.join()
    assert calls == [f'/pubs/{provider}/10.5555/decision/na/json', f'/details/{provider}/10.1101/123456/na/json']
    assert len(load_workspace(workspace).papers) == 2
    assert all(result['status'] == 'updated' for result in service.state()['results'])


def test_new_preprint_alias_does_not_duplicate_already_saved_version_dates(tmp_path):
    from allfold.application.api_completion import saved_paper_evidence, save_api_completion
    from allfold.application.paper_enrichment import read_paper_target
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    config, workspace = write_valid_config(tmp_path)
    paper_id, _ = missing(workspace)
    raw = {'source': 'PPR', 'id': 'PPR3', 'title': 'Preprint', 'versionNumber': '3', 'firstPublicationDate': '2025-09-01',
        'commentCorrectionList': {'commentCorrection': [{'type': 'Preprint of', 'source': 'MED', 'id': '42', 'doi': '10.5555/decision'}]},
        'versionList': {'version': [{'id': 'PPR1', 'source': 'PPR', 'versionNumber': '1', 'firstPublishDate': '2020-06'}]}}
    with DiscoveryClient('europe_pmc', transport=httpx.MockTransport(lambda _: pytest.fail('Unexpected request'))) as client:
        for addition in ({}, {'doi': '10.1101/123456'}):
            evidence = client.normalize({**raw, **addition}, SourceScope('journal', ''))
            with workspace_operation_lock(workspace) as lock:
                target = read_paper_target(workspace, paper_id, operation_lock=lock)
                save_api_completion(target, (saved_paper_evidence(target), evidence), operation_lock=lock)
            paper, = load_workspace(workspace).inbox
            assert paper.first_public_at == '2020-06'
            assert len(paper.date_evidence) == 2


@pytest.mark.parametrize('handoff', [False, True])
def test_saved_aggregate_preprint_ids_do_not_join_independent_version_families(tmp_path, handoff):
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.canonicalize import canonicalize_records
    from allfold.models import Author, EvidenceDate, EvidenceDateKind
    from allfold.persistence.materialize import materialize_papers
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [biorxiv]\n')
    first = ProviderWorkEvidence(provenance=MetadataSource(provider='arxiv', record_id='2201.12345',
        retrieved_at=datetime.now(timezone.utc)), external_ids=ExternalIds(arxiv='2201.12345'),
        related_dois=('10.1101/123456',), publication_type='preprint', publication_date='2022-01-02',
        title='Preprint', abstract='Saved abstract', authors=(Author(name='Saved author'),),
        dates=(EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=2022, month=1, day=2, first_version=True),))
    later = first.model_copy(update={'provenance': first.provenance.model_copy(update={'provider': 'biorxiv', 'record_id': '10.1101/123456:2'}),
        'external_ids': ExternalIds(doi='10.1101/123456'), 'related_dois': (), 'publication_date': '2024-01',
        'dates': (EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=2024, month=1, version='2'),)})
    paper, = canonicalize_records((first, later)).papers
    assert paper.metadata.first_public_at is None
    assert materialize_papers((paper,), workspace).created_papers
    if handoff:
        with workspace_operation_lock(workspace) as lock:
            append_discovery_evidence(lock, paper.id, (first, later))
    calls = []
    def response(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': [
            {'doi': '10.1101/123456', 'date': '2019-01', 'version': '1'}]})
    service = ApiCompletion(config, BrowserTaskLock(), client_factory=lambda provider, **kwargs:
        SupplementalClient(provider, interval=0, transport=httpx.MockTransport(response), **kwargs))
    service.start((paper.id,))
    service.join()
    assert calls == ['/details/biorxiv/10.1101/123456/na/json']
    saved, = load_workspace(workspace).inbox
    assert saved.first_public_at == '2019-01' and saved.paper_id == paper.id
    assert saved.external_ids == paper.external_ids


def test_paper_commit_sync_failure_preserves_saved_fields_through_commit_guard(tmp_path, monkeypatch):
    import os
    import stat
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [crossref]\n')
    paper_id, path = missing(workspace)
    original_sync, failures = os.fsync, []
    def fail_committed_directory_sync(descriptor):
        if (not failures and stat.S_ISDIR(os.fstat(descriptor).st_mode)
                and 'Committed before sync failure' in path.read_text()):
            failures.append(True)
            raise OSError('Synthetic directory sync failure')
        return original_sync(descriptor)
    monkeypatch.setattr(os, 'fsync', fail_committed_directory_sync)
    service = ApiCompletion(config, BrowserTaskLock(), client_factory=lambda provider, **kwargs:
        SupplementalClient(provider, interval=0, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
            'message': {'DOI': '10.5555/decision', 'type': 'journal-article', 'abstract': 'Committed before sync failure'}})), **kwargs))
    service.start((paper_id,))
    service.join()
    result = service.state()
    assert failures and load_workspace(workspace).inbox[0].abstract == 'Committed before sync failure'
    assert result['phase'] == 'Partial' and result['results'][0]['status'] == 'updated'
    assert 'abstract' in result['results'][0]['saved_fields'] and result['results'][0]['warning']


def test_local_evidence_completes_without_enabled_network_sources(tmp_path):
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.models import Author
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: []\n')
    paper_id, path = missing(workspace)
    with workspace_operation_lock(workspace) as lock:
        append_discovery_evidence(lock, paper_id, (ProviderWorkEvidence(
            provenance=MetadataSource(provider='wos',record_id='WOS:123456',retrieved_at=datetime.now(timezone.utc)),
            external_ids=ExternalIds(doi='10.5555/decision'), title='Saved title', journal='Journal',
            abstract='Locally saved abstract', authors=(Author(name='Full author'),), publication_type='journal'),))
    service = ApiCompletion(config, BrowserTaskLock(), client_factory=lambda *args,**kwargs:
        pytest.fail('No network client is needed'))
    service.start((paper_id,)); service.join()
    result = service.state()
    assert result['phase'] == 'Completed'
    assert result['results'][0]['lookups'] == []
    assert load_workspace(workspace).inbox[0].abstract == 'Locally saved abstract'
    assert result['results'][0]['first_public_status'] == 'no_association'


def test_selected_papers_share_one_arxiv_batch_and_preserve_existing_first_public(tmp_path):
    from uuid import uuid4
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    from test_application_decisions import write_paper, replace_frontmatter
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [arxiv]\n')
    ids, paths = [], []
    for index in range(3):
        paper_id = uuid4(); ids.append(paper_id)
        path = write_paper(workspace,paper_id,filename=f'{index}.md'); paths.append(path)
        replace_frontmatter(path,doi=f'10.5555/paper-{index}',external_ids={'doi':f'10.5555/paper-{index}'},
            first_public_at='2020' if index == 2 else None)
        with workspace_operation_lock(workspace) as lock:
            append_discovery_evidence(lock,paper_id,(ProviderWorkEvidence(
                provenance=MetadataSource(provider='wos',record_id=f'WOS:{index+1}',retrieved_at=datetime.now(timezone.utc)),
                external_ids=ExternalIds(doi=f'10.5555/paper-{index}'),
                related_ids=(ProviderRecordRef(provider='arxiv',record_id=f'2201.{index:05}'),)),))
    from allfold.diagnostics import DiagnosticStore
    store = DiagnosticStore(config,root=tmp_path / "logs")
    calls = []
    def response(request):
        calls.append(request)
        assert request.url.params['id_list'] == '2201.00000,2201.00001,2201.00002'
        return httpx.Response(200,text='<feed xmlns="http://www.w3.org/2005/Atom">'+''.join(
            f'<entry><id>https://arxiv.org/abs/2201.{index:05}v3</id><title>Title</title><published>2022-01-02T00:00:00Z</published></entry>'
            for index in (1,0))+'</feed>')
    service = ApiCompletion(config,BrowserTaskLock(),diagnostics=store,client_factory=lambda provider,**kwargs:
        SupplementalClient(provider,interval=0,transport=httpx.MockTransport(response),**kwargs))
    service.start(ids); service.join()
    results = service.state()['results']
    assert len(calls) == 1
    assert [result['first_public_status'] for result in results] == ['recorded','recorded','known_unresolved']
    assert results[2]['first_public_recorded'] is True
    assert {paper.paper_id:paper.first_public_at for paper in load_workspace(workspace).papers}[ids[2]] == '2020'
    statistics = store.history()['records'][0]['statistics']
    assert statistics['first_public_recorded'] == 2
    assert statistics['first_public_known_unresolved'] == 1
    assert statistics['evidence'] == 2 and statistics['no_match'] == 1


def test_saved_native_reverse_online_event_never_becomes_a_preprint_lookup(tmp_path):
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    config,workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [biorxiv]\n')
    paper_id,path = missing(workspace)
    calls=[]
    def response(request):
        calls.append(request.url.path)
        rows = [{'preprint_doi':'10.1101/123456','published_doi':'10.5555/decision','published_date':'2026-01'}] if '/pubs/' in request.url.path else [
            {'doi':'10.1101/123456','published':'10.5555/decision','version':'1','date':'2022-01-02',
             'title':'Title','abstract':'Abstract','authors':'Author','server':'biorxiv'}]
        return httpx.Response(200,json={'messages':[{'status':'ok'}],'collection':rows})
    for _ in range(2):
        service=ApiCompletion(config,BrowserTaskLock(),client_factory=lambda provider,**kwargs:
            SupplementalClient(provider,interval=0,transport=httpx.MockTransport(response),**kwargs))
        service.start((paper_id,));service.join()
        assert service.state()['phase']=='Completed'
    assert calls == ['/pubs/biorxiv/10.5555/decision/na/json','/details/biorxiv/10.1101/123456/na/json']


@pytest.mark.parametrize('paper_count', [1, 2])
@pytest.mark.parametrize('cancel_native', [False, True])
def test_newly_discovered_arxiv_targets_share_a_batch_before_further_aggregation(tmp_path, paper_count, cancel_native):
    from uuid import uuid4
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    from test_application_decisions import write_paper, replace_frontmatter
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [crossref, arxiv, openalex]\n')
    ids = []
    for index in range(paper_count):
        paper_id = uuid4()
        ids.append(paper_id)
        path = write_paper(workspace, paper_id, filename=f'{index}.md')
        replace_frontmatter(path, doi=f'10.5555/formal-{index}', external_ids={'doi': f'10.5555/formal-{index}'})
    calls = []
    def response(request):
        calls.append((request.url.host, request.url.params.get('id_list')))
        if request.url.host == 'api.crossref.org':
            index = int(request.url.path[-1])
            targets = ['2201.00001', '2201.00002'] if paper_count == 1 else [f'2201.{index + 1:05}']
            return httpx.Response(200, json={'message': {
                'DOI': f'10.5555/formal-{index}', 'type': 'journal-article',
                'relation': {'has-preprint': [{'id-type': 'uri', 'id': f'https://arxiv.org/abs/{value}'} for value in targets]}}})
        assert request.url.host == 'export.arxiv.org', 'Known native targets must precede further aggregators'
        if cancel_native:
            assert service.cancel(service.state()['request_id'])
        return httpx.Response(200, text='<feed xmlns="http://www.w3.org/2005/Atom">' + ''.join(
            f'<entry><id>https://arxiv.org/abs/{value}v2</id><title>Title</title>'
            '<published>2022-01-02T00:00:00Z</published></entry>'
            for value in reversed(request.url.params['id_list'].split(','))) + '</feed>')
    from allfold.application.coordinators.api_completion import completion_client
    service = ApiCompletion(config, BrowserTaskLock(), client_factory=lambda provider, **kwargs:
        completion_client(provider, interval=0, transport=httpx.MockTransport(response), **kwargs))
    service.start(ids)
    service.join()
    assert calls == [('api.crossref.org', None)] * paper_count + [('export.arxiv.org', '2201.00001,2201.00002')]
    results = service.state()['results']
    assert service.state()['phase'] == ('Cancelled' if cancel_native else 'Completed')
    assert all(result['first_public_status'] == ('cancelled' if cancel_native else 'recorded') for result in results)
    assert all(any(lookup['provider'] == 'crossref' and lookup['status'] == 'evidence'
                   for lookup in result['lookups']) for result in results)
    assert all(paper.first_public_at == (None if cancel_native else '2022-01-02') for paper in load_workspace(workspace).papers)


def test_native_batch_relations_join_the_next_shared_wave(tmp_path):
    from uuid import uuid4
    from allfold.application.coordinators.api_completion import ApiCompletion
    from allfold.application.browser_runtime import BrowserTaskLock
    from test_application_decisions import write_paper, replace_frontmatter
    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\ncompletion_providers: [arxiv]\n')
    paper_ids = []
    for index in (1, 2):
        paper_id = uuid4()
        paper_ids.append(paper_id)
        path = write_paper(workspace, paper_id, filename=f'{index}.md')
        replace_frontmatter(path, doi=f'10.5555/{index}', external_ids={'doi': f'10.5555/{index}', 'arxiv': f'2201.{index:05}'})
    batches = []
    def response(request):
        identifiers = request.url.params['id_list'].split(',')
        batches.append(identifiers)
        entries = []
        for identifier in identifiers:
            index = int(identifier[-1])
            relation = f'<arxiv:doi>10.48550/arxiv.2201.{index + 2:05}</arxiv:doi>' if index < 3 else ''
            entries.append(f'<entry><id>https://arxiv.org/abs/{identifier}</id><title>Title</title>'
                f'<published>2022-01-02T00:00:00Z</published>{relation}</entry>')
        return httpx.Response(200, text='<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">' + ''.join(entries) + '</feed>')
    service = ApiCompletion(config, BrowserTaskLock(), client_factory=lambda provider, **kwargs:
        SupplementalClient(provider, interval=0, transport=httpx.MockTransport(response), **kwargs))
    service.start(paper_ids)
    service.join()
    assert batches == [['2201.00001', '2201.00002'], ['2201.00003', '2201.00004']]
    assert service.state()['phase'] == 'Completed'
    assert all(result['first_public_status'] == 'recorded' for result in service.state()['results'])
