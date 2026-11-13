from dataclasses import replace
import re

import pytest

from allfold.pdf_rules import KnownPdfUrl, PdfRuleInputs, PdfTarget, iter_p1_candidates, iter_p2_candidates


def target(host='link.springer.com', platform='springer', content_type='journal-article', **kwargs):
    return PdfTarget(paper_id='paper-1', doi='10.1234/AbC/Part(2)?x=Y', platform=platform,
                     content_host=host, content_type=content_type, **kwargs)


def test_springer_encodes_complete_doi_but_binds_original_target():
    paper = target()
    candidate, = iter_p1_candidates(paper)
    assert candidate.url == 'https://link.springer.com/content/pdf/10.1234%2FAbC%2FPart(2)%3Fx%3DY.pdf'
    assert candidate.target is paper
    assert (candidate.stage, candidate.rule_id, candidate.platform) == ('P1', 'R001', 'springer')
    assert list(iter_p1_candidates(replace(paper, content_host='pubs.acs.org'))) == []
    assert list(iter_p1_candidates(replace(paper, content_type='book-chapter'))) == []


@pytest.mark.parametrize('host,platform,rule,expected', [
    ('onlinelibrary.wiley.com', 'wiley', 'R002', '/doi/pdfdirect/10.1234/AbC/Part(2)%3Fx=Y?download=true'),
    ('www.tandfonline.com', 'taylor_francis', 'R003', '/doi/pdf/10.1234/AbC/Part(2)%3Fx=Y'),
    ('www.nejm.org', 'nejm', 'R004', '/doi/pdf/10.1234/AbC/Part(2)%3Fx=Y'),
    ('journals.sagepub.com', 'sage', 'R005', '/doi/pdf/10.1234/AbC/Part(2)%3Fx=Y'),
    ('www.annualreviews.org', 'annual_reviews', 'R006', '/doi/pdf/10.1234/AbC/Part(2)%3Fx=Y'),
    ('www.frontiersin.org', 'frontiers', 'R007', '/articles/10.1234/AbC/Part(2)%3Fx=Y/pdf'),
    ('dl.acm.org', 'acm', 'R008', '/doi/pdf/10.1234/AbC/Part(2)%3Fx=Y?download=true'),
    ('projecteuclid.org', 'project_euclid', 'R009', '/journalArticle/Download?urlId=10.1234%2FAbC%2FPart(2)%3Fx%3DY'),
    ('arc.aiaa.org', 'aiaa', 'R010', '/doi/pdf/10.1234/AbC/Part(2)%3Fx=Y'),
    ('www.ajronline.org', 'ajr', 'R011', '/doi/pdf/10.1234/AbC/Part(2)%3Fx=Y?download=true'),
    ('www.science.org', 'science', 'R014', '/doi/pdf/10.1234/AbC/Part(2)%3Fx=Y'),
    ('www.pnas.org', 'pnas', 'R015', '/doi/pdf/10.1234/AbC/Part(2)%3Fx=Y'),
    ('pubs.rsna.org', 'rsna', 'R016', '/doi/pdf/10.1234/AbC/Part(2)%3Fx=Y?download=true'),
    ('www.worldscientific.com', 'world_scientific', 'R017', '/doi/pdf/10.1234/AbC/Part(2)%3Fx=Y?download=true'),
])
def test_each_direct_template_is_host_and_content_bound(host, platform, rule, expected):
    paper = target(host, platform)
    candidate, = iter_p1_candidates(paper)
    assert (candidate.rule_id, candidate.url) == (rule, 'https://' + host + expected)
    assert list(iter_p1_candidates(replace(paper, content_host='unrelated.example.org'))) == []
    assert list(iter_p1_candidates(replace(paper, doi=None))) == []
    assert list(iter_p1_candidates(replace(paper, content_type='supplement'))) == []


def test_spie_never_guesses_between_journal_and_proceedings():
    paper = target('www.spiedigitallibrary.org', 'spie')
    journal, = iter_p1_candidates(paper)
    conference, = iter_p1_candidates(replace(paper, content_type='conference-paper'))
    assert (journal.rule_id, journal.url) == ('R012', 'https://www.spiedigitallibrary.org/journalArticle/Download?urlId=10.1234%2FAbC%2FPart(2)%3Fx%3DY')
    assert (conference.rule_id, conference.url) == ('R013', 'https://www.spiedigitallibrary.org/Proceedings/Download?urlId=10.1234%2FAbC%2FPart(2)%3Fx%3DY')
    assert list(iter_p1_candidates(replace(paper, content_type='unknown'))) == []
    assert list(iter_p1_candidates(target('projecteuclid.org', 'project_euclid', 'conference-paper'))) == []


