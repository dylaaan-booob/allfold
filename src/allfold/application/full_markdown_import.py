"""Complete, revision-bound list.md import and export for the shared Settings editor."""

from __future__ import annotations

import hashlib
import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from allfold.persistence.safe_write import source_file_identity
from allfold.application.settings import SettingsIssueSource, _read_snapshot
from allfold.config import ConfigurationError, parse_settings_list_text
from allfold.providers.openalex import OpenAlexClient
from allfold.application.journal_lookup import verify_journal
from allfold.persistence.safe_write import (
    ContentChangedError, TextWriteCommittedError, replace_regular_text_at_identity,
)

MAX_MARKDOWN_BYTES = 1024 * 1024
MANAGED = {"Journals", "Groups", "Custom Labels", "Access Services"}
AI_MAPPING_PACK_MARKER = "<!-- allfold-file-type: ai-mapping-pack/v1 -->"


class MarkdownImportCommittedWarning(RuntimeError):
    """Atomic replacement occurred but directory synchronization reported an error."""

    def __init__(self, revision: str):
        super().__init__("list.md replacement committed, but directory fsync failed")
        self.revision = revision


@dataclass(frozen=True)
class FullMarkdownPreview:
    path: Path
    original: str
    proposed: str
    directory_identity: tuple[int, int]
    file_identity: tuple[int, int]
    changes: tuple[str, ...]
    verification_journal_keys: tuple[str, ...]

    @property
    def target_digest(self) -> str:
        return hashlib.sha256(self.original.encode("utf-8")).hexdigest()

    @property
    def source_digest(self) -> str:
        return hashlib.sha256(self.proposed.encode("utf-8")).hexdigest()


def _other_content(contents: str) -> str:
    """Non-managed headings plus any surrounding prose are whole-file user data."""
    lines = contents.splitlines(keepends=True)
    output = []
    in_managed = False
    for line in lines:
        if line.startswith("## "):
            in_managed = line[3:].strip() in MANAGED
        if not in_managed:
            output.append(line)
    return "".join(output)


