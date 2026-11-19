from dataclasses import replace
from datetime import datetime, timezone
from threading import Event

import httpx
import pytest

from allfold.pdf_discovery import CandidateResult, CurrentResponse, PdfDiscovery
from allfold.pdf_facts import PdfCandidateFact, PdfDiscoveryFacts
from allfold.pdf_rules import KnownPdfUrl, PdfRuleInputs, PdfTarget


def target(host='onlinelibrary.wiley.com', **values):
    return PdfTarget('paper-1', doi='10.1234/AbC', content_host=host,
        content_type='journal-article', **values)


@pytest.mark.parametrize('cached',[False,True])
def test_openalex_later_distinct_locations_remain_eligible(cached):
    from allfold.pdf_facts import openalex_discovery_facts
    paper=target('unrecognised.example.org')
    urls=['https://repository.example.org/'+str(n)+'.pdf' for n in range(20)]
    raw={'doi':paper.doi,'best_oa_location':{'pdf_url':urls[0]},'locations':[
        {'pdf_url':url} for url in [urls[0],*urls]]}
    class IO:
        def openalex(self,doi):return raw
    seen=[]
    result=PdfDiscovery(paper,io=IO(),facts=(openalex_discovery_facts(raw,datetime.now(timezone.utc)),) if cached else ()).run(
        lambda c:seen.append(c.url) or (CandidateResult.pdf(transfer_complete=True) if c.url==urls[-1] else CandidateResult.failed()))
    assert result.status=='transferred' and result.pdf_source=='P5' and result.fallback_used
    assert seen==urls


def document(paper, candidates=(), status='complete'):
    return PdfDiscoveryFacts(source='document', capability='document-pdf', status=status,
        observed_at=datetime.now(timezone.utc), target_doi=paper.identity_doi,
        landing_url=paper.article_url or 'https://' + paper.content_host + '/article',
        candidates=tuple(candidates))


def test_lww_ambiguous_saved_article_numbers_do_not_choose_another_paper():
    from allfold.pdf_facts import PdfIdentifier
    paper = target('journals.lww.com', article_url='https://journals.lww.com/journal/fulltext/2026/paper.aspx')
    facts = document(paper).model_copy(update={'platform': 'lww', 'identifiers': (
        PdfIdentifier(kind='an', value='11111111-111111111-11111', rule_id='R060'),
        PdfIdentifier(kind='an', value='22222222-222222222-22222', rule_id='R060'))})
    result = PdfDiscovery(paper, facts=(facts,)).run(lambda _: pytest.fail('Ambiguous AN cannot choose a reader'))
    assert result.status == 'exhausted'


def test_exact_doi_free_work_cache_requires_trusted_direct_identity():
    from allfold.pdf_facts import openalex_discovery_facts
    facts = openalex_discovery_facts({'id': 'https://openalex.org/W123', 'doi': None,
        'best_oa_location': {'pdf_url': 'https://repository.example.org/Body.PDF'},
        'locations': []}, datetime.now(timezone.utc))
    paper = PdfTarget('paper-1', direct_identities=(('openalex', 'W123'),))
    seen = []
    result = PdfDiscovery(paper, facts=(facts,)).run(lambda c: seen.append(c) or CandidateResult.pdf(transfer_complete=True))
    assert len(seen) == 1 and seen[0].target is paper
    assert (result.pdf_source, result.fallback_used) == ('P5', False)
    for unrelated in (PdfTarget('paper-1'), replace(paper, direct_identities=(('openalex', 'W999'),))):
        assert PdfDiscovery(unrelated, facts=(facts,)).run(lambda _: pytest.fail('Unbound Work')).status == 'exhausted'


def test_t01_p1_confirmation_stops_before_any_later_io():
    class IO:
        def __getattr__(self, name):
            raise AssertionError('Unexpected later IO: ' + name)
    paper = target()
    seen = []
    def consume(candidate):
        seen.append(candidate)
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, io=IO()).run(consume)
    assert result.status == 'transferred'
    assert (result.pdf_source, result.fallback_used) == ('P1', False)
    assert [item.rule_id for item in seen] == ['R002']


@pytest.mark.parametrize('host,path', [
    ('epubs.siam.org', '/doi/10.1234/AbC'),
    ('onlinelibrary.wiley.com', '/doi/10.1234/AbC'),
    ('link.springer.com', '/article/10.1234/AbC'),
])
def test_direct_candidates_keep_qualified_article_referrer(host, path):
    paper = target(host, article_url='https://' + host + path)
    seen = []
    result = PdfDiscovery(paper).run(lambda c: seen.append(c)
        or CandidateResult.pdf(transfer_complete=True))
    assert len(seen) == 1 and seen[0].referer == paper.article_url
    assert seen[0].target is paper and result.status == 'transferred'


def test_explicit_candidate_referrer_is_not_replaced_by_article():
    paper = target('unknown.example.org', article_url='https://unknown.example.org/article')
    explicit = 'https://reader.example.org/current'
    facts = document(paper, [PdfCandidateFact(stage='P3', rule_id='GENERIC',
        url='https://cdn.example.org/current.pdf', referer=explicit)])
    seen = []
    PdfDiscovery(paper, facts=(facts,)).run(lambda c: seen.append(c)
        or CandidateResult.pdf(transfer_complete=True))
    assert seen[0].referer == explicit


def test_refreshed_document_referrer_uses_current_route_without_changing_target():
    from allfold.application.document_metadata import CurrentPdfClue, DocumentPdfResult
    paper = target('unknown.example.org', article_url='https://doi.org/10.1234/AbC')
    article = 'https://publisher.example.org/article/10.1234/AbC'
    class IO:
        def document(self, _):
            facts = document(paper).model_copy(update={'landing_url': article})
            return DocumentPdfResult(facts, (CurrentPdfClue('P3', 'GENERIC', 'https://cdn.example.org/current.pdf'),))
    seen = []
    PdfDiscovery(paper, io=IO()).run(lambda c: seen.append(c)
        or CandidateResult.pdf(transfer_complete=True))
    assert seen[0].referer == article and seen[0].target is paper


def test_missing_article_context_does_not_invent_a_referrer():
    seen = []
    PdfDiscovery(target()).run(lambda c: seen.append(c)
        or CandidateResult.pdf(transfer_complete=True))
    assert seen[0].referer is None


def test_explicit_initial_candidates_keep_their_own_request_context():
    from allfold.pdf_rules import PdfCandidate
    paper = target(article_url='https://onlinelibrary.wiley.com/doi/10.1234/AbC')
    original = PdfCandidate(paper, 'P2', 'GENERIC', 'generic', 'https://cdn.example.org/current.pdf')
    seen = []
    PdfDiscovery(paper, candidates=(original,)).run(lambda c: seen.append(c)
        or CandidateResult.pdf(transfer_complete=True))
    assert seen == [original] and seen[0] is original and original.referer is None


def test_reader_can_explicitly_suppress_referrer_on_its_session_continuation():
    from allfold.application.document_metadata import CurrentPdfClue, DocumentPdfResult
    paper = target('ieeexplore.ieee.org', article_url='https://ieeexplore.ieee.org/document/123')
    body, seen = 'https://cdn.example.org/current.pdf', []
    class IO:
        def reader(self, *_):
            return DocumentPdfResult(document(paper), (CurrentPdfClue('P4', 'R025', body, referer=None),))
    def consume(candidate):
        seen.append(candidate)
        if 'stampPDF' in candidate.url:
            assert candidate.referer == paper.article_url
            return CandidateResult.current(CurrentResponse(candidate.url, 'text/html', b'<html>Reader</html>'))
        assert candidate.url == body and candidate.referer is None
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, io=IO()).run(consume)
    assert len(seen) == 2 and result.status == 'transferred'


@pytest.mark.parametrize('host', ['epubs.siam.org', 'www.liebertpub.com'])
def test_shared_doi_direct_pdf_finishes_before_article_reader_and_oa_requests(host):
    class IO:
        def document(self, _):
            pytest.fail('A successful direct PDF must not open the article/ePDF reader')

        def openalex(self, _):
            pytest.fail('A successful direct PDF must not fall back to another version')

    paper = target(host, article_url='https://' + host + '/doi/10.1234/AbC')
    seen = []
    result = PdfDiscovery(paper, io=IO()).run(
        lambda candidate: seen.append(candidate) or CandidateResult.pdf(transfer_complete=True))
    assert result.status == 'transferred'
    assert (result.pdf_source, result.fallback_used) == ('P1', False)
    assert [(c.rule_id, c.url, c.target) for c in seen] == [
        ('R039', 'https://' + host + '/doi/pdf/10.1234/AbC', paper)]


@pytest.mark.parametrize('host,rule', [('epubs.siam.org', 'R061'), ('www.liebertpub.com', 'R039')])
def test_shared_doi_failed_direct_entry_keeps_observed_article_pdf_fallback(host, rule):
    paper = target(host, article_url='https://' + host + '/doi/10.1234/AbC')
    reader = 'https://' + host + '/doi/epdf/10.1234/AbC'
    facts = document(paper, [PdfCandidateFact(stage='P4', rule_id=rule, url=reader)])
    seen = []
    def consume(candidate):
        seen.append(candidate)
        return CandidateResult.failed() if candidate.stage == 'P1' else CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, facts=(facts,)).run(consume)
    assert [(c.stage, c.url) for c in seen] == [
        ('P1', 'https://' + host + '/doi/pdf/10.1234/AbC'), ('P4', reader)]
    assert (result.pdf_source, result.fallback_used) == ('P4', True)


@pytest.mark.parametrize('host,reader,kind', [
    ('www.sciencedirect.com', 'https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft', 'sciencedirect'),
    ('ieeexplore.ieee.org', 'https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=123', 'ieee'),
])
def test_available_direct_pdf_precedes_reader_and_optional_io(host, reader, kind):
    paper = target(host)
    direct = 'https://cdn.example.org/current.pdf'
    facts = document(paper, [
        PdfCandidateFact(stage='P3', rule_id='GENERIC', url=reader,
                         field='citation_pdf_url', reader_kind=kind),
        PdfCandidateFact(stage='P4', rule_id='GENERIC', url=direct),
    ])
    class IO:
        def query_missing(self, *_):
            pytest.fail('An available direct PDF precedes optional discovery requests')

        def document(self, _):
            pytest.fail('An available direct PDF needs no new Document')

    seen = []
    result = PdfDiscovery(paper, facts=(facts,), io=IO()).run(
        lambda candidate: seen.append(candidate.url) or CandidateResult.pdf(transfer_complete=True))
    assert seen == [direct]
    assert (result.pdf_source, result.fallback_used) == ('P4', False)