def test_plos_uses_only_established_journal_slug_and_printable():
    paper = target('journals.plos.org', 'plos')
    assert list(iter_p1_candidates(paper)) == []
    inputs = PdfRuleInputs(target=paper, identifiers=(('journal_slug', 'plosone'),))
    candidate, = iter_p1_candidates(paper, inputs)
    assert candidate.url == 'https://journals.plos.org/plosone/article/file?id=10.1234%2FAbC%2FPart(2)%3Fx%3DY&type=printable'
    assert candidate.rule_id == 'R018'
    unknown = replace(inputs, identifiers=(('journal_slug', 'madeup'),))
    assert list(iter_p1_candidates(paper, unknown)) == []


def test_springer_reference_is_explicit_later_variant_only():
    paper = target()
    assert [c.rule_id for c in iter_p1_candidates(paper)] == ['R001']
    stream = iter_p1_candidates(paper, PdfRuleInputs(paper, conditions=frozenset({'springer_in_press'})))
    assert next(stream).rule_id == 'R001'
    reference = next(stream)
    assert (reference.rule_id, reference.url) == ('R019', 'https://link.springer.com/content/pdf/10.1234/AbC/Part(2)%3Fx=Y_reference.pdf')
    other = target('www.nature.com', 'springer')
    assert list(iter_p1_candidates(other, PdfRuleInputs(other, conditions=frozenset({'springer_in_press'})))) == []


def test_request_spelling_and_encoded_components_are_not_lowercased_or_doubled():
    paper = replace(target(), doi='https://doi.org/10.1234/AbC%2FDef')
    candidate, = iter_p1_candidates(paper)
    assert candidate.url == 'https://link.springer.com/content/pdf/10.1234%2FAbC%2FDef.pdf'
    assert paper.identity_doi == '10.1234/abc%2fdef'
    moved = replace(paper, article_url='https://www.annualreviews.org/content/journals/10.1234/AbC')
    candidate, = iter_p1_candidates(moved)
    assert (candidate.rule_id, candidate.platform) == ('R006', 'annual_reviews')


def test_sciencedirect_checks_each_alternative_id_and_preserves_bounded_variants():
    paper = target('www.sciencedirect.com', 'sciencedirect')
    inputs = PdfRuleInputs(paper, alternative_ids=('not-a-pii', 'S014067362400123X'))
    candidates = iter_p2_candidates(paper, inputs)
    first = next(candidates)
    assert (first.rule_id, first.url) == ('R024', 'https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft')
    assert next(candidates).url == 'https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft?download=true'
    assert list(iter_p2_candidates(paper, PdfRuleInputs(paper, alternative_ids=('junk', '12345678901234567')))) == []
    punctuated = PdfRuleInputs(paper, identifiers=(('pii', 'S0140-6736(24)00123-4'),))
    assert list(iter_p2_candidates(paper, punctuated)) == []


def test_known_scidir_pdf_does_not_require_pii_and_has_bound_field():
    paper = target('www.sciencedirect.com', 'sciencedirect')
    url = 'https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft?md5=AbC&pid=1-s2.0-X&token=XyZ'
    inputs = PdfRuleInputs(paper, known_pdf_urls=(KnownPdfUrl(url, 'API06', 'coredata.link[rel=scidir-pdf]'),))
    candidate, = iter_p2_candidates(paper, inputs)
    assert (candidate.url, candidate.rule_id, candidate.field, candidate.target) == (url, 'API06', 'coredata.link[rel=scidir-pdf]', paper)
    with pytest.raises(ValueError, match='another target'):
        list(iter_p2_candidates(replace(paper, paper_id='paper-2'), inputs))


