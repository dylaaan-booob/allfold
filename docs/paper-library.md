# Independent SQLite Paper library (WF01)

The Python library kernel is implemented and tested with temporary, real SQLite
databases. **Production Paper reads and writes still use Markdown.** Nothing in
startup, Run, HTTP/IPC, Workspace UI, Enrich, Import or downloads opens this library.
There is no migration, dual write, mixed read, fallback or user switch. WF02 owns
the unified production adoption; see [task boundaries](workflow-refactor-tasks.md).

## Files, connections and schema

`PaperRepository.create(workspace)` exclusively creates `workspace/papers.sqlite`
in an existing directory. It refuses an existing file or orphan SQLite sidecars.
`open(workspace, expected_workspace_id=...)` never creates a missing library.
Both return a context manager; `close()` is explicit and idempotent. Reopening
preserves the Workspace UUID and all Paper UUIDs, including excluded and cleared
records. Neither function reads or changes configuration, UserState, Journals,
Services, credentials, Markdown, Run snapshots or actual PDFs.

Each repository owns one thread-confined standard-library `sqlite3` connection.
Concurrent workers open separate repositories. Foreign keys are enabled on every
connection; writes use `BEGIN IMMEDIATE`, read projections use one consistent read
transaction, and exceptions roll back the entire transaction. New databases use
SQLite's default DELETE journal and FULL synchronization. Each busy wait defaults
to two seconds, configurable from zero to five. There are no retries or public
transaction callbacks: network, page and file work finishes before repository
calls. No lock spans those operations.

The application ID identifies an Allfold library, `PRAGMA user_version` records
schema version 1, and `library_info` stores the Workspace UUID. Opening checks
the version, expected table/index definitions, integrity and references. Missing,
corrupt, unsafe and unsupported-schema libraries raise distinct errors. Existing
content is never overwritten, downgraded or rebuilt. `upgrade_schema` in
`library_database.py` is the explicit entry for future known transactional
upgrades; no older migration is defined. Failed initialization preserves its
exclusively created file for inspection rather than deleting it.

| Table | Responsibility |
| --- | --- |
| `library_info` | Stable Workspace identity |
| `paper_core` | Paper UUID, exclusion and metadata/operation/body generations |
| `paper_identities` | Unique `(namespace, normalized_value)` ownership, referencing the core |
| `paper_metadata` | Deletable complete payload and manual-abstract generation |
| `paper_body` | One current relative PDF association, source URL and optional byte count |

There is no kept/exported state, Zotero parent item, Markdown authority path,
download queue, attempt ledger or durable candidate cache. Clearing metadata
deletes its row and all contained bibliography, notes, dates, sources and Preprint
results. Core, direct identities, exclusion and an existing body association
remain. This is logical deletion, not a forensic file-erasure guarantee.

## Public API and conditional writes

Import the public API and errors from `allfold.persistence.paper_repository`.
`library_models.py` defines immutable values; `library_database.py` owns schema
and connection safety. These helpers are not alternate application writers.

| Interface | Result and conditions |
| --- | --- |
| `create`, `open`, `close` | Explicit lifecycle; optional expected Workspace UUID on open |
| `get(paper_id)`, `list_papers()` | Immutable `PaperRecord` projections, including excluded and cleared records |
| `match(direct_ids)` | Match saved direct identities; different owners raise `IdentityConflict` |
| `create_or_match(workspace_id, direct_ids=..., metadata=...)` | `CreationResult(paper, created)`; a new full record requires title and reliable direct identity. Matches return the existing record unchanged in every state |
| `merge_metadata(token, delta, direct_ids=...)` | Merge eligible automatic dates, Preprint/source facts and the first valid abstract; optionally add verified direct identities in the same transaction |
| `edit_metadata(token, changes)` | Apply only named local fields to the latest payload; no whole-record snapshot save |
| `exclude(token)` | Mark excluded and revoke prior operation authority |
| `restore(token)` | Restore a full record, advancing authority; old tokens stay invalid |
| `clear_metadata(token)` | Only in the recycle bin; delete the payload and advance metadata/operation generations |
| `unexclude(token)` | Release only a cleared identity placeholder; content remains absent |
| `rebuild_from_run(token, direct_ids=..., metadata=...)` | Only a cleared, unexcluded placeholder accepts a new caller-verified Run result directly identifying it; retain UUID and establish new generations |
| `complete_body(token, body)` | Associate a newly completed body only with complete, unexcluded metadata and unchanged body authority |
| `clear_body(token)` | Local unlink, also allowed when excluded or without metadata; revoke pending results even when no body is associated |

Returned records include `.token`. `WriteToken` binds Workspace UUID, Paper UUID,
metadata lifetime and operation generation. Exclusion, restoration, clearing and
rebuilding cannot resurrect old authority. Even a current-generation token cannot
authorize automatic metadata or a new body while excluded or without metadata.

