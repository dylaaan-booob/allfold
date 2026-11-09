"""Explicit, compare-and-replace Paper enrichment writes."""
from __future__ import annotations

import os
import json
import hashlib
import hmac
from dataclasses import dataclass
from contextlib import nullcontext

import yaml
from pathlib import Path
from uuid import UUID

from allfold.application.decisions import _locate_paper, _read_paper_candidate
from allfold.persistence.markdown_state import (
    analyze_body, parse_paper_identity, parse_paper_state, render_abstract_section,
)
from allfold.identifiers import valid_doi
from allfold.models import EvidenceDate, EvidenceDateKind, WorkflowStatus, parse_publication_date
from allfold.paper_dates import date_value, merge_dates
from allfold.persistence.safe_write import (
    CompareReadError, ContentChangedError, TextWriteCommittedError, replace_regular_text_at_identity,
    workspace_operation_lock,
)


@dataclass(frozen=True)
class EnrichmentTarget:
    workspace: Path
    path: Path
    paper_id: UUID
    doi: str | None
    original: str
    workspace_identity: tuple[int, int]
    directory_identity: tuple[int, int]
    file_identity: tuple[int, int]
    publication_date: str | None
    missing_abstract: bool
    missing_date: bool
    missing_authors: bool
    history_kinds: tuple[str, ...]

    @property
    def missing_fields(self) -> tuple[str, ...]:
        return (*tuple(field for field, missing in (
            ('abstract', self.missing_abstract), ('authors', self.missing_authors),
            ('publication_date', self.missing_date),
        ) if missing), *self.history_kinds)


def missing_history(paper) -> tuple[str, ...]:
    formal_journal = paper.publication_type == 'journal' or (
        paper.publication_type is None and paper.journal and not paper.conference)
    if not formal_journal:
        return ()
    # Match the Reader's date summary: Provider record IDs need not be DOIs.
    recorded = {event.kind for event in paper.date_evidence if
                event.publication_type == 'journal' and event.provider and event.record_id}
    return tuple(kind.value for kind in (EvidenceDateKind.RECEIVED, EvidenceDateKind.ACCEPTED)
                 if kind not in recorded)


def read_paper_target(workspace: Path, paper_id: UUID, *, operation_lock=None) -> EnrichmentTarget:
    with nullcontext(operation_lock) if operation_lock else workspace_operation_lock(workspace) as lock:
        directory = os.open('Papers', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=lock.directory)
        try:
            reads = {}
            path, failure = _locate_paper(lock.path, paper_id, WorkflowStatus.CANDIDATE,
                                         require_safe_candidates=True, directory=directory, paper_reads=reads)
            if failure:
                raise ValueError(failure.message)
            read = _read_paper_candidate(path, directory)
        finally:
            os.close(directory)
        state = parse_paper_state(path, read.contents)
        identity = parse_paper_identity(path, read.contents)
        if state is None or not state.updateable or state.paper_id != paper_id:
            raise ValueError('Paper is invalid or its identity changed'
                + (': ' + '; '.join(state.problems) if state is not None and state.problems else ''))
        if identity is None or identity.problems:
            raise ValueError('Paper identity is missing or conflicting')
        missing_abstract = not state.abstract or not state.abstract.strip()
        missing_date = state.publication_date is None or len(state.publication_date) == 7
        missing_authors = not state.authors
        lock.verify()
        return EnrichmentTarget(lock.path, path, paper_id, valid_doi(identity.primary_doi), read.contents,
                              lock.identity, read.directory_identity, read.file_identity, state.publication_date,
                              missing_abstract, missing_date, missing_authors, missing_history(state))


def read_enrichment_target(workspace: Path, paper_id: UUID) -> EnrichmentTarget:
    target = read_paper_target(workspace, paper_id)
    if not target.doi:
        raise ValueError("A valid primary DOI is required for external Enrich")
    if not target.missing_fields:
        raise ValueError('Paper has no eligible missing Enrich fields')
    return target


def field_revision(target: EnrichmentTarget) -> str:
    """Bind the displayed field snapshot to the exact file and its location."""
    identity = json.dumps([str(target.workspace), str(target.path), str(target.paper_id),
                           target.workspace_identity, target.directory_identity, target.file_identity])
    return hashlib.sha256((identity + '\0' + target.original).encode('utf-8')).hexdigest()