def test_available_direct_pdf_failure_preserves_reader_recovery():
    paper = target('ieeexplore.ieee.org')
    direct = 'https://cdn.example.org/current.pdf'
    reader = 'https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=123'
    facts = document(paper, [
        PdfCandidateFact(stage='P3', rule_id='GENERIC', url=reader,
                         field='citation_pdf_url', reader_kind='ieee'),
        PdfCandidateFact(stage='P4', rule_id='GENERIC', url=direct),
    ])
    seen = []
    result = PdfDiscovery(paper, facts=(facts,)).run(lambda candidate: seen.append(candidate.url)
        or (CandidateResult.failed() if candidate.url == direct else CandidateResult.pdf(transfer_complete=True)))
    assert seen == [direct, reader]
    assert (result.pdf_source, result.fallback_used) == ('P3', True)


def test_current_document_direct_pdf_precedes_its_reader_meta():
    from allfold.application.document_metadata import CurrentPdfClue, DocumentPdfResult
    paper = target('ieeexplore.ieee.org')
    direct = 'https://cdn.example.org/current.pdf'
    reader = 'https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=123'
    class IO:
        def document(self, _):
            return DocumentPdfResult(document(paper), (
                CurrentPdfClue('P3', 'GENERIC', reader, reader_kind='ieee', field='citation_pdf_url'),
                CurrentPdfClue('P4', 'GENERIC', direct),
            ))
    seen = []
    result = PdfDiscovery(paper, io=IO()).run(
        lambda candidate: seen.append(candidate.url) or CandidateResult.pdf(transfer_complete=True))
    assert seen == [direct]
    assert result.pdf_source == 'P4'


def ieee_document_entries(paper):
    from allfold.application.document_metadata import validate_document_pdf_clues
    return validate_document_pdf_clues({'outcome': 'retrieved', 'pdf_clues': {
        'status': 'complete', 'landing_url': 'https://ieeexplore.ieee.org/document/123',
        'observed_at': '2026-11-17T01:02:03.000Z', 'platform': 'ieee',
        'content_type': 'journal-article', 'identifiers': [], 'diagnostics': [],
        'candidates': [
            {'stage': 'P3', 'rule_id': 'R025', 'field': 'citation_pdf_url',
             'url': 'https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=123'},
            {'stage': 'P4', 'rule_id': 'R025', 'url': 'https://cdn.example.org/current.pdf'},
        ]}}, target_doi=paper.identity_doi)


@pytest.mark.parametrize('cached', [False, True])
def test_native_meta_without_reader_marker_keeps_direct_pdf_ahead_of_stamp(cached):
    paper = target('ieeexplore.ieee.org')
    parsed = ieee_document_entries(paper)
    assert parsed.current_candidates[0].reader_kind is None
    class IO:
        def document(self, _):
            return parsed
    seen = []
    def consume(candidate):
        seen.append(candidate.url)
        return (CandidateResult.pdf(transfer_complete=True) if candidate.url.endswith('/current.pdf')
            else CandidateResult.failed())
    result = PdfDiscovery(paper, facts=(parsed.facts,) if cached else (), io=IO()).run(consume)
    assert seen == (['https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=123&ref=']
        if cached else []) + ['https://cdn.example.org/current.pdf']
    assert result.pdf_source == 'P4'


@pytest.mark.parametrize('direct_succeeds', [True, False])
def test_html_reader_recovery_waits_for_existing_direct_and_retains_response_context(direct_succeeds):
    from allfold.application.document_metadata import CurrentPdfClue, DocumentPdfResult
    paper = target('ieeexplore.ieee.org')
    parsed = ieee_document_entries(paper)
    entry = 'https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=123&ref='
    direct = 'https://cdn.example.org/current.pdf'
    body = 'https://cdn.example.org/reader-body.pdf'
    response = CurrentResponse(entry, 'text/html', b'<html><body>Reader</body></html>',
                               context_key='a' * 64)
    seen, readers = [], []
    class IO:
        def reader(self, candidate, actual):
            assert seen == [entry, direct]
            assert candidate.target == paper and actual is response
            readers.append(candidate.url)
            return DocumentPdfResult(parsed.facts, (CurrentPdfClue('P4', 'R025', body),))
    def consume(candidate):
        seen.append(candidate.url)
        if candidate.url == entry:
            return CandidateResult.current(response)
        if candidate.url == direct and not direct_succeeds:
            return CandidateResult.failed()
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, facts=(parsed.facts,), io=IO()).run(consume)
    assert seen == [entry, direct] + ([] if direct_succeeds else [body])
    assert readers == ([] if direct_succeeds else [entry])
    assert result.status == 'transferred'


def test_newly_qualified_query_entries_prefer_direct_over_existing_reader():
    from allfold.pdf_discovery import P2Resolution
    paper = target('ieeexplore.ieee.org')
    reader = KnownPdfUrl('https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=123',
                         'R025', 'citation_pdf_url', reader_kind='ieee_stamp')
    inputs = PdfRuleInputs(paper)
    class IO:
        def query_missing(self, _, current, facts):
            yield P2Resolution(replace(current, known_pdf_urls=(reader,),
                                       identifiers=(('article_number', '123'),)))
        def reader(self, *_):
            pytest.fail('A newly qualified direct entry precedes the known Reader')
    seen = []
    def consume(candidate):
        seen.append(candidate.url)
        return (CandidateResult.current(CurrentResponse(reader.url, 'text/html', b'<html>Reader</html>'))
            if candidate.url == reader.url
            else CandidateResult.pdf(transfer_complete=True))
    result = PdfDiscovery(paper, inputs=inputs, io=IO()).run(consume)
    assert seen == ['https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=123&ref=']
    assert result.status == 'transferred'


@pytest.mark.parametrize('access', ['authorization', 'challenge'])
def test_queried_publisher_access_failure_tries_prepared_ebsco_before_document_refresh(access):
    from allfold.pdf_discovery import P2Resolution
    from allfold.pdf_rules import PdfCandidate

    publisher = 'https://publisher.example.org'
    paper = target('publisher.example.org', article_url=publisher+'/article')
    denied, licensed = publisher+'/body.pdf', 'https://content.ebscohost.com/cds/retrieve'

    class IO:
        def query_missing(self, _, inputs, facts):
            yield P2Resolution(replace(inputs, known_pdf_urls=(KnownPdfUrl(denied, 'API06', 'link'),)))

        def ebsco_candidates(self, target):
            return (PdfCandidate(target, 'P4', 'R073', 'ebsco', licensed),)

        def document(self, target):
            pytest.fail('Prepared EBSCO should be attempted before a separate publisher refresh')

    seen = []

    def consume(candidate):
        seen.append(candidate.url)
        if candidate.url == denied:
            return CandidateResult.current(CurrentResponse(denied, 'text/html', status=403, access=access))
        return CandidateResult.pdf(transfer_complete=True)

    result = PdfDiscovery(paper, io=IO()).run(consume)
    assert seen == [denied, licensed]
    assert (result.status, result.pdf_source, result.fallback_used) == ('transferred', 'P4', True)


@pytest.mark.parametrize('institution_body', ['available', 'failed', 'unprepared', 'direct'])
def test_prepared_ebsco_can_save_before_publisher_challenge_recovery(institution_body):
    from types import SimpleNamespace

    from allfold.pdf_discovery import PdfSourceReadError
    from allfold.pdf_rules import PdfCandidate

    publisher = 'https://publisher.example.org'
    paper = target('publisher.example.org', article_url=publisher+'/article')
    entry = publisher+'/body.pdf'
    licensed = 'https://content.ebscohost.com/cds/retrieve'
    direct = 'https://cdn.example.org/available.pdf'
    clues = [PdfCandidateFact(stage='P4', rule_id='GENERIC', url=entry)]
    if institution_body == 'direct':
        clues.append(PdfCandidateFact(stage='P4', rule_id='GENERIC', url=direct))
    facts = document(paper, clues)
    seen = []

    class IO:
        def ebsco_candidates(self, target):
            seen.append('EBSCO lookup')
            if institution_body == 'unprepared':
                raise PdfSourceReadError('EBSCO requires a prepared Service', diagnostic='service-unprepared')
            return (PdfCandidate(target, 'P4', 'R073', 'ebsco', licensed),)

        def reader(self, candidate, response):
            return SimpleNamespace(current_candidates=(replace(candidate, recover_access=True),))

    def consume(candidate):
        if candidate.recover_access:
            seen.append('publisher recovery')
            return CandidateResult.pdf(transfer_complete=True)
        seen.append(candidate.url)
        if candidate.url == entry:
            return CandidateResult.current(CurrentResponse(entry, 'text/html', status=403,
                                                           access='challenge'))
        if candidate.url == direct or institution_body == 'available':
            return CandidateResult.pdf(transfer_complete=True)
        return CandidateResult.failed()

    result = PdfDiscovery(paper, facts=(facts,), io=IO()).run(consume)
    expected = [entry, 'EBSCO lookup']
    if institution_body == 'direct':
        expected = [entry, direct]
    elif institution_body != 'unprepared':
        expected.append(licensed)
    if institution_body in {'failed', 'unprepared'}:
        expected.append('publisher recovery')
    assert seen == expected
    assert result.status == 'transferred'
    assert result.candidate.rule_id == ('R073' if institution_body == 'available' else 'GENERIC')


