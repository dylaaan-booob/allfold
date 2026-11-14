# SQLite Paper library

`Workspace/papers.sqlite` is the only production Paper store. Current Run/WoS,
Workspace/Reader/search, local fields, Preprint and Trash share `PaperRepository`.
Uninitialized read-only Workspace views remain empty without creating a database;
the first Run explicitly initializes one. Corruption, unsafe paths, unsupported
schemas and database failures are errors, never an empty or recreated library.
No Paper Markdown migration, dual write, mixed read or backend switch exists.

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
schema version 4, and `library_info` stores the Workspace UUID. Opening checks
the version, expected table/index definitions, integrity and references. Missing,
corrupt, unsafe and unsupported-schema libraries raise distinct errors. Existing
content is never overwritten or rebuilt implicitly. An exactly valid v3 schema has one transactional forward change to v4; unknown,
corrupt and retired v1/v2 formats remain refused. Acceptance uses isolated data. Failed initialization preserves its
exclusively created file for inspection rather than deleting it.

| Table | Responsibility |
| --- | --- |
| `library_info` | Stable Workspace identity |
| `paper_core` | Paper UUID, exclusion and metadata/operation/body generations |
| `library_state`, `paper_projection` | Persisted library and record revisions for current projections |
| `paper_identities` | Unique `(namespace, normalized_value)` ownership, referencing the core |
| `paper_metadata` | Deletable complete payload and manual-abstract generation |
| `paper_body` | One current relative PDF association, source URL and optional byte count |
| `paper_collection` | Current metadata lifetime's attempt, captured generations/lifecycle, state, cancellation and bounded reason |
| `paper_collection_branch` | At most 16 current branch facts and last committed result sequence |
| `paper_download` | Current body attempt, captured qualification, state, bounded reason and actual output ownership |

There is no kept/exported state, Zotero parent item, Markdown authority path,
replayable download queue, unbounded attempt history or executable download replay. Collection
facts contain no queue order, client, page handles or replay instructions. Clearing metadata
deletes its row and all contained bibliography, notes, dates, sources and Preprint
results, including the complete PDF discovery-facts payload. Core, direct identities, exclusion and an existing body association
remain. This is logical deletion, not a forensic file-erasure guarantee.

Collection facts are deleted when metadata is cleared, after the current owner
settles. A verified new Run hit may rebuild the same UUID into a new metadata
lifetime and admit collection; existing body associations remain intact.

## Public API and conditional writes

Import the public API and errors from `allfold.persistence.paper_repository`.
`library_models.py` defines immutable values; `library_database.py` owns schema
and connection safety. These helpers are not alternate application writers.

| Interface | Result and conditions |
| --- | --- |
| `create`, `open`, `close` | Explicit lifecycle; optional expected Workspace UUID on open |
| `get(paper_id)`, `list_papers()` | Immutable `PaperRecord` projections, including excluded and cleared records |
| `match(direct_ids, additional_identities=...)` | Match saved direct identities; different owners raise `IdentityConflict` |
| `create_or_match(workspace_id, direct_ids=..., metadata=...)` | `CreationResult(paper, created)`; a new full record requires title and reliable direct identity. Matches return the existing record unchanged in every state |
| `merge_metadata(token, delta, direct_ids=...)` | Merge eligible automatic dates, Preprint/source/discovery facts and the first valid abstract; optionally add verified direct identities in the same transaction |
| `edit_metadata(token, changes)` | Apply only named local fields to the latest payload; no whole-record snapshot save |
| `exclude(token)` | Mark excluded and revoke prior operation authority |
| `restore(token)` | Restore a full record, advancing authority; old tokens stay invalid |
| `clear_metadata(token)` | Only in the recycle bin; delete the payload and advance metadata/operation generations |
| `unexclude(token)` | Release only a cleared identity placeholder; content remains absent |
| `rebuild_from_run(token, direct_ids=..., metadata=...)` | Only a cleared, unexcluded placeholder accepts a new caller-verified Run result directly identifying it; retain UUID and establish new generations |
| `complete_body(token, body)` | Logical fixture seeding only; preserves existing body, grants no file authority |
| `begin_download`, `require_download`, `record_download_output`, `complete_download`, `finish_download`, `interrupt_downloads` | Captured current attempt, owned output, unique final body/terminal transaction and no-replay interruption; see [body lifecycle](body-downloads.md) |
| `clear_body(token)` | Local unlink, also allowed when excluded or without metadata; revoke pending results even when no body is associated |
| `admit_collection(workspace_id, lifecycle_id=..., branches=..., direct_ids=..., metadata=...)` | Atomically create/match and establish queued authority; rebuild additionally requires original `expected_token` and `allow_rebuild=True`; return `CollectionAdmission(paper, token, admitted, created)` |
| `require_collection(token)`, `mark_collection_running(token)` | Recheck captured attempt/lifecycle and uncancelled execution authority; optionally mark dispatch |
| `commit_collection_branch(token, branch, sequence=..., delta=..., outcome=..., reason=..., direct_ids=...)` | Atomically merge an increment and its branch fact; duplicate/older sequences never reapply content |
| `request_collection_cancel(token, reason=...)` | Revoke writes immediately; preserve active occupancy through actual cleanup |
| `finish_collection(token, reason=..., failed=False)` | Aggregate settled branches after actual cleanup; optional cleanup failure prevents completion |
| `retry_collection(write_token, lifecycle_id=..., branches=...)` | Explicit retry of settled failed/cancelled full, unexcluded Papers; preserve successful/skipped branch facts |
| `interrupt_collections(lifecycle_id)` | Explicit lifecycle initialization; fail other lifecycles' queued/running work as interrupted, without replay |

