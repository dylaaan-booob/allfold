"""NCBI native records: direct article identity, bibliography and named events."""
from __future__ import annotations

from calendar import month_abbr, month_name
from datetime import datetime, timezone
import re
import xml.etree.ElementTree as ET

from allfold.identifiers import normalize_external_id, valid_doi
from allfold.models import Author, ExternalIds, MetadataSource, ProviderRecordRef, ProviderWorkEvidence
from allfold.paper_dates import source_date
from allfold.providers.integrated import DiscoveryError, IdentityMismatch

MONTHS = {name.casefold(): index for index in range(1, 13) for name in (month_abbr[index], month_name[index], str(index), f'{index:02d}')}
EVENTS = {'received':'received', 'accepted':'accepted', 'epublish':'published-online', 'ppublish':'published', 'aheadofprint':'published-online'}


def has_entrez_error(payload):
    errors = payload.get('errorlist')
    return bool(payload.get('error')) or (any(errors.values()) if isinstance(errors, dict) else bool(errors))


def esearch_identifiers(payload):
    """Require the entire PubMed ESearch UID set before using it as identity evidence."""
    data = payload.get('esearchresult')
    if not isinstance(data, dict) or has_entrez_error(data):
        raise DiscoveryError('PubMed: Entrez ESearch application error or invalid result')
    count, identifiers = data.get('count'), data.get('idlist')
    if not re.fullmatch(r'[0-9]+', str(count)) or len(str(count)) > 4 or int(count) > 9999:
        raise DiscoveryError('Incomplete: invalid or excessive PubMed ESearch count')
    if (not isinstance(identifiers, list) or len(identifiers) != int(count)
            or any(not isinstance(value, str) or not re.fullmatch(r'[0-9]+', value) for value in identifiers)
            or len(set(identifiers)) != len(identifiers)
            or str(data.get('retstart', '0')) != '0'):
        raise DiscoveryError('Incomplete: PubMed ESearch PMID set is shortened or invalid')
    return tuple(identifiers)


def _text(node):
    return ' '.join(''.join(node.itertext()).split()) if node is not None else ''


def _date(node):
    if node is None:
        return None
    year = node.findtext('Year')
    if not year:
        text = node.findtext('MedlineDate') or ''
        match = re.fullmatch(r'(\d{4})(?:\s+([A-Za-z]+))?', text.strip())
        if not match:
            return None
        year, month = match.groups()
        return year + (f'-{MONTHS[month.casefold()]:02d}' if month and month.casefold() in MONTHS else '')
    month = MONTHS.get((node.findtext('Month') or '').casefold())
    day = node.findtext('Day')
    value = year + (f'-{month:02d}' if month else '')
    return value + (f'-{int(day):02d}' if day and month and day.isdigit() else '')