def test_qualified_reader_success_needs_no_optional_identifier_query():
    from allfold.application.document_metadata import CurrentPdfClue, DocumentPdfResult
    paper = target('ieeexplore.ieee.org')
    reader = KnownPdfUrl('https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=123',
                         'R025', 'citation_pdf_url', reader_kind='ieee_stamp')
    body = 'https://cdn.example.org/current.pdf'
    class IO:
        def query_missing(self, *_):
            pytest.fail('A qualified Reader can finish without optional identifier APIs')
        def reader(self, *_):
            return DocumentPdfResult(document(paper), (CurrentPdfClue('P4', 'R025', body),))
    seen = []
    def consume(candidate):
        seen.append(candidate.url)
        return (CandidateResult.current(CurrentResponse(reader.url, 'text/html', b'<html>Reader</html>'))
            if candidate.url == reader.url else CandidateResult.pdf(transfer_complete=True))
    result = PdfDiscovery(paper, inputs=PdfRuleInputs(paper, known_pdf_urls=(reader,)), io=IO()).run(consume)
    assert seen == [reader.url, body]
    assert result.status == 'transferred' and not result.fallback_used


@pytest.mark.parametrize('terminal', ['cancelled', 'stale', 'expired', 'local_failure'])
def test_terminal_direct_outcome_discards_deferred_reader(terminal):
    paper = target('ieeexplore.ieee.org')
    parsed = ieee_document_entries(paper)
    seen = []
    class IO:
        def reader(self, *_):
            pytest.fail('A terminal outcome must not resume the earlier Reader')
    def consume(candidate):
        seen.append(candidate.url)
        if 'stampPDF' in candidate.url:
            return CandidateResult.current(CurrentResponse(candidate.url, 'text/html', b'<html>Reader</html>'))
        return CandidateResult(terminal)
    result = PdfDiscovery(paper, facts=(parsed.facts,), io=IO()).run(consume)
    assert seen[-1] == 'https://cdn.example.org/current.pdf'
    assert result.status == ('local-failure' if terminal == 'local_failure' else terminal)


@pytest.mark.parametrize('download_entry_available', [True, False])
def test_sciencedirect_generated_download_entry_comes_before_reader_fallback(download_entry_available):
    from allfold.application.document_metadata import DocumentPdfResult, ReaderResult

    article = 'https://www.sciencedirect.com/science/article/pii/S014067362400123X'
    reader_url = article + '/pdfft'
    download_url = reader_url + '?download=true'
    body_url = 'https://cdn.example.org/Body.PDF'
    available = download_url if download_entry_available else reader_url
    paper = target('www.sciencedirect.com', article_url=article)
    facts = document(paper, [])
    calls = []

    class IO:
        def reader(self, candidate, response):
            calls.append(('reader', response.url))
            if response.url == available:
                return DocumentPdfResult(facts, (), reader_result=ReaderResult(
                    body_url, response.url, False, '0' * 64))
            return DocumentPdfResult(facts, ())

    def consume(candidate):
        assert candidate.target is paper
        calls.append(('get', candidate.url))
        if candidate.url in {download_url, reader_url}:
            return CandidateResult.current(CurrentResponse(candidate.url, 'text/html', b'<html>Reader</html>'))
        assert candidate.url == body_url
        assert candidate.referer == available
        return CandidateResult.pdf(transfer_complete=True)

    result = PdfDiscovery(paper, facts=(facts,), io=IO()).run(consume)
    expected = [('get', download_url), ('reader', download_url)]
    if not download_entry_available:
        expected.extend([('get', reader_url), ('reader', reader_url)])
    expected.append(('get', body_url))
    assert calls == expected
    assert (result.status, result.pdf_source, result.fallback_used) == ('transferred', 'P2', not download_entry_available)


@pytest.mark.parametrize('reader_succeeds', [True, False])
def test_reader_keeps_same_endpoint_template_variants_as_fallbacks(reader_succeeds):
    from allfold.application.document_metadata import CurrentPdfClue, DocumentPdfResult
    article = 'https://www.sciencedirect.com/science/article/pii/S014067362400123X'
    entry, body = article + '/pdfft?download=true', 'https://cdn.example.org/current.pdf'
    paper = target('www.sciencedirect.com', article_url=article)
    facts = document(paper, [PdfCandidateFact(stage='P4', rule_id='R024', url=entry,
                                            reader_kind='sciencedirect')])
    seen, readers = [], []
    class IO:
        def reader(self, candidate, response):
            readers.append(candidate.url)
            if reader_succeeds:
                return DocumentPdfResult(facts, (CurrentPdfClue('P4', 'R024', body),))
    def consume(candidate):
        seen.append(candidate.url)
        if candidate.url == entry:
            return CandidateResult.current(CurrentResponse(entry, 'text/html', b'<html>Reader</html>'))
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, facts=(facts,), io=IO()).run(consume)
    assert seen == [entry, body if reader_succeeds else article + '/pdfft']
    assert readers == [entry]
    assert result.fallback_used is not reader_succeeds


@pytest.mark.parametrize('winner', ['direct', 'reader', 'variant'])
def test_paused_reader_variants_wait_for_other_direct_and_their_original_reader(winner):
    from allfold.application.document_metadata import CurrentPdfClue, DocumentPdfResult
    article = 'https://www.sciencedirect.com/science/article/pii/S014067362400123X'
    entry, variant = article + '/pdfft?download=true', article + '/pdfft'
    direct, body = 'https://cdn.example.org/current.pdf', 'https://cdn.example.org/reader-body.pdf'
    paper = target('www.sciencedirect.com', article_url=article)
    facts = document(paper, [
        PdfCandidateFact(stage='P3', rule_id='R024', field='citation_pdf_url', url=variant),
        PdfCandidateFact(stage='P4', rule_id='R024', url=direct),
    ])
    seen, readers = [], []
    class IO:
        def reader(self, candidate, response):
            assert seen == [entry, direct]
            readers.append(candidate.url)
            if winner == 'reader':
                return DocumentPdfResult(facts, (CurrentPdfClue('P4', 'R024', body),))
    def consume(candidate):
        seen.append(candidate.url)
        if candidate.url == entry:
            return CandidateResult.current(CurrentResponse(entry, 'text/html', b'<html>Reader</html>'))
        if candidate.url == direct and winner != 'direct':
            return CandidateResult.failed()
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, facts=(facts,), io=IO()).run(consume)
    assert seen == [entry, direct] + ([] if winner == 'direct' else [body if winner == 'reader' else variant])
    assert readers == ([] if winner == 'direct' else [entry])
    assert result.status == 'transferred' and result.fallback_used


@pytest.mark.parametrize('host,article,entry', [
    ('www.sciencedirect.com', 'https://www.sciencedirect.com/science/article/pii/S014067362400123X',
     'https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft?download=true'),
    ('ieeexplore.ieee.org', 'https://ieeexplore.ieee.org/document/123',
     'https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=123&ref='),
])
@pytest.mark.parametrize('variant', [False, True])
def test_duplicate_meta_is_not_another_direct_source_or_fallback(host, article, entry, variant):
    from allfold.application.document_metadata import CurrentPdfClue, DocumentPdfResult
    paper = target(host, article_url=article)
    meta = entry + '&fixture-variant=1' if variant else entry
    facts = document(paper, [PdfCandidateFact(stage='P3', rule_id='R024' if 'sciencedirect' in host else 'R025',
                                            field='citation_pdf_url', url=meta)])
    body, seen = 'https://cdn.example.org/current.pdf', []
    class IO:
        def reader(self, *_):
            return DocumentPdfResult(facts, (CurrentPdfClue('P4', 'GENERIC', body),))
    def consume(candidate):
        seen.append(candidate.url)
        if candidate.url == entry:
            return CandidateResult.current(CurrentResponse(entry, 'text/html', b'<html>Reader</html>'))
        assert candidate.url == body, 'A duplicate Meta must not interrupt its original Reader'
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, facts=(facts,), io=IO()).run(consume)
    assert seen == [entry, body]
    assert not result.fallback_used


@pytest.mark.parametrize('alternative', ['failed', 'skipped'])
def test_resumed_reader_retains_original_source_index_and_skips_are_not_fallback(alternative):
    from allfold.application.document_metadata import CurrentPdfClue, DocumentPdfResult
    paper = target('ieeexplore.ieee.org')
    parsed = ieee_document_entries(paper)
    body, seen = 'https://cdn.example.org/reader-body.pdf', []
    class IO:
        def reader(self, *_):
            assert discovery.source_attempt == 1
            return DocumentPdfResult(parsed.facts, (CurrentPdfClue('P4', 'R025', body),))
    def consume(candidate):
        seen.append(candidate.url)
        if 'stampPDF' in candidate.url:
            return CandidateResult.current(CurrentResponse(candidate.url, 'text/html', b'<html>Reader</html>'))
        if candidate.url.endswith('/current.pdf'):
            return CandidateResult(alternative)
        return CandidateResult.pdf(transfer_complete=True)
    discovery = PdfDiscovery(paper, facts=(parsed.facts,), io=IO())
    result = discovery.run(consume)
    assert seen[-1] == body and discovery.source_attempt == 1
    assert result.fallback_used is (alternative == 'failed')


@pytest.mark.parametrize('host,landing,entry', [
    ('www.sciencedirect.com', 'https://www.sciencedirect.com/science/article/pii/S014067362400123X',
     'https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft?download=true'),
    ('opg.optica.org', 'https://opg.optica.org/abstract.cfm?uri=ao-63-1-1',
     'https://opg.optica.org/viewmedia.cfm?uri=ao-63-1-1'),
    ('ieeexplore.ieee.org', 'https://ieeexplore.ieee.org/document/123',
     'https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=123&ref='),
])
def test_possible_binary_entries_are_not_declared_readers_from_url(host, landing, entry):
    paper = target(host, article_url=landing)
    facts = document(paper, [
        PdfCandidateFact(stage='P3', rule_id='GENERIC', url=entry, field='citation_pdf_url'),
        PdfCandidateFact(stage='P4', rule_id='GENERIC', url='https://cdn.example.org/current.pdf'),
    ])
    seen = []
    result = PdfDiscovery(paper, facts=(facts,)).run(lambda c: seen.append(c.url)
        or CandidateResult.pdf(transfer_complete=True))
    assert seen == [entry] and result.status == 'transferred'