def test_pii_can_only_be_extracted_from_explicit_platform_paths():
    paper = target('www.sciencedirect.com', 'sciencedirect', article_url='https://www.sciencedirect.com/science/article/pii/S014067362400123X')
    assert next(iter_p2_candidates(paper)).url == 'https://www.sciencedirect.com/science/article/pii/S014067362400123X/pdfft'
    assert list(iter_p2_candidates(replace(paper, article_url='https://www.sciencedirect.com/search/S014067362400123X'))) == []


@pytest.mark.parametrize('article_url', [
    'https://www.cell.com/cell/fulltext/S0092-8674(24)00123-4',
    'https://www.cell.com/cell/pdfExtended/S0092-8674(24)00123-4',
    'https://www.cell.com/action/showPdf?pii=S0092-8674(24)00123-4',
])
def test_cell_retains_punctuated_pii_and_endpoint_scope(article_url):
    paper = target('www.cell.com', 'cell', article_url=article_url)
    candidate, = iter_p2_candidates(paper)
    assert (candidate.rule_id, candidate.url) == ('R023', 'https://www.cell.com/action/showPdf?pii=S0092-8674(24)00123-4')
    assert list(iter_p2_candidates(replace(paper, article_url='https://www.cell.com/search/S0092-8674(24)00123-4'))) == []


def test_ieee_uses_real_number_and_getpdf_precedes_reader():
    paper = target('ieeexplore.ieee.org', 'ieee')
    assert list(iter_p2_candidates(replace(paper, doi='10.1109/ABC.1234567'))) == []
    inputs = PdfRuleInputs(paper, identifiers=(('article_number', '1234567'),))
    stream = iter_p2_candidates(paper, inputs)
    assert next(stream).url == 'https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=1234567&ref='
    stamp = next(stream)
    assert (stamp.url, stamp.reader_kind, stamp.rule_id) == ('https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber=1234567', 'ieee_stamp', 'R025')
    article = replace(paper, article_url='https://ieeexplore.ieee.org/document/7654321')
    assert 'arnumber=7654321' in next(iter_p2_candidates(article)).url
    query = replace(paper, article_url='https://ieeexplore.ieee.org/xpl/documentDetails.jsp?arnumber=7654321')
    assert 'arnumber=7654321' in next(iter_p2_candidates(query)).url
    invalid = PdfRuleInputs(paper, identifiers=(('article_number', '1/234'),))
    assert list(iter_p2_candidates(paper, invalid)) == []


def test_oup_accepts_only_reliable_article_resource_ids():
    paper = target('academic.oup.com', 'oup')
    inputs = PdfRuleInputs(paper, identifiers=(('resource_id', '1234567'),))
    candidate, = iter_p2_candidates(paper, inputs)
    assert (candidate.url, candidate.reader_kind) == ('https://academic.oup.com/Citation/Download?resourceId=1234567&resourceType=3&citationFormat=2', 'oup_citation')
    canonical = replace(paper, article_url='https://academic.oup.com/library/article/24/2/235/1234567')
    assert next(iter_p2_candidates(canonical)).url == candidate.url
    assert list(iter_p2_candidates(replace(paper, article_url='https://academic.oup.com/search/1234567'))) == []
    acs = replace(paper, content_host='pubs.acs.org')
    assert list(iter_p2_candidates(acs, replace(inputs, target=acs))) == []


def test_jstor_preserves_doi_like_multilevel_stable_id_but_refuses_tdm_uuid():
    paper = target('www.jstor.org', 'jstor', article_url='https://www.jstor.org/stable/10.2307/AbC/Part2?seq=1')
    candidate, = iter_p2_candidates(paper)
    assert candidate.url == 'https://www.jstor.org/stable/pdfplus/10.2307/AbC/Part2.pdf'
    assert 'acceptTC' not in candidate.url
    bare = replace(paper, article_url=None)
    assert list(iter_p2_candidates(bare, PdfRuleInputs(bare, identifiers=(('jstor_item_id', 'a3ffb0c3-f9c7-4fa9-b61e-e3604524d443'),)))) == []
    uuid = replace(paper, article_url='https://www.jstor.org/stable/a3ffb0c3-f9c7-4fa9-b61e-e3604524d443')
    assert list(iter_p2_candidates(uuid)) == []