def preview_full_markdown(path: Path, proposed: str, *, filename: str) -> FullMarkdownPreview:
    path = path.absolute()
    if proposed.lstrip("\ufeff \t\r\n").startswith(AI_MAPPING_PACK_MARKER):
        raise ConfigurationError("AI Mapping Pack is a work file, not importable list.md; import the AI-produced complete list.md instead")
    if not filename.lower().endswith(".md") or Path(filename).name != filename:
        raise ConfigurationError("Import requires a complete .md file, not CSV/TSV or a filesystem path")
    if not proposed or len(proposed.encode("utf-8")) > MAX_MARKDOWN_BYTES or "\x00" in proposed:
        raise ConfigurationError("Markdown Import source is empty, contains NUL, or exceeds 1 MiB")
    if any(candidate.is_symlink() for candidate in (path, *path.parents)):
        raise ConfigurationError("unsafe list.md path: symlink")
    original_identity = source_file_identity(path)
    disk = _read_snapshot(path, source=SettingsIssueSource.JOURNAL_DATA)
    if disk.issue or disk.contents is None:
        raise ConfigurationError(disk.issue.message if disk.issue else "list.md is missing")
    old_list = parse_settings_list_text(disk.contents, path=path)
    new_list = parse_settings_list_text(proposed, path=path)
    old_journals, old_services = old_list.journals, old_list.access_services
    new_journals, new_services = new_list.journals, new_list.access_services
    if source_file_identity(path) != original_identity:
        raise ContentChangedError("list.md identity changed during Import Preview")

    previous_j = {j.key: j for j in old_journals}
    next_j = {j.key: j for j in new_journals}
    previous_s = {s.id: s for s in old_services}
    next_s = {s.id: s for s in new_services}
    def service_label(service_id: str | None, services: dict) -> str:
        if service_id is None:
            return "Unassigned"
        service = services[service_id]  # The full-file parser rejects dangling IDs.
        return f"{service.name} ({service_id})"

    changes = []
    for title, before, after in (("Groups", old_list.groups, new_list.groups),
                                 ("Custom Labels", old_list.custom_labels, new_list.custom_labels)):
        for name in before:
            if name not in after:
                changes.append(f"Remove {title} registry entry: {name}")
        for name in after:
            if name not in before:
                changes.append(f"Add {title} registry entry: {name}")
        if before != after:
            changes.append(f"{title} registry order: {list(before)} → {list(after)}")
    new_ids = []
    for identity, current in next_j.items():
        old = previous_j.get(identity)
        if old is None or (old.issn, old.eissn) != (current.issn, current.eissn):
            new_ids.append(identity)
            changes.append(f"Add/change Journal identity: {current.name} ({identity}); Registry verification required")
        elif old.name != current.name:
            new_ids.append(identity)
            changes.append(f"Journal name: {identity}: {old.name} → {current.name}; Registry verification required")
        if (old is None and current.group) or (old is not None and old.group != current.group):
            changes.append(f"Journal Group: {identity}: {old.group if old and old.group else 'Ungrouped'} → {current.group or 'Ungrouped'}")
        if (old is None and current.labels) or (old is not None and old.labels != current.labels):
            changes.append(f"Journal Labels: {identity}: {'; '.join(old.labels) if old and old.labels else '(none)'} → "
                           f"{'; '.join(current.labels) or '(none)'}")
        if old is None or old.access_service_id != current.access_service_id:
            changes.append(f"Journal default Service: {current.name}: "
                           f"{service_label(old.access_service_id, previous_s) if old else '(new)'} → "
                           f"{service_label(current.access_service_id, next_s)}")
    for identity, old in previous_j.items():
        if identity not in next_j:
            changes.append(f"Remove Journal: {old.name} ({identity})")
    for identity, current in next_s.items():
        old = previous_s.get(identity)
        if old is None:
            changes.append(f"Add Access Service: {current.name} ({identity})")
        elif (old.name, old.access_url) != (current.name, current.access_url):
            changes.append(f"Access Service edit: {identity}: {old.name} / {old.access_url or '(blank)'} → {current.name} / {current.access_url or '(blank)'}")
        if old is not None and old.access_method != current.access_method:
            labels = {"carsi": "CARSI", "manual": "Manual Login"}
            changes.append(f"Access Method: {current.name} ({identity}): "
                           f"{labels[old.access_method]} → {labels[current.access_method]}")
    for identity, old in previous_s.items():
        if identity not in next_s:
            members = [j for j in old_journals if j.access_service_id == identity]
            changes.append(f"Delete Access Service: {old.name} ({identity}); {len(members)} previous Journals")
            for journal in members:
                replacement = next_j.get(journal.key)
                destination = service_label(replacement.access_service_id, next_s) if replacement else "Journal removed"
                changes.append(f"Service deletion affects Journal: {journal.name} ({journal.key}): "
                               f"{service_label(identity, previous_s)} → {destination}")
    old_extra, new_extra = _other_content(disk.contents), _other_content(proposed)
    if old_extra != new_extra:
        changes.append(f"Replace Conferences / unknown sections / manual text ({len(old_extra)} → {len(new_extra)} characters); all previous non-managed content is discarded")
        diff = list(difflib.unified_diff(old_extra.splitlines(), new_extra.splitlines(),
                                         fromfile="saved non-managed text", tofile="imported non-managed text",
                                         lineterm=""))
        changes.extend(f"Non-managed: {line[:180]}" for line in diff[:70])
        if len(diff) > 70:
            changes.append(f"Non-managed diff truncated after 70 lines; {len(diff) - 70} more lines differ")
    if disk.contents != proposed and not changes:
        changes.append("Whole-file Markdown formatting, table order or surrounding content changes")
    return FullMarkdownPreview(path, disk.contents, proposed, original_identity[0], original_identity[1],
                               tuple(changes), tuple(new_ids))


def confirm_full_markdown(
    preview: FullMarkdownPreview, *, client: OpenAlexClient | None = None,
    before_write: Callable[[], None] | None = None,
) -> str:
    """Revalidate every part of the preview, then atomically CAS one complete file."""
    current = preview_full_markdown(preview.path, preview.proposed, filename="list.md")
    if current != preview:
        raise ContentChangedError("Import source, target contents or target identity changed since Preview")
    new_journals = parse_settings_list_text(preview.proposed, path=preview.path).journals
    for journal in new_journals:
        if journal.key in preview.verification_journal_keys:
            verify_journal(preview.path, journal, client=client)
    # Provider resolution is transient; the originally previewed file and object must still match.
    current = preview_full_markdown(preview.path, preview.proposed, filename="list.md")
    if current != preview:
        raise ContentChangedError("list.md changed during Import verification")
    if preview.proposed != preview.original:
        try:
            replace_regular_text_at_identity(
                preview.path, preview.proposed, expected_contents=preview.original,
                expected_directory_identity=preview.directory_identity,
                expected_file_identity=preview.file_identity,
                validate_before_replace=before_write,
            )
        except TextWriteCommittedError:
            # Failure after replace must not be misreported as zero writes.
            observed = _read_snapshot(preview.path, source=SettingsIssueSource.JOURNAL_DATA)
            if observed.issue is None and observed.contents == preview.proposed:
                raise MarkdownImportCommittedWarning(observed.revision.digest or "") from None
            raise
    saved = _read_snapshot(preview.path, source=SettingsIssueSource.JOURNAL_DATA)
    if saved.issue or saved.contents != preview.proposed:
        raise ConfigurationError("Import write could not be confirmed by reading saved list.md")
    return saved.revision.digest or ""