def paper_fields(workspace: Path, paper_id: UUID) -> dict:
    target = read_paper_target(workspace, paper_id)
    state = parse_paper_state(target.path, target.original)
    return {'revision': field_revision(target), 'abstract': state.abstract,
            'authors': list(state.authors), 'publication_date': state.publication_date}


def fill_abstract(original: str, abstract: str) -> str:
    if not isinstance(abstract, str) or not abstract.strip():
        raise ValueError('Abstract is empty')
    # Preserve the original YAML spelling and every byte outside the section.
    lines = original.splitlines(keepends=True)
    closing = next(i for i in range(1, len(lines)) if lines[i].rstrip('\r\n') in {'---', '...'})
    prefix, body = ''.join(lines[:closing + 1]), ''.join(lines[closing + 1:])
    layout = analyze_body(body)
    if layout.abstract and layout.abstract.strip():
        raise ValueError('Paper already has an Abstract')
    body_lines = body.splitlines(keepends=True)
    rendered = render_abstract_section(abstract)
    # A translator result must remain one unambiguous managed Abstract section.
    checked = analyze_body('# Paper\n\n' + rendered + '## Sources\n\n## Notes\n')
    if checked.abstract != abstract.strip("\r\n"):
        raise ValueError('Abstract has an ambiguous Markdown boundary')
    if 'abstract' in layout.sections:
        start, end = layout.sections['abstract']
    else:
        start = layout.sections.get('sources', (layout.notes_index if layout.notes_index is not None
                                                else len(body_lines),))[0]
        end = start
        if start and body_lines[start - 1].strip():
            rendered = '\n' + rendered
    return prefix + ''.join(body_lines[:start]) + rendered + ''.join(body_lines[end:])


def fill_publication_date(original: str, value: str) -> str:
    """Fill an absent date or upgrade a month scalar, without dumping frontmatter."""
    if not isinstance(value, str) or parse_publication_date(value) is None:
        raise ValueError('Publication date must be a valid ISO string')
    replacement = json.dumps(value)
    lines = original.splitlines(keepends=True)
    closing = next(i for i in range(1, len(lines)) if lines[i].rstrip('\r\n') in {'---', '...'})
    payload = ''.join(lines[1:closing])
    document = yaml.compose(payload)
    if not isinstance(document, yaml.MappingNode) or document.flow_style:
        raise ValueError('Cannot safely locate publication_date in YAML')
    entries = [(key, node) for key, node in document.value if key.value == 'publication_date']
    if not entries:
        newline = '\r\n' if lines[0].endswith('\r\n') else '\n'
        return ''.join(lines[:closing]) + f'publication_date: {replacement}{newline}' + ''.join(lines[closing:])
    if len(entries) != 1:
        raise ValueError('Duplicate publication_date')
    key, node = entries[0]
    start, end = node.start_mark.index, node.end_mark.index
    monthly = (isinstance(node, yaml.ScalarNode) and node.tag == 'tag:yaml.org,2002:str'
               and len(node.value) == 7 and parse_publication_date(node.value) is not None)
    if monthly and len(value) != 10:
        raise ValueError('A month date can only be enriched with a complete YYYY-MM-DD date')
    if (not isinstance(node, yaml.ScalarNode) or (node.tag != 'tag:yaml.org,2002:null' and not monthly)
            or node.style in {'|', '>'} or start < key.end_mark.index
            or any(isinstance(token, (yaml.AnchorToken, yaml.AliasToken))
                   and start <= token.start_mark.index < end for token in yaml.scan(payload))):
        raise ValueError('Cannot safely replace publication_date YAML scalar')
    if start == end and start and payload[start - 1] == ':':
        replacement = ' ' + replacement
    return lines[0] + payload[:start] + replacement + payload[end:] + ''.join(lines[closing:])


def fill_authors(original: str, authors: list[str]) -> str:
    """Splice names into one empty sequence without rewriting other YAML bytes."""
    if not authors or any(not isinstance(name, str) or not name.strip() for name in authors):
        raise ValueError('Authors must contain nonempty names')
    lines = original.splitlines(keepends=True)
    closing = next(i for i in range(1, len(lines)) if lines[i].rstrip('\r\n') in {'---', '...'})
    payload = ''.join(lines[1:closing])
    document = yaml.compose(payload)
    if not isinstance(document, yaml.MappingNode) or document.flow_style:
        raise ValueError('Cannot safely locate authors in YAML')
    entries = [(key, node) for key, node in document.value if key.value == 'authors']
    if len(entries) != 1:
        raise ValueError('Cannot safely locate one authors sequence')
    key, node = entries[0]
    start, end = node.start_mark.index, node.end_mark.index
    if (not isinstance(node, yaml.SequenceNode) or node.value or start < key.end_mark.index
            or any(isinstance(token, (yaml.AnchorToken, yaml.AliasToken))
                   and start <= token.start_mark.index < end for token in yaml.scan(payload))):
        raise ValueError('Cannot safely replace authors YAML sequence')
    return lines[0] + payload[:start] + json.dumps(authors, ensure_ascii=False) + payload[end:] + ''.join(lines[closing:])