def test_clinicalkey_requires_its_own_access_and_ready_session():
    paper = target('www.clinicalkey.com', 'clinicalkey')
    inputs = PdfRuleInputs(paper, identifiers=(('pii', 'S014067362400123X'),))
    assert list(iter_p2_candidates(paper, inputs)) == []
    ready = replace(inputs, conditions=frozenset({'clinicalkey_access', 'clinicalkey_session_ready'}),
                    clinicalkey_query='locale=en_US&searchIndex=AbC')
    candidate, = iter_p2_candidates(paper, ready)
    assert (candidate.rule_id, candidate.url) == ('R026', 'https://www.clinicalkey.com/service/content/pdf/watermarked/1-s2.0-S014067362400123X.pdf?locale=en_US&searchIndex=AbC')
    assert list(iter_p2_candidates(paper, replace(ready, conditions=frozenset({'sciencedirect_access'})))) == []


@pytest.mark.parametrize('host,platform,article_url,rule,expected', [
    ('www.nature.com', 'nature', 'https://www.nature.com/onc/journal/v30/n1/full/onc.2011.282.html?token=AbC&x=2',
     'R028', 'https://www.nature.com/onc/journal/v30/n1/pdf/onc.2011.282.pdf?token=AbC&x=2'),
    ('www.palgrave-journals.com', 'nature', 'https://www.palgrave-journals.com/jibs/journal/v45/n2/abs/Jibs.2014.7.html',
     'R028', 'https://www.palgrave-journals.com/jibs/journal/v45/n2/pdf/Jibs.2014.7.pdf'),
    ('iopscience.iop.org', 'iop', 'https://iopscience.iop.org/article/10.1234/AbC/Part2/meta?token=AbC',
     'R029', 'https://iopscience.iop.org/article/10.1234/AbC/Part2/pdf?token=AbC'),
    ('journals.aps.org', 'aps', 'https://journals.aps.org/prl/abstract/10.1234/AbC/Part2?token=AbC',
     'R030', 'https://journals.aps.org/prl/pdf/10.1234/AbC/Part2?token=AbC'),
    ('ascopubs.org', 'asco', 'https://ascopubs.org/doi/full/10.1234/AbC?token=AbC&epdf=Keep',
     'R031', 'https://ascopubs.org/doi/pdfdirect/10.1234/AbC?token=AbC&epdf=Keep'),
    ('ahajournals.org', 'aha', 'https://ahajournals.org/doi/reader/10.1234/AbC?token=AbC',
     'R032', 'https://ahajournals.org/doi/pdf/10.1234/AbC?token=AbC'),
    ('journals.healio.com', 'healio', 'https://journals.healio.com/doi/epdf/10.1234/AbC?token=AbC',
     'R033', 'https://journals.healio.com/doi/pdf/10.1234/AbC?token=AbC'),
    ('journals.uchicago.edu', 'chicago', 'https://journals.uchicago.edu/doi/full/10.1234/AbC?token=AbC',
     'R034', 'https://journals.uchicago.edu/doi/pdf/10.1234/AbC?token=AbC'),
    ('jmlr.org', 'jmlr', 'https://jmlr.org/papers/v25/AbC24a.html?token=AbC',
     'R035', 'https://jmlr.org/papers/volume25/AbC24a/AbC24a.pdf?token=AbC'),
    ('proceedings.mlr.press', 'pmlr', 'https://proceedings.mlr.press/v235/AbC24a.html?token=AbC',
     'R036', 'https://proceedings.mlr.press/v235/AbC24a/AbC24a.pdf?token=AbC'),
])
def test_each_existing_article_url_transform_preserves_request_spelling(host, platform, article_url, rule, expected):
    paper = target(host, platform, article_url=article_url)
    candidate, = iter_p2_candidates(paper)
    assert (candidate.rule_id, candidate.url, candidate.target) == (rule, expected, paper)
    assert list(iter_p2_candidates(replace(paper, article_url=article_url.replace(host, 'unrelated.example.org')))) == []
    assert list(iter_p2_candidates(replace(paper, content_type='book-chapter'))) == []
    assert list(iter_p2_candidates(replace(paper, article_url='https://' + host + '/search/irrelevant'))) == []


