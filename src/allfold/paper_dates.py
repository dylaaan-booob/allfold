"""Version-bound date facts shared by creation and explicit enrichment."""
from datetime import date
from calendar import monthrange
import re

from allfold.models import EvidenceDate, EvidenceDateKind
from allfold.identifiers import normalize_external_id, strong_identifiers


def source_date(value, kind=EvidenceDateKind.SOURCE, **fields):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}(?:-\d{2}){0,2}", value):
        return None
    parts = [int(part) for part in value.split("-")]
    try:
        return EvidenceDate(kind=kind, year=parts[0], month=parts[1] if len(parts) > 1 else None,
                            day=parts[2] if len(parts) > 2 else None, **fields)
    except ValueError:
        return None


def date_value(item: EvidenceDate) -> str:
    return (f"{item.year:04d}" + (f"-{item.month:02d}" if item.month else "")
            + (f"-{item.day:02d}" if item.day else ""))


def date_key(item: EvidenceDate):
    # Missing parts exist only in the sorting key, never in stored/display dates.
    return item.year, item.month or 1, item.day or 1, item.model_dump_json()


def merge_dates(*collections):
    facts = {}
    for collection in collections:
        for item in collection:
            # A newly discovered alias can refine the derived chain label without
            # making the same sourced event a new fact. Keep saved facts intact.
            facts.setdefault(item.model_dump_json(exclude={'version_family'}), item)
    return tuple(sorted(facts.values(), key=date_key))


def preprint_identity(namespace, identifier):
    if namespace in {'crossref', 'biorxiv', 'medrxiv'}:
        namespace = 'doi'
    value = normalize_external_id(namespace, identifier)
    if namespace == 'doi' and value and value.startswith('10.48550/arxiv.'):
        namespace, value = 'arxiv', normalize_external_id('arxiv', value.removeprefix('10.48550/arxiv.'))
    return f'{namespace}:{value}' if value else None


def _record_type(record):
    return record.publication_type or ('preprint' if record.provenance.provider in {'arxiv', 'biorxiv', 'medrxiv'} else
        'journal' if record.journal else 'conference' if record.conference else None)


def _preprint_families(records):
    # Union only identities of one preprint version chain. A relation to another
    # preprint of the same research work does not establish the same chain.
    groups = []
    def add(keys):
        keys = set(filter(None, keys))
        if not keys:
            return
        for index in reversed(range(len(groups))):
            if keys & groups[index]:
                keys.update(groups.pop(index))
        groups.append(keys)
    for record in records:
        preprint = _record_type(record) == 'preprint'
        if preprint and record.provenance.provider != 'workspace':
            keys = {preprint_identity(ns, value) for ns, value in strong_identifiers(record.external_ids)}
            keys.update(preprint_identity(ref.provider, ref.record_id) for ref in record.related_ids if ref.relation == 'version')
            add(keys or {f'{record.provenance.provider}:{record.provenance.record_id}'})
        elif preprint and record.external_ids.doi:
            # A saved Paper aggregates work identities from distinct systems.
            # Its primary DOI is known, but is not a same-chain assertion.
            add({preprint_identity('doi', record.external_ids.doi)})
        for ref in record.related_ids:
            if (ref.relation == 'preprint' or ref.provider in {'arxiv', 'biorxiv', 'medrxiv'}
                    or preprint and ref.relation == 'version'
                    or ref.provider == 'europe_pmc' and ref.record_id.startswith('PPR:')):
                add({preprint_identity(ref.provider, ref.record_id), ref.version_family})
        for namespace, value in strong_identifiers(record.external_ids, record.related_dois):
            if (namespace in {'arxiv', 'biorxiv', 'medrxiv'}
                    or namespace == 'doi' and value.startswith(('10.48550/arxiv.', '10.1101/'))
                    or namespace == 'europe_pmc' and value.startswith('PPR:')):
                add({preprint_identity(namespace, value)})
        for item in record.dates:
            if item.kind == EvidenceDateKind.PREPRINT and (item.publication_type == 'preprint' or preprint):
                identity = preprint_identity(item.provider or record.provenance.provider, item.record_id or record.provenance.record_id)
                if item.version_family:
                    add({item.version_family, identity})
                elif not preprint:
                    add({identity})
    def rank(key):
        return ({'arxiv': 0, 'doi': 1, 'europe_pmc': 2}.get(key.partition(':')[0], 3), key)
    return {key: min(group, key=rank) for group in groups for key in group}