def test_p3_cache_keeps_stage_and_field_order_after_actual_failure():
    paper = target()
    facts = document(paper, [
        PdfCandidateFact(stage='P3', rule_id='GENERIC', url='https://cdn.example.org/full.pdf', field='fulltext_pdf_url'),
        PdfCandidateFact(stage='P3', rule_id='GENERIC', url='https://cdn.example.org/citation.pdf', field='citation_pdf_url'),
    ])
    seen = []
    def consume(candidate):
        seen.append(candidate)
        return CandidateResult.failed() if candidate.stage == 'P1' else CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, facts=(facts,)).run(consume)
    assert [(c.stage, c.url) for c in seen] == [
        ('P1', 'https://onlinelibrary.wiley.com/doi/pdfdirect/10.1234/AbC?download=true'),
        ('P3', 'https://cdn.example.org/citation.pdf')]
    assert (result.pdf_source, result.fallback_used) == ('P3', True)


def test_t15_sd_current_redirect_response_keeps_initial_source_and_actual_base():
    paper = target('www.sciencedirect.com', article_url='https://www.sciencedirect.com/science/article/pii/S014067362400123X')
    seen = []
    def consume(candidate):
        seen.append(candidate)
        if len(seen) == 1:
            return CandidateResult.current(CurrentResponse(
                'https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft',
                'text/html', b'<meta http-equiv="refresh" content="0; url=../../Files/Body.PDF?md5=AbC&amp;pid=Keep">'))
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper).run(consume)
    assert [c.url for c in seen] == [
        'https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft?download=true',
        'https://www.sciencedirect.com/science/article/Files/Body.PDF?md5=AbC&pid=Keep']
    assert (result.pdf_source, result.fallback_used) == ('P2', False)


def test_t16_challenge_iframe_is_not_reader():
    paper = target('ieeexplore.ieee.org', article_url='https://ieeexplore.ieee.org/document/123')
    seen = []
    def consume(candidate):
        seen.append(candidate)
        return CandidateResult.current(CurrentResponse(candidate.url, 'text/html',
            b'<title>Verify you are human</title><iframe src="https://cdn.example.org/challenge.pdf"></iframe>'))
    result = PdfDiscovery(paper).run(consume)
    assert len(seen) == 2
    assert all('challenge.pdf' not in c.url for c in seen)
    assert result.pdf_source is None


def test_sciencedirect_background_cloudflare_script_does_not_block_current_pdf_link():
    paper=target('www.sciencedirect.com',article_url='https://www.sciencedirect.com/science/article/pii/S014067362400123X')
    seen=[]
    def consume(candidate):
        seen.append(candidate)
        if len(seen)==1:
            return CandidateResult.current(CurrentResponse(candidate.url,'text/html',
                b'<html><title>View PDF</title><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
                b'<div class="PdfEmbed"><object data="https://pdf.sciencedirectassets.com/main.pdf?token=synthetic"></object></div></html>'))
        return CandidateResult.pdf(transfer_complete=True)
    result=PdfDiscovery(paper).run(consume)
    assert result.status=='transferred'
    assert seen[-1].url=='https://pdf.sciencedirectassets.com/main.pdf?token=synthetic'


@pytest.mark.parametrize('destination',[
    'https://pdf.sciencedirectassets.com/1-s2.0-S014067362400999X/main.pdf',
    'https://pdf.sciencedirectassets.com.evil.example/1-s2.0-S014067362400123X/main.pdf',
    'http://pdf.sciencedirectassets.com/1-s2.0-S014067362400123X/main.pdf',
])
def test_observed_get_redirect_is_not_limited_by_pii_host_or_filename(destination):
    from allfold.pdf_rules import PdfCandidate
    from allfold.pdf_responses import parse_current_response
    url='https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft'
    candidate=PdfCandidate(target(),'P1','R024','sciencedirect',url)
    response=CurrentResponse(url,'',status=302,redirect_url=destination)
    following,=parse_current_response(candidate,response)
    assert following.url==destination and following.stage==candidate.stage
    assert following.credential is None and following.access is candidate.access


@pytest.mark.parametrize('body',[
    '<article><h1>Article</h1><p>access denied, captcha and checking your browser are research terms.</p><input name="password" type="password"><iframe hidden src="https://newassets.hcaptcha.com/captcha"></iframe></article>',
    '<script src="https://www.google.com/recaptcha/api.js"></script><article>Normal content</article>',
    '<script>var errors="CPE00001 There was a problem providing the content you requested";</script><p>Article content</p>',
    '<p>Article content</p><iframe src="/_Incapsula_Resource?edet=15">Request unsuccessful. Incapsula incident ID: 123-456</iframe>',
])
def test_background_error_strings_or_embedded_frames_are_not_main_access_denials(body):
    from allfold.pdf_responses import access_limited
    assert not access_limited(CurrentResponse('https://publisher.example.org/article','text/html',body.encode()))


def test_openalex_cancel_is_never_recoverable_and_parent_expiry_wins_over_previous_http_error():
    from allfold.providers.openalex import OpenAlexClient
    from allfold.providers.provider_http import Cancelled, ProviderBudgetExceeded
    cancelled = Event()
    cancelled.set()
    with OpenAlexClient(cancel_event=cancelled, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))) as client:
        with pytest.raises(Cancelled):
            client.get_work_by_doi('10.1234/test')
    now = [0.0]
    def handle(_):
        now[0] = 2.0
        return httpx.Response(503)
    with OpenAlexClient(deadline=1.0, monotonic=lambda: now[0], transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderBudgetExceeded):
            client.get_work_by_doi('10.1234/test')


def test_t02_only_applicable_openalex_path_is_not_fallback_and_initialization_is_lazy():
    class IO:
        queried = []
        def openalex(self, doi):
            self.queried.append(doi)
            return {'doi': doi, 'best_oa_location': {'pdf_url': 'https://repository.example.org/Body.PDF'}}
    io = IO()
    discovery = PdfDiscovery(target('unrecognised.example.org'), io=io)
    assert io.queried == []
    result = discovery.run(lambda _: CandidateResult.pdf(transfer_complete=True))
    assert (result.pdf_source, result.fallback_used) == ('P5', False)
    assert io.queried == ['10.1234/abc']


@pytest.mark.parametrize('host,identifiers,url', [
    ('www.sciencedirect.com', (('pii', 'S014067362400123X'),), '/pii/S014067362400123X/pdfft?download=true'),
    ('ieeexplore.ieee.org', (('article_number', '123'),), '/getPDF.jsp?tp=&arnumber=123&ref='),
    ('www.jstor.org', (('jstor_stable_id', '10.2307/AbC/Part2'),), '/stable/pdfplus/10.2307/AbC/Part2.pdf'),
])
def test_t03_known_id_does_not_query_again(host, identifiers, url):
    class IO:
        def query_missing(self, *_):
            pytest.fail('Known target identifier must not be requeried')
    paper = target(host)
    seen = []
    result = PdfDiscovery(paper, inputs=PdfRuleInputs(paper, identifiers=identifiers), io=IO()).run(
        lambda c: seen.append(c) or CandidateResult.pdf(transfer_complete=True))
    assert seen[0].url.endswith(url)
    assert (result.pdf_source, result.fallback_used) == ('P2', False)


def test_t04_current_landing_host_wins_over_old_platform():
    paper = target('pubs.acs.org', platform='acs', article_url='https://www.annualreviews.org/content/journals/10.1234/AbC')
    seen = []
    result = PdfDiscovery(paper).run(lambda c: seen.append(c) or CandidateResult.pdf(transfer_complete=True))
    assert (seen[0].rule_id, seen[0].platform) == ('R006', 'annual_reviews')
    assert result.pdf_source == 'P1'


def test_t05_all_crossref_alternative_ids_are_qualified_before_use():
    from allfold.pdf_facts import crossref_discovery_facts
    paper = target('www.sciencedirect.com')
    facts = crossref_discovery_facts({'DOI': paper.doi, 'alternative-id': ['junk', 'S014067362400123X']}, datetime.now(timezone.utc))
    seen = []
    result = PdfDiscovery(paper, facts=(facts,)).run(lambda c: seen.append(c) or CandidateResult.pdf(transfer_complete=True))
    assert seen[0].url == 'https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft?download=true'
    assert result.pdf_source == 'P2'


def test_pdf_refresh_uses_observed_content_host_and_ids_before_openalex():
    from allfold.application.document_metadata import DocumentPdfResult
    from allfold.pdf_facts import PdfIdentifier, crossref_discovery_facts
    paper = PdfTarget('paper-1', doi='10.1016/j.example.2026.123456',
        article_url='https://linkinghub.elsevier.com/retrieve/pii/S014067362400123X',
        content_type='journal-article')
    facts = crossref_discovery_facts({'DOI': paper.doi,
        'alternative-id': ['S014067362400123X'],
        'resource': {'primary': {'URL': paper.article_url}}}, datetime.now(timezone.utc))
    calls, seen = [], []
    class IO:
        def query_missing(self, *_):
            return iter(())
        def document(self, _):
            calls.append('document')
            return DocumentPdfResult(PdfDiscoveryFacts(source='document', capability='document-pdf',
                status='complete', observed_at=datetime.now(timezone.utc), target_doi=paper.identity_doi,
                landing_url='https://www.sciencedirect.com/science/article/pii/S014067362400123X',
                platform='sciencedirect', identifiers=(
                    PdfIdentifier(kind='pii', value='S014067362400123X', rule_id='R024'),)), ())
        def openalex(self, doi):
            calls.append('openalex')
            return {'doi': doi, 'locations': []}
    result = PdfDiscovery(paper, facts=(facts,), io=IO()).run(
        lambda c: seen.append(c) or CandidateResult.pdf(transfer_complete=True))
    assert result.status == 'transferred'
    assert calls == ['document']
    assert len(seen) == 1 and seen[0].target is paper
    assert (seen[0].stage, seen[0].rule_id, seen[0].url) == ('P2', 'R024',
        'https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft?download=true')
    assert (result.pdf_source, result.fallback_used) == ('P2', False)