Returned records include `.token`. `WriteToken` binds Workspace UUID, Paper UUID,
metadata lifetime and operation generation. Exclusion, restoration, clearing and
rebuilding cannot resurrect old authority. Even a current-generation token cannot
authorize automatic metadata or a new body while excluded or without metadata.

`CollectionToken` wraps the original `WriteToken`, integer attempt and Workspace
lifecycle UUID. Persisting the original write token prevents repeated admission
from renewing old authority after Reject/Restore or a manual abstract edit.
`PaperRecord.collection` is optional; `.collection_status` supplies `not_started`
when absent. Task facts advance the same library/record revisions as metadata.
Existing full completed, failed and cancelled records are reused without automatic
collection; queued/running returns the same attempt. Explicit retry increments it.

Branches use bounded names and `queued/running/completed/skipped/failed/cancelled`
facts. Each attempt's positive monotonic sequence deduplicates callbacks without
an event ledger. Empty success is completed; skipped requires an applicability
reason. Only all settled successful/skipped branches can complete. Branch, write
or cleanup failure makes the group failed; requested cancellation makes it
cancelled. `finish_collection` is called only after the runtime has joined actual
resources. Repository transactions contain no cleanup wait.

Cancellation, exclusion and replaced attempts block content. Captured failure or
cancellation-only branch settlement and group finish remain possible for the same
attempt after Reject/Restore, without renewing execution authority. These cannot
write content or touch a later attempt/lifetime. Successful facts and committed
fields survive failure, cancellation and explicit retry. Metadata clearing and
body completion reject active collection in their own transaction. The application
also serializes download/explicit-Preprint occupation and admission under one Paper gate.

`open()` never interrupts tasks. The Workspace lifecycle owner explicitly calls
`interrupt_collections` before first admission; ordinary worker/reader connections
cannot mistake current-process work for a restart. Interruption preserves committed
fields and successful branch facts, starts no network/pages and never retries.

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
collection derives `publication_date` or Preprint results. Run keeps its existing query and first-version algorithms. Event facts remain
operation-local inputs; the library ordinary date set has no event/source columns.

Existing nonempty abstract text is retained exactly. Empty/markup-only candidates,
standalone wrapper/heading-only candidates, pure ellipses and explicit unavailable,
sign-in or Read more notices do not occupy the first-valid
opportunity. New automatic candidates use `abstract_text.normalize_abstract_text`,
separate from Run base `canonicalize.normalize_abstract`. It removes explicit
markup and standalone Abstract/Summary wrappers, retaining internal scientific
headings, ordered newline-separated paragraphs, Unicode and inequalities/angle
notation. `MetadataDelta` qualifies candidates without rewriting their input;
the short transaction normalizes an accepted new value once. `PaperMetadata`
preserves existing nonempty strings exactly, including their whitespace, when
reopening or merging unrelated dates/notes. The first eligible candidate fills
the latest empty value only if its captured abstract generation still agrees;
later or longer candidates do not replace it. No schema or bulk rewrite is needed.
The repository performs no extraction/API queries and does not judge source eligibility.

`BranchContext.read_paper()` is a guarded current projection, never a new token.
The internal `document_metadata_branch` and `necessary_metadata_branch` emit
explicit sequences through the original attempt; wrappers return no second delta.
The native adapter distinguishes empty success, whole failure and an explicitly
partial abstract result. Candidate/budget failures retain qualified dates and a
failed branch, with fixed diagnostics in the operation-local service report;
JSON-LD-only warnings can complete. Document/recovery/diagnostic annotations do
not enter persistent metadata. Final native live verification precedes normal
owned-page cleanup; repository commit then rechecks captured task authority
without revisiting the closed Document.

