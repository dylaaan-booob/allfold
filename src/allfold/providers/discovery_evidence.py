"""Keep only explicit identity, location and version/date facts from native hits."""
from datetime import datetime, timezone
import re
from urllib.parse import quote, urlparse, unquote

from allfold.identifiers import normalize_doi, normalize_external_id, valid_doi
from allfold.models import (Author, EvidenceDate, EvidenceDateKind, ExternalIds,
    MetadataSource, ProviderRecordRef, ProviderTopic, ProviderWorkEvidence)
from allfold.providers.integrated import DiscoveryError
from allfold.paper_dates import source_date




def normalize_openalex(raw, source):
    if (raw.get('primary_location') or {}).get('raw_type') == 'journal-issue':
        return None
    record_id = str(raw.get('id') or '')
    if not record_id or not raw.get('title'):
        raise DiscoveryError('OpenAlex record lacks identity or title')
    now = datetime.now(timezone.utc)
    abstract = raw.get('abstract_inverted_index') or {}
    tokens = {i: word for word, positions in abstract.items() for i in positions}
    identifiers = {'openalex': record_id, 'doi': normalize_doi(raw.get('doi'))}
    for namespace in ('pmid', 'pmcid'):
        if identifier := normalize_external_id(namespace, (raw.get('ids') or {}).get(namespace)):
            identifiers[namespace] = identifier
    related, refs, locations = set(), set(), []
    for location in raw.get('locations', []):
        if not isinstance(location, dict):
            continue
        if doi := valid_doi(location.get('doi')):
            related.add(doi)
        for field in ('landing_page_url', 'pdf_url'):
            url = location.get(field)
            if not isinstance(url, str) or not url.startswith(('https://', 'http://')):
                continue
            venue = location.get('source') or {}
            locations.append(MetadataSource(provider='openalex', record_id=venue.get('id') or venue.get('display_name') or url,
                retrieved_at=now, url=url, version=location.get('version')))
            parsed = urlparse(url)
            host, path = (parsed.hostname or '').lower(), unquote(parsed.path)
            if host in {'doi.org', 'dx.doi.org'} and (doi := valid_doi(path.lstrip('/'))):
                related.add(doi)
            if host in {'arxiv.org', 'www.arxiv.org', 'export.arxiv.org'}:
                arxiv = normalize_external_id('arxiv', re.sub(r'^/(?:abs|pdf)/', '', path).removesuffix('.pdf'))
                if arxiv:
                    refs.add(ProviderRecordRef(provider='arxiv', record_id=arxiv))
            for platform in ('biorxiv', 'medrxiv'):
                if host in {platform + '.org', 'www.' + platform + '.org'}:
                    match = re.match(r'/content/(10\.1101/.+?)(?:v\d+)?(?:\.full(?:\.pdf)?)?/?$', path)
                    if match and (doi := valid_doi(match.group(1))):
                        related.add(doi)
                        refs.add(ProviderRecordRef(provider=platform, record_id=doi))
    return ProviderWorkEvidence(provenance=MetadataSource(provider='openalex', record_id=record_id, retrieved_at=now, url=record_id),
        title=raw['title'], journal=source.name or None,
        publication_type='preprint' if raw.get('type') in {'preprint', 'posted-content'} else 'journal',
        publication_date=raw.get('publication_date'),
        related_dois=tuple(sorted(related - {identifiers['doi']})), related_ids=tuple(sorted(refs, key=lambda x: (x.provider, x.record_id))),
        locations=tuple(locations), abstract=' '.join(tokens[i] for i in sorted(tokens)) or None,
        external_ids=ExternalIds(**identifiers), monitor_journal_issns=source.issns,
        authors=tuple(Author(name=x['author']['display_name']) for x in raw.get('authorships', []) if x.get('author', {}).get('display_name')))


def normalize_europe_pmc(raw, source):
    source_id, record_id = raw.get('source'), raw.get('id')
    if not source_id or not record_id or not raw.get('title'):
        raise DiscoveryError('Europe PMC record lacks source, identity or title')
    identity = f'{source_id}:{record_id}'
    preprint = source_id == 'PPR'
    ids = {'europe_pmc': identity, 'doi': normalize_doi(raw.get('doi'))}
    if source_id == 'MED':
        ids['pmid'] = str(record_id)
    if raw.get('pmcid'):
        ids['pmcid'] = raw['pmcid']
    related, refs, dates = set(), set(), []
    for relation in (raw.get('commentCorrectionList') or {}).get('commentCorrection', []):
        if str(relation.get('type', '')).strip().casefold() not in {'preprint in', 'preprint of'}:
            continue
        if relation.get('source') and relation.get('id'):
            refs.add(ProviderRecordRef(provider='europe_pmc', record_id=f"{relation['source']}:{relation['id']}"))
        if doi := valid_doi(relation.get('doi')):
            related.add(doi)
    version = str(raw.get('versionNumber') or '') or None
    current = source_date(raw.get('firstPublicationDate'), kind=EvidenceDateKind.PREPRINT if preprint else EvidenceDateKind.SOURCE,
        record_id=identity, version=version, publication_type='preprint' if preprint else 'journal', first_version=preprint and version == '1')
    if current:
        dates.append(current)
    for item in (raw.get('versionList') or {}).get('version', []):
        src, key = item.get('source'), item.get('id')
        if not src or not key:
            continue
        reference = f'{src}:{key}'
        refs.add(ProviderRecordRef(provider='europe_pmc', record_id=reference))
        if doi := valid_doi(item.get('doi')):
            related.add(doi)
        number = str(item.get('versionNumber') or '') or None
        event = source_date(item.get('firstPublishDate'), kind=EvidenceDateKind.PREPRINT if src == 'PPR' else EvidenceDateKind.SOURCE,
            record_id=reference, version=number, publication_type='preprint' if src == 'PPR' else 'journal',
            first_version=src == 'PPR' and number == '1')
        if event:
            dates.append(event)
    keywords = raw.get('keywordList', {}).get('keyword', [])
    return ProviderWorkEvidence(provenance=MetadataSource(provider='europe_pmc', record_id=identity,
        retrieved_at=datetime.now(timezone.utc), version=version,
        url='https://europepmc.org/article/' + quote(str(source_id), safe='') + '/' + quote(str(record_id), safe='')),
        title=raw['title'], journal=None if preprint else source.name or None,
        publication_type='preprint' if preprint else 'journal', publication_date=raw.get('firstPublicationDate'),
        related_dois=tuple(sorted(related - {ids['doi']})), related_ids=tuple(sorted(refs, key=lambda x: (x.provider, x.record_id))),
        dates=tuple(dates), abstract=raw.get('abstractText'), external_ids=ExternalIds(**ids), monitor_journal_issns=source.issns,
        indexed_terms=tuple(ProviderTopic(value=k, source='europe_pmc', kind='keyword') for k in keywords if isinstance(k, str) and k)
            + tuple(ProviderTopic(value=k['descriptorName'], source='europe_pmc', kind='mesh') for k in raw.get('meshHeadingList', {}).get('meshHeading', []) if k.get('descriptorName')),
        authors=tuple(Author(name=x['fullName']) for x in raw.get('authorList', {}).get('author', []) if x.get('fullName')))