@pytest.mark.parametrize('landing', [
    'https://iopscience.iop.org/article/10.1234/other/meta',
    'https://journals.aps.org/prl/abstract/10.1234/other',
    'https://ascopubs.org/doi/full/10.1234/other',
    'https://ahajournals.org/doi/reader/10.1234/other',
    'https://journals.healio.com/doi/epdf/10.1234/other',
    'https://journals.uchicago.edu/doi/full/10.1234/other',
])
def test_pdf_refresh_does_not_transform_an_explicit_other_doi(landing):
    from allfold.application.document_metadata import DocumentPdfResult
    paper = PdfTarget('paper-1', doi='10.1234/original', content_type='journal-article')
    original_pdf = 'https://repository.example.org/Original.PDF'
    class IO:
        def document(self, _):
            return DocumentPdfResult(PdfDiscoveryFacts(source='document', capability='document-pdf',
                status='complete', observed_at=datetime.now(timezone.utc), target_doi=paper.identity_doi,
                landing_url=landing), ())
        def openalex(self, doi):
            return {'doi': doi, 'best_oa_location': {'pdf_url': original_pdf}}
    seen = []
    result = PdfDiscovery(paper, io=IO()).run(
        lambda c: seen.append(c.url) or CandidateResult.pdf(transfer_complete=True))
    assert seen == [original_pdf]
    assert result.pdf_source == 'P5'


def test_refreshed_article_backlink_enters_reader_before_another_article_get():
    from allfold.application.document_metadata import CurrentPdfClue, DocumentPdfResult
    article = 'https://www.sciencedirect.com/science/article/pii/S014067362400123X'
    entry, final = article + '/pdfft', 'https://pdf.sciencedirectassets.com/current.pdf?md5=Keep'
    paper = PdfTarget('paper-1', doi='10.1016/j.example.2026.123456',
        article_url='https://linkinghub.elsevier.com/retrieve/pii/S014067362400123X',
        content_type='journal-article')
    snapshot = PdfDiscoveryFacts(source='document', capability='document-pdf', status='complete',
        observed_at=datetime.now(timezone.utc), target_doi=paper.identity_doi,
        landing_url=article, platform='sciencedirect')
    calls = []
    class IO:
        def document(self, _):
            return DocumentPdfResult(snapshot, (CurrentPdfClue('P4', 'R024', entry, referer=article),))
        def reader(self, candidate, response):
            calls.append('reader')
            assert candidate.target is paper and response.url == entry
            return DocumentPdfResult(snapshot, (CurrentPdfClue('P4', 'R024', final),))
    def consume(candidate):
        calls.append(candidate.url)
        if candidate.url == entry:
            return CandidateResult.current(CurrentResponse(entry, '', status=302, redirect_url=article))
        assert candidate.url == final, 'The article backlink needs browser execution, not another GET'
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, io=IO()).run(consume)
    assert calls == [entry, 'reader', final]
    assert (result.pdf_source, result.fallback_used) == ('P4', False)


@pytest.mark.parametrize('host,doi', [
    ('ieeexplore.ieee.org', '10.1109/ABC.1234567'),
    ('www.nature.com', '10.1038/s41586.2026.0123'),
    ('www.mdpi.com', '10.3390/admsci3030032'),
])
def test_t06_t09_t10_unqualified_numeric_suffix_and_volume_guesses_never_dispatch(host, doi):
    paper = replace(target(host), doi=doi)
    facts = document(paper, [PdfCandidateFact(stage='P3', rule_id='GENERIC',
        url='https://cdn.example.org/Explicit.PDF', field='citation_pdf_url')])
    seen = []
    result = PdfDiscovery(paper, facts=(facts,)).run(lambda c: seen.append(c) or CandidateResult.pdf(transfer_complete=True))
    assert [(c.stage, c.url) for c in seen] == [('P3', 'https://cdn.example.org/Explicit.PDF')]
    assert (result.pdf_source, result.fallback_used) == ('P3', False)


def test_t07_oup_article_only_eprint_is_not_pdf_success():
    paper = target('academic.oup.com', article_url='https://academic.oup.com/journal/article/1/2/3/123')
    seen = []
    def consume(c):
        seen.append(c)
        if c.stage == 'P2':
            return CandidateResult.current(CurrentResponse(c.url, 'application/x-bibtex',
                b'@article{x, eprint={https://academic.oup.com/journal/article/1/2/3/123}}'))
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper).run(consume)
    assert [c.stage for c in seen] == ['P2']
    assert result.status == 'exhausted' and result.pdf_source is None


def test_oup_explicit_pdf_precedes_eprint_lookup():
    paper = target('academic.oup.com', article_url='https://academic.oup.com/journal/article/1/2/3/123')
    facts = document(paper, [PdfCandidateFact(stage='P3', rule_id='R020',
        url='https://cdn.example.org/Explicit.PDF', field='citation_pdf_url')])
    seen = []
    result = PdfDiscovery(paper, facts=(facts,)).run(lambda c: seen.append(c)
        or CandidateResult.pdf(transfer_complete=True))
    assert [(c.stage, c.url) for c in seen] == [('P3', 'https://cdn.example.org/Explicit.PDF')]
    assert (result.pdf_source, result.fallback_used) == ('P3', False)


def test_t08_stable_doi_like_path_survives_but_tdm_uuid_never_dispatches():
    paper = target('www.jstor.org', article_url='https://www.jstor.org/stable/10.2307/AbC/Part2')
    seen = []
    PdfDiscovery(paper).run(lambda c: seen.append(c) or CandidateResult.pdf(transfer_complete=True))
    assert seen[0].url == 'https://www.jstor.org/stable/pdfplus/10.2307/AbC/Part2.pdf'
    uuid = replace(paper, article_url='https://www.jstor.org/stable/a3ffb0c3-f9c7-4fa9-b61e-e3604524d443')
    assert PdfDiscovery(uuid).run(lambda _: pytest.fail('TDM UUID is not stable ID')).status == 'exhausted'


def test_t11_saved_acs_silverchair_entry_wins_and_retired_templates_stay_disabled():
    paper = target('pubs.acs.org')
    facts = document(paper, [
        PdfCandidateFact(stage='P4', rule_id='R062', url='https://pubs.acs.org/doi/pdf/10.1234/AbC'),
        PdfCandidateFact(stage='P4', rule_id='R044', url='https://pubs.acs.org/journal/article-pdf/Body.PDF')])
    seen = []
    result = PdfDiscovery(paper, facts=(facts,)).run(lambda c: seen.append(c) or CandidateResult.pdf(transfer_complete=True))
    assert [(c.stage, c.rule_id) for c in seen] == [('P4', 'R044')]
    assert result.fallback_used is False


@pytest.mark.parametrize('kind,rule', [('journal-article', 'R012'), ('conference-paper', 'R013'), ('unknown', None)])
def test_t12_spie_type_is_not_guessed(kind, rule):
    paper = replace(target('www.spiedigitallibrary.org'), content_type=kind)
    seen = []
    result = PdfDiscovery(paper).run(lambda c: seen.append(c) or CandidateResult.pdf(transfer_complete=True))
    assert [c.rule_id for c in seen] == ([rule] if rule else [])
    assert result.pdf_source == ('P1' if rule else None)


def test_t14_plos_manuscript_and_jats_are_never_pdf_confirmation():
    paper = target('journals.plos.org')
    facts = document(paper, [
        PdfCandidateFact(stage='P3', rule_id='R041', url='https://journals.plos.org/plosone/article/file?id=10.1234/AbC&type=manuscript', field='citation_pdf_url'),
        PdfCandidateFact(stage='P3', rule_id='R041', url='https://journals.plos.org/plosone/article/file?id=10.1234/AbC&type=printable', field='fulltext_pdf_url')])
    seen = []
    result = PdfDiscovery(paper, facts=(facts,)).run(lambda c: seen.append(c) or CandidateResult.current(
        CurrentResponse(c.url, 'application/xml', b'<article>JATS</article>')))
    assert len(seen) == 1 and 'type=printable' in seen[0].url
    assert result.pdf_source is None


def test_t17_lww_an_and_slug_supply_viewer_and_signed_current_context():
    from allfold.pdf_facts import PdfIdentifier, persistent_pdf_candidate
    paper = target('journals.lww.com', article_url='https://journals.lww.com/journal/fulltext/2026/Body.aspx')
    facts = document(paper).model_copy(update={'platform': 'lww', 'identifiers': (
        PdfIdentifier(kind='an', value='12345678-123456789-12345', rule_id='R060'),)})
    seen = []
    signed = 'https://cdn.example.org/Body.PDF?Signature=AbC&Expires=Keep'
    def consume(c):
        seen.append(c)
        if len(seen) == 1:
            return CandidateResult.current(CurrentResponse(c.url, 'text/html',
                ('<script type="application/json">{"pdfDownloadDetails":{"pdfUrl":"' + signed + '"}}</script>').encode()))
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, facts=(facts,)).run(consume)
    assert 'downloadpdf.aspx?trckng_src_pg=ArticleViewer&an=12345678-123456789-12345' in seen[0].url
    assert (seen[1].url, seen[1].referer) == (signed, seen[0].url)
    assert (result.pdf_source, result.fallback_used) == ('P4', False)
    durable = persistent_pdf_candidate(stage='P4', rule_id='R060', url=signed,
        refresh_kind='document-pdf', landing_url=paper.article_url, referer=seen[0].url)
    assert durable.url is None and durable.refresh.kind == 'document-pdf'


def test_t18_duplicate_candidates_and_reader_loops_do_not_repeat_request():
    paper = target('ieeexplore.ieee.org', article_url='https://ieeexplore.ieee.org/document/123')
    facts = document(paper, [PdfCandidateFact(stage='P3', rule_id='R025',
        url='https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=123&ref=', field='citation_pdf_url')])
    seen = []
    def consume(c):
        seen.append(c)
        return CandidateResult.current(CurrentResponse(c.url, 'text/html',
            ('<iframe src="' + c.url.replace('&', '&amp;') + '"></iframe>').encode()))
    result = PdfDiscovery(paper, facts=(facts,)).run(consume)
    assert len(seen) == len({c.url for c in seen}) == 2
    assert result.status == 'exhausted' and result.pdf_source is None