Manual abstract edits have a separate generation. Editing or clearing revokes
older automatic abstract candidates, while their date/source increments can still
merge. Unrelated title/notes edits do not revoke candidates. Repeated manual
abstract edits compare that field's generation. Other named local fields use the
latest payload; the last successful explicit edit wins. Body generation prevents
late completion after unlink/replacement without invalidating metadata increments.

`LibraryMissingError`, `LibraryExistsError`, `LibraryCorruptError`,
`UnsupportedLibrarySchema`, `UnsafeLibraryPath` and `LibraryBusyError` distinguish
library failures. `PaperNotFoundError`, `IdentityConflict`, `StaleWriteError` and
`InvalidPaperState` distinguish Paper failures. All derive from `LibraryError`.
Invalid input raises `ValueError`, including Pydantic validation errors.

## Identity, metadata and dates

`ExternalIds`, `strong_identifiers` and existing reliable namespace normalizers
remain the identity source, including DOI-free IDs, DOI spellings and deterministic
arXiv DOI-to-ID mapping. Titles/authors and related Preprint IDs never establish
ownership. Direct IDs are an explicit input separate from `PreprintResult`; the
caller verifies their direct relationship to the article.

All direct identities remain indexed after exclusion and metadata deletion. The
new library retains multiple verified values within a namespace across increments.
The unique key prevents any normalized identity from belonging to two UUIDs.
Matching/creation, conflict adjudication and identity additions occur under the
same short write transaction. `create_or_match` never updates a matched full record
or reconstructs a placeholder; use the guarded increment or rebuild API instead.

`PaperMetadata` contains title, bibliography, authors, keywords, sources, notes,
optional abstract, `ordinary_dates` and separate Preprint results. `MetadataDelta`
contains only automatic abstract/date/Preprint/source candidates, without notes
or title. Bibliographic `publication_date` keeps the existing `YYYY`, `YYYY-MM`
or `YYYY-MM-DD` precision and stays independent of the two collections.

Ordinary dates accept only valid `YYYY-MM`/`YYYY-MM-DD` values, deduplicate, remove
a month when any day in that month exists, retain different days and sort
deterministically. Year-only ordinary dates are refused; a year-only bibliographic
field never manufactures a month/day. Legal future dates remain; the repository
has no Run range filter. Preprint results never add or subtract ordinary nodes,
including an equal date independently supplied by the formal article. Neither
collection derives `publication_date` or Preprint results. Production
`paper_dates.py` event semantics are unchanged.

Existing nonempty abstract text is retained exactly. Empty/markup-only candidates
do not occupy the first-candidate opportunity. The existing abstract normalizer
is reused when accepting a new automatic candidate in the transaction observing
the latest empty value and manual generation. The repository performs no
extraction/API queries and does not judge source eligibility.

## Paths and actual files

Before connecting, the database path and every parent reject symlinks. Existing
main, `-journal`, `-wal` and `-shm` files must be ordinary, single-link files. An
open repository also checks original Workspace/database inode identities before
transactions. These checks follow applicable UserState safety principles without
sharing its database or configuration payload.

`BodyReference` accepts a canonical POSIX relative path below `Documents/`, optional
source URL and nonnegative byte count. Absolute/drive paths, traversal, empty/dot
components, backslashes and control characters are refused. This lexical contract
does not assert file existence or grant permission to follow filesystem links.
WF09's file service must validate the live managed directory when landing files.
WF01 never creates Documents, reads/writes PDF bytes, downloads, opens, locates or
deletes actual PDFs.

## Test and contract disposition

| Disposition | Evidence and scope |
| --- | --- |
| Added | `test_paper_repository.py` and `test_paper_repository_safety.py`: real reopen, identity/abstract/body contention, conflicts, dates, manual invalidation, lifecycle/rebuild, unsafe paths, foreign keys, bounded busy waits and trigger-injected rollback |
| Retained as valid | Existing identity, materialization, Markdown/safe-write, decisions, Import, preprint, enrichment, Run and UserState tests; production callers still rely on them |
| Shared symbol changed, behavior retained | Abstract normalizer is now public as `normalize_abstract`; existing callers and assertions retain their semantics |
| Documentation corrected | Architecture, Paper identity, Workspace layout, safety, development and README scope production Markdown separately from this kernel |
| Removed as uncalled | None; WF01 retires no production consumer or event-date assertion. WF02 owns cleanup with its replacement |

The path precondition test forbids connecting to unsafe targets; it does not mock
the store. Other fixtures use real SQLite connections, including concurrent
writers and injected statement failures. This is component acceptance, not
workflow/UI, real-site, Zotero, actual PDF or production-cutover acceptance.
