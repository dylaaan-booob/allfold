"""Keep only explicit identity, location and version/date facts from native hits."""
from datetime import datetime, timezone
import re
from urllib.parse import quote, urlparse, unquote

from allfold.identifiers import normalize_doi, normalize_external_id, valid_doi, supported_preprint_uri
from allfold.models import (Author, EvidenceDate, EvidenceDateKind, ExternalIds,
    MetadataSource, ProviderRecordRef, ProviderTopic, ProviderWorkEvidence)
from allfold.providers.integrated import DiscoveryError
from allfold.paper_dates import source_date




def _openalex_associations(raw, now):
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
            try:
                parsed = urlparse(url)
                port = parsed.port
            except ValueError:
                continue
            host, path = (parsed.hostname or '').lower(), unquote(parsed.path)
            if (host in {'doi.org', 'dx.doi.org'} and not parsed.username and not parsed.password
                    and not parsed.query and not parsed.fragment and port in {None, 80 if parsed.scheme == 'http' else 443}
                    and (doi := valid_doi(path.lstrip('/')))):
                related.add(doi)
            if target := supported_preprint_uri(url):
                platform, identifier = target
                refs.add(ProviderRecordRef(provider=platform, record_id=identifier, relation='preprint'))
                if platform in {'biorxiv', 'medrxiv'}:
                    related.add(identifier)
    return related, refs, locations


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
    related, refs, locations = _openalex_associations(raw, now)
    # Work merges can retain a preprint's PMID even when the top DOI is formal.
    # A Work-level identifier is association evidence, not direct article proof.
    for namespace in ('pmid', 'pmcid'):
        if identifier := normalize_external_id(namespace, (raw.get('ids') or {}).get(namespace)):
            if raw.get('type') in {'preprint', 'posted-content'}:
                identifiers[namespace] = identifier
            else:
                refs.add(ProviderRecordRef(provider=namespace, record_id=identifier))
    venue = (raw.get('primary_location') or {}).get('source') or {}
    issns = tuple(dict.fromkeys(str(value).upper() for value in (venue.get('issn') or [])
        if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{3}[\dXx]', value)))
    return ProviderWorkEvidence(provenance=MetadataSource(provider='openalex', record_id=record_id, retrieved_at=now, url=record_id),
        title=raw['title'], journal=venue.get('display_name') or source.name or None, journal_issns=issns,
        publication_type='preprint' if raw.get('type') in {'preprint', 'posted-content'} else 'journal',
        publication_date=raw.get('publication_date'),
        related_dois=tuple(sorted(related - {identifiers['doi']})), related_ids=tuple(sorted(refs, key=lambda x: (x.provider, x.record_id))),
        locations=tuple(locations), abstract=' '.join(tokens[i] for i in sorted(tokens)) or None,
        external_ids=ExternalIds(**identifiers), monitor_journal_issns=source.issns,
        authors=tuple(Author(name=x['author']['display_name']) for x in raw.get('authorships', []) if x.get('author', {}).get('display_name')))


def _europe_pmc_associations(raw):
    source_id, record_id = raw.get('source'), raw.get('id')
    if not isinstance(source_id, str) or not source_id.isalnum() or not isinstance(record_id, str) or not record_id.isalnum():
        raise DiscoveryError('Europe PMC record lacks reliable source/identity')
    identity = f'{source_id}:{record_id}'
    preprint = source_id == 'PPR'
    ids = {'europe_pmc': identity, 'doi': normalize_doi(raw.get('doi'))}
    if source_id == 'MED':
        ids['pmid'] = str(record_id)
    if raw.get('pmcid'):
        ids['pmcid'] = raw['pmcid']
    related, refs, dates = set(), set(), []
    publisher = str((raw.get('bookOrReportDetails') or {}).get('publisher') or '').strip().casefold()
    if preprint and publisher in {'biorxiv', 'medrxiv'} and ids['doi'] and ids['doi'].startswith(('10.1101/', '10.64898/')):
        refs.add(ProviderRecordRef(provider=publisher, record_id=ids['doi'], relation='preprint', version_family='doi:' + ids['doi']))
    for relation in (raw.get('commentCorrectionList') or {}).get('commentCorrection', []):
        if str(relation.get('type', '')).strip().casefold() not in {'preprint in', 'preprint of'}:
            continue
        target_preprint = str(relation.get('type', '')).strip().casefold() == 'preprint in'
        doi = valid_doi(relation.get('doi'))
        reference = f"{relation['source']}:{relation['id']}" if relation.get('source') and relation.get('id') else None
        target_family = ('doi:' + doi if doi else 'europe_pmc:' + reference if reference else None) if target_preprint else None
        note = str(relation.get('note') or '').strip() or None
        if reference:
            refs.add(ProviderRecordRef(provider='europe_pmc', record_id=reference,
                relation='preprint' if target_preprint else None, version_family=target_family, note=note))
        if doi:
            related.add(doi)
            if target_preprint:
                refs.add(ProviderRecordRef(provider='doi', record_id=doi, relation='preprint', version_family=target_family, note=note))
    version = str(raw.get('versionNumber') or '') or None
    versions = (raw.get('versionList') or {}).get('version', [])
    family = ('doi:' + ids['doi'] if ids['doi'] else 'europe_pmc:' + identity) if preprint else None
    if not family:
        family = next(('europe_pmc:' + f"{item['source']}:{item['id']}" for item in versions
            if item.get('source') == 'PPR' and item.get('id')), None)
    current = source_date(raw.get('firstPublicationDate'), kind=EvidenceDateKind.PREPRINT if preprint else EvidenceDateKind.PUBLISHED,
        source_label='firstPublicationDate', record_id=identity, version=version, version_family=family if preprint else None,
        publication_type='preprint' if preprint else 'journal', first_version=preprint and version == '1')
    if current:
        dates.append(current)
    for item in versions:
        src, key = item.get('source'), item.get('id')
        if not src or not key:
            continue
        reference = f'{src}:{key}'
        relation = 'version' if preprint and src == 'PPR' else 'preprint' if src == 'PPR' else None
        refs.add(ProviderRecordRef(provider='europe_pmc', record_id=reference, relation=relation, version_family=family if relation else None))
        if doi := valid_doi(item.get('doi')):
            related.add(doi)
            if relation:
                refs.add(ProviderRecordRef(provider='doi', record_id=doi, relation=relation, version_family=family))
        number = str(item.get('versionNumber') or '') or None
        event = source_date(item.get('firstPublishDate'), kind=EvidenceDateKind.PREPRINT if src == 'PPR' else EvidenceDateKind.PUBLISHED,
            source_label='firstPublishDate', record_id=reference, version=number, version_family=family if src == 'PPR' else None,
            publication_type='preprint' if src == 'PPR' else 'journal',
            first_version=src == 'PPR' and number == '1')
        if event:
            dates.append(event)
    return identity, preprint, ids, related, refs, dates, version


def normalize_europe_pmc(raw, source):
    if not raw.get('title'):
        raise DiscoveryError('Europe PMC record lacks title')
    source_id, record_id = raw.get('source'), raw.get('id')
    identity, preprint, ids, related, refs, dates, version = _europe_pmc_associations(raw)
    notes = sorted({f"{ref.provider}:{ref.record_id}: {ref.note}" for ref in refs if ref.note})
    keywords = raw.get('keywordList', {}).get('keyword', [])
    return ProviderWorkEvidence(provenance=MetadataSource(provider='europe_pmc', record_id=identity,
        retrieved_at=datetime.now(timezone.utc), version=version,
        note='; '.join(notes) or None,
        url='https://europepmc.org/article/' + quote(str(source_id), safe='') + '/' + quote(str(record_id), safe='')),
        title=raw['title'], journal=None if preprint else source.name or None,
        publication_type='preprint' if preprint else 'journal', publication_date=raw.get('firstPublicationDate'),
        related_dois=tuple(sorted(related - {ids['doi']})), related_ids=tuple(sorted(refs, key=lambda x: (x.provider, x.record_id))),
        dates=tuple(dates), abstract=raw.get('abstractText'), external_ids=ExternalIds(**ids), monitor_journal_issns=source.issns,
        indexed_terms=tuple(ProviderTopic(value=k, source='europe_pmc', kind='keyword') for k in keywords if isinstance(k, str) and k)
            + tuple(ProviderTopic(value=k['descriptorName'], source='europe_pmc', kind='mesh') for k in raw.get('meshHeadingList', {}).get('meshHeading', []) if k.get('descriptorName')),
        authors=tuple(Author(name=x['fullName']) for x in raw.get('authorList', {}).get('author', []) if x.get('fullName')))


def normalize_candidate(raw, source, provider):
    """Identity-only native discovery has no ordinary-metadata completeness claim."""
    now = datetime.now(timezone.utc)
    if provider == 'openalex':
        if (raw.get('primary_location') or {}).get('raw_type') == 'journal-issue':
            return None
        identity = normalize_external_id('openalex', raw.get('id'))
        if not identity:
            raise DiscoveryError('OpenAlex candidate lacks reliable Work identity')
        ids = {'openalex': raw['id'], 'doi': valid_doi(raw.get('doi'))}
        related, refs, locations = _openalex_associations(raw, now)
        publication_type = 'preprint' if raw.get('type') in {'preprint', 'posted-content'} else 'journal'
        for namespace in ('pmid', 'pmcid'):
            if value := normalize_external_id(namespace, (raw.get('ids') or {}).get(namespace)):
                if publication_type == 'preprint':
                    ids[namespace] = value
                else:
                    refs.add(ProviderRecordRef(provider=namespace, record_id=value))
        dates = ()
    else:
        identity, preprint, ids, related, refs, dates, _ = _europe_pmc_associations(raw)
        locations = []
        publication_type = 'preprint' if preprint else 'journal'
    return ProviderWorkEvidence(provenance=MetadataSource(provider=provider, record_id=raw['id'] if provider == 'openalex' else identity,
        retrieved_at=now, role='discovery'), external_ids=ExternalIds(**ids),
        publication_type=publication_type, monitor_journal_issns=source.issns, dates=tuple(dates),
        related_dois=tuple(sorted(related - {ids.get('doi')})),
        related_ids=tuple(sorted(refs, key=lambda item: (item.provider, item.record_id))), locations=tuple(locations))