The registry now executes applicable same-Paper branches concurrently using a
bounded leaf scheduler separate from its parent Paper pool. Each leaf opens its
own repository, client/cache scope and native owner; thread checking remains
enabled. Actual client/native/page cleanup and final writes gate Paper release.
The [runtime contract](collection-runtime.md) documents Run admission, original
snapshot/rebuild qualification, deferred intent behind manual work, exact scoped
maintenance and pending-only explicit retry.

The earlier Reader pipeline fixture remains component evidence for API-first,
DOM-first and simultaneous transactions, first-valid abstracts, empty candidates,
manual edits/clear, notes, duplicate sequences, identity rollback and Reject/Restore.
Registry/host tests now additionally exercise actual production schedulers and
independent thread-owned SQLite/client scopes. Production Run/UI adoption is
verified separately from these foundational runtime checks.

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
WF09's [file service](body-downloads.md) validates the live managed directory and actual inode when landing files.
WF02 does not read/write PDF bytes, download, open, locate or delete actual PDFs.
A body association classifies an unexcluded record as Downloaded. It confers no
physical file-operation authority; those services belong to WF09/WF10.

## Production lifecycle and projections

WF07 adds bounded `discovery_facts` inside the deletable `PaperMetadata` payload
and `MetadataDelta`; it does not reuse `BodyReference`. Each version-1 snapshot
names its exact target, source/capability, observation time and completeness, with
typed stable PDF/landing/XML facts or fixed refresh locators. No snapshot means
unknown; complete-empty, partial and failed responses remain distinct. These are
current collection capabilities, not old-payload compatibility states. Stored facts
use the current typed payload contract. Acceptance does not read or migrate old data.

There is one bounded current snapshot per source/capability, rather than an
attempt history. Merging preserves qualified facts and stage order under the
same captured token, branch sequence and metadata generations.
Merge capacity includes both item counts and the complete 64 KiB serialized
snapshot. If the union exceeds either, the preferred verified snapshot is kept
with a bounded overflow reason when it fits; this cannot discard independent
Date/Abstract in the same delta. Identity conflicts remain failures.
Signed/session URLs become refresh locators instead of permanent templates;
live current candidates retain their original parameters only within their task. Clearing
metadata removes every discovery fact. Identity, body and manual text/date/
Preprint contracts remain independent. The complete rules and evidence are in
the [adopted discovery specification](pdf-source-discovery.md).

HTTP handlers and Run/Preprint workers open, use and close repositories in their
own execution thread. Network/browser waits never occur in a database transaction.
Workspace/database identities and short commit eligibility prevent results from
writing after Reset, path replacement or output-directory switching. Shutdown
stops new work and waits for real worker/bridge settlement before final teardown.

Unexcluded full records are Candidate unless associated with a body, when they
are Downloaded. Excluded records are Trash regardless of metadata/body presence.
A cleared, unexcluded record with a body is an identity-only Downloaded entry;
without a body it is a hidden identity placeholder awaiting an actual Run hit.
Local restore never sends a request to recover metadata or notes.

Reject commits exclusion and invalidates tokens before invoking exact-Paper
cancellation outside database/Workspace write locks. Restore may happen during
cleanup; old tokens remain invalid. Clearing metadata waits for that Paper's real
cleanup to finish. Shared Run discovery remains available to other Papers.

`test_paper_repository.py`, `test_collection_repository.py` and `test_paper_repository_safety.py` use real temporary
SQLite databases for reopening, contention, identity conflicts, dates, generations,
rollback, paths, concurrent admission, captured branch writes,
cancellation, retry and explicit interruption. Production Run now uses atomic
base/queued admission with original token/rebuild qualification and complete plans.
Workspace owns branch resources after foreground completion. Public single-Paper
retry uses the same eligibility service as its projection and preserves successful
branch facts; Download stays internal. Application/API fixtures exercise
production adoption, fields, Preprint and recycling; Electron fixtures exercise
projections, response ordering and the existing layout. None establishes real
provider, institution, user-library or actual-PDF acceptance.

`touch_projection(paper_id)` advances only the Paper/library response revisions
for a runtime reservation change. It grants no metadata/operation/abstract/body
qualification. The application holds the same Paper gate and captured reservation
identity through that commit and runtime ownership change; failed persistence
cannot silently release the reservation.