def test_t19_only_unambiguous_main_article_pdf_is_used():
    paper = target('unknown.example.org')
    inputs = PdfRuleInputs(paper, known_pdf_urls=(KnownPdfUrl('https://unknown.example.org/download', 'API02', 'link'),))
    seen = []
    def consume(c):
        seen.append(c)
        if len(seen) == 1:
            return CandidateResult.current(CurrentResponse(c.url, 'text/html', b'''
                <head><meta name="citation_doi" content="10.1234/AbC"></head><article>
                <a href="supplement.pdf" type="application/pdf">Supporting Information PDF</a>
                <a href="issue.pdf">Entire issue PDF</a><a href="Body.PDF">PDF</a></article>
                <section class="related"><a href="other.pdf">PDF</a></section>'''))
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, inputs=inputs).run(consume)
    assert [c.url for c in seen] == ['https://unknown.example.org/download', 'https://unknown.example.org/Body.PDF']
    assert result.fallback_used is False


def test_t20_missing_optional_api_credential_keeps_web_template_and_meta_available():
    paper = target()
    facts = document(paper, [PdfCandidateFact(stage='P3', rule_id='GENERIC',
        url='https://cdn.example.org/Body.PDF', field='citation_pdf_url')])
    seen = []
    def consume(c):
        seen.append(c)
        return CandidateResult.failed() if c.stage == 'P1' else CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, facts=(facts,), inputs=PdfRuleInputs(paper,
        conditions=frozenset({'wiley_tdm_access'}))).run(consume)
    assert [c.rule_id for c in seen] == ['R002', 'GENERIC']
    assert result.pdf_source == 'P3'


def test_t21_openalex_first_pdf_stops_without_version_comparison():
    from allfold.pdf_facts import openalex_discovery_facts
    paper = target('unknown.example.org')
    facts = openalex_discovery_facts({'doi': paper.doi, 'best_oa_location': {'pdf_url': 'https://repository.example.org/preprint.PDF'},
        'locations': [{'pdf_url': 'https://publisher.example.org/published.PDF'}]}, datetime.now(timezone.utc))
    seen = []
    result = PdfDiscovery(paper, facts=(facts,)).run(lambda c: seen.append(c) or CandidateResult.pdf(transfer_complete=True))
    assert [c.url for c in seen] == ['https://repository.example.org/preprint.PDF']
    assert result.pdf_source == 'P5'


@pytest.mark.parametrize('terminal', ['cancel', 'expiry', 'stale'])
def test_t22_terminal_parent_state_stops_all_followup(terminal):
    from allfold.providers.provider_http import Cancelled, ProviderBudgetExceeded
    cancelled, now, stale = Event(), [0.0], [False]
    def guard():
        if stale[0]:
            raise RuntimeError('Captured authority revoked')
    paper = target()
    seen = []
    def consume(c):
        seen.append(c)
        if terminal == 'cancel':
            cancelled.set()
        elif terminal == 'expiry':
            now[0] = 2.0
        else:
            stale[0] = True
        return CandidateResult.failed()
    with pytest.raises({'cancel': Cancelled, 'expiry': ProviderBudgetExceeded, 'stale': RuntimeError}[terminal]):
        PdfDiscovery(paper, cancel_event=cancelled, guard=guard, deadline=1.0, monotonic=lambda: now[0]).run(consume)
    assert len(seen) == 1


@pytest.mark.parametrize('terminal', ['cancel', 'expiry', 'stale'])
def test_completed_transfer_survives_late_parent_signal(terminal):
    cancelled, now, stale = Event(), [0.0], [False]
    def guard():
        if stale[0]:
            raise RuntimeError('Captured authority revoked')
    seen = []
    def consume(candidate):
        seen.append(candidate)
        if terminal == 'cancel':
            cancelled.set()
        elif terminal == 'expiry':
            now[0] = 2.0
        else:
            stale[0] = True
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(target(), cancel_event=cancelled, guard=guard,
        deadline=1.0, monotonic=lambda: now[0]).run(consume)
    assert (result.status, result.pdf_source, len(seen)) == ('transferred', 'P1', 1)


def test_t23_same_candidate_retry_and_known_chain_are_not_fallback():
    paper = target('ieeexplore.ieee.org', article_url='https://ieeexplore.ieee.org/document/123')
    seen = []
    def consume(c):
        seen.append(c)
        if len(seen) == 1:
            return CandidateResult('retry')
        if len(seen) == 2:
            return CandidateResult.current(CurrentResponse(c.url, 'text/html', b'<iframe src="https://cdn.example.org/Body.PDF?token=Keep"></iframe>'))
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper).run(consume)
    assert len(seen) == 3 and seen[0].url == seen[1].url
    assert (result.pdf_source, result.fallback_used) == ('P2', False)


def test_t24_pending_candidate_has_no_success_source_and_local_failure_never_falls_back():
    paper = target()
    result = PdfDiscovery(paper).run(lambda _: CandidateResult.pdf())
    assert (result.status, result.pdf_source) == ('pending', None)
    seen = []
    def consume(c):
        seen.append(c)
        return CandidateResult('local_failure', pdf_type=True, transfer_complete=True, diagnostic='association-failed')
    result = PdfDiscovery(paper).run(consume)
    assert (result.status, result.pdf_source, len(seen)) == ('local-failure', None, 1)


@pytest.mark.parametrize('status,expected_queries', [('complete', 0), ('partial', 1), ('failed', 1)])
def test_openalex_complete_empty_reuses_capability_but_partial_or_failed_queries_only_at_p5(status, expected_queries):
    paper = target('unknown.example.org')
    facts = PdfDiscoveryFacts(source='openalex', capability='openalex-locations', status=status,
        target_doi=paper.identity_doi, observed_at=datetime.now(timezone.utc))
    class IO:
        queries = []
        def openalex(self, doi):
            self.queries.append(doi)
            return {'doi': doi, 'best_oa_location': None, 'locations': []}
    io = IO()
    result = PdfDiscovery(paper, facts=(facts,), io=io).run(lambda _: pytest.fail('No PDF field'))
    assert len(io.queries) == expected_queries
    assert result.pdf_source is None
    assert result.fallback_used is False


def test_p5_signed_persisted_locator_is_requeried_and_current_raw_query_is_preserved():
    from allfold.pdf_facts import openalex_discovery_facts
    paper = target('unknown.example.org')
    raw = {'doi': paper.doi, 'best_oa_location': {'pdf_url': 'https://repository.example.org/Old.PDF?token=Old'}, 'locations': []}
    facts = openalex_discovery_facts(raw, datetime.now(timezone.utc))
    assert facts.status == 'complete' and facts.candidates[0].url is None
    class IO:
        count = 0
        def openalex(self, doi):
            self.count += 1
            return {'doi': doi, 'best_oa_location': {'pdf_url': 'https://repository.example.org/Body.PDF?token=AbC&Expires=Keep#page=2'},
                'locations': [{'pdf_url': 'https://content.openalex.org/works/W123.pdf'},
                    {'landing_page_url': 'https://publisher.example.org/article'},
                    {'pdf_url': 'http://127.0.0.1/body.pdf'}]}
    io, seen = IO(), []
    result = PdfDiscovery(paper, facts=(facts,), io=io).run(lambda c: seen.append(c) or CandidateResult.pdf(transfer_complete=True))
    assert io.count == 1 and seen[0].url == 'https://repository.example.org/Body.PDF?token=AbC&Expires=Keep'
    assert result.pdf_source == 'P5'


@pytest.mark.parametrize('refresh', ['unavailable', 'failed', 'not-found', 'empty', 'duplicate'])
def test_p5_refresh_never_discards_later_stable_cache(refresh):
    from allfold.pdf_facts import openalex_discovery_facts
    from allfold.pdf_discovery import PdfSourceReadError
    from allfold.providers.openalex import OpenAlexNotFoundError
    paper = target('unknown.example.org')
    stable = 'https://repository.example.org/Body.PDF'
    fact = openalex_discovery_facts({'doi': paper.doi,
        'best_oa_location': {'pdf_url': 'https://publisher.example.org/old.pdf?token=old'},
        'locations': [{'pdf_url': stable}]}, datetime.now(timezone.utc))
    class IO:
        openalex_available = refresh != 'unavailable'
        def openalex(self, doi):
            if refresh == 'failed':
                raise PdfSourceReadError('unavailable', diagnostic='provider-unavailable')
            if refresh == 'not-found':
                raise OpenAlexNotFoundError('missing')
            return {'doi': doi, 'best_oa_location': {'pdf_url': stable} if refresh == 'duplicate' else None,
                'locations': [{'pdf_url': stable}] if refresh == 'duplicate' else []}
    seen = []
    def consume(candidate):
        seen.append(candidate.url)
        return CandidateResult.failed()
    PdfDiscovery(paper, facts=(fact,), io=IO()).run(consume)
    assert seen == [stable]


def test_p5_best_first_dedup_and_exact_doi():
    paper = target('unknown.example.org')
    class IO:
        doi = paper.doi
        def openalex(self, _):
            return {'doi': self.doi, 'best_oa_location': {'pdf_url': 'https://repository.example.org/Best.PDF?x=AbC#page=1'},
                'locations': [{'pdf_url': 'https://repository.example.org/Best.PDF?x=AbC#page=2'},
                    {'pdf_url': 'https://openalex.org/W123.pdf'},
                    {'pdf_url': 'https://cdn.example.org/2.pdf'}, {'pdf_url': 'https://cdn.example.org/3.pdf'},
                    {'pdf_url': 'https://cdn.example.org/4.pdf'}, {'pdf_url': 'https://cdn.example.org/5.pdf'}]}
    io, seen = IO(), []
    result = PdfDiscovery(paper, io=io).run(lambda c: seen.append(c) or CandidateResult.failed())
    assert [c.url for c in seen] == ['https://repository.example.org/Best.PDF?x=AbC',
        'https://cdn.example.org/2.pdf', 'https://cdn.example.org/3.pdf', 'https://cdn.example.org/4.pdf', 'https://cdn.example.org/5.pdf']
    assert result.pdf_source is None and result.fallback_used
    io.doi = '10.9999/other'
    assert PdfDiscovery(paper, io=io).run(lambda _: pytest.fail('Wrong exact Work')).status == 'exhausted'


def test_empty_p5_does_not_invent_another_physical_attempt():
    class IO:
        def openalex(self, doi):
            return {'doi': doi, 'best_oa_location': None, 'locations': []}
    result = PdfDiscovery(target(), io=IO()).run(lambda _: CandidateResult.failed())
    assert result.status == 'exhausted' and not result.fallback_used and result.pdf_source is None


