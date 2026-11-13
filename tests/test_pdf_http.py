from dataclasses import replace
from threading import Event
import time

import httpx
import pytest

from allfold.pdf_discovery import CandidateResult, CurrentResponse, PdfDiscovery
from allfold.pdf_http import PdfDiscoveryIO, PdfHttpClient, UnsafePdfTarget, ieee_metadata_inputs
from allfold.pdf_rules import PdfCandidate, PdfRuleInputs, PdfTarget


def client(handler, **options):
    return PdfHttpClient(guard=lambda: None, cancel_event=Event(), deadline=time.monotonic() + 20,
        resolver=lambda *_: ('8.8.8.8',), transport=httpx.MockTransport(handler), **options)


def target(host='www.sciencedirect.com', **values):
    return PdfTarget('paper-1', doi='10.1234/AbC', content_type='journal-article', content_host=host, **values)


def test_actual_http_redirect_final_url_is_relative_base_and_no_probe():
    seen = []
    def handle(request):
        seen.append(str(request.url))
        if len(seen) == 1:
            return httpx.Response(302, headers={'Location': 'https://cdn.example.org/Dir/Article'})
        if len(seen) == 2:
            return httpx.Response(200, headers={'Content-Type': 'text/html'}, content=b'''
                <head><meta name="citation_doi" content="10.1234/AbC">
                <meta name="citation_pdf_url" content="Body.PDF?sig=AbC&amp;pid=Keep"></head>''')
        return httpx.Response(200, headers={'Content-Type': 'application/pdf'}, content=b'controlled-transfer')
    paper = target('unrelated.example.org')
    from allfold.pdf_rules import KnownPdfUrl
    inputs = PdfRuleInputs(paper, known_pdf_urls=(KnownPdfUrl('https://publisher.example.org/download', 'API02', 'link'),))
    with client(handle) as http:
        result = PdfDiscovery(paper, inputs=inputs).run(lambda candidate: http.consume(candidate,
            transfer=lambda response, _: CandidateResult.pdf(transfer_complete=response.read() == b'controlled-transfer')))
    assert seen == ['https://publisher.example.org/download', 'https://cdn.example.org/Dir/Article',
        'https://cdn.example.org/Dir/Body.PDF?sig=AbC&pid=Keep']
    assert (result.status, result.pdf_source, result.fallback_used) == ('transferred', 'P2', False)


def test_pdf_header_alone_never_reads_body_or_claims_transfer():
    class Stream(httpx.SyncByteStream):
        closed = False
        def __iter__(self):
            raise AssertionError('No discovery PDF body reader')
        def close(self):
            self.closed = True
    stream = Stream()
    paper = target('onlinelibrary.wiley.com')
    with client(lambda _: httpx.Response(200, headers={'Content-Type': 'application/pdf'}, stream=stream)) as http:
        result = PdfDiscovery(paper).run(http.consume)
        assert result.status == 'pending'
        assert result.pdf_source is None
    assert stream.closed


@pytest.mark.parametrize('failure', [httpx.ReadError, httpx.RemoteProtocolError, httpx.DecodingError])
def test_current_response_stream_failure_closes_source_and_allows_next_candidate(failure):
    from allfold.pdf_rules import KnownPdfUrl
    class Broken(httpx.SyncByteStream):
        closed = False
        def __iter__(self):
            yield b'<head>'
            raise failure('Controlled current-response read failure')
        def close(self):
            self.closed = True
    stream, seen = Broken(), []
    paper = target('pubs.acs.org')
    inputs = PdfRuleInputs(paper, known_pdf_urls=(KnownPdfUrl('https://pubs.acs.org/broken', 'API02', 'link'),
        KnownPdfUrl('https://cdn.example.org/Body.PDF', 'API02', 'link')))
    def handle(request):
        seen.append(str(request.url))
        return (httpx.Response(200, headers={'Content-Type': 'text/html'}, stream=stream) if len(seen) == 1
            else httpx.Response(200, headers={'Content-Type': 'application/pdf'}))
    with client(handle) as http:
        result = PdfDiscovery(paper, inputs=inputs).run(lambda c: http.consume(c,
            transfer=lambda *_: CandidateResult.pdf(transfer_complete=True)))
    assert stream.closed and seen == ['https://pubs.acs.org/broken', 'https://cdn.example.org/Body.PDF']
    assert (result.status, result.pdf_source, result.fallback_used) == ('transferred', 'P2', True)
    assert result.diagnostics == (('P2', 'API02', 'source-failed'),)


