"""Isolated real-service races and DTO→disk→HTTP fixture for the built Reader.

Invoked by the Electron wrapper with a fresh Main-produced envelope. No generated
DTO, library, credential or HTTP result belongs in the source tree.
"""
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from copy import deepcopy
import json
from pathlib import Path
import sys
from threading import Barrier, Event, get_ident

import httpx
from fastapi.testclient import TestClient

from allfold.application.collection_runtime import BranchContext, WorkspaceRegistry
from allfold.application.document_metadata import collect_document_metadata, document_metadata_branch, validate_document_metadata
from allfold.application.metadata_completion import completion_client
from allfold.application.necessary_metadata import collect_necessary_metadata, necessary_metadata_branch
from allfold.application.task_clients import IndependentClientFactory
from allfold.application.task_authority import TaskAuthority
from allfold.models import ExternalIds
from allfold.persistence.paper_repository import IdentityConflict, PaperMetadata, PaperRepository, StaleWriteError
from allfold.web.app import create_app
from electron_test_helpers import OfflineBridge
from test_web_app import write_valid_config


API_TEXT = ('Background\nA complete structured API result with α < β and P < 0.05.\n'
    'Methods\n' + '\n'.join(f'Paragraph {i}: independent measurements preserve their original order and scientific text.' for i in range(35))
    + '\nResults\nLonger content never replaces an earlier valid abstract.')


class NativeResult:
    """External Bridge boundary, replaying only a fresh verified local DTO."""
    def __init__(self, envelope):
        self.envelope = envelope
        self.calls = []

    def execute(self, action, data, *args, **kwargs):
        self.calls.append((get_ident(), action, data))
        future = Future()
        if action == 'release_workflow_pages':
            future.set_result({'released': True})
        else:
            assert action == 'extract_paper_metadata'
            result = deepcopy(self.envelope)
            if not data['wantAbstract']:
                result['metadata']['abstract'] = None
            future.set_result(result)
        return future

    def cancel_task(self, *_):
        pass


def client_factory(events, abstract=API_TEXT):
    def response(request):
        filters = request.url.params.get('filter', '')
        if 'relation.type:' in filters:
            rows = []
        elif filters == 'doi:10.5555/formal':
            rows = [{'DOI': '10.5555/formal', 'type': 'journal-article',
                'abstract': abstract, 'published-online': {'date-parts': [[2020, 5]]},
                'published-print': {'date-parts': [[2026, 1, 2]]},
                'relation': {'has-preprint': [
                    {'id-type': 'doi', 'id': '10.5555/preprint'},
                    {'id-type': 'doi', 'id': '10.5555/earlier'}]}}]
        else:
            rows = [{'DOI': doi, 'type': 'posted-content', 'abstract': 'Unrelated preprint abstract.',
                'posted': {'date-parts': [date]}} for doi, date in (
                    ('10.5555/preprint', [2020, 5, 2]), ('10.5555/earlier', [2019, 1, 2]))
                    if doi in filters]
        return httpx.Response(200, json={'message': {'total-results': len(rows), 'items': rows}})

    @contextmanager
    def factory(provider, **kwargs):
        with completion_client(provider, transport=httpx.MockTransport(response), interval=0, **kwargs) as client:
            events.append(('opened', get_ident(), id(client)))
            yield client
        events.append(('closed', get_ident(), id(client)))
    return factory


class TransactionRaceRegistry(WorkspaceRegistry):
    def paper_gate(self):
        # Remove only the Python commit gate at this component seam, so the real
        # independent SQLite BEGIN IMMEDIATE transactions arbitrate the writes.
        # Admission/live checks retain the normal registry's captured owner.
        return nullcontext()