def set_managed_value(original, field, value):
    """Splice one managed YAML value, retaining human content and unrelated bytes."""
    lines = original.splitlines(keepends=True)
    closing = next(i for i in range(1, len(lines)) if lines[i].rstrip('\r\n') in {'---', '...'})
    payload = ''.join(lines[1:closing])
    document = yaml.compose(payload)
    if not isinstance(document, yaml.MappingNode) or document.flow_style:
        raise ValueError('Cannot safely locate managed Paper fields')
    entries = [(key, node) for key, node in document.value if key.value == field]
    replacement = json.dumps(value, ensure_ascii=False)
    if not entries:
        newline = '\r\n' if lines[0].endswith('\r\n') else '\n'
        return ''.join(lines[:closing]) + f'{field}: {replacement}{newline}' + ''.join(lines[closing:])
    if len(entries) != 1:
        raise ValueError(f'Duplicate {field}')
    key, node = entries[0]
    start, end = node.start_mark.index, node.end_mark.index
    if start < key.end_mark.index or any(isinstance(token, (yaml.AnchorToken, yaml.AliasToken))
            and start <= token.start_mark.index < end for token in yaml.scan(payload)):
        raise ValueError(f'Cannot safely replace {field}')
    if isinstance(node, (yaml.SequenceNode, yaml.MappingNode)) and not node.flow_style and node.value:
        # End at the final scalar, retaining trailing comments/newlines verbatim.
        def last(node):
            if isinstance(node, yaml.MappingNode) and node.value:
                return last(node.value[-1][1])
            if isinstance(node, yaml.SequenceNode) and node.value:
                return last(node.value[-1])
            return node.end_mark.index
        end = last(node)
    if node.start_mark.column == 0:
        replacement = '  ' + replacement
    if start == end and start and payload[start - 1] == ':':
        replacement = ' ' + replacement
    return lines[0] + payload[:start] + replacement + payload[end:] + ''.join(lines[closing:])



def save_enrichment(target: EnrichmentTarget, abstract: str | None = None,
                    publication_date: str | None = None, authors: list[str] | None = None, date_evidence=()) -> dict:
    current = read_enrichment_target(target.workspace, target.paper_id)
    if current != target:
        raise ContentChangedError('Paper or Workspace changed; enrichment was not saved')
    contents = target.original
    if abstract is not None:
        if not target.missing_abstract:
            raise ValueError('Paper already has an Abstract')
        contents = fill_abstract(contents, abstract)
    if publication_date is not None:
        if not target.missing_date:
            raise ValueError('Paper already has a publication date')
        contents = fill_publication_date(contents, publication_date)
    if authors is not None:
        if not target.missing_authors:
            raise ValueError('Paper already has Authors')
        contents = fill_authors(contents, authors)
    saved = {key: value for key, value in dict(abstract=abstract, publication_date=publication_date, authors=authors).items() if value is not None}
    if date_evidence:
        state = parse_paper_state(target.path, target.original)
        additions = tuple(EvidenceDate.model_validate(item) for item in date_evidence)
        def web_fact(event):
            return event.kind, event.record_id, event.url, date_value(event)
        def is_web_history(event):
            return event.provider == 'translator-web' and event.kind in {EvidenceDateKind.RECEIVED, EvidenceDateKind.ACCEPTED}
        existing_web = {web_fact(event) for event in state.date_evidence if is_web_history(event)}
        dates = merge_dates(state.date_evidence, (
            event for event in additions if not is_web_history(event) or web_fact(event) not in existing_web))
        if dates != state.date_evidence:
            values = [item.model_dump(mode='json', exclude_none=True) for item in dates]
            contents = set_managed_value(contents, 'date_evidence', values)
            saved['date_evidence'] = values
    if saved:
        _commit_fields(target, contents)
    return saved