def _event(value, kind, label, pmid, publication_type):
    return source_date(value, kind=kind, source_label=label, provider='pubmed', record_id=pmid,
                       publication_type=publication_type, url=f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/')


def _relation(kind, identifier):
    key = re.sub(r'[^a-z]', '', str(kind).casefold())
    relation = ('preprint' if key == 'preprintin' else 'version' if key in {'updatein','updateof','republishedin','republishedfrom'} else None)
    pmid = normalize_external_id('pmid', identifier)
    if pmid and (relation or key == 'preprintof'):
        return ProviderRecordRef(provider='pubmed', record_id=pmid, relation=relation)
    return None


def fetch_records(xml):
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise DiscoveryError('PubMed: invalid EFetch XML') from None
    if root.tag != 'PubmedArticleSet' or root.find('.//ERROR') is not None or root.find('.//Error') is not None:
        raise DiscoveryError('PubMed: Entrez application error or invalid EFetch document')
    records = []
    for item in root:
        if item.tag != 'PubmedArticle':
            raise DiscoveryError('PubMed: unsupported or incomplete EFetch article')
        citation, data = item.find('MedlineCitation'), item.find('PubmedData')
        pmid = normalize_external_id('pmid', citation.findtext('PMID') if citation is not None else None)
        article = citation.find('Article') if citation is not None else None
        if not pmid or article is None:
            raise DiscoveryError('PubMed: EFetch article lacks direct PMID or bibliography')
        ids = {'pmid':pmid}
        for identity in data.findall('./ArticleIdList/ArticleId') if data is not None else ():
            kind, value = identity.get('IdType'), _text(identity)
            if kind == 'pubmed' and normalize_external_id('pmid', value) != pmid:
                raise IdentityMismatch('PubMed: conflicting direct PMID')
            if kind == 'doi' and (doi := valid_doi(value)):
                if ids.get('doi') and ids['doi'] != doi:
                    raise IdentityMismatch('PubMed: conflicting direct DOI')
                ids['doi'] = doi
            if kind == 'pmc' and (pmcid := normalize_external_id('pmcid', value)):
                ids['pmcid'] = pmcid
        # ELocationID identifies this Article, unlike cited ReferenceList DOIs.
        for identity in article.findall('ELocationID'):
            if identity.get('EIdType') == 'doi' and identity.get('ValidYN', 'Y') == 'Y' and (doi := valid_doi(_text(identity))):
                if ids.get('doi') and ids['doi'] != doi:
                    raise IdentityMismatch('PubMed: conflicting direct DOI')
                ids['doi'] = doi
        preprint = (any(_text(node).casefold() == 'preprint' for node in article.findall('./PublicationTypeList/PublicationType'))
            or any(node.get('RefType', '').casefold() == 'preprintof' for node in citation.findall('./CommentsCorrectionsList/CommentsCorrections')))
        publication_type = 'preprint' if preprint else 'journal'
        dates = []
        for event in data.findall('./History/PubMedPubDate') if data is not None else ():
            label = event.get('PubStatus')
            if label in EVENTS and (fact := _event(_date(event), EVENTS[label], 'PubMedPubDate:' + label, pmid, publication_type)):
                dates.append(fact)
        for event in article.findall('ArticleDate'):
            if event.get('DateType') == 'Electronic' and (fact := _event(_date(event), 'published-online', 'ArticleDate:Electronic', pmid, publication_type)):
                dates.append(fact)
        publication = _date(article.find('./Journal/JournalIssue/PubDate'))
        if fact := _event(publication, 'published', 'JournalIssue:PubDate', pmid, publication_type):
            dates.append(fact)
        authors = []
        for author in article.findall('./AuthorList/Author'):
            name = _text(author.find('CollectiveName')) or ' '.join(filter(None, (author.findtext('ForeName') or author.findtext('Initials'), author.findtext('LastName'))))
            if name:
                authors.append(Author(name=name))
        abstract = []
        for part in article.findall('./Abstract/AbstractText'):
            text, label = _text(part), part.get('Label')
            if text:
                abstract.append(f'{label}: {text}' if label else text)
        refs = tuple(ref for relation in citation.findall('./CommentsCorrectionsList/CommentsCorrections')
                     if (ref := _relation(relation.get('RefType'), relation.findtext('PMID'))))
        issns = tuple(dict.fromkeys(value.upper() for value in (article.findtext('./Journal/ISSN'), citation.findtext('./MedlineJournalInfo/ISSNLinking')) if value and re.fullmatch(r'\d{4}-\d{3}[\dXx]', value)))
        records.append(ProviderWorkEvidence(provenance=MetadataSource(provider='pubmed', record_id=pmid,
            retrieved_at=datetime.now(timezone.utc), url=f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/'),
            title=_text(article.find('ArticleTitle')) or None, journal=article.findtext('./Journal/Title'),
            journal_issns=issns, publication_type=publication_type, publication_date=publication,
            abstract='\n'.join(abstract) or None, authors=tuple(authors), external_ids=ExternalIds(**ids), dates=tuple(dates), related_ids=refs,
            volume=article.findtext('./Journal/JournalIssue/Volume'), issue=article.findtext('./Journal/JournalIssue/Issue'),
            pages=article.findtext('./Pagination/MedlinePgn')))
    return tuple(records)


def _summary_date(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    numeric = re.fullmatch(r'(\d{4})/(\d{1,2})/(\d{1,2})(?:\s+\d{2}:\d{2}(?::\d{2})?)?', value)
    if numeric:
        year, month, day = map(int, numeric.groups())
        return f'{year:04d}-{month:02d}-{day:02d}'
    if re.fullmatch(r'\d{4}(?:-\d{2}){0,2}', value):
        return value
    match = re.fullmatch(r'(\d{4})(?:\s+([A-Za-z]+|\d{1,2})(?:\s+(\d{1,2}))?)?(?:\s+\d{2}:\d{2})?', value)
    if not match:
        return None
    year, month, day = match.groups()
    number = MONTHS.get((month or '').casefold())
    return year + (f'-{number:02d}' if number else '') + (f'-{int(day):02d}' if number and day else '')


def summary_records(payload):
    if has_entrez_error(payload):
        raise DiscoveryError('PubMed: Entrez ESummary application error')
    result = payload.get('result')
    if not isinstance(result, dict) or not isinstance(result.get('uids'), list):
        raise DiscoveryError('PubMed: invalid ESummary v2 response')
    records = []
    for uid in result['uids']:
        item = result.get(str(uid))
        pmid = normalize_external_id('pmid', uid)
        if not isinstance(item, dict) or item.get('error') or not pmid or normalize_external_id('pmid', item.get('uid')) != pmid:
            raise DiscoveryError('PubMed: incomplete ESummary record')
        ids, dates, refs = {'pmid':pmid}, [], []
        for identity in item.get('articleids', []):
            kind, value = identity.get('idtype'), identity.get('value')
            if kind == 'doi' and (doi := valid_doi(value)):
                if ids.get('doi') and ids['doi'] != doi:
                    raise IdentityMismatch('PubMed: conflicting direct DOI')
                ids['doi'] = doi
            if kind == 'pubmed' and normalize_external_id('pmid', value) != pmid:
                raise IdentityMismatch('PubMed: conflicting direct PMID')
            if kind == 'pmc' and (pmcid := normalize_external_id('pmcid', value)):
                ids['pmcid'] = pmcid
        preprint = (any(str(kind).casefold() == 'preprint' for kind in item.get('pubtype', []))
            or any(str(ref.get('reftype') or ref.get('type')).casefold() == 'preprintof' for ref in item.get('references', [])))
        publication_type = 'preprint' if preprint else 'journal'
        for event in item.get('history', []):
            label = event.get('pubstatus')
            if label in EVENTS and (fact := _event(_summary_date(event.get('date')), EVENTS[label], 'history:' + label, pmid, publication_type)):
                dates.append(fact)
        for field, kind in (('pubdate','published'), ('epubdate','published-online')):
            if fact := _event(_summary_date(item.get(field)), kind, field, pmid, publication_type):
                dates.append(fact)
        for relation in item.get('references', []):
            if ref := _relation(relation.get('reftype') or relation.get('type'), relation.get('pmid')):
                refs.append(ref)
        records.append(ProviderWorkEvidence(provenance=MetadataSource(provider='pubmed', record_id=pmid,
            retrieved_at=datetime.now(timezone.utc), url=f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/'),
            title=item.get('title') or None, journal=item.get('fulljournalname') or item.get('source') or None,
            publication_type=publication_type, publication_date=_summary_date(item.get('pubdate')),
            journal_issns=tuple(dict.fromkeys(value for value in (item.get('issn'), item.get('essn')) if value)),
            authors=tuple(Author(name=author['name']) for author in item.get('authors', []) if author.get('name')),
            external_ids=ExternalIds(**ids), dates=tuple(dates), related_ids=tuple(refs)))
    return tuple(records)