def test_transfer_consumer_read_error_remains_terminal_instead_of_source_fallback():
    paper = target('onlinelibrary.wiley.com')
    def local_consumer(*_):
        raise httpx.ReadError('Consumer-owned failure must not be reclassified')
    with client(lambda _: httpx.Response(200, headers={'Content-Type': 'application/pdf'})) as http:
        with pytest.raises(httpx.ReadError, match='Consumer-owned'):
            PdfDiscovery(paper).run(lambda c: http.consume(c, transfer=local_consumer))


@pytest.mark.parametrize('stop', ['cancelled', 'expired', 'stale'])
def test_current_response_read_failure_cannot_hide_terminal_task_state(stop):
    from allfold.pdf_rules import KnownPdfUrl
    from allfold.providers.provider_http import Cancelled, ProviderBudgetExceeded
    from allfold.persistence.paper_repository import StaleWriteError
    cancel, clock, revoked, seen = Event(), [0.0], [False], []
    def guard():
        if revoked[0]:
            raise StaleWriteError('Captured task revoked')
    class Broken(httpx.SyncByteStream):
        closed = False
        def __iter__(self):
            yield b'<head>'
            if stop == 'cancelled':
                cancel.set()
            elif stop == 'expired':
                clock[0] = 11.0
            else:
                revoked[0] = True
            raise httpx.ReadError('Read failed after task state changed')
        def close(self):
            self.closed = True
    stream, paper = Broken(), target('pubs.acs.org')
    inputs = PdfRuleInputs(paper, known_pdf_urls=(KnownPdfUrl('https://pubs.acs.org/broken', 'API02', 'link'),
        KnownPdfUrl('https://cdn.example.org/MustNotStart.PDF', 'API02', 'link')))
    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(200, headers={'Content-Type': 'text/html'}, stream=stream)
    with PdfHttpClient(guard=guard, cancel_event=cancel, deadline=10, monotonic=lambda: clock[0],
            resolver=lambda *_: ('8.8.8.8',), transport=httpx.MockTransport(handle)) as http:
        with pytest.raises({'cancelled': Cancelled, 'expired': ProviderBudgetExceeded, 'stale': StaleWriteError}[stop]):
            PdfDiscovery(paper, inputs=inputs, guard=guard, cancel_event=cancel, deadline=10,
                monotonic=lambda: clock[0]).run(http.consume)
    assert stream.closed and seen == ['https://pubs.acs.org/broken']


def test_every_redirect_boundary_checks_dns_and_scopes_secrets_but_keeps_referer():
    seen = []
    def handle(request):
        seen.append((str(request.url), dict(request.headers)))
        if len(seen) == 1:
            return httpx.Response(303, headers={'Location': 'https://cdn.example.org/Body.PDF?Signature=Keep',
                'Set-Cookie': 'private=cookie; Domain=cdn.example.org'})
        return httpx.Response(200, headers={'Content-Type': 'application/pdf'})
    paper = target('onlinelibrary.wiley.com')
    candidate = PdfCandidate(paper, 'P2', 'API07', 'wiley',
        'https://api.wiley.com/onlinelibrary/tdm/v1/articles/10.1234%2FAbC',
        referer='https://onlinelibrary.wiley.com/Article', credential='wiley_tdm', accept='application/pdf')
    with client(handle, credentials=(('wiley_tdm', 'fixture-secret'),)) as http:
        http.consume(candidate)
    assert seen[0][1]['wiley-tdm-client-token'] == 'fixture-secret'
    assert 'wiley-tdm-client-token' not in seen[1][1]
    assert 'cookie' not in seen[1][1] and 'authorization' not in seen[1][1]
    assert seen[1][1]['referer'] == candidate.referer
    dispatched = []
    def blocked(request):
        dispatched.append(str(request.url))
        return httpx.Response(302, headers={'Location': 'https://internal.example.org/secret'})
    with PdfHttpClient(guard=lambda: None, cancel_event=Event(), deadline=time.monotonic() + 20,
            resolver=lambda host, _: ('10.1.2.3',) if host.startswith('internal') else ('8.8.8.8',),
            transport=httpx.MockTransport(blocked)) as http:
        outcome = http.consume(replace(candidate, credential=None))
    assert outcome.kind == 'failed'
    assert len(dispatched) == 1


