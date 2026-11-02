"""Read CARSI's public embedded SPList and build the AI Mapping Pack.

This module has no Settings UI, configuration write or persistent cache.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from allfold.persistence.safe_write import source_file_identity
from allfold.application.full_markdown_import import (
    AI_MAPPING_PACK_MARKER, MAX_MARKDOWN_BYTES,
)
from allfold.application.settings import SettingsIssueSource, _read_snapshot
from allfold.config import ConfigurationError, parse_settings_list_text
from allfold.persistence.safe_write import ContentChangedError


CARSI_DIRECTORY_URL = "https://www.carsi.edu.cn/SPlist.html"
AI_MAPPING_PACK_FILENAME = "allfold-ai-mapping-pack.md"
MAX_CARSI_HTML_BYTES = 2 * 1024 * 1024
MAX_CARSI_RECORDS = 10_000
CARSI_TIMEOUT = httpx.Timeout(8.0, connect=4.0)
CARSI_TOTAL_SECONDS = 20.0

AI_EDITING_PROMPT_V1 = """### Editing contract (CARSI Access Mapping)

Use the complete saved list.md and the official CARSI resources below.
First return the complete importable list.md in ONE standalone Markdown code
block tagged markdown, with fences longer than any backtick run in the file.
Then provide Mapping changes summary, Existing manual Services review,
Unassigned Journals research, and Manual action items outside list.md.
Do not return this Pack, its marker, the catalog appendix or research inside list.md.

- Edit ONLY ## Access Services and the Access Service ID cell of EXISTING rows
  in ## Journals. Preserve every Journal name, ISSN, eISSN, Group, Labels and row order.
  Labels and their order are human-managed: never generate, add, remove, rename or reorder them.
  Preserve ## Groups and ## Custom Labels verbatim, including unused entries and registry row order.
  Journal Group / Labels assignments and each Journal's Label assignment order are protected independently
  of registry order. Never infer, merge or rebuild these registries from Journal rows.
  Never add, delete or rename a Journal. Preserve Conferences, unknown sections,
  human notes and all other non-managed content. Publisher names are descriptive
  evidence only; there is no Publisher table or Publisher ID relationship.
- Inspect ALL Journals, their direct Service assignments, ALL Services and their
  Journal members before editing. Several Journals may share one Service;
  each Journal has at most one default Service and may remain Unassigned.
- Preserve existing Service IDs, names, URLs, Access Methods and assignments by
  default. Classify officially evidenced CARSI Services separately from existing
  user-maintained Services without confirmed CARSI catalog correspondence.
  Absence from this catalog alone does not invalidate a user decision.
- Access Method is exactly carsi or manual. Preserve each existing Access Method;
  never overwrite a user's manual classification from CARSI directory evidence.
  An institutional login option alone does not establish CARSI compatibility.
  Existing manual Services and their Journal assignments must remain intact.
- Prefer reusing an existing Service for the same official resource. Preserve its
  stable Service ID across name, URL and membership changes; never regenerate IDs
  or duplicate an existing resource. Only genuinely new CARSI resources receive
  independently generated unique UUIDs as svc_ followed by 32 lowercase hex digits.
- A new CARSI Service name must equal the exact production string from the
  official catalog, and its Access URL must use that resource's url value.
  vendor_name is matching evidence only. Preserve an existing user's fields and
  report conflicts for manual review rather than overwriting them. Catalog URLs
  without schemes remain evidence only; never invent a scheme or an unsafe URL.
- Assign an Unassigned Journal only with reliable evidence connecting that actual
  Journal/PDF access platform to the official CARSI resource. Never infer access
  from journal-name or publisher-name similarity. Uncertainty means Unassigned.
  Do not replace an existing assignment with weaker or conflicting evidence.
- Non-CARSI institutional platforms are manual candidates for human action only:
  do not automatically create or assign them in list.md. Never fabricate resource
  aliases, WAYFless URLs, institution/IdP login routes or authentication evidence.
- The first block is ONLY complete valid list.md for Markdown Import → Preview
  → Confirm. Keep the six-column Journal | ISSN | eISSN | Access Service ID | Group | Labels schema.

### Mapping changes summary
Identify new/reused CARSI Services and changed Journal assignments by Journal
name, ISSN/eISSN and stable Service ID. If unchanged, state No mapping changes.