def _reset_yaml_field(original: str, field: str) -> str:
    """Clear one managed value while retaining all other frontmatter bytes."""
    lines = original.splitlines(keepends=True)
    closing = next(i for i in range(1, len(lines)) if lines[i].rstrip('\r\n') in {'---', '...'})
    payload = ''.join(lines[1:closing])
    document = yaml.compose(payload)
    if not isinstance(document, yaml.MappingNode) or document.flow_style:
        raise ValueError(f'Cannot safely locate {field} in YAML')
    entries = [(key, node) for key, node in document.value if key.value == field]
    # An absent field is already empty; do not introduce spelling changes.
    if not entries:
        return original
    if len(entries) != 1:
        raise ValueError(f'Cannot safely locate one {field} value')
    key, node = entries[0]
    start, end = node.start_mark.index, node.end_mark.index
    expected = yaml.SequenceNode if field == 'authors' else yaml.ScalarNode
    if (not isinstance(node, expected) or start < key.end_mark.index
            or isinstance(node, yaml.ScalarNode) and node.style in {'|', '>'}
            or any(isinstance(token, (yaml.AnchorToken, yaml.AliasToken))
                   and start <= token.start_mark.index < end for token in yaml.scan(payload))):
        raise ValueError(f'Cannot safely clear {field} YAML value')
    if isinstance(node, yaml.SequenceNode) and not node.flow_style and node.value:
        # YAML includes trailing comments in a block collection's end mark;
        # retain comments belonging to the following key or section.
        end = node.value[-1].end_mark.index
    replacement = '[]' if field == 'authors' else 'null'
    if isinstance(node, yaml.SequenceNode) and not node.flow_style and node.start_mark.column == 0:
        replacement = '  ' + replacement
    if start == end and start and payload[start - 1] == ':':
        replacement = ' ' + replacement
    # A block sequence's end mark can include the newline before the next key.
    if end > start and payload[end - 1] in '\r\n':
        replacement += '\r\n' if payload[end - 2:end] == '\r\n' else '\n'
    return lines[0] + payload[:start] + replacement + payload[end:] + ''.join(lines[closing:])


def edit_paper_fields(workspace: Path, paper_id: UUID, revision: str, *,
                      reset_fields: list[str] | None = None, abstract: str | None = None) -> None:
    target = read_paper_target(workspace, paper_id)
    if not hmac.compare_digest(field_revision(target), revision):
        raise ContentChangedError('Paper or Workspace changed; refresh before editing fields')
    contents = target.original
    if reset_fields is not None:
        if not reset_fields or set(reset_fields) - {'abstract', 'authors', 'publication_date'}:
            raise ValueError('Select Abstract, Authors or Date to reset')
        if abstract is not None:
            raise ValueError('Reset and Input must be separate operations')
        for field in dict.fromkeys(reset_fields):
            if field == 'abstract':
                if target.missing_abstract:
                    continue
                lines = contents.splitlines(keepends=True)
                closing = next(i for i in range(1, len(lines)) if lines[i].rstrip('\r\n') in {'---', '...'})
                body = ''.join(lines[closing + 1:])
                start, end = analyze_body(body).sections['abstract']
                body_lines = body.splitlines(keepends=True)
                contents = (''.join(lines[:closing + 1]) + ''.join(body_lines[:start])
                            + render_abstract_section(None) + ''.join(body_lines[end:]))
            else:
                contents = _reset_yaml_field(contents, field)
    else:
        contents = fill_abstract(contents, abstract)
    _commit_fields(target, contents)


def _commit_fields(target: EnrichmentTarget, contents: str, *, operation_lock=None) -> None:
    state = parse_paper_state(target.path, contents)
    if state is None or not state.updateable:
        raise ValueError('Enrichment would produce an invalid Paper')
    with nullcontext(operation_lock) if operation_lock else workspace_operation_lock(target.workspace) as lock:
        if lock.identity != target.workspace_identity:
            raise ContentChangedError('Workspace identity changed')
        try:
            replace_regular_text_at_identity(
                target.path, contents, expected_contents=target.original,
                expected_directory_identity=target.directory_identity,
                expected_file_identity=target.file_identity,
                expected_workspace_identity=target.workspace_identity, operation_lock=lock,
            )
        except TextWriteCommittedError:
            # The Paper commit reaches Web's Completed-with-warning path.
            raise
        except (ValueError, OSError, ContentChangedError, CompareReadError) as exc:
            raise ValueError(f'Paper was not saved: {exc}') from exc