def test_missing_pii_queries_handle_only_and_keeps_original_target_binding():
    seen = []
    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={'values': [{'type': 'URL', 'data': {
            'value': 'https://www.sciencedirect.com/science/article/pii/S014067362400123X'}}]})
    paper = target()
    with client(handle) as http:
        candidates = []
        result = PdfDiscovery(paper, io=PdfDiscoveryIO(http)).run(lambda c: (
            candidates.append(c) or CandidateResult.pdf(transfer_complete=True)))
    assert seen == ['https://doi.org/api/handles/10.1234/abc']
    assert candidates[0].url == 'https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft'
    assert candidates[0].target is paper
    assert (result.pdf_source, result.fallback_used) == ('P2', False)


@pytest.mark.parametrize('prior_optional_failure', [False, True])
def test_missing_id_query_routes_to_new_host_template_in_its_original_phase(prior_optional_failure):
    paper = target('www.sciencedirect.com')
    inputs = PdfRuleInputs(paper, credentials=frozenset({'elsevier'}) if prior_optional_failure else frozenset(),
        conditions=frozenset({'elsevier_pdf_access'}) if prior_optional_failure else frozenset())
    seen, consumed = [], []
    def handle(request):
        seen.append(str(request.url))
        if request.url.host == 'api.elsevier.com':
            return httpx.Response(403)
        if request.url.host == 'doi.org':
            return httpx.Response(200, json={'values': [{'type': 'URL', 'data': {
                'value': 'https://onlinelibrary.wiley.com/doi/10.1234/AbC'}}]})
        assert request.url.host == 'onlinelibrary.wiley.com'
        return httpx.Response(200, headers={'Content-Type': 'application/pdf'})
    with client(handle, credentials=(('elsevier', 'fixture-key'),) if prior_optional_failure else ()) as http:
        def consume(candidate):
            consumed.append(candidate)
            return http.consume(candidate, transfer=lambda *_: CandidateResult.pdf(transfer_complete=True))
        result = PdfDiscovery(paper, inputs=inputs, io=PdfDiscoveryIO(http)).run(consume)
    assert [httpx.URL(url).host for url in seen] == ((['api.elsevier.com'] if prior_optional_failure else [])
        + ['doi.org', 'onlinelibrary.wiley.com'])
    assert consumed[-1].rule_id == 'R002' and consumed[-1].stage == 'P2' and consumed[-1].target is paper
    assert (result.status, result.pdf_source, result.fallback_used) == ('transferred', 'P2', prior_optional_failure)


@pytest.mark.parametrize('landing,expected', [
    ('https://www.sciencedirect.com/science/article/pii/S1234567812345678',
     'https://www.sciencedirect.com/science/article/pii/S1234567812345678/pdfft'),
    ('https://ieeexplore.ieee.org/document/12345',
     'https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=12345&ref='),
])
def test_existing_crossref_resource_supplies_missing_internal_id_before_queries(landing, expected):
    from allfold.providers.crossref import normalize_crossref_discovered_work
    from datetime import datetime, timezone
    paper = target(httpx.URL(landing).host)
    record, _ = normalize_crossref_discovered_work({'DOI': paper.doi, 'type': 'journal-article',
        'title': ['Paper'], 'resource': {'primary': {'URL': landing}}}, datetime.now(timezone.utc))
    seen = []
    with client(lambda _: pytest.fail('Existing exact-work resource must be reused')) as http:
        result = PdfDiscovery(paper, facts=record.discovery_facts, io=PdfDiscoveryIO(http)).run(
            lambda c: seen.append(c) or CandidateResult.pdf(transfer_complete=True))
    assert seen[0].url == expected and seen[0].target is paper
    assert (result.pdf_source, result.fallback_used) == ('P2', False)


def test_existing_crossref_resource_cannot_override_actual_new_content_host():
    from allfold.pdf_facts import crossref_discovery_facts
    from datetime import datetime, timezone
    paper = target('www.sciencedirect.com', article_url='https://onlinelibrary.wiley.com/doi/10.1234/AbC')
    facts = crossref_discovery_facts({'DOI': paper.doi, 'resource': {'primary': {
        'URL': 'https://www.sciencedirect.com/science/article/pii/S1234567812345678'}}}, datetime.now(timezone.utc))
    seen = []
    result = PdfDiscovery(paper, facts=(facts,)).run(lambda c: seen.append(c) or CandidateResult.pdf(transfer_complete=True))
    assert seen[0].rule_id == 'R002' and result.pdf_source == 'P1'