def component_race(path, native, order, *, mutation=None, empty_api=False):
    path.mkdir()
    with PaperRepository.create(path):
        pass
    events, bridge = [], NativeResult(native)
    factory = IndependentClientFactory(path.parent / 'missing.yaml',
        client_factory=client_factory(events, '<p> </p>' if empty_api else API_TEXT))
    registry = TransactionRaceRegistry(path, factory=factory, bridge=bridge,
        authority_capture=lambda service, providers: TaskAuthority.capture(factory.config_path, None, service, providers))
    branches = (document_metadata_branch(), necessary_metadata_branch(providers=('crossref',)))
    base = '  Original base.\n\nMethods: keep  ' if mutation == 'base' else None
    handle = registry.admit(direct_ids=ExternalIds(doi='10.5555/formal'),
        metadata=PaperMetadata(title='Formal', publication_type='journal', abstract=base), branches=branches)
    ready, release, first_done = Barrier(3), Event(), Event()
    first = 'document' if order == 'dom-first' else 'necessary-api'
    simultaneous = Barrier(2) if order == 'simultaneous' else None
    owners = []

    class CompetingRepository(PaperRepository):
        first_increment = True

        def commit_collection_branch(self, token, branch, **kwargs):
            if self.first_increment:
                self.first_increment = False
                ready.wait(timeout=10)
                assert release.wait(10)
                if simultaneous:
                    simultaneous.wait(timeout=10)
                elif branch != first:
                    assert first_done.wait(10)
            # The barrier is immediately before the real write transaction,
            # after ordinary context guards and candidate preparation.
            result = super().commit_collection_branch(token, branch, **kwargs)
            if branch == first:
                first_done.set()
            return result

    def worker(branch):
        # Construct and close every mutable execution resource in its own thread.
        with CompetingRepository.open(path) as repository:
            with factory.open(cancel_event=handle.cancel_event, deadline=handle.deadline,
                    request_guard=lambda: registry._guard(handle, repository), providers=branch.providers) as clients:
                owners.append((get_ident(), id(repository), id(clients)))
                context = BranchContext(registry, handle, repository, clients, branch, [])
                if branch.name == 'document':
                    return collect_document_metadata(context)
                return collect_necessary_metadata(context, providers=('crossref',))

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, branch) for branch in branches]
            ready.wait(timeout=10)
            with PaperRepository.open(path) as repository:
                paper = repository.get(handle.paper_id)
                repository.edit_metadata(paper.token, {'notes': 'Human notes survive.'})
                if mutation in {'manual', 'clear'}:
                    repository.edit_metadata(paper.token, {'abstract': 'Human abstract.' if mutation == 'manual' else None})
                elif mutation == 'reject-restore':
                    repository.restore(repository.exclude(paper.token).token)
            release.set()
            if mutation == 'reject-restore':
                for future in futures:
                    try:
                        future.result(15)
                    except StaleWriteError:
                        pass
                    else:
                        raise AssertionError('Reject→Restore renewed old service authority')
            else:
                for future in futures:
                    future.result(15)
        assert len({row[0] for row in owners}) == 2
        assert len({row[1] for row in owners}) == len({row[2] for row in owners}) == 2
        assert len(events) == 2 and events[0][0] == 'opened' and events[1][0] == 'closed'
        with PaperRepository.open(path) as repository:
            paper = repository.get(handle.paper_id)
            assert paper.metadata.notes == 'Human notes survive.'
            if mutation == 'reject-restore':
                assert paper.metadata.abstract is None and paper.metadata.ordinary_dates == ()
                return
            assert paper.metadata.ordinary_dates == ('2020-05-02', '2026-01-02')
            assert {item.year for item in paper.metadata.preprint_evidence} == {2019, 2020}
            assert paper.metadata.first_public_at is None
            expected = (base if mutation == 'base' else 'Human abstract.' if mutation == 'manual' else None if mutation == 'clear'
                else native['metadata']['abstract'] if order == 'dom-first' or empty_api else API_TEXT)
            if order == 'simultaneous' and mutation is None and not empty_api:
                assert paper.metadata.abstract in {native['metadata']['abstract'], API_TEXT}
            else:
                assert paper.metadata.abstract == expected
            # Repeated old sequence cannot refill a later user clear.
            saved = repository.edit_metadata(paper.token, {'abstract': None})
            delta = validate_document_metadata(native).delta
            assert repository.commit_collection_branch(handle.token, 'document', sequence=1, delta=delta) == saved
            # Identity conflict rolls back the whole actual native increment.
            other = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(pmid='999'),
                metadata=PaperMetadata(title='Other')).paper
            try:
                repository.commit_collection_branch(handle.token, 'document', sequence=2, delta=delta,
                    direct_ids=ExternalIds(pmid='999'))
            except IdentityConflict:
                pass
            else:
                raise AssertionError('Identity collision was accepted')
            assert repository.get(saved.id) == saved and repository.get(other.id) == other
            # All service Futures, clients and thread connections ended before settlement.
            for branch in paper.collection.branches:
                repository.commit_collection_branch(handle.token, branch.name,
                    sequence=branch.last_sequence + 1, outcome='completed')
            assert repository.finish_collection(handle.token).collection_status == 'completed'
    finally:
        release.set()
        registry.shutdown()
        registry.join()
        factory.close()


