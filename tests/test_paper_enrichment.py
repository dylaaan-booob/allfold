from electron_test_helpers import OfflineBridge
from electron_test_helpers import PendingBridge
from allfold.application.browser_runtime import BrowserTaskLock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from test_application_decisions import write_paper
from test_web_app import write_valid_config
from allfold.application.paper_enrichment import (
    read_enrichment_target, save_enrichment, paper_fields, edit_paper_fields,
)
from allfold.persistence.markdown_state import MISSING_ABSTRACT, parse_paper_state
from allfold.models import WorkflowStatus
from allfold.persistence.safe_write import ContentChangedError
from allfold.application.coordinators.paper_enrichment import PaperEnrichment
from allfold.web.app import create_app


def missing(workspace, status=WorkflowStatus.CANDIDATE):
    paper_id = uuid4()
    path = write_paper(workspace, paper_id, status=status)
    original = path.read_text().replace('Decision abstract.', MISSING_ABSTRACT)
    original = original.replace('status:', '# Preserve YAML comment\ncustom: "do not normalize"\nstatus:')
    original += '\n## Custom section\n\nHuman notes.\n'
    path.write_text(original)
    return paper_id, path


def test_field_api_is_available_offline_and_respects_csrf_revision_and_workflow(tmp_path):
    config, workspace = write_valid_config(tmp_path)
    paper_id, path = missing(workspace)
    app = create_app(config, electron_bridge=OfflineBridge())
    with TestClient(app, base_url='http://localhost') as client:
        endpoint = f'/api/papers/{paper_id}'
        snapshot = client.get(f'{endpoint}/fields').json()
        body = {'revision': snapshot['revision'], 'abstract': 'Manual abstract.'}
        assert client.post(f'{endpoint}/abstract/input', json={**body, 'csrf_token': 'invalid'}).status_code == 403
        body['csrf_token'] = app.state.csrf_token
        from dataclasses import replace
        workflow=app.state.kept_workflow
        workflow._snapshot=replace(workflow.snapshot(),phase='preparing')
        before = path.read_bytes()
        assert client.post(f'{endpoint}/abstract/input', json=body).status_code == 409
        assert path.read_bytes() == before
        workflow._snapshot=replace(workflow.snapshot(),phase='idle')
        assert client.post(f'{endpoint}/abstract/input', json={**body, 'abstract': '  '}).status_code == 409
        assert client.post(f'{endpoint}/abstract/input', json=body).json()['saved'] is True
        assert client.post(f'{endpoint}/fields/reset', json={
            'csrf_token': app.state.csrf_token, 'revision': snapshot['revision'], 'fields': ['abstract'],
        }).status_code == 409
        snapshot = client.get(f'{endpoint}/fields').json()
        assert client.post(f'{endpoint}/fields/reset', json={
            'csrf_token': app.state.csrf_token, 'revision': snapshot['revision'], 'fields': ['abstract'],
        }).json()['saved'] is True
    assert parse_paper_state(path, path.read_text()).abstract is None


@pytest.mark.parametrize('mutation', ['contents', 'file', 'directory', 'workspace', 'doi', 'symlink'])
def test_external_changes_never_write(tmp_path, mutation):
    workspace = tmp_path / 'workspace'
    paper_id, path = missing(workspace)
    target = read_enrichment_target(workspace, paper_id)
    if mutation == 'contents': path.write_text(path.read_text() + 'User edit\n')
    elif mutation == 'doi': path.write_text(path.read_text().replace('10.5555/decision', '10.5555/other'))
    elif mutation == 'file':
        data = path.read_bytes(); path.unlink(); path.write_bytes(data)
    elif mutation == 'directory':
        old = workspace / 'OriginalPapers'; path.parent.rename(old)
        path.parent.mkdir(); path.write_bytes((old / path.name).read_bytes())
    elif mutation == 'workspace':
        workspace.rename(tmp_path / 'old'); paper_id2, path2 = missing(workspace)
        path2.write_bytes((tmp_path / 'old' / 'Papers' / 'paper.md').read_bytes())
    else:
        actual = path.with_suffix('.txt'); path.rename(actual); path.symlink_to(actual)
    before = path.read_bytes()
    with pytest.raises((ValueError, OSError, ContentChangedError)):
        save_enrichment(target, 'New abstract')
    assert path.read_bytes() == before


def service(tmp_path):
    paper_id, path = missing(tmp_path)
    capture = PendingBridge()
    return paper_id, path, capture, PaperEnrichment(capture, BrowserTaskLock())