@pytest.mark.parametrize('platform,host,doi', [
    ('nature', 'www.nature.com', '10.1038/onc.2011.282'),
    ('nature', 'www.nature.com', '10.1038/nsmb.1371'),
    ('mdpi', 'www.mdpi.com', '10.3390/admsci3030032'),
    ('acs', 'pubs.acs.org', '10.1021/JA1234'),
    ('cambridge', 'www.cambridge.org', '10.1017/ABC'),
    ('thieme', 'www.thieme-connect.com', '10.1055/ABC'),
    ('embopress', 'www.embopress.org', '10.15252/ABC'),
])
def test_no_default_or_failure_pool_for_excluded_doi_shortcuts(platform, host, doi):
    paper = replace(target(host, platform), doi=doi)
    assert list(iter_p1_candidates(paper)) == []
    assert list(iter_p2_candidates(paper)) == []


def test_iop_requires_known_structure_and_aps_requires_known_journal():
    paper = target('iopscience.iop.org', 'iop')
    assert list(iter_p2_candidates(paper)) == []
    iop, = iter_p2_candidates(paper, PdfRuleInputs(paper, conditions=frozenset({'iop_doi_article'})))
    assert iop.url == 'https://iopscience.iop.org/article/10.1234/AbC/Part(2)%3Fx=Y/pdf'
    aps = target('journals.aps.org', 'aps')
    assert list(iter_p2_candidates(aps)) == []
    candidate, = iter_p2_candidates(aps, PdfRuleInputs(aps, identifiers=(('journal_slug', 'prl'),)))
    assert candidate.url == 'https://journals.aps.org/prl/pdf/10.1234/AbC/Part(2)%3Fx=Y'
    assert list(iter_p2_candidates(aps, PdfRuleInputs(aps, identifiers=(('journal_slug', '../other'),)))) == []


def test_existing_no_doi_jmlr_pmlr_urls_do_not_add_identity_lookup():
    jmlr = PdfTarget('paper-jmlr', article_url='https://jmlr.org/papers/v25/23-1234.html', content_type='journal-article')
    pmlr = PdfTarget('paper-pmlr', article_url='https://proceedings.mlr.press/v235/smith24a.html', content_type='conference-paper')
    assert next(iter_p2_candidates(jmlr)).url == 'https://jmlr.org/papers/volume25/23-1234/23-1234.pdf'
    assert next(iter_p2_candidates(pmlr)).url == 'https://proceedings.mlr.press/v235/smith24a/smith24a.pdf'
    assert list(iter_p2_candidates(replace(jmlr, article_url=None))) == []


@pytest.mark.parametrize('host,platform,credential,condition,rule,expected', [
    ('www.sciencedirect.com', 'sciencedirect', 'elsevier', 'elsevier_pdf_access', 'API06',
     'https://api.elsevier.com/content/article/doi/10.1234%2FAbC%2FPart(2)%3Fx%3DY'),
    ('onlinelibrary.wiley.com', 'wiley', 'wiley_tdm', 'wiley_tdm_access', 'API07',
     'https://api.wiley.com/onlinelibrary/tdm/v1/articles/10.1234%2FAbC%2FPart(2)%3Fx%3DY'),
    ('journals.aps.org', 'aps', 'aps_harvest', 'aps_harvest_authorized', 'API08',
     'https://harvest.aps.org/v2/journals/articles/10.1234/AbC/Part(2)%3Fx=Y'),
])
def test_optional_pdf_apis_require_both_credential_capability_and_access(host, platform, credential, condition, rule, expected):
    paper = target(host, platform)
    assert list(iter_p2_candidates(paper)) == []
    inputs = PdfRuleInputs(paper, credentials=frozenset({credential}), conditions=frozenset({condition}))
    candidate, = iter_p2_candidates(paper, inputs)
    assert (candidate.rule_id, candidate.url, candidate.credential, candidate.accept) == (rule, expected, credential, 'application/pdf')
    assert list(iter_p2_candidates(paper, replace(inputs, credentials=frozenset()))) == []
    assert list(iter_p2_candidates(paper, replace(inputs, conditions=frozenset()))) == []
    other = replace(paper, content_host='unrelated.example.org')
    assert list(iter_p2_candidates(other, replace(inputs, target=other))) == []


def test_aps_harvest_has_explicit_oa_path_without_credential():
    paper = target('journals.aps.org', 'aps')
    candidate, = iter_p2_candidates(paper, PdfRuleInputs(paper, conditions=frozenset({'aps_harvest_oa'})))
    assert (candidate.rule_id, candidate.credential, candidate.accept) == ('API08', None, 'application/pdf')