def test_sciencedirect_md5_current_url_stays_intact_but_durable_fact_requires_refresh():
    from allfold.pdf_facts import persistent_pdf_candidate
    from allfold.application.document_metadata import CurrentPdfClue, DocumentPdfResult
    paper = target('www.sciencedirect.com')
    signed = 'https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft?md5=AbC&pid=Keep'
    durable = persistent_pdf_candidate(stage='P4', rule_id='R024', url=signed,
        refresh_kind='document-pdf', landing_url='https://www.sciencedirect.com/science/article/pii/S014067362400123X')
    assert durable.url is None and durable.refresh.kind == 'document-pdf'
    facts = document(paper, [durable])
    class IO:
        queried = 0
        def document(self, _):
            self.queried += 1
            return DocumentPdfResult(facts, (CurrentPdfClue('P4', 'R024', signed),))
    io, seen = IO(), []
    result = PdfDiscovery(paper, facts=(facts,), io=io).run(lambda c: seen.append(c) or CandidateResult.pdf(transfer_complete=True))
    assert io.queried == 1 and seen[0].url == signed
    assert result.pdf_source == 'P4'


def test_p5_candidate_can_resolve_known_ieee_reader_without_losing_original_source():
    from allfold.pdf_facts import openalex_discovery_facts
    paper = target('unrecognised.example.org')
    facts = openalex_discovery_facts({'doi': paper.doi, 'best_oa_location': {
        'pdf_url': 'https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=123'}, 'locations': []}, datetime.now(timezone.utc))
    seen = []
    def consume(c):
        seen.append(c)
        if len(seen) == 1:
            return CandidateResult.current(CurrentResponse(c.url, 'text/html', b'<iframe src="https://cdn.example.org/Body.PDF"></iframe>'))
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, facts=(facts,)).run(consume)
    assert len(seen) == 2 and all(c.rule_id == 'OPENALEX' for c in seen)
    assert (result.pdf_source, result.fallback_used) == ('P5', False)


def test_long_known_chain_uses_parent_deadline_instead_of_hop_or_operation_counts():
    from allfold.providers.provider_http import ProviderBudgetExceeded
    paper=target('ieeexplore.ieee.org',article_url='https://ieeexplore.ieee.org/document/123')
    seen=[]
    def consume(c):
        seen.append(c)
        if len(seen)==60:return CandidateResult.pdf(transfer_complete=True)
        return CandidateResult.current(CurrentResponse(c.url,'text/html',
            ('<iframe src="https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=123&hop='+str(len(seen))+'"></iframe>').encode()))
    result=PdfDiscovery(paper).run(consume)
    assert result.status=='transferred' and len(seen)==60 and not result.fallback_used
    clock=[0]
    def timed(c):
        clock[0]+=1
        return consume(c)
    with pytest.raises(ProviderBudgetExceeded):
        PdfDiscovery(paper,deadline=3,monotonic=lambda:clock[0]).run(timed)


def test_cached_p5_stable_best_stops_before_later_signed_locator_requires_refresh():
    from allfold.pdf_facts import openalex_discovery_facts
    paper = target('unknown.example.org')
    facts = openalex_discovery_facts({'doi': paper.doi, 'best_oa_location': {'pdf_url': 'https://repository.example.org/Best.PDF'},
        'locations': [{'pdf_url': 'https://cdn.example.org/Body.PDF?token=Expired'}]}, datetime.now(timezone.utc))
    class IO:
        def openalex(self, _):
            pytest.fail('First stable candidate succeeded before refresh was needed')
    result = PdfDiscovery(paper, facts=(facts,), io=IO()).run(lambda _: CandidateResult.pdf(transfer_complete=True))
    assert result.pdf_source == 'P5'


def test_partial_openalex_retains_qualified_increment_before_refresh():
    from allfold.pdf_facts import openalex_discovery_facts
    paper=target('unknown.example.org')
    fact=openalex_discovery_facts({'doi':paper.doi,'best_oa_location':{'pdf_url':'https://repository.example.org/body.pdf'}},datetime.now(timezone.utc))
    assert fact.status=='partial'
    class IO:
        def openalex(self,_):pytest.fail('A qualified retained increment can finish before refresh')
    result=PdfDiscovery(paper,facts=(fact,),io=IO()).run(lambda _:CandidateResult.pdf(transfer_complete=True))
    assert result.status=='transferred' and result.pdf_source=='P5' and not result.fallback_used


def test_unrelated_deep_reader_json_cannot_erase_a_qualified_link():
    from allfold.pdf_rules import PdfCandidate
    paper=target('www.sciencedirect.com',article_url='https://www.sciencedirect.com/science/article/pii/S014067362400123X')
    candidate=PdfCandidate(paper,'P2','R024','sciencedirect',paper.article_url+'/pdfft')
    seen=[]
    def consume(item):
        seen.append(item.url)
        if len(seen)>1:return CandidateResult.pdf(transfer_complete=True)
        body=(b'<div class="PdfEmbed"><object data="https://cdn.example.org/body.pdf"></object></div>'
            b'<script type="application/json">'+b'['*10000+b'0'+b']'*10000+b'</script>')
        return CandidateResult.current(CurrentResponse(item.url,'text/html',body))
    result=PdfDiscovery(paper,candidates=(candidate,)).run(consume)
    assert result.status=='transferred' and seen[-1]=='https://cdn.example.org/body.pdf'
    assert ('P2','R024','parse-failed') in result.diagnostics


def test_reader_self_loop_failure_then_alternative_reports_actual_fallback():
    from allfold.pdf_rules import PdfCandidate
    paper=target('ieeexplore.ieee.org',article_url='https://ieeexplore.ieee.org/document/123')
    reader='https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=123'
    bad=reader+'&step=bad';good='https://cdn.example.org/good.pdf'
    candidate=PdfCandidate(paper,'P2','R025','ieee',reader)
    def consume(item):
        if item.url==good:return CandidateResult.pdf(transfer_complete=True)
        links=[bad,good] if item.url==reader else [bad]
        return CandidateResult.current(CurrentResponse(item.url,'text/html',
            ''.join('<iframe src="'+url+'"></iframe>' for url in links).encode()))
    result=PdfDiscovery(paper,candidates=(candidate,)).run(consume)
    assert result.status=='transferred' and result.fallback_used and result.candidate.url==good


def test_distinct_response_candidates_count_fallback_after_first_path_failure():
    paper = target('unknown.example.org')
    inputs = PdfRuleInputs(paper, known_pdf_urls=(KnownPdfUrl('https://unknown.example.org/download', 'API02', 'link'),))
    seen = []
    def consume(c):
        seen.append(c)
        if len(seen) == 1:
            return CandidateResult.current(CurrentResponse(c.url, 'text/html', b'<head><meta name="citation_doi" content="10.1234/AbC">'
                b'<meta name="citation_pdf_url" content="First.PDF"><meta name="fulltext_pdf_url" content="Second.PDF"></head>'))
        if len(seen) == 2:
            return CandidateResult.failed()
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, inputs=inputs).run(consume)
    assert [c.url for c in seen] == ['https://unknown.example.org/download', 'https://unknown.example.org/First.PDF',
        'https://unknown.example.org/Second.PDF']
    assert result.fallback_used and result.pdf_source == 'P2'


def test_local_transfer_consumer_error_is_terminal_without_new_source():
    seen = []
    def consume(c):
        seen.append(c)
        raise PermissionError('Controlled local writer refusal')
    with pytest.raises(PermissionError):
        PdfDiscovery(target()).run(consume)
    assert len(seen) == 1


def test_partial_document_known_p3_can_finish_before_missing_fields_are_refreshed():
    paper = target('www.mdpi.com')
    facts = document(paper, [PdfCandidateFact(stage='P3', rule_id='R042',
        url='https://cdn.example.org/Body.PDF', field='citation_pdf_url')], status='partial')
    class IO:
        def document(self, _):
            pytest.fail('Existing P3 candidate already finished')
    result = PdfDiscovery(paper, facts=(facts,), io=IO()).run(lambda _: CandidateResult.pdf(transfer_complete=True))
    assert (result.pdf_source, result.fallback_used) == ('P3', False)


@pytest.mark.parametrize('stable', ['success', 'failed', 'failed-complete', 'absent'])
def test_saved_acs_p4_precedes_optional_refresh_and_refresh_remains_available(stable):
    from types import SimpleNamespace
    from allfold.application.document_metadata import CurrentPdfClue
    from allfold.pdf_facts import PdfRefreshLocator
    paper = target('pubs.acs.org')
    url = 'https://pubs.acs.org/journal/article-pdf/Body.PDF'
    candidates = [PdfCandidateFact(stage='P4', rule_id='R044',
        refresh=PdfRefreshLocator(kind='document-pdf', landing_url='https://pubs.acs.org/article'))]
    if stable != 'absent':
        candidates.insert(0, PdfCandidateFact(stage='P4', rule_id='R044', url=url))
    facts = document(paper, candidates[:1] if stable == 'failed-complete' else candidates,
        status='complete' if stable == 'failed-complete' else 'partial')
    calls = []
    class IO:
        def document(self, _):
            calls.append('document')
            return SimpleNamespace(facts=document(paper), current_candidates=(
                CurrentPdfClue('P3', 'GENERIC', 'https://cdn.example.org/fresh-meta.pdf', field='citation_pdf_url'),
                CurrentPdfClue('P4', 'R044', 'https://cdn.example.org/fresh-entry.pdf')))
    def consume(candidate):
        calls.append(candidate.url)
        return CandidateResult.failed() if candidate.url == url and stable.startswith('failed') else CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, facts=(facts,), io=IO()).run(consume)
    assert calls == ([url] if stable == 'success' else
        ([url] if stable.startswith('failed') else []) + ['document', 'https://cdn.example.org/fresh-meta.pdf'])
    assert (result.pdf_source, result.fallback_used) == ('P4' if stable == 'success' else 'P3', stable.startswith('failed'))