def without_authors(workspace, status=WorkflowStatus.CANDIDATE, *, missing_abstract=False, missing_date=False):
    paper_id, path = missing(workspace, status)
    text = path.read_text()
    start, end = text.index('authors:\n'), text.index('journal:')
    text = text[:start] + 'authors: [] # retain author comment\n' + text[end:]
    if not missing_abstract: text = text.replace(MISSING_ABSTRACT, 'Existing Abstract')
    if missing_date: text = text.replace("publication_date: '2026-09-20'", 'publication_date: null')
    path.write_text(text)
    return paper_id, path


CREATORS = [
    {'creatorType': 'author', 'firstName': 'Ada', 'lastName': 'Lovelace', 'orcid': 'invented', 'openalex_id': 'invented'},
    {'creatorType': 'editor', 'firstName': 'Ignored', 'lastName': 'Editor'},
    {'creatorType': 'author', 'fieldMode': 1, 'lastName': 'Research Consortium'},
]
NAMES = ['Ada Lovelace', 'Research Consortium']


def test_author_snapshot_conflict_creates_no_author(tmp_path):
    paper_id, path = without_authors(tmp_path)
    target = read_enrichment_target(tmp_path, paper_id)
    path.write_text(path.read_text() + 'External edit\n'); edited = path.read_bytes()
    with pytest.raises(ContentChangedError): save_enrichment(target, authors=NAMES)
    assert path.read_bytes() == edited and not (tmp_path / 'Authors').exists()


def enrichment_command(enrich):
    import time
    deadline=time.monotonic()+2
    while (enrich.bridge.future is None or enrich.bridge.future.done()) and time.monotonic()<deadline:
        time.sleep(.005)
    assert enrich.bridge.future is not None and not enrich.bridge.future.done()
    return enrich.state(enrich._task['target'].paper_id)


def finish_enrichment(enrich, items):
    future = enrich.bridge.future
    if future.done():
        return None
    item = dict(items[0]) if len(items) == 1 else None
    if item is not None:
        for old, new in [('item_type','itemType'),('doi','DOI'),('abstract','abstractNote')]:
            if old in item:
                item[new] = item.pop(old)
    future.set_result({'item':item})
    enrich.join()
    return enrich.state(enrich._task['target'].paper_id)


@pytest.mark.parametrize('ordinary', ['month_upgrade', 'events_only'])
def test_web_enrich_saves_returned_events_with_or_without_ordinary_updates(tmp_path, ordinary):
    paper_id, path, bridge, enrich = service(tmp_path)
    path.write_text(path.read_text().replace("publication_date: '2026-09-20'", "publication_date: '2026-09'"))
    enrich.start(tmp_path, paper_id)
    enrichment_command(enrich)
    item = dict(itemType='journalArticle', DOI='10.5555/decision',
        accepted='2026-08', accepted_parts={'year': 2026, 'month': 8},
        date='2026-09-21' if ordinary == 'month_upgrade' else '2026-09',
        date_parts={'year': 2026, 'month': 9, **({'day': 21} if ordinary == 'month_upgrade' else {})})
    result = finish_enrichment(enrich, [item])
    assert result['phase'] == 'Completed'
    assert 'date_evidence' in result['saved']
    state = parse_paper_state(path, path.read_text())
    assert state.publication_date == ('2026-09-21' if ordinary == 'month_upgrade' else '2026-09')
    assert state.first_public_at is None
    assert {event.kind.value for event in state.date_evidence} == {'accepted', 'source-date'}


@pytest.mark.parametrize('change', ['doi', 'cancel', 'disconnect', 'revision'])
def test_web_date_events_share_all_response_and_revision_guards(tmp_path, change):
    from allfold.application.browser_runtime import ElectronDisconnected
    paper_id, path, bridge, enrich = service(tmp_path)
    state = enrich.start(tmp_path, paper_id)
    enrichment_command(enrich)
    if change == 'cancel':
        enrich.cancel(paper_id, state['request_id'])
    if change == 'revision':
        path.write_text(path.read_text() + 'Human edit\n')
    before = path.read_bytes()
    item = dict(itemType='journalArticle', DOI='10.5555/other' if change == 'doi' else '10.5555/decision',
                accepted='2026-08-01', accepted_parts={'year': 2026, 'month': 8, 'day': 1})
    if change == 'disconnect':
        bridge.future.set_exception(ElectronDisconnected('Disconnected'))
        enrich.join()
    else:
        finish_enrichment(enrich, [item])
    assert path.read_bytes() == before