def test_known_pdf_field_preserves_signed_url_and_referer_without_credential_values():
    paper = target('journals.lww.com', 'lww')
    url = 'https://cdn.publisher.org/Body/File.PDF?Policy=AbC&Signature=XyZ&Key-Pair-Id=Keep'
    viewer = 'https://journals.lww.com/journal/_layouts/15/oaks.journals/downloadpdf.aspx?an=00000000-202001000-00001'
    known = KnownPdfUrl(url, 'R060', 'pdfDownloadDetails.pdfUrl', referer=viewer)
    candidate, = iter_p2_candidates(paper, PdfRuleInputs(paper, known_pdf_urls=(known,)))
    assert (candidate.url, candidate.referer, candidate.target) == (url, viewer, paper)
    assert candidate.credential is None
    for unsafe in ('javascript:alert(1)', 'file:///tmp/Paper.pdf', 'http://127.0.0.1/Paper.pdf', 'https://name:secret@example.org/Paper.pdf'):
        with pytest.raises(ValueError):
            KnownPdfUrl(unsafe, 'API02', 'link[].URL')


def test_inputs_are_bounded_immutable_and_target_binding_cannot_be_replaced():
    paper = target()
    with pytest.raises(ValueError):
        PdfRuleInputs(paper, identifiers=[('pii', 'value')])
    with pytest.raises(ValueError):
        PdfRuleInputs(paper, identifiers=tuple(('pii', 'value') for _ in range(25)))
    with pytest.raises(ValueError):
        PdfRuleInputs(paper, known_pdf_urls=tuple('https://example.org/Paper.pdf' for _ in range(2)))
    with pytest.raises(ValueError):
        KnownPdfUrl('https://example.org/Paper.pdf', 'API02', '')


def test_adoption_catalogue_keeps_all_ids_conditions_and_source_references():
    from allfold.pdf_catalog import API_CATALOG, RULE_CATALOG

    assert set(RULE_CATALOG) == {f'R{i:03}' for i in range(1, 73)}
    assert set(API_CATALOG) == {f'API{i:02}' for i in range(1, 18)}
    for item in (*RULE_CATALOG.values(), *API_CATALOG.values()):
        assert item.expression and item.requirements and item.access and item.adoption
        assert item.source_ids and all(re.fullmatch(r'S[0-9]{3}', source) for source in item.source_ids)
        assert item.spec_ref == 'docs/pdf-source-discovery.md#' + item.rule_id.lower()
    assert RULE_CATALOG['R009'].status == 'conditional'
    assert RULE_CATALOG['R021'].status == RULE_CATALOG['R027'].status == 'extension'
    assert all(RULE_CATALOG[f'R{i:03}'].status == 'historical' for i in range(62, 73))
    assert all(API_CATALOG[f'API{i:02}'].status == 'non-pdf' for i in (5, 10, 11, 14))
    assert API_CATALOG['API12'].stages == ('P1',)
    with pytest.raises(TypeError):
        RULE_CATALOG['R001'] = RULE_CATALOG['R072']


def test_encoded_doi_octets_are_preserved_and_literal_percent_is_escaped_once():
    paper = replace(target(), doi='10.1234/AbC%2fDef%FF/100%')
    candidate, = iter_p1_candidates(paper)
    assert candidate.url == 'https://link.springer.com/content/pdf/10.1234%2FAbC%2fDef%FF%2F100%25.pdf'


def test_known_fields_do_not_reactivate_historical_or_non_pdf_services():
    for rule in ('R000', 'R021', 'R027', 'R062', 'R063', 'R072', 'API01', 'API05', 'API10', 'API11', 'API14', 'API17'):
        with pytest.raises(ValueError):
            KnownPdfUrl('https://example.org/Paper.pdf', rule, 'url')
    # Independent generic Meta belongs to P3; disabling a historical conversion
    # does not blacklist its Host for explicitly identified API PDF facts.
    paper = target('www.hindawi.com', 'hindawi')
    item = KnownPdfUrl('https://www.hindawi.com/journals/Test.pdf?token=AbC', 'API02', 'link[].URL')
    candidate, = iter_p2_candidates(paper, PdfRuleInputs(paper, known_pdf_urls=(item,)))
    assert candidate.url == item.url