def test_explicit_actual_article_route_outranks_an_older_document_landing():
    from datetime import datetime, timezone
    from allfold.pdf_facts import PdfDiscoveryFacts, PdfCandidateFact
    paper = target('pubs.acs.org', article_url='https://pubs.acs.org/current/article')
    cached = PdfDiscoveryFacts(source='document', capability='document-pdf', status='complete',
        observed_at=datetime.now(timezone.utc), target_doi=paper.identity_doi,
        landing_url='https://onlinelibrary.wiley.com/doi/10.1234/AbC',
        candidates=(PdfCandidateFact(stage='P3', rule_id='GENERIC', field='citation_pdf_url',
            url='https://cdn.example.org/Body.PDF'),))
    seen = []
    with client(lambda request: seen.append(str(request.url)) or httpx.Response(200,
            headers={'Content-Type': 'application/pdf'})) as http:
        result = PdfDiscovery(paper, facts=(cached,), io=PdfDiscoveryIO(http)).run(lambda c: http.consume(c,
            transfer=lambda *_: CandidateResult.pdf(transfer_complete=True)))
    assert seen == ['https://cdn.example.org/Body.PDF']
    assert (result.pdf_source, result.fallback_used) == ('P3', False)


def test_failed_optional_existing_source_does_not_block_still_missing_web_identifier():
    seen = []
    paper = target()
    inputs = PdfRuleInputs(paper, credentials=frozenset({'elsevier'}),
        conditions=frozenset({'elsevier_pdf_access'}))
    def handle(request):
        seen.append(str(request.url))
        if request.url.host == 'api.elsevier.com':
            return httpx.Response(403)
        if request.url.host == 'doi.org':
            return httpx.Response(200, json={'values': [{'type': 'URL', 'data': {
                'value': 'https://www.sciencedirect.com/science/article/pii/S1234567812345678'}}]})
        return httpx.Response(200, headers={'Content-Type': 'application/pdf'})
    with client(handle, credentials=(('elsevier', 'fixture-key'),)) as http:
        result = PdfDiscovery(paper, inputs=inputs, io=PdfDiscoveryIO(http)).run(lambda c: http.consume(c,
            transfer=lambda *_: CandidateResult.pdf(transfer_complete=True)))
    assert [httpx.URL(url).host for url in seen] == ['api.elsevier.com', 'doi.org', 'www.sciencedirect.com']
    assert (result.status, result.pdf_source, result.fallback_used) == ('transferred', 'P2', True)


def test_current_crossref_signed_pdf_field_is_not_lost_to_durable_projection():
    seen = []
    def handle(request):
        seen.append(str(request.url))
        if request.url.host == 'doi.org':
            return httpx.Response(200, json={'values': []})
        return httpx.Response(200, json={'message': {'DOI': '10.1234/AbC', 'alternative-id': ['bad'],
            'link': [{'URL': 'https://cdn.example.org/Body.PDF?token=AbC&Expires=Keep', 'content-type': 'application/pdf'}]}})
    paper = target()
    with client(handle) as http:
        attempted = []
        result = PdfDiscovery(paper, io=PdfDiscoveryIO(http)).run(lambda c: (
            attempted.append(c) or CandidateResult.pdf(transfer_complete=True)))
    assert [httpx.URL(url).host for url in seen] == ['doi.org', 'api.crossref.org']
    assert attempted[0].url == 'https://cdn.example.org/Body.PDF?token=AbC&Expires=Keep'
    assert result.pdf_source == 'P2'


