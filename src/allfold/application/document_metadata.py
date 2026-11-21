"""Guarded fixed Document operation; native evidence is consumed after normal cleanup."""
from dataclasses import dataclass, field
import re

from allfold.url_safety import normalize_public_http_url
from allfold.pdf_facts import (PdfDiscoveryFacts, PdfIdentifier, PdfRefreshLocator,
    persistent_pdf_candidate, stable_discovery_url, bounded_discovery_facts)

from allfold.application.collection_runtime import BranchSpec
from allfold.persistence.library_models import MetadataDelta, normalize_ordinary_dates


_DIAGNOSTICS = frozenset({'json_ld_invalid', 'json_ld_ambiguous',
    'abstract_candidate_failed', 'abstract_budget_exceeded', 'date_scan_failed', 'metadata_extraction_failed'})
_PARTIAL = frozenset({'abstract_candidate_failed', 'abstract_budget_exceeded', 'date_scan_failed', 'metadata_extraction_failed',
    'pdf_parse_failed', 'pdf_budget_exceeded', 'pdf_context_missing'})


class DocumentMetadataFailed(RuntimeError):
    pass


class DocumentMetadataPartial(DocumentMetadataFailed):
    """Independent content survived a local scanner failure; the branch is incomplete."""


@dataclass(frozen=True)
class DocumentMetadataResult:
    delta: MetadataDelta
    diagnostics: tuple[str, ...]
    recovery: object = None
    diagnostics_status: object = None

    @property
    def partial(self):
        return bool(_PARTIAL.intersection(self.diagnostics))