def test_plos_manuscript_response_is_never_a_pdf_candidate():
    paper = target('journals.plos.org', 'plos')
    item = KnownPdfUrl('https://journals.plos.org/plosone/article/file?id=10.1371%2Fjournal.pone.1&type=manuscript', 'API02', 'link[].URL')
    assert list(iter_p2_candidates(paper, PdfRuleInputs(paper, known_pdf_urls=(item,)))) == []


def test_sensitive_urls_are_not_in_default_repr_and_capabilities_cannot_hold_secrets():
    paper = target(article_url='https://link.springer.com/article/10.1234/AbC?token=DontLog')
    item = KnownPdfUrl('https://cdn.example.org/File.PDF?token=DontLog', 'API02', 'link[].URL')
    candidate = next(iter_p2_candidates(paper, PdfRuleInputs(paper, known_pdf_urls=(item,))))
    assert all('DontLog' not in repr(value) for value in (paper, item, candidate))
    with pytest.raises(ValueError):
        PdfRuleInputs(paper, credentials=frozenset({'real-api-key-value'}))


@pytest.mark.parametrize('kwargs', [
    {'identifiers': (('pii', None),)}, {'identifiers': (('pii', 123),)},
    {'alternative_ids': (None,)}, {'conditions': frozenset({None})},
])
def test_fact_value_types_are_strict(kwargs):
    with pytest.raises(ValueError):
        PdfRuleInputs(target(), **kwargs)


def test_oup_advance_article_and_reference_links_remain_host_and_resource_bound():
    paper = target('academic.oup.com', 'oup', article_url='https://academic.oup.com/nar/advance-article/doi/10.1093/nar/gkaa123/1234567')
    assert next(iter_p2_candidates(paper)).url == 'https://academic.oup.com/Citation/Download?resourceId=1234567&resourceType=3&citationFormat=2'
    citation = replace(paper, article_url='https://academic.oup.com/Citation/Download?resourceId=1234567&resourceType=3')
    assert next(iter_p2_candidates(citation)).reader_kind == 'oup_citation'
    assert list(iter_p2_candidates(replace(citation, article_url='https://academic.oup.com/Citation/Download?resourceId=1234567&resourceType=4'))) == []


@pytest.mark.parametrize('host,platform,ids,rule,conditions', [
    ('www.sciencedirect.com', 'sciencedirect', (('pii', 'S014067362400123X'),), 'R024', frozenset()),
    ('www.cell.com', 'cell', (('cell_pii', 'S0092-8674(24)00123-4'),), 'R023', frozenset()),
    ('ieeexplore.ieee.org', 'ieee', (('article_number', '1234567'),), 'R025', frozenset()),
    ('academic.oup.com', 'oup', (('resource_id', '1234567'),), 'R020', frozenset()),
    ('www.jstor.org', 'jstor', (('jstor_stable_id', '10.2307/AbC'),), 'R022', frozenset()),
    ('www.clinicalkey.com', 'clinicalkey', (('pii', 'S014067362400123X'),), 'R026', frozenset({'clinicalkey_access', 'clinicalkey_session_ready'})),
])
def test_each_id_rule_is_host_and_article_type_bound(host, platform, ids, rule, conditions):
    paper = target(host, platform)
    inputs = PdfRuleInputs(paper, identifiers=ids, conditions=conditions)
    assert next(iter_p2_candidates(paper, inputs)).rule_id == rule
    other = replace(paper, content_host='unrelated.example.org')
    assert list(iter_p2_candidates(other, replace(inputs, target=other))) == []
    chapter = replace(paper, content_type='book-chapter')
    assert list(iter_p2_candidates(chapter, replace(inputs, target=chapter))) == []


def test_elsevier_optional_api_can_use_existing_pii_without_doi():
    paper = replace(target('www.sciencedirect.com', 'sciencedirect'), doi=None)
    inputs = PdfRuleInputs(paper, identifiers=(('pii', 'S014067362400123X'),),
                           credentials=frozenset({'elsevier'}), conditions=frozenset({'elsevier_pdf_access'}))
    candidates = list(iter_p2_candidates(paper, inputs))
    assert candidates[-1].url == 'https://api.elsevier.com/content/article/pii/S014067362400123X'
    assert candidates[-1].rule_id == 'API06'