def collect_dates(records):
    evidence = []
    families = _preprint_families(records)
    for record in records:
        dates = list(record.dates)
        record_type = _record_type(record)
        if (record.publication_date and record.provenance.provider != 'workspace'
                and not any(item.kind in {EvidenceDateKind.SOURCE, EvidenceDateKind.PUBLISHED, EvidenceDateKind.PUBLISHED_ONLINE,
                    EvidenceDateKind.PUBLISHED_PRINT, EvidenceDateKind.ISSUED, EvidenceDateKind.EARLY_ACCESS, EvidenceDateKind.PREPRINT}
                    and date_value(item) == record.publication_date for item in dates)):
            parts = [int(part) for part in record.publication_date.split("-")]
            # A generic source date is not evidence for Accepted or an online event.
            dates.append(EvidenceDate(kind=EvidenceDateKind.PREPRINT if record_type == 'preprint' else EvidenceDateKind.SOURCE, year=parts[0],
                month=parts[1] if len(parts) > 1 else None, day=parts[2] if len(parts) > 2 else None))
        for item in dates:
            family = item.version_family
            if item.kind == EvidenceDateKind.PREPRINT and (item.publication_type == 'preprint' or record_type == 'preprint'):
                identity = preprint_identity(item.provider or record.provenance.provider, item.record_id or record.provenance.record_id)
                family = families.get(family or identity)
                if family is None and record_type == 'preprint':
                    family = next((families[key] for ns, value in sorted(strong_identifiers(record.external_ids))
                        if (key := preprint_identity(ns, value)) in families), None)
            evidence.append(item.model_copy(update={
                "provider": item.provider or record.provenance.provider,
                "record_id": item.record_id or record.provenance.record_id,
                "version": item.version or record.provenance.version,
                "version_family": family,
                "publication_type": item.publication_type or record_type,
                "url": item.url or record.provenance.url,
            }))
    return merge_dates(evidence)


def _date_bounds(item):
    return (date(item.year, item.month or 1, item.day or 1),
        date(item.year, item.month or 12, item.day or monthrange(item.year, item.month or 12)[1]))


def _resolved_preprints(evidence, records, today=None):
    families = _preprint_families(records)
    facts = {}
    for item in evidence:
        if item.kind != EvidenceDateKind.PREPRINT or item.publication_type != 'preprint':
            continue
        family = families.get(item.version_family, item.version_family)
        if family:
            facts.setdefault(family, []).append(item)
    resolved = {}
    for family, dates in facts.items():
        first = [item for item in dates if item.first_version and _date_bounds(item)[0] <= (today or date.today())]
        if not first:
            continue
        lower, upper = max(_date_bounds(item)[0] for item in first), min(_date_bounds(item)[1] for item in first)
        if lower > upper or any(_date_bounds(item)[1] < lower for item in dates):
            continue  # Conflicting first-version or clearly earlier version evidence.
        resolved[family] = min(date_value(item) for item in first)
    return families, resolved


def first_public_date(evidence, *, records, today=None):
    families, resolved = _resolved_preprints(evidence, records, today)
    if not set(families.values()).issubset(resolved):
        return None
    return min(resolved.values(), default=None)


def preprint_date_coverage(records):
    families, resolved = _resolved_preprints(collect_dates(records), records)
    complete = bool(families) and set(families.values()).issubset(resolved)
    return complete, {key for key, family in families.items() if family in resolved}


def journal_dates(evidence):
    return tuple(item for item in merge_dates(evidence)
        if item.publication_type == "journal" and item.kind != EvidenceDateKind.PREPRINT)