### Existing manual Services review
List existing Services without confirmed CARSI catalog correspondence, their
Journal members, evidence gaps and Preparation limitations. Preserve user choices.
Do not claim manual institutional access has been prepared by CARSI.

### Unassigned Journals research
Investigate EVERY Journal still Unassigned. Distinguish DOI landing pages,
PDF hosts and institutional access platforms. Report reliable sources and
unresolved conflicts. Never claim a login, entitlement or PDF was verified
without actual evidence. Leave uncertain assignments blank.

### Manual action items
List human decisions and manual Service candidates separately from the importable
file. AI proposals require the existing human Preview/Confirm boundary.
"""


class MappingPackError(ValueError):
    """The public catalog or saved Markdown cannot safely produce a Pack."""


@dataclass(frozen=True)
class CarsiResource:
    production: str
    vendor_name: str
    url: str


@dataclass(frozen=True)
class AIMappingPack:
    filename: str
    markdown: str


class _Scripts(HTMLParser):
    """Collect HTML script text without evaluating JavaScript or fetching assets."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._active = False
        self._parts: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._active = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._active:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._active:
            self.scripts.append("".join(self._parts))
            self._active = False


def parse_carsi_directory(html: str) -> tuple[CarsiResource, ...]:
    """Parse the verified inline `var SPList=[...];` in official SPlist.html."""
    if len(html.encode("utf-8")) > MAX_CARSI_HTML_BYTES:
        raise MappingPackError("CARSI directory response exceeds size limit")
    scripts = _Scripts()
    scripts.feed(html)
    declarations = []
    for script in scripts.scripts:
        match = re.match(r"\s*var\s+SPList\s*=\s*", script)
        if match is not None:
            declarations.append(script[match.end():])
    if len(declarations) != 1:
        raise MappingPackError("CARSI directory has no unique official SPList data")
    try:
        records, position = json.JSONDecoder().raw_decode(declarations[0])
    except (ValueError, TypeError) as error:
        raise MappingPackError("CARSI SPList is not valid JSON data") from error
    if not declarations[0][position:].lstrip().startswith(";"):
        raise MappingPackError("CARSI SPList declaration is incomplete")
    if not isinstance(records, list) or not 0 < len(records) <= MAX_CARSI_RECORDS:
        raise MappingPackError("CARSI SPList must contain a bounded, nonempty resource array")

    resources = []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict) or any(
            not isinstance(record.get(field), str) or not record[field].strip()
            for field in ("production", "vendor_name", "url")
        ):
            raise MappingPackError(f"CARSI SPList resource {index} lacks required fields")
        url = record["url"]
        try:
            parsed = urlsplit(url)
        except ValueError as error:
            raise MappingPackError(f"CARSI SPList resource {index} has an invalid URL") from error
        # The live official SPList contains scheme-less "www..." URL fields.
        # Preserve these verbatim as reference data; NEVER invent https://.
        if parsed.scheme:
            acceptable = (parsed.scheme in ("https", "http") and parsed.hostname
                          and parsed.username is None and parsed.password is None)
        else:
            acceptable = (url.startswith("www.") and not re.search(r"\s|[<>]", url)
                          and "@" not in url)
        if not acceptable:
            raise MappingPackError(f"CARSI SPList resource {index} has an invalid URL")
        resources.append(CarsiResource(
            production=record["production"],
            vendor_name=record["vendor_name"],
            url=url,
        ))
    return tuple(resources)


def fetch_carsi_directory(*, transport: httpx.BaseTransport | None = None) -> tuple[CarsiResource, ...]:
    """One uncached public GET, no redirect following, with response/elapsed bounds."""
    started = time.monotonic()
    try:
        with httpx.Client(
            transport=transport, timeout=CARSI_TIMEOUT, follow_redirects=False,
        ) as client:
            with client.stream("GET", CARSI_DIRECTORY_URL, headers={
                "Accept": "text/html",
                "User-Agent": "allfold/0.1.0 (public CARSI catalog export)",
            }) as response:
                if response.is_redirect:
                    raise MappingPackError("CARSI directory redirected; refusing unexpected destination")
                if response.status_code != 200:
                    raise MappingPackError(f"CARSI directory returned HTTP {response.status_code}")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "text/html":
                    raise MappingPackError("CARSI directory has an unexpected content type")
                declared = response.headers.get("content-length")
                if declared is not None:
                    try:
                        size = int(declared)
                    except ValueError as error:
                        raise MappingPackError("CARSI directory has invalid Content-Length") from error
                    if size < 0 or size > MAX_CARSI_HTML_BYTES:
                        raise MappingPackError("CARSI directory exceeds size limit")
                data = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    data.extend(chunk)
                    if len(data) > MAX_CARSI_HTML_BYTES:
                        raise MappingPackError("CARSI directory exceeds size limit")
                    if time.monotonic() - started > CARSI_TOTAL_SECONDS:
                        raise MappingPackError("CARSI directory request exceeded total time limit")
    except httpx.TimeoutException as error:
        raise MappingPackError("CARSI directory request timed out") from error
    except httpx.RequestError as error:
        raise MappingPackError("CARSI directory request failed") from error
    try:
        return parse_carsi_directory(data.decode("utf-8"))
    except UnicodeError as error:
        raise MappingPackError("CARSI directory is not valid UTF-8") from error


