"""WoS expressions, tagged plain-text records and bounded download reads."""
from __future__ import annotations

import os
import stat
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from allfold.persistence.safe_write import _open_directory_nofollow
from allfold.config import JournalConfig, normalize_journal_issn

from allfold.identifiers import normalize_doi
from allfold.models import Author, CanonicalPaper, ExternalIds, MetadataSource, ProviderWorkEvidence, ProviderTopic, EvidenceDate, EvidenceDateKind, parse_publication_date
from allfold.canonicalize import canonicalize_records


class WoSQueryError(ValueError):
    def __init__(self, message: str, position: int = 0):
        self.position = position
        super().__init__(f"{message} at column {position + 1}")


def compile_wos_query(text) -> str:
    from allfold.keywords import parse_keyword_expression, compile_native_expression
    try:
        expression = parse_keyword_expression(text) if isinstance(text, str) else text
        return compile_native_expression(expression, provider="wos")
    except ValueError as error:
        raise WoSQueryError(str(error), getattr(error, "position", 0)) from error


def combined_query(compiled: str, journals, from_date, to_date) -> str:
    issns = {identifier for journal in journals for identifier in journal.identifiers}
    if not issns:
        raise ValueError('No configured Journals')
    return f"{compiled} AND IS=({' OR '.join(sorted(issns))}) AND DOP={from_date}/{to_date}"


def match_journal(record: dict, identifiers: dict[str, JournalConfig]) -> JournalConfig | None:
    matches = {}
    for tag in ('SN', 'EI'):
        for value in record.get(tag, []):
            try:
                identifier = normalize_journal_issn(value)
            except ValueError:
                continue
            journal = identifiers.get(identifier)
            if journal is not None:
                matches[journal.key] = journal
    return next(iter(matches.values())) if len(matches) == 1 else None


@dataclass
class TaggedExport:
    records: list[dict[str, list[str]]]
    issues: list[str]


def parse_tagged(text: str) -> TaggedExport:
    """Only ER-closed records are usable; EOF never repairs a truncated record."""
    records, issues = [], []
    current, key = None, None
    header, version, ended = False, False, False
    for number, line in enumerate(text.removeprefix('\ufeff').splitlines(), 1):
        if not line.strip():
            continue
        if ended:
            issues.append('content_after_EF')
            break
        if line.startswith('   '):
            if current is not None and key:
                current[key].append(line[3:].strip())
            else:
                issues.append(f'orphan_continuation:{number}')
            continue
        match = re.fullmatch(r'([A-Z][A-Z0-9])(?: (.*))?', line.rstrip())
        if not match:
            issues.append(f'invalid_line:{number}')
            if current is not None:
                current['_invalid'] = ['invalid_line']
            continue
        tag, value = match[1], (match[2] or '').strip()
        if tag == 'FN' and current is None:
            header = bool(value)
        elif tag == 'VR' and current is None:
            version = bool(value)
        elif tag == 'PT':
            if current is not None:
                issues.append('record_missing_ER')
            current, key = {'PT': [value]}, 'PT'
        elif tag == 'ER':
            if current is None:
                issues.append('orphan_ER')
            else:
                records.append(current)
            current, key = None, None
        elif tag == 'EF':
            if current is not None:
                issues.append('record_missing_ER')
            current, key, ended = None, None, True
        elif current is not None:
            current.setdefault(tag, []).append(value)
            key = tag
        else:
            issues.append(f'field_outside_record:{number}')
    if not header or not version:
        # A random text file must not contribute even accidentally ER-closed data.
        return TaggedExport([], ['invalid_tagged_header'])
    if current is not None:
        issues.append('record_missing_ER')
    if not ended:
        issues.append('missing_EF')
    return TaggedExport(records, list(dict.fromkeys(issues)))