@pytest.mark.parametrize('template_succeeds', [False, True])
def test_known_crossref_refresh_locator_is_used_only_after_reaching_p2(template_succeeds):
    from datetime import datetime, timezone
    from allfold.providers.crossref import normalize_crossref_discovered_work
    paper = target('onlinelibrary.wiley.com')
    old, _ = normalize_crossref_discovered_work({'DOI': paper.doi, 'link': [{'URL':
        'https://cdn.example.org/Old.PDF?Signature=Old', 'content-type': 'application/pdf'}]}, datetime.now(timezone.utc))
    signed = 'https://cdn.example.org/Current.PDF?Signature=Keep%2FCase&Expires=123'
    seen = []
    def handle(request):
        seen.append(str(request.url))
        if request.url.host == 'onlinelibrary.wiley.com':
            return httpx.Response(200, headers={'Content-Type': 'application/pdf'}) if template_succeeds else httpx.Response(404)
        if request.url.host == 'api.crossref.org':
            return httpx.Response(200, json={'message': {'DOI': paper.doi,
                'link': [{'URL': signed, 'content-type': 'application/pdf'}]}})
        assert str(request.url) == signed
        return httpx.Response(200, headers={'Content-Type': 'application/pdf'})
    with client(handle) as http:
        result = PdfDiscovery(paper, facts=old.discovery_facts, io=PdfDiscoveryIO(http)).run(lambda c: http.consume(c,
            transfer=lambda *_: CandidateResult.pdf(transfer_complete=True)))
    assert [httpx.URL(url).host for url in seen] == (['onlinelibrary.wiley.com'] if template_succeeds
        else ['onlinelibrary.wiley.com', 'api.crossref.org', 'cdn.example.org'])
    assert (result.status, result.pdf_source, result.fallback_used) == ('transferred',
        'P1' if template_succeeds else 'P2', not template_succeeds)
    assert old.discovery_facts[0].candidates[0].url is None


def test_complete_empty_crossref_capability_does_not_trigger_refresh_after_template_failure():
    from datetime import datetime, timezone
    from allfold.pdf_facts import crossref_discovery_facts
    paper, seen = target('onlinelibrary.wiley.com'), []
    facts = crossref_discovery_facts({'DOI': paper.doi, 'link': []}, datetime.now(timezone.utc))
    def handle(request):
        seen.append(str(request.url))
        assert request.url.host == 'onlinelibrary.wiley.com'
        return httpx.Response(404)
    with client(handle) as http:
        result = PdfDiscovery(paper, facts=(facts,), io=PdfDiscoveryIO(http)).run(http.consume)
    assert result.status == 'exhausted' and result.pdf_source is None and not result.fallback_used
    assert len(seen) == 1


@pytest.mark.parametrize('doi_endpoint', [False, True])
def test_optional_ieee_fixture_is_exact_and_known_number_needs_no_query(doi_endpoint):
    paper = target('ieeexplore.ieee.org')
    inputs = PdfRuleInputs(paper, conditions=frozenset({'ieee_doi_metadata'}) if doi_endpoint else frozenset())
    wrong = ieee_metadata_inputs({'articles': [{'doi': '10.9999/other', 'article_number': '999'}]}, paper, inputs)
    assert wrong == inputs
    for rule in ('API03', 'API04'):
        qualified = ieee_metadata_inputs({'articles': [{'doi': paper.doi, 'article_number': '123',
            'pdf_url': 'https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?arnumber=123'}]}, paper, inputs, rule=rule)
        assert qualified.identifiers == (('article_number', '123'),)
        assert qualified.known_pdf_urls[0].rule_id == rule
    seen = []
    def handle(request):
        seen.append(str(request.url))
        if request.url.host == 'doi.org':
            return httpx.Response(200, json={'values': []})
        assert request.url.params['apikey'] == 'fixture-key'
        return httpx.Response(200, json={'articles': [{'doi': paper.doi, 'article_number': '123'}]})
    with client(handle, credentials=(('ieee', 'fixture-key'),)) as http:
        result = PdfDiscovery(paper, inputs=inputs, io=PdfDiscoveryIO(http)).run(lambda _: CandidateResult.pdf(transfer_complete=True))
        assert result.pdf_source == 'P2'
    assert [httpx.URL(url).host for url in seen] == ['doi.org', 'ieeexploreapi.ieee.org']
    assert ('/articles/doi/' in httpx.URL(seen[-1]).path) == doi_endpoint
    with client(lambda _: pytest.fail('Known ID must not requery')) as http:
        result = PdfDiscovery(paper, inputs=replace(inputs, identifiers=(('article_number', '123'),)),
            io=PdfDiscoveryIO(http)).run(lambda _: CandidateResult.pdf(transfer_complete=True))
    assert result.pdf_source == 'P2'