def _fence_for(*contents: str) -> str:
    longest = max((len(match.group()) for item in contents
                   for match in re.finditer(r"`+", item)), default=0)
    return "`" * max(4, longest + 1)


def build_ai_mapping_pack(saved_list: str, resources: tuple[CarsiResource, ...]) -> AIMappingPack:
    """Embed the exact UTF-8 source with size/hash for lossless extraction."""
    if not resources:
        raise MappingPackError("Cannot build Pack without official CARSI resources")
    raw = saved_list.encode("utf-8")
    if not raw or len(raw) > MAX_MARKDOWN_BYTES:
        raise MappingPackError("Saved list.md exceeds the supported size boundary")
    directory = json.dumps([{
        "production": item.production, "vendor_name": item.vendor_name, "url": item.url,
    } for item in resources], ensure_ascii=False, indent=2)
    fence = _fence_for(saved_list, directory)
    # The single separator newline after a non-LF-terminated source is NOT part
    # of the source: the recorded byte length and SHA-256 identify it exactly.
    closing_line = "" if saved_list.endswith("\n") else "\n"
    markdown = (
        f"{AI_MAPPING_PACK_MARKER}\n"
        "# Allfold AI Mapping Pack — v1 (work file; do not import)\n\n"
        "## Fixed AI editing instructions\n\n"
        f"{AI_EDITING_PROMPT_V1}\n"
        "## Complete saved list.md — byte-exact UTF-8 source\n\n"
        f"UTF-8 byte length: {len(raw)}\n"
        f"SHA-256: {hashlib.sha256(raw).hexdigest()}\n\n"
        f"{fence}markdown\n{saved_list}{closing_line}{fence}\n\n"
        "## CARSI official public resource directory (reference only)\n\n"
        f"Source: {CARSI_DIRECTORY_URL}\n\n"
        f"{fence}json\n{directory}\n{fence}\n"
    )
    return AIMappingPack(filename=AI_MAPPING_PACK_FILENAME, markdown=markdown)


def generate_ai_mapping_pack(
    saved_list_path: Path, *, transport: httpx.BaseTransport | None = None,
) -> AIMappingPack:
    """Read only validated disk configuration, fetch fresh official data, generate."""
    path = saved_list_path.absolute()
    try:
        identity = source_file_identity(path)
        if path.stat().st_size > MAX_MARKDOWN_BYTES:
            raise MappingPackError("Saved list.md exceeds 1 MiB")
        snapshot = _read_snapshot(path, source=SettingsIssueSource.JOURNAL_DATA)
        if snapshot.issue or snapshot.contents is None:
            raise MappingPackError("Saved list.md cannot be safely read as UTF-8")
        parse_settings_list_text(snapshot.contents, path=path)
        if source_file_identity(path) != identity:
            raise MappingPackError("Saved list.md changed during reading")
    except (OSError, ConfigurationError, ContentChangedError) as error:
        raise MappingPackError("Saved list.md is missing, unsafe or not a valid current configuration") from error
    resources = fetch_carsi_directory(transport=transport)
    current = _read_snapshot(path, source=SettingsIssueSource.JOURNAL_DATA)
    try:
        unchanged = source_file_identity(path) == identity
    except (OSError, ContentChangedError):
        unchanged = False
    if (not unchanged or current.issue or current.contents != snapshot.contents
            or current.revision != snapshot.revision):
        raise MappingPackError("Saved list.md changed during CARSI retrieval; retry export")
    return build_ai_mapping_pack(snapshot.contents, resources)
