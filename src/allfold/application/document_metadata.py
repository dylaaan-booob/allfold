"""Guarded fixed Document operation; native evidence is consumed after normal cleanup."""
from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from allfold.url_safety import normalize_public_http_url
from allfold.pdf_facts import (PdfDiscoveryFacts, PdfIdentifier, PdfRefreshLocator,
    persistent_pdf_candidate, stable_discovery_url)

from allfold.application.collection_runtime import BranchSpec
from allfold.persistence.library_models import MetadataDelta, normalize_ordinary_dates


_DIAGNOSTICS = frozenset({'json_ld_invalid', 'json_ld_ambiguous',
    'abstract_candidate_failed', 'abstract_budget_exceeded', 'metadata_extraction_failed'})
_PARTIAL = frozenset({'abstract_candidate_failed', 'abstract_budget_exceeded', 'metadata_extraction_failed',
    'pdf_parse_failed', 'pdf_budget_exceeded'})


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
    """Strict small content/binding contract, allowing Main's outer annotations."""
    if not isinstance(value, dict) or value.get('outcome') != 'retrieved' or value.get('diagnostic') or value.get('error'):
        raise DocumentMetadataFailed('Document extraction failed')
    metadata, document, diagnostics = (value.get(key) for key in ('metadata', 'document', 'extraction_diagnostics'))
    if not isinstance(metadata, dict) or set(metadata) != {'dates', 'abstract'}:
        raise DocumentMetadataFailed('Invalid Document metadata')
    dates, abstract = metadata['dates'], metadata['abstract']
    if not isinstance(dates, list) or len(dates) > 256:
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
    if (not isinstance(diagnostics, list) or len(diagnostics) > 4
            or any(not isinstance(code, str) or code not in _DIAGNOSTICS for code in diagnostics)
            or len(set(diagnostics)) != len(diagnostics)):
        raise DocumentMetadataFailed('Invalid Document extraction diagnostics')
    if not isinstance(document, dict) or set(document) != {
            'pageId', 'processId', 'frameToken', 'documentId', 'navigationGeneration'}:
        raise DocumentMetadataFailed('Invalid Document binding')
    for key in ('pageId', 'processId', 'navigationGeneration'):
        if type(document[key]) is not int or not 0 <= document[key] <= 2**53 - 1:
            raise DocumentMetadataFailed('Invalid Document binding')
    for key in ('frameToken', 'documentId'):
        if not isinstance(document[key], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', document[key]):
            raise DocumentMetadataFailed('Invalid Document binding')
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
class DocumentPdfResult:
    facts: PdfDiscoveryFacts
    current_candidates: tuple[CurrentPdfClue, ...]
    recovery: object = None
    diagnostics_status: object = None


def validate_document_pdf_clues(value, *, target_doi=None):
    """Validate fixed native evidence; build a separate persistable projection."""
    if not isinstance(value, dict) or value.get('outcome') != 'retrieved' or value.get('diagnostic') or value.get('error'):
        raise DocumentMetadataFailed('Document PDF extraction failed')
    # Reuse the exact native envelope validation without requiring content scanning.
    _validate_content_metadata(value | {'metadata': {'dates': [], 'abstract': None}, 'extraction_diagnostics': []})
    clues = value.get('pdf_clues')
    if not isinstance(clues, dict) or set(clues) != {'status', 'landing_url', 'observed_at',
            'platform', 'content_type', 'identifiers', 'candidates', 'diagnostics'}:
        raise DocumentMetadataFailed('Invalid Document PDF clues')
    if len(str(clues)) > 70000:
        raise DocumentMetadataFailed('Invalid Document PDF payload budget')
    landing = clues['landing_url']
    if (not isinstance(landing, str) or not 1 <= len(landing) <= 4096 or re.search(r'[\s\x00-\x1f]', landing)):
        raise DocumentMetadataFailed('Invalid Document PDF landing URL')
    try:
        parsed = urlsplit(landing)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Invalid landing URL')
        parsed.port
        if (not isinstance(clues['observed_at'], str) or not re.fullmatch(
                r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z', clues['observed_at'])
                or not isinstance(clues['candidates'], list) or len(clues['candidates']) > 32
                or not isinstance(clues['identifiers'], list) or len(clues['identifiers']) > 16
                or not isinstance(clues['diagnostics'], list) or len(clues['diagnostics']) > 2
                or len(set(clues['diagnostics'])) != len(clues['diagnostics'])
                or any(code not in {'pdf_parse_failed', 'pdf_budget_exceeded'} for code in clues['diagnostics'])):
            raise ValueError('Invalid bounded clues')
        current, persisted = [], []
        for candidate in clues['candidates']:
            if (not isinstance(candidate, dict) or not {'stage', 'rule_id', 'url'} <= set(candidate)
                    or set(candidate) - {'stage', 'rule_id', 'url', 'action', 'reader_kind', 'referer', 'field'}
                    or candidate['stage'] not in {'P1', 'P2', 'P3', 'P4', 'P5'}
                    or not re.fullmatch(r'(?:R[0-9]{3}|GENERIC)', candidate['rule_id'])
                    or not isinstance(candidate['url'], str) or len(candidate['url']) > 4096
                    or candidate.get('action') not in {None, 'refresh_form'}
                    or candidate.get('reader_kind') not in {None, 'sciencedirect', 'lww', 'ieee'}
                    or candidate.get('field') not in {None, 'citation_pdf_url', 'fulltext_pdf_url'}):
                raise ValueError('Invalid candidate')
            if normalize_public_http_url(candidate['url']) is None:
                raise ValueError('Empty candidate URL')
            if candidate.get('referer') is not None:
                if not isinstance(candidate['referer'], str) or len(candidate['referer']) > 4096:
                    raise ValueError('Invalid Referer')
                normalize_public_http_url(candidate['referer'])
            current.append(CurrentPdfClue(**candidate))
            fields = dict(candidate)
            if fields.get('action') == 'refresh_form':
                # A form locator is an action to re-read, never a durable GET request.
                fields.update(url=None, referer=None, refresh=PdfRefreshLocator(kind='document-pdf',
                    landing_url=stable_discovery_url(landing)))
            persisted.append(persistent_pdf_candidate(refresh_kind='document-pdf', landing_url=landing, **fields))
        if any(not isinstance(item, dict) or set(item) != {'kind', 'value', 'rule_id'} for item in clues['identifiers']):
            raise ValueError('Invalid identifiers')
        facts = PdfDiscoveryFacts(source='document', capability='document-pdf', status=clues['status'],
            observed_at=clues['observed_at'], target_doi=target_doi,
            landing_url=stable_discovery_url(landing), platform=clues['platform'], content_type=clues['content_type'],
            identifiers=tuple(PdfIdentifier(**item) for item in clues['identifiers']), candidates=tuple(persisted),
            diagnostics=tuple('overflow' if code == 'pdf_budget_exceeded' else 'parse-failed' for code in clues['diagnostics']))
        if facts.status != 'complete' and not facts.diagnostics:
            raise ValueError('Failed extraction must carry a bounded diagnostic')
        if facts.status == 'complete' and facts.diagnostics:
            raise ValueError('Parse failures cannot become complete empty success')
    except (TypeError, ValueError) as error:
        raise DocumentMetadataFailed('Invalid Document PDF clues') from error
    return DocumentPdfResult(facts, tuple(current), value.get('recovery'), value.get('diagnostics_status'))


def validate_document_metadata(value, *, target_doi=None):
    """Keep Date/Abstract and PDF outcomes independent under one final binding."""
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
    return DocumentMetadataResult(MetadataDelta(**content.delta.model_dump() | {'discovery_facts': (pdf.facts,)}),
        content.diagnostics + tuple(value['pdf_clues']['diagnostics']),
        recovery=content.recovery, diagnostics_status=content.diagnostics_status)


def _paper_identity(paper, confirmed_article_url):
    identity = {}
    if paper.primary_identity is not None and paper.primary_identity.namespace == 'doi':
        identity['doi'] = paper.primary_identity.value
    if confirmed_article_url is not None:
        if not isinstance(confirmed_article_url, str) or not 1 <= len(confirmed_article_url) <= 4096 or re.search(r'\s', confirmed_article_url):
            raise ValueError('Expected a trusted confirmed article URL')
        parsed = urlsplit(confirmed_article_url)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError('Expected a trusted confirmed article URL')
        identity['confirmed_article_url'] = confirmed_article_url
    if not identity:
        raise DocumentMetadataFailed('Document extraction requires DOI or confirmed article URL')
    return identity


def read_document_pdf_clues(context, *, confirmed_article_url=None, reader=None):
    """Read current PDF inputs without emitting or reopening any collection state.

    The caller owns a captured read-only task context with read_paper(),
    native_payload(), execute_native() and its normal authority/cleanup lifecycle.
    A reader is a trusted immutable candidate chain, never a webpage-supplied URL.
    """
    identity = _paper_identity(context.read_paper(), confirmed_article_url)
    payload = context.native_payload() | {'identity': identity}
    if reader is not None:
        payload['reader'] = dict(reader) | {'target': identity}
    return validate_document_pdf_clues(context.execute_native('extract_paper_pdf_clues', payload).result(),
        target_doi=identity.get('doi'))


def collect_document_metadata(context, *, confirmed_article_url=None):
    paper = context.read_paper()
    identity = _paper_identity(paper, confirmed_article_url)
    payload = context.native_payload() | dict(identity=identity,
        wantAbstract=not paper.metadata.abstract and paper.abstract_generation == context.token.write.abstract_generation)
    result = validate_document_metadata(context.execute_native('extract_paper_metadata', payload).result(), target_doi=identity.get('doi'))
    # Native has already revalidated the live Document and closed its owned page.
    # Only the original attempt/field authority is rechecked by emit, never the page.
    context.emit(result.delta, sequence=1)
    return result


def document_metadata_branch(*, name='document', confirmed_article_url=None):
    def run(context):
        result = collect_document_metadata(context, confirmed_article_url=confirmed_article_url)
        if result.partial:
            raise DocumentMetadataPartial('Partial Document extraction: ' + ', '.join(result.diagnostics))
    return BranchSpec(name, run)