@pytest.mark.parametrize('status,code', [(401, 'authorization'), (403, 'authorization'), (402, 'quota'), (404, 'not-found')])
def test_http_errors_remain_observable(status, code):
    paper = target('onlinelibrary.wiley.com')
    with client(lambda _: httpx.Response(status)) as http:
        result = PdfDiscovery(paper).run(http.consume)
    assert result.status == 'exhausted'
    assert result.diagnostics == (('P1', 'R002', code),)


def test_elsevier_current_json_uses_only_exact_work_scidir_pdf_and_scoped_api_header():
    seen = []
    def handle(request):
        seen.append((str(request.url), dict(request.headers)))
        if request.url.host == 'www.sciencedirect.com':
            return httpx.Response(404)
        if request.url.host == 'api.elsevier.com':
            return httpx.Response(200, json={'full-text-retrieval-response': {'coredata': {
                'prism:doi': '10.1234/AbC', 'link': [{'@rel': 'scidir', '@href': 'https://www.sciencedirect.com/article'},
                    {'@rel': 'scidir-pdf', '@href': 'https://cdn.example.org/Body.PDF?Signature=Keep'}]}}})
        return httpx.Response(200, headers={'Content-Type': 'application/pdf'})
    paper = target()
    inputs = PdfRuleInputs(paper, identifiers=(('pii', 'S014067362400123X'),), credentials=frozenset({'elsevier'}),
        conditions=frozenset({'elsevier_pdf_access'}))
    with client(handle, credentials=(('elsevier', 'fixture-secret'),)) as http:
        result = PdfDiscovery(paper, inputs=inputs).run(lambda c: http.consume(c,
            transfer=lambda *_: CandidateResult.pdf(transfer_complete=True)))
    assert [httpx.URL(url).host for url, _ in seen] == ['www.sciencedirect.com', 'www.sciencedirect.com', 'api.elsevier.com', 'cdn.example.org']
    assert seen[2][1]['x-els-apikey'] == 'fixture-secret'
    assert 'x-els-apikey' not in seen[3][1]
    assert seen[3][0] == 'https://cdn.example.org/Body.PDF?Signature=Keep'
    assert (result.pdf_source, result.fallback_used) == ('P2', True)


def test_optional_springer_metadata_accepts_exact_pdf_field_after_template_failure():
    seen = []
    def handle(request):
        seen.append(str(request.url))
        assert request.url.params['api_key'] == 'fixture-key'
        return httpx.Response(200, json={'records': [{'doi': '10.1234/AbC', 'url': [
            {'format': 'html', 'value': 'https://publisher.example.org/article'},
            {'format': 'pdf', 'value': 'https://cdn.example.org/Body.PDF?sig=Keep'}]}]})
    paper = target('link.springer.com')
    attempted = []
    def consume(c):
        attempted.append(c)
        return CandidateResult.failed() if c.stage == 'P1' else CandidateResult.pdf(transfer_complete=True)
    with client(handle, credentials=(('springer_metadata', 'fixture-key'),)) as http:
        result = PdfDiscovery(paper, io=PdfDiscoveryIO(http)).run(consume)
    assert len(seen) == 1 and httpx.URL(seen[0]).host == 'api.springernature.com'
    assert [(c.stage, c.rule_id) for c in attempted] == [('P1', 'R001'), ('P2', 'API09')]
    assert attempted[1].url == 'https://cdn.example.org/Body.PDF?sig=Keep'
    assert result.fallback_used


