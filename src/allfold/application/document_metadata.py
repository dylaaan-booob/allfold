"""Guarded fixed Document operation; native evidence is consumed after normal cleanup."""
from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from allfold.application.collection_runtime import BranchSpec
from allfold.persistence.library_models import MetadataDelta, normalize_ordinary_dates


_DIAGNOSTICS = frozenset({'json_ld_invalid', 'json_ld_ambiguous',
    'abstract_candidate_failed', 'abstract_budget_exceeded'})
_PARTIAL = frozenset({'abstract_candidate_failed', 'abstract_budget_exceeded'})


class DocumentMetadataFailed(RuntimeError):
    pass


class DocumentMetadataPartial(DocumentMetadataFailed):
    """Dates survived a locally failed abstract; this branch is not complete."""


@dataclass(frozen=True)
class DocumentMetadataResult:
    delta: MetadataDelta
    diagnostics: tuple[str, ...]
    recovery: object = None
    diagnostics_status: object = None

    @property
    def partial(self):
        return bool(_PARTIAL.intersection(self.diagnostics))


def validate_document_metadata(value):
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


def collect_document_metadata(context, *, confirmed_article_url=None):
    paper = context.read_paper()
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
    payload = context.native_payload() | dict(identity=identity,
        wantAbstract=not paper.metadata.abstract and paper.abstract_generation == context.token.write.abstract_generation)
    result = validate_document_metadata(context.execute_native('extract_paper_metadata', payload).result())
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