def _validate_content_metadata(value):
    """Strict structured content contract, allowing Main's outer annotations."""
    if not isinstance(value, dict) or value.get('outcome') != 'retrieved' or value.get('diagnostic') or value.get('error'):
        raise DocumentMetadataFailed('Document extraction failed')
    metadata, diagnostics = (value.get(key) for key in ('metadata', 'extraction_diagnostics'))
    if not isinstance(metadata, dict) or set(metadata) != {'dates', 'abstract'}:
        raise DocumentMetadataFailed('Invalid Document metadata')
    dates, abstract = metadata['dates'], metadata['abstract']
    if not isinstance(dates, list):
        raise DocumentMetadataFailed('Invalid Document dates')
    values = []
    for item in dates:
        if (not isinstance(item, dict) or set(item) != {'value', 'precision'}
                or not isinstance(item['value'], str)
                or not re.fullmatch(r'[0-9]{4}-[0-9]{2}(?:-[0-9]{2})?', item['value'])
                or item['precision'] != ('day' if len(item['value']) == 10 else 'month')):
            raise DocumentMetadataFailed('Invalid Document date')
        values.append(item['value'])
    try:
        if tuple(values) != normalize_ordinary_dates(tuple(values)):
            raise ValueError('Noncanonical dates')
    except ValueError as error:
        raise DocumentMetadataFailed('Invalid Document dates') from error
    if abstract is not None and (not isinstance(abstract, str) or not abstract.strip()
            or len(abstract.encode('utf-16-le', errors='surrogatepass')) // 2 > 65536
            or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', abstract)):
        raise DocumentMetadataFailed('Invalid Document abstract')
    if (not isinstance(diagnostics, list) or len(diagnostics) > len(_DIAGNOSTICS)
            or any(not isinstance(code, str) or code not in _DIAGNOSTICS for code in diagnostics)
            or len(set(diagnostics)) != len(diagnostics)):
        raise DocumentMetadataFailed('Invalid Document extraction diagnostics')
    return DocumentMetadataResult(MetadataDelta(ordinary_dates=tuple(values), abstract=abstract), tuple(diagnostics),
        recovery=value.get('recovery'), diagnostics_status=value.get('diagnostics_status'))


@dataclass(frozen=True)
class CurrentPdfClue:
    """A bounded current-operation candidate; transient URLs are never metadata."""
    stage: str
    rule_id: str
    url: str
    action: str | None = None
    reader_kind: str | None = None
    referer: str | None = None
    field: str | None = None


@dataclass(frozen=True)
class ReaderResult:
    """Operation-local navigation/access result, never a durable PDF fact."""
    url: str
    referer: str | None
    context_changed: bool
    context_key: str = field(repr=False)


@dataclass(frozen=True)
class DocumentPdfResult:
    facts: PdfDiscoveryFacts
    current_candidates: tuple[CurrentPdfClue, ...]
    recovery: object = None
    diagnostics_status: object = None
    reader_result: ReaderResult | None = None
    ebsco_viewer_url: str | None = field(default=None, repr=False)


def validate_document_pdf_clues(value, *, target_doi=None):
    """Validate fixed native evidence; build a separate persistable projection."""
    if not isinstance(value, dict) or value.get('outcome') != 'retrieved' or value.get('diagnostic') or value.get('error'):
        raise DocumentMetadataFailed('Document PDF extraction failed')
    clues = value.get('pdf_clues')
    if not isinstance(clues, dict) or set(clues) != {'status', 'landing_url', 'observed_at',
            'platform', 'content_type', 'identifiers', 'candidates', 'diagnostics'}:
        raise DocumentMetadataFailed('Invalid Document PDF clues')
    def public_url(url):
        try:
            return normalize_public_http_url(url) if isinstance(url, str) else None
        except ValueError:
            return None

    landing = public_url(clues['landing_url'])
    try:
        if (not isinstance(clues['observed_at'], str) or not re.fullmatch(
                r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z', clues['observed_at'])
                or not isinstance(clues['candidates'], list)
                or not isinstance(clues['identifiers'], list)
                or not isinstance(clues['diagnostics'], list) or len(clues['diagnostics']) > 3
                or len(set(clues['diagnostics'])) != len(clues['diagnostics'])
                or any(code not in {'pdf_parse_failed', 'pdf_budget_exceeded', 'pdf_context_missing'} for code in clues['diagnostics'])):
            raise ValueError('Invalid bounded clues')
        current, persisted = [], []
        reasons = {'pdf_budget_exceeded': 'overflow', 'pdf_context_missing': 'invalid-url', 'pdf_parse_failed': 'parse-failed'}
        diagnostics = list(dict.fromkeys(reasons[code] for code in clues['diagnostics']))
        def missing_context():
            if 'invalid-url' not in diagnostics:
                diagnostics.append('invalid-url')

        if landing is None:
            missing_context()
        for candidate in clues['candidates']:
            if (not isinstance(candidate, dict) or not {'stage', 'rule_id', 'url'} <= set(candidate)
                    or set(candidate) - {'stage', 'rule_id', 'url', 'action', 'reader_kind', 'referer', 'field'}
                    or candidate['stage'] not in {'P1', 'P2', 'P3', 'P4', 'P5'}
                    or not re.fullmatch(r'(?:R[0-9]{3}|GENERIC)', candidate['rule_id'])
                    or candidate.get('action') not in {None, 'refresh_form'}
                    or candidate.get('reader_kind') not in {None, 'sciencedirect', 'lww', 'ieee'}
                    or candidate.get('field') not in {None, 'citation_pdf_url', 'fulltext_pdf_url', 'ebsco_download_link'}
                    or candidate.get('field') == 'ebsco_download_link' and (
                        clues['platform'], candidate['rule_id'], candidate['stage']) != ('ebsco', 'R073', 'P4')):
                raise ValueError('Invalid candidate')
            if not public_url(candidate['url']):
                missing_context()
                continue
            fields = dict(candidate)
            if fields.get('referer') is not None and public_url(fields['referer']) is None:
                missing_context()
                fields['referer'] = None
            current.append(CurrentPdfClue(**fields))
            if fields.get('action') == 'refresh_form':
                # A form locator is an action to re-read, never a durable GET request.
                fields.update(url=None, referer=None, refresh=PdfRefreshLocator(kind='document-pdf',
                    landing_url=stable_discovery_url(landing)))
            persisted.append(persistent_pdf_candidate(refresh_kind='document-pdf', landing_url=landing, **fields))
        if any(not isinstance(item, dict) or set(item) != {'kind', 'value', 'rule_id'} for item in clues['identifiers']):
            raise ValueError('Invalid identifiers')
        status = clues['status']
        if status == 'complete' and clues['diagnostics']:
            raise ValueError('Parse failures cannot become complete empty success')
        if status == 'complete' and diagnostics:
            status = 'partial'
        facts = bounded_discovery_facts(source='document', capability='document-pdf', status=status,
            observed_at=clues['observed_at'], target_doi=target_doi,
            landing_url=stable_discovery_url(landing), platform=clues['platform'], content_type=clues['content_type'],
            identifiers=tuple(PdfIdentifier(**item) for item in clues['identifiers']), candidates=tuple(persisted),
            diagnostics=tuple(diagnostics))
        if facts.status != 'complete' and not facts.diagnostics:
            raise ValueError('Failed extraction must carry a diagnostic')
    except (TypeError, ValueError) as error:
        raise DocumentMetadataFailed('Invalid Document PDF clues') from error
    reader = value.get('reader_result')
    if reader is not None:
        try:
            if (not isinstance(reader, dict) or set(reader) != {'url', 'referer', 'context_changed', 'context_key'}
                    or type(reader['context_changed']) is not bool
                    or not isinstance(reader['context_key'], str) or not re.fullmatch(r'[a-f0-9]{64}', reader['context_key'])):
                raise ValueError('Invalid Reader result')
            if not public_url(reader['url']) or reader['referer'] is not None and not public_url(reader['referer']):
                raise ValueError('Invalid Reader URL')
            reader = ReaderResult(**reader)
        except (TypeError, ValueError):
            reader = None
            status = 'partial' if facts.status == 'complete' else facts.status
            facts = facts.model_copy(update={'status': status,
                'diagnostics': tuple(dict.fromkeys((*facts.diagnostics, 'invalid-url')))})
    viewer = value.get('ebsco_viewer_url')
    if viewer is not None and (clues['platform'] != 'ebsco' or not public_url(viewer)):
        viewer = None
        facts = facts.model_copy(update={'status': 'partial',
            'diagnostics': tuple(dict.fromkeys((*facts.diagnostics, 'invalid-url')))})
    return DocumentPdfResult(facts, tuple(current), value.get('recovery'), value.get('diagnostics_status'), reader, viewer)


def validate_document_metadata(value, *, target_doi=None):
    """Keep Date/Abstract and PDF outcomes independent from the captured page."""
    if not isinstance(value, dict) or value.get('metadata_status') not in {'complete', 'partial', 'failed'}:
        raise DocumentMetadataFailed('Invalid Document metadata status')
    status = value['metadata_status']
    if status == 'failed':
        if value.get('metadata') is not None or value.get('extraction_diagnostics') != ['metadata_extraction_failed']:
            raise DocumentMetadataFailed('Invalid failed Document metadata')
        content = _validate_content_metadata(value | {'metadata': {'dates': [], 'abstract': None}})
    else:
        content = _validate_content_metadata(value)
        if (status == 'partial') != content.partial:
            raise DocumentMetadataFailed('Invalid partial Document metadata')
    pdf = validate_document_pdf_clues(value, target_doi=target_doi)
    pdf_diagnostics = (*value['pdf_clues']['diagnostics'], *(
        code for reason, code in (('overflow', 'pdf_budget_exceeded'), ('invalid-url', 'pdf_context_missing'))
        if reason in pdf.facts.diagnostics))
    return DocumentMetadataResult(MetadataDelta(**content.delta.model_dump() | {'discovery_facts': (pdf.facts,)}),
        content.diagnostics + tuple(dict.fromkeys(pdf_diagnostics)),
        recovery=content.recovery, diagnostics_status=content.diagnostics_status)


def _paper_identity(paper, confirmed_article_url):
    identity = {}
    if paper.primary_identity is not None and paper.primary_identity.namespace == 'doi':
        identity['doi'] = paper.primary_identity.value
    if confirmed_article_url is not None:
        if not isinstance(confirmed_article_url, str) or not normalize_public_http_url(confirmed_article_url):
            raise ValueError('Expected a trusted confirmed article URL')
        identity['confirmed_article_url'] = confirmed_article_url
    if not identity:
        raise DocumentMetadataFailed('Document extraction requires DOI or confirmed article URL')
    return identity


def read_document_pdf_clues(context, *, confirmed_article_url=None, reader=None, prepared_source=None,
                           prepared_record=None, prepared_viewer=None):
    """Read current PDF inputs without emitting or reopening any collection state.

    The caller owns a captured read-only task context with read_paper(),
    native_payload(), execute_native() and its normal authority/cleanup lifecycle.
    A reader is a trusted immutable candidate chain, never a webpage-supplied URL.
    """
    paper = context.read_paper()
    identity = _paper_identity(paper, confirmed_article_url)
    payload = context.native_payload() | {'identity': identity}
    if reader is not None:
        payload['reader'] = dict(reader) | {'target': identity}
    if prepared_source is not None:
        payload.update(prepared_source=prepared_source, target_title=paper.metadata.title)
        if prepared_record is not None:
            payload['prepared_record'] = prepared_record
        if prepared_viewer is not None:
            payload['prepared_viewer'] = prepared_viewer
    return validate_document_pdf_clues(context.execute_native('extract_paper_pdf_clues', payload).result(),
        target_doi=identity.get('doi'))


def collect_document_metadata(context, *, confirmed_article_url=None):
    paper = context.read_paper()
    identity = _paper_identity(paper, confirmed_article_url)
    payload = context.native_payload() | dict(identity=identity,
        wantAbstract=not paper.metadata.abstract and paper.abstract_generation == context.token.write.abstract_generation)
    result = validate_document_metadata(context.execute_native('extract_paper_metadata', payload).result(), target_doi=identity.get('doi'))
    # Native parsed a detached snapshot and closed its owned page.
    # Only the original attempt/field authority is rechecked by emit, never the page.
    context.emit(result.delta, sequence=1)
    return result


def document_metadata_branch(*, name='document', confirmed_article_url=None):
    def run(context):
        result = collect_document_metadata(context, confirmed_article_url=confirmed_article_url)
        if result.partial:
            raise DocumentMetadataPartial('Partial Document extraction: ' + ', '.join(result.diagnostics))
    return BranchSpec(name, run)
