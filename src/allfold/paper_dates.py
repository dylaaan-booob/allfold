"""Version-bound date facts shared by creation and explicit enrichment."""
from datetime import date
import re

from allfold.models import EvidenceDate, EvidenceDateKind


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
    return tuple(sorted({item for collection in collections for item in collection}, key=date_key))


def collect_dates(records):
    evidence = []
    for record in records:
        dates = list(record.dates)
        record_type = record.publication_type or ("preprint" if record.provenance.provider in {"arxiv", "biorxiv", "medrxiv"} else
            "journal" if record.journal else "conference" if record.conference else None)
        if (record.publication_date and record_type != "preprint" and record.provenance.provider != 'workspace'
                and not any(item.kind in {EvidenceDateKind.SOURCE, EvidenceDateKind.PUBLISHED, EvidenceDateKind.PUBLISHED_ONLINE,
                    EvidenceDateKind.PUBLISHED_PRINT, EvidenceDateKind.ISSUED, EvidenceDateKind.EARLY_ACCESS}
                    and date_value(item) == record.publication_date for item in dates)):
            parts = [int(part) for part in record.publication_date.split("-")]
            # A generic source date is not evidence for Accepted or an online event.
            dates.append(EvidenceDate(kind=EvidenceDateKind.SOURCE, year=parts[0],
                month=parts[1] if len(parts) > 1 else None, day=parts[2] if len(parts) > 2 else None))
        for item in dates:
            evidence.append(item.model_copy(update={
                "provider": item.provider or record.provenance.provider,
                "record_id": item.record_id or record.provenance.record_id,
                "version": item.version or record.provenance.version,
                "publication_type": item.publication_type or record_type,
                "url": item.url or record.provenance.url,
            }))
    return merge_dates(evidence)


def first_public_date(evidence, *, today=None):
    today = (today or date.today()).isoformat()
    return min((date_value(item) for item in evidence
        if item.kind == EvidenceDateKind.PREPRINT and item.publication_type == "preprint"
        and item.first_version and date_value(item) <= today[:len(date_value(item))]), default=None)


def journal_dates(evidence):
    return tuple(item for item in merge_dates(evidence)
        if item.publication_type == "journal" and item.kind != EvidenceDateKind.PREPRINT)