def project_paper(path, native, *, api=False, with_dom=False):
    path.mkdir()
    config, workspace = write_valid_config(path)
    workspace.mkdir()
    with PaperRepository.create(workspace):
        pass
    bridge, events = NativeResult(native), []
    factory = IndependentClientFactory(config, client_factory=client_factory(events))
    registry = WorkspaceRegistry(workspace, factory=factory, bridge=bridge,
        authority_capture=lambda service, providers: TaskAuthority.capture(config, None, service, providers))
    try:
        branch = necessary_metadata_branch(providers=('crossref',)) if api else document_metadata_branch()
        branches = (branch, document_metadata_branch()) if with_dom else (branch,)
        task = registry.submit(direct_ids=ExternalIds(doi='10.5555/formal'),
            metadata=PaperMetadata(title='API structured abstract' if api else 'DOM structured abstract',
                journal='Biometrics', journal_issns=('0006-341X',), publication_type='journal'), branches=branches)
        result = task.future.result(15)
        expected = API_TEXT if api else native['metadata']['abstract']
        assert result.metadata.abstract == expected
        if with_dom:
            assert [data['wantAbstract'] for _, action, data in bridge.calls if action == 'extract_paper_metadata'] == [False]
    finally:
        registry.shutdown()
        registry.join()
        factory.close()
    with PaperRepository.open(workspace) as reopened:
        assert reopened.get(result.id).metadata.abstract == expected
    with TestClient(create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=path / 'logs'), base_url='http://localhost') as client:
        response = client.get('/api/ui-next/workspace')
        assert response.status_code == 200
        payload = response.json()
        paper, = [paper for group in payload['subjects'] for journal in group['journals'] for paper in journal['papers']]
        assert paper['id'] == str(result.id) and paper['abstract'] == expected
    return paper


def main():
    native_path, output_path = (Path(value).resolve() for value in sys.argv[1:])
    native = json.loads(native_path.read_text())
    validate_document_metadata(native)
    root = output_path.parent
    for order in ('api-first', 'dom-first', 'simultaneous'):
        component_race(root / order, native, order)
    for mutation in ('manual', 'clear', 'reject-restore', 'base'):
        component_race(root / mutation, native, 'simultaneous', mutation=mutation)
    component_race(root / 'empty-api', native, 'api-first', empty_api=True)
    papers = [project_paper(root / source, native, api=source == 'api') for source in ('dom', 'api')]
    project_paper(root / 'serial', native, api=True, with_dom=True)
    output_path.write_text(json.dumps({'papers': papers}, ensure_ascii=False))
    print('METADATA PIPELINE PASS: 8 independent service races; serial registry; DOM/API disk→HTTP projections')


if __name__ == '__main__':
    main()