def test_native_reader_access_flow_receives_fixed_qualification_and_retains_p5_source():
    from concurrent.futures import Future
    from types import SimpleNamespace
    from allfold.pdf_facts import openalex_discovery_facts, PdfDiscoveryFacts
    from allfold.persistence.paper_repository import DirectIdentity
    from datetime import datetime, timezone
    class Context:
        calls = []
        def read_paper(self):
            return SimpleNamespace(primary_identity=DirectIdentity('doi', '10.1234/abc'))
        def native_payload(self):
            return {'paper_id': 'paper-1'}
        def execute_native(self, action, data):
            self.calls.append((action, data))
            future = Future()
            future.set_result({'outcome': 'retrieved', 'document': {
                'pageId': 1, 'processId': 2, 'frameToken': 'frame', 'documentId': 'doc', 'navigationGeneration': 1},
                'pdf_clues': {'status': 'complete', 'landing_url': data['reader']['url'],
                    'observed_at': '2026-11-14T00:00:00.000Z', 'platform': 'ieee', 'content_type': 'unknown',
                    'identifiers': [], 'diagnostics': [], 'candidates': [{'stage': 'P4', 'rule_id': 'R025',
                        'url': 'https://cdn.example.org/Body.PDF?Signature=Keep'}]}})
            return future
    paper = target('www.mdpi.com')
    facts = openalex_discovery_facts({'doi': paper.doi, 'best_oa_location': {
        'pdf_url': 'https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=123'}, 'locations': []}, datetime.now(timezone.utc))
    article = PdfDiscoveryFacts(source='document', capability='document-pdf', status='complete',
        target_doi=paper.identity_doi, observed_at=datetime.now(timezone.utc), landing_url='https://www.mdpi.com/article')
    context, seen = Context(), []
    def consume(c):
        seen.append(c)
        return CandidateResult.pdf(transfer_complete=True) if len(seen) > 1 else CandidateResult.current(
            CurrentResponse(c.url, 'text/html',
                b'<title>Verify you are human</title><iframe src="https://bad.example.org/challenge"></iframe>'))
    with client(lambda _: pytest.fail('No parallel HTTP')) as http:
        result = PdfDiscovery(paper, facts=(facts, article), io=PdfDiscoveryIO(http, document_context=context)).run(consume)
    assert len(context.calls) == 1
    action, data = context.calls[-1]
    assert action == 'extract_paper_pdf_clues'
    assert data['identity'] == {'doi': '10.1234/abc'}
    assert data['reader'] == {'rule_id': 'R025', 'platform': 'ieee', 'url': seen[0].url,
        'identifier': '123', 'source_url': seen[0].url, 'stage': 'P5', 'target': {'doi': '10.1234/abc'}}
    assert (result.pdf_source, result.fallback_used) == ('P5', False)


def test_current_form_action_stays_pending_and_is_never_mechanical_get():
    paper = target('www.microbiologyresearch.org')
    candidate = PdfCandidate(paper, 'P4', 'R059', 'microbiology', 'https://www.microbiologyresearch.org/action', action='refresh_form')
    with client(lambda _: pytest.fail('A form action is not a GET')) as http:
        outcome = http.consume(candidate)
    assert outcome.kind == 'pending' and not outcome.transfer_complete


def test_supported_current_silverchair_response_uses_explicit_selector_without_reopening_article():
    from allfold.pdf_rules import KnownPdfUrl
    paper = target('pubs.acs.org')
    inputs = PdfRuleInputs(paper, known_pdf_urls=(KnownPdfUrl('https://pubs.acs.org/current', 'API02', 'link'),))
    seen = []
    def handle(request):
        seen.append(str(request.url))
        if len(seen) == 1:
            return httpx.Response(200, headers={'Content-Type': 'text/html'}, content=b'''
                <head><meta name="citation_doi" content="10.1234/AbC"></head>
                <a class="article-pdfLink" href="/journal/article-pdf/Body.PDF?Signature=Keep">Full text</a>''')
        return httpx.Response(200, headers={'Content-Type': 'application/pdf'})
    with client(handle) as http:
        result = PdfDiscovery(paper, inputs=inputs, io=PdfDiscoveryIO(http)).run(lambda c: http.consume(c,
            transfer=lambda *_: CandidateResult.pdf(transfer_complete=True)))
    assert seen == ['https://pubs.acs.org/current', 'https://pubs.acs.org/journal/article-pdf/Body.PDF?Signature=Keep']
    assert (result.pdf_source, result.fallback_used) == ('P2', False)


@pytest.mark.parametrize('link', [
    '<a class="article-pdfLink" href="/Supplements.pdf">Supplementary information PDF</a>',
    '<a class="article-pdfLink" href="/issue.pdf">Whole issue PDF</a>',
    '<a class="article-pdfLink" href="/doi/pdf/10.1234/other">PDF</a>',
    '<a class="article-pdfLink" data-doi="10.1234/other" href="/other.pdf">PDF</a>',
])
def test_current_platform_selector_rejects_non_target_body_entries(link):
    from allfold.pdf_responses import parse_current_response
    paper = target('pubs.acs.org')
    candidate = PdfCandidate(paper, 'P2', 'API02', 'acs', 'https://pubs.acs.org/current')
    response = CurrentResponse(candidate.url, 'text/html',
        ('<head><meta name="citation_doi" content="10.1234/AbC"></head>'+link).encode())
    assert parse_current_response(candidate, response) == ()