_MONTHS = {name: i for i, name in enumerate(
    ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'), 1)}
_MONTHS.update({name: i for i, name in enumerate(
    ('JANUARY', 'FEBRUARY', 'MARCH', 'APRIL', 'MAY', 'JUNE', 'JULY', 'AUGUST',
     'SEPTEMBER', 'OCTOBER', 'NOVEMBER', 'DECEMBER'), 1)})


def _bibliographic_date(raw: str, year: str = '') -> str | None:
    value = raw.strip().upper()
    if not value:
        return None
    years = re.findall(r'(?<!\d)[12]\d{3}(?!\d)', value)
    if not years and re.fullmatch(r'[12]\d{3}', year):
        value += ' ' + year
        years = [year]
    try:
        return parse_publication_date(value)
    except ValueError:
        pass
    if len(set(years)) != 1:
        return None
    y = int(years[0])
    # Explicit single dates. Month names are parsed without depending on OS locale.
    patterns = (
        r'([A-Z]{3,9}) (\d{1,2}) (\d{4})',
        r'(\d{1,2}) ([A-Z]{3,9}) (\d{4})',
        r'(\d{4})[- ]([A-Z]{3,9})[- ](\d{1,2})',
    )
    for index, pattern in enumerate(patterns):
        m = re.fullmatch(pattern, value)
        if m:
            month, day = (m[1], m[2]) if index == 0 else (m[2], m[1] if index == 1 else m[3])
            try:
                return date(y, _MONTHS[month], int(day)).isoformat()
            except (KeyError, ValueError):
                return None
    m = re.fullmatch(r'([A-Z]{3,9}) (\d{4})|(\d{4})[- ]([A-Z]{3,9})', value)
    if m:
        month = _MONTHS.get(m[1] or m[4])
        return f'{y:04}-{month:02}' if month else None
    m = re.fullmatch(r'(\d{4}-\d{2}-\d{2})[ /–](\d{4}-\d{2}-\d{2})', value)
    if m:
        try:
            start, end = date.fromisoformat(m[1]), date.fromisoformat(m[2])
        except ValueError:
            return None
        if start > end or start.year != end.year:
            return None
        return start.isoformat()[:7] if start.month == end.month else str(start.year)
    # A range supplies only its common precision, never an arbitrarily chosen endpoint.
    m = re.fullmatch(r'([A-Z]{3,9}) (\d{1,2})[-–](?:\1 )?(\d{1,2}) (\d{4})', value)
    if m:
        try:
            month = _MONTHS[m[1]]
            start, end = date(y, month, int(m[2])), date(y, month, int(m[3]))
            return start.isoformat()[:7] if start <= end else None
        except (KeyError, ValueError):
            return None
    m = re.fullmatch(r'([A-Z]{3,9})[-–/]([A-Z]{3,9}) (\d{4})', value)
    if m and m[1] in _MONTHS and m[2] in _MONTHS:
        return str(y)
    if re.fullmatch(r'(?:SPR(?:ING)?|SUM(?:MER)?|FAL(?:L)?|AUT(?:UMN)?|WIN(?:TER)?) \d{4}', value):
        return str(y)
    return None


def publication_date(pd: str, py: str, ea: str) -> tuple[str | None, list[str]]:
    formal = _bibliographic_date(pd, py) or _bibliographic_date(py)
    early = _bibliographic_date(ea)  # EA must supply its own year.
    issues = []
    embedded = re.findall(r'(?<!\d)[12]\d{3}(?!\d)', pd)
    if embedded and py and py not in embedded:
        issues.append('PD_PY_year_conflict')
    if pd and _bibliographic_date(pd, py) is None:
        issues.append('unusable_PD')
    selected = formal
    if (not formal or len(formal) == 4) and early and len(early) >= 7:
        selected = early
        issues.append('EA_fallback')
    if selected is None:
        issues.append('date_unavailable')
    elif len(selected) == 4:
        issues.append('year_only')
    return selected, issues


def record_paper(record: dict, journal: JournalConfig, warnings: list | None = None) -> CanonicalPaper:
    def text(tag):
        return ' '.join(' '.join(record.get(tag, [])).split())

    if record.get('_invalid'):
        raise ValueError('Malformed record')
    doi = normalize_doi(text('DI') or None)
    ut = text('UT').upper()
    if not re.fullmatch(r'WOS:\d+', ut):
        ut = ''
    pd, py, ea = (text(tag) for tag in ('PD', 'PY', 'EA'))
    selected, date_issues = publication_date(pd, py, ea)
    if warnings is not None and date_issues:
        warnings.append(dict(journal=journal.key, doi=doi, ut=ut, PD=pd, PY=py, EA=ea,
                             selected=selected, reasons=date_issues))
    if doi and not re.fullmatch(r'10\.\d{4,9}/[^\s]+', doi):
        raise ValueError('invalid_doi')
    if not doi and not ut:
        raise ValueError('missing_identity')
    title = text('TI')
    if not title:
        raise ValueError('Record has no title')
    authors = [Author(name=name) for name in ([name for name in record.get('AF', []) if name.strip()] or record.get('AU') or [])
               if name.strip() and not any(c in name for c in ']\n\r\0')]
    dates = []
    early = _bibliographic_date(ea)
    if early:
        parts = [int(part) for part in early.split('-')]
        dates.append(EvidenceDate(kind=EvidenceDateKind.EARLY_ACCESS, year=parts[0],
                                 month=parts[1] if len(parts) > 1 else None, day=parts[2] if len(parts) > 2 else None))
    keywords = lambda tag: tuple(value.strip() for value in text(tag).split(';') if value.strip())
    evidence = ProviderWorkEvidence(
        provenance=MetadataSource(provider='wos', record_id=ut or doi, retrieved_at=datetime.now(timezone.utc), role='discovery'),
        title=title, journal=journal.name, publication_type='journal', abstract=text('AB') or None,
        publication_date=selected, dates=tuple(dates), authors=tuple(authors),
        author_keywords=keywords('DE'),
        indexed_terms=tuple(ProviderTopic(value=value, source='wos', kind='Keywords Plus') for value in keywords('ID')),
        external_ids=ExternalIds(doi=doi, **({'wos': ut} if ut else {})), monitor_journal_issns=(journal.key,),
    )
    return canonicalize_records([evidence]).papers[0]



def read_export(filename: str, relative_name: str, root: Path | None = None) -> tuple[str, Path]:
    """Read only the server-issued random suffix, without following any symlinks."""
    path, relative = Path(filename), Path(relative_name)
    if not path.is_absolute() or '..' in path.parts or '..' in relative.parts or relative.is_absolute():
        raise ValueError('invalid_export_path')
    if path.parts[-len(relative.parts):] != relative.parts:
        raise ValueError('export_path_not_issued')
    download_root = path.parents[len(relative.parts) - 1]
    if root is not None and download_root != root:
        raise ValueError('download_root_changed')
    directory = _open_directory_nofollow(path.parent)
    descriptor = None
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.getuid()
                or before.st_size <= 0):
            raise ValueError('unsafe_export_file')
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None
            data = stream.read()
            after = os.fstat(stream.fileno())
        named = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if identity(before) != identity(after) or identity(after) != identity(named) or len(data) != before.st_size:
            raise ValueError('export_file_changed')
        return data.decode('utf-8-sig'), download_root
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


@dataclass
class WoSRecords:
    """Invocation-local DOI union; conflicting incoming evidence is quarantined."""
    papers: dict
    uts: dict
    conflicts: set

    def __init__(self):
        self.papers, self.uts, self.conflicts = {}, {}, set()

    def add(self, paper: CanonicalPaper):
        doi = paper.doi or f'wos:{paper.external_ids.wos}'
        for source in paper.sources:
            previous = self.uts.get(source.record_id)
            if previous and previous != doi:
                self.conflicts.update((previous, doi))
            self.uts[source.record_id] = doi
        old = self.papers.get(doi)
        if old:
            changes = {}
            for field in ('title', 'journal', 'abstract', 'publication_date'):
                before, after = getattr(old.metadata, field), getattr(paper.metadata, field)
                if before and after and ' '.join(before.split()).casefold() != ' '.join(after.split()).casefold():
                    if field != 'publication_date' or not (before.startswith(after) or after.startswith(before)):
                        self.conflicts.add(doi)
                if after and (not before or field == 'publication_date' and len(after) > len(before)):
                    changes[field] = after
            if old.authors and paper.authors and old.authors != paper.authors:
                self.conflicts.add(doi)
            sources = {(s.provider, s.record_id): s for s in (*paper.sources, *old.sources)}
            paper = old.model_copy(update=dict(metadata=old.metadata.model_copy(update=changes),
                authors=old.authors or paper.authors, sources=tuple(sources.values()),
                journal_issns=tuple(sorted(set(old.journal_issns + paper.journal_issns)))))
        self.papers[doi] = paper
