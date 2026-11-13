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


def document(paper, candidates=(), status='complete'):
    return PdfDiscoveryFacts(source='document', capability='document-pdf', status=status,
        observed_at=datetime.now(timezone.utc), target_doi=paper.identity_doi,
        landing_url=paper.article_url or 'https://' + paper.content_host + '/article',
        candidates=tuple(candidates))


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
        'https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft',
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
    ('www.sciencedirect.com', (('pii', 'S014067362400123X'),), '/pii/S014067362400123X/pdfft'),
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
    assert seen[0].url == 'https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft'
    assert result.pdf_source == 'P2'


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
    facts = document(paper, [PdfCandidateFact(stage='P3', rule_id='R020',
        url='https://cdn.example.org/Explicit.PDF', field='citation_pdf_url')])
    seen = []
    def consume(c):
        seen.append(c)
        if c.stage == 'P2':
            return CandidateResult.current(CurrentResponse(c.url, 'application/x-bibtex',
                b'@article{x, eprint={https://academic.oup.com/journal/article/1/2/3/123}}'))
        return CandidateResult.pdf(transfer_complete=True)
    result = PdfDiscovery(paper, facts=(facts,)).run(consume)
    assert [c.stage for c in seen] == ['P2', 'P3']
    assert (result.pdf_source, result.fallback_used) == ('P3', True)


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


def test_p5_historical_best_first_dedup_four_and_exact_doi_are_unchanged():
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
        'https://cdn.example.org/2.pdf', 'https://cdn.example.org/3.pdf', 'https://cdn.example.org/4.pdf']
    assert result.pdf_source is None and result.fallback_used
    io.doi = '10.9999/other'
    assert PdfDiscovery(paper, io=io).run(lambda _: pytest.fail('Wrong exact Work')).status == 'exhausted'


def test_failed_path_then_empty_p5_is_still_observable_fallback():
    class IO:
        def openalex(self, doi):
            return {'doi': doi, 'best_oa_location': None, 'locations': []}
    result = PdfDiscovery(target(), io=IO()).run(lambda _: CandidateResult.failed())
    assert result.status == 'exhausted' and result.fallback_used and result.pdf_source is None


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


def test_global_operation_and_known_chain_hop_budgets_are_finite():
    from allfold.providers.provider_http import ProviderBudgetExceeded
    paper = target('ieeexplore.ieee.org', article_url='https://ieeexplore.ieee.org/document/123')
    seen = []
    def consume(c):
        seen.append(c)
        return CandidateResult.current(CurrentResponse(c.url, 'text/html',
            ('<iframe src="https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=123&hop=' + str(len(seen)) + '"></iframe>').encode()))
    result = PdfDiscovery(paper, max_hops=1).run(consume)
    assert len(seen) <= 4 and result.status == 'exhausted'
    with pytest.raises(ProviderBudgetExceeded):
        PdfDiscovery(paper, max_operations=1).run(consume)


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