def test_oup_qualified_citation_response_eprint_uses_current_url_in_original_stage():
    paper = target('academic.oup.com', article_url='https://academic.oup.com/journal/article/1/2/3/123')
    seen = []
    def consume(c):
        seen.append(c)
        if len(seen) == 1:
            return CandidateResult.current(CurrentResponse(c.url, 'application/x-bibtex',
                b'@article{x, eprint={https://academic.oup.com/journal/article-pdf/Body.PDF?sig=Keep}}'))
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper).run(consume)
    assert [c.url for c in seen][1:] == ['https://academic.oup.com/journal/article-pdf/Body.PDF?sig=Keep']
    assert (result.pdf_source, result.fallback_used) == ('P2', False)


def test_reader_progress_keeps_distinct_entry_and_reader_cookie_contexts():
    from types import SimpleNamespace
    from allfold.application.document_metadata import CurrentPdfClue, ReaderResult
    from allfold.pdf_rules import PdfCandidate
    article = 'https://www.sciencedirect.com/science/article/pii/S1234567890123456'
    paper = target('www.sciencedirect.com', article_url=article)
    entry, final = article+'/pdfft', article+'/pdf'
    candidate = PdfCandidate(paper, 'P2', 'R024', 'sciencedirect', entry)
    calls = []
    class IO:
        reads = 0
        def reader(self, item, response):
            self.reads += 1
            return SimpleNamespace(current_candidates=(CurrentPdfClue('P2', 'R024', entry),),
                reader_result=ReaderResult(final, None, True, f'{self.reads:064x}'))
    io = IO()
    def consume(item):
        calls.append(item.url)
        if io.reads == 2:
            return CandidateResult.pdf(transfer_complete=True)
        # Only the redirected Reader path receives the script's Cookie.
        return CandidateResult.current(CurrentResponse(final, 'text/html', b'<title>Reader</title>', context_key='0'*64))
    result = PdfDiscovery(paper, io=io, candidates=(candidate,)).run(consume)
    assert calls == [entry]*3 and io.reads == 2
    assert (result.status, result.pdf_source, result.fallback_used) == ('transferred', 'P2', False)


def test_observed_redirect_keeps_cookie_progress_when_it_has_no_context_key():
    from allfold.pdf_rules import PdfCandidate
    paper = target('publisher.example.org')
    entry, hop = 'https://publisher.example.org/entry', 'https://download.example.org/hop'
    html = ('<head><meta name="citation_doi" content="'+paper.doi+'">'
        '<meta name="citation_pdf_url" content="'+hop+'"></head>').encode()
    calls, contexts = [], iter(['1'*64, '2'*64])
    def consume(item):
        calls.append(item.url)
        if item.url == hop:
            return CandidateResult.current(CurrentResponse(hop, '', status=302, redirect_url=entry))
        if len(calls) == 5:
            return CandidateResult.pdf(transfer_complete=True)
        return CandidateResult.current(CurrentResponse(entry, 'text/html', html,
            context_changed=True, context_key=next(contexts)))
    result = PdfDiscovery(paper, candidates=(PdfCandidate(paper, 'P3', 'GENERIC', 'generic', entry),)).run(consume)
    assert calls == [entry, hop, entry, hop, entry]
    assert (result.status, result.pdf_source, result.fallback_used) == ('transferred', 'P3', False)


def test_optica_known_reader_skips_first_frame_and_preserves_meta_source():
    paper = target('opg.optica.org', article_url='https://opg.optica.org/abstract.cfm?uri=ol-1-2-3')
    facts = document(paper, [PdfCandidateFact(stage='P3', rule_id='R053',
        url='https://opg.optica.org/viewmedia.cfm?uri=ol-1-2-3', field='citation_pdf_url')])
    seen = []
    def consume(c):
        seen.append(c)
        if len(seen) == 1:
            return CandidateResult.current(CurrentResponse(c.url, 'text/html',
                b'<frameset><frame src="menu.html"><frame src="Files/Body.PDF?sig=Keep"></frameset>'))
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, facts=(facts,)).run(consume)
    assert [c.url for c in seen] == ['https://opg.optica.org/viewmedia.cfm?uri=ol-1-2-3',
        'https://opg.optica.org/Files/Body.PDF?sig=Keep']
    assert (result.pdf_source, result.fallback_used) == ('P3', False)


def test_sd_cdn_md5_pid_pair_is_refresh_fact_without_rewriting_current_url():
    from allfold.pdf_facts import persistent_pdf_candidate
    url = 'https://pdf.sciencedirectassets.com/Body.PDF?md5=AbC&pid=Keep'
    fact = persistent_pdf_candidate(stage='P4', rule_id='R024', url=url,
        refresh_kind='document-pdf', landing_url='https://www.sciencedirect.com/science/article/pii/S014067362400123X')
    assert fact.url is None and fact.refresh.kind == 'document-pdf'
    assert url == 'https://pdf.sciencedirectassets.com/Body.PDF?md5=AbC&pid=Keep'


@pytest.mark.parametrize('content_type', ['book', 'chapter', 'book-chapter', 'supplement'])
@pytest.mark.parametrize('cache', ['none', 'document', 'openalex'])
def test_explicit_unsupported_target_never_dispatches_any_stage_even_with_bound_cache(content_type, cache):
    paper = replace(target('unknown.example.org'), content_type=content_type)
    document_cache = document(paper, [PdfCandidateFact(stage='P3', rule_id='GENERIC',
        url='https://repository.example.org/Book.PDF', field='citation_pdf_url')])
    openalex_cache = PdfDiscoveryFacts(source='openalex', capability='openalex-locations', status='complete',
        target_doi=paper.identity_doi, observed_at=datetime.now(timezone.utc), candidates=(
            PdfCandidateFact(stage='P5', rule_id='OPENALEX', url='https://repository.example.org/Book.PDF'),))
    facts = {'none': (), 'document': (document_cache,), 'openalex': (openalex_cache,)}[cache]
    calls = []
    class IO:
        def query_missing(self, *_):
            calls.append('query')
            return iter(())
        def document(self, _):
            calls.append('document')
        def openalex(self, doi):
            calls.append('openalex')
            return {'doi': doi, 'best_oa_location': {'pdf_url': 'https://repository.example.org/Book.PDF'}}
    result = PdfDiscovery(paper, facts=facts, io=IO()).run(lambda _: calls.append('consume')
        or CandidateResult.pdf(transfer_complete=True))
    assert calls == []
    assert (result.status, result.pdf_source, result.fallback_used) == ('not-applicable', None, False)
    assert result.diagnostics == (('P1', 'SCOPE', 'unsupported-content-type'),)


@pytest.mark.parametrize('content_type', ['journal-article', 'conference-paper', 'unknown'])
@pytest.mark.parametrize('cached', [False, True])
def test_article_or_unknown_target_keeps_own_repository_preprint_p5(content_type, cached):
    from allfold.pdf_facts import openalex_discovery_facts
    paper = replace(target('unknown.example.org'), content_type=content_type)
    raw = {'doi': paper.doi, 'type': 'preprint', 'best_oa_location': {
        'pdf_url': 'https://repository.example.org/Preprint.PDF'}, 'locations': []}
    facts = (openalex_discovery_facts(raw, datetime.now(timezone.utc)),) if cached else ()
    calls = []
    class IO:
        def openalex(self, _):
            calls.append('openalex')
            return raw
    result = PdfDiscovery(paper, facts=facts, io=IO()).run(lambda c: calls.append(c.url)
        or CandidateResult.pdf(transfer_complete=True))
    assert calls == ([] if cached else ['openalex']) + ['https://repository.example.org/Preprint.PDF']
    assert (result.status, result.pdf_source) == ('transferred', 'P5')

@pytest.mark.parametrize('preceded_by_failure',[False,True])
def test_unavailable_condition_continues_without_creating_fallback(preceded_by_failure):
    from allfold.pdf_rules import PdfCandidate
    paper=target()
    candidates=tuple(PdfCandidate(paper,'P1' if index==0 else 'P2','GENERIC','generic',f'https://example.org/{index}')
        for index in range(3 if preceded_by_failure else 2))
    seen=[]
    def consume(candidate):
        seen.append(candidate.url)
        if preceded_by_failure and len(seen)==1:return CandidateResult.failed('source-failed')
        if candidate is candidates[-1]:return CandidateResult.pdf(transfer_complete=True)
        return CandidateResult('skipped',diagnostic='native-unsupported')
    result=PdfDiscovery(paper,candidates=candidates).run(consume)
    assert result.status=='transferred' and result.fallback_used is preceded_by_failure
    assert ('P2' if preceded_by_failure else 'P1','GENERIC','native-unsupported') in result.diagnostics


@pytest.mark.parametrize('extra', [
    '<aside><h2>Sign in to your account</h2><form><input type="password"></form></aside>',
    '<footer><iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe></footer>',
    '<template><iframe src="https://newassets.hcaptcha.com/captcha/v1"></iframe></template>',
    '<noscript><iframe src="https://newassets.hcaptcha.com/captcha/v1"></iframe></noscript>',
    '<iframe style="opacity:0" src="https://newassets.hcaptcha.com/captcha/v1"></iframe>',
])
def test_auxiliary_captcha_does_not_block_readable_http_content(extra):
    from allfold.pdf_responses import access_limited
    body = '<main><h1>Paper title</h1><p>Article text</p><a href="/body.pdf">PDF</a></main>' + extra
    assert not access_limited(CurrentResponse('https://publisher.example.org/article', 'text/html', body.encode()))


@pytest.mark.parametrize('body', [
    '<title>Publisher</title><p>Please complete the security check to continue.</p><iframe src="https://newassets.hcaptcha.com/captcha/v1"></iframe>',
    '<main><h1>Sign in</h1><p>Sign in to view this article</p><form><input type="password"></form></main>',
    '<title>Publisher</title><h1>Sign in</h1><form><input type="password"></form>',
    '<title>Just a moment...</title><article>Checking your browser</article>'
    '<script>window._cf_chl_opt = {};</script><script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script>',
])
def test_contextual_login_or_cloudflare_page_remains_access_limited(body):
    from allfold.pdf_responses import access_limited
    assert access_limited(CurrentResponse('https://publisher.example.org/article', 'text/html', body.encode()))
