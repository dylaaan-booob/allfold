# Data and execution safety

This guide owns cross-runtime data and authority boundaries. Module guides describe
current interfaces and known limitations; historical implementation checks are not
requirements to preserve when those modules change.

## Library and user data

Production Paper reads and writes use one [SQLite library](paper-library.md),
with stable Workspace/Paper UUIDs and reliable direct-identity uniqueness. A Run
uses the repository-returned UUID. Repeat full matches preserve saved metadata;
excluded records stay excluded; only an actual Run hit can rebuild an unexcluded
identity placeholder. Conflicting identity owners remain explicit failures.

Each HTTP handler/worker owns a thread-confined connection and closes it in that
context. Short rollback-safe transactions contain no network/browser wait.
Unsafe paths, missing/corrupt/unsupported libraries and busy/commit failures do
not authorize replacement or clearing. Schema v5 supports the documented v4/v3
forward changes without retired-format or Markdown fallback. Database-open
validation and transaction scope are implementation details scheduled for later
revision, not a requirement for a full integrity check/write transaction on every open.

Async writes retain the original Workspace/Paper/attempt and relevant field
eligibility. A late result cannot obtain fresh authority by rereading current
tokens. Manual abstract edits/clears protect that field independently of legal
date/source increments. Library revision and response ordering prevent stale UI
snapshots; they are distinct from task authority.

Reject persists exclusion before exact-Paper cancellation outside write locks.
Deferred signals retain their captured task, so they cannot cancel a replacement
after Restore. Restore is local and does not renew old write authority or fetch
content. Clearing metadata waits for actual conflicting work and preserves UUID,
reliable identities, exclusion and body association. Exclusion has no expiry.

Journals/Groups/Labels/Services live in canonical-configuration-scoped UserState.
Compare-and-write protects newer edits; corrupt state is not replaced by defaults.
First-configuration `list.md` initialization and explicit Research Scope exchange
remain separate from retired per-Paper Markdown. Resource refresh replaces only
validated complete cache snapshots, never user Service choices. Setup preserves
configuration, credentials and existing vendor trees.

## Files and destructive operations

A body association classifies Downloaded but grants no physical file authority.
[Body downloads](body-downloads.md) owns managed path/object checks, no-clobber
publication, local open/locate and Trash deletion. Relative body paths reject
traversal and absolute paths. Only confirmed absence clears the captured current
association; permission, shell and unsafe-path errors preserve it. Filesystem and
SQLite changes are not one atomic transaction. Clearing metadata leaves bytes intact.

Original DownloadItem output retains the measured
[native cancellation limitation](body-downloads.md#native-output-and-accepted-cancellation-risk).
Chromium may delete an externally replaced private staging pathname after
`done(cancelled)`; item terminal is not proof of file-worker closure. Application
cleanup touches only proven owned output, and final publication stays no-clobber.

Workspace switching stops admission and drains owned work before rebinding.
Workspace Reset is explicit preview/confirm deletion of the verified Workspace,
including library, exclusions, Documents and snapshots. Custom Workspace paths
inside the project are supported; project/runtime trees, UserState, Registry,
covers, configuration/Journal inputs and their ancestors remain protected.
Directory identity and symlink checks apply before deletion. Logs Reset removes
only owned history/diagnostics, preserving library, configuration, Session and
credentials. Neither operation silently resets corrupt data.

## Native requests and access

IPC messages and native responses stay associated with the actual request, target,
frame and resource owner. Selecting a Browser tab never retargets a task. Remote
pages have no Node or host IPC capability. Trusted UI sender checks and the
sandboxed, isolated Document preload remain in use. CARSI credential authority
applies only to the saved institution and attributable authentication chain.

[Document access](browser-documents.md) owns page reading and Solver behavior.
Current fixed probes still have extra URL/subject/identity checks; their planned
replacement does not remove request correlation or credential protection. Capturing
rendered HTML for independent parsing is an agreed follow-up, not a current
capability or a reason to restore Translator Runtime. Raw pages and credentials
stay out of diagnostics and public projections.

Saved Service and captured access dependencies determine access authority;
configuration revisions also serve compare-and-write and diagnostic purposes.
Access cleanup carries captured old keys, waits outside configuration write locks
and cannot close a new context. Retained-page destruction revokes that page's
preparation; a late Login result cannot restore a closed page. Covers final saves
protect the captured Journal and managed asset while allowing unrelated edits.
The Download-wide Prepare admission policy remains unresolved; see
[body admission](body-downloads.md#public-input-and-admission).

## Cancellation and task release

Run, Login, Covers and Paper cancellation address the captured task/attempt.
Cancellation and shutdown join actual workers and native resources before their
owners disappear. Shared Run requests and independent branches keep serving
unaffected work. Page capacity follows actual resource ownership; see
[Browser pages](browser-pages.md) and [Session events](browser-session.md).

[Workspace runtime](collection-runtime.md) owns atomic base/queued admission,
independent branch resources, retry and maintenance. Foreground Run ends separately
from accepted Paper collection. Branch-specific access failure must not revoke
unrelated work. Successful increments survive a later failure; startup records
interrupted attempts without replaying queues, network or page actions.

Actual unfinished I/O still needs its original owner. Finished work is released
despite logging, terminal-record or auxiliary cleanup faults. A failed required
terminal transaction remains a storage error; only its exact ended token is kept
for settlement on the next explicit Paper operation, never for automatic replay
or whole-Workspace recovery. Successful transport/open/locate results are not
revoked by late cancellation, expiry or repeated qualification. Original-target
protection remains at actual file/SQLite writes. There is no local completion
phase, state or extra deadline.

[Logging](logging.md) owns diagnostic privacy and retention. Logging failure cannot
change business results. Use isolated SQLite, files, HTTP and Electron profiles;
source/fixture checks do not prove live-provider, institution, user-library or
system-PDF behavior. Select verification through [development](development.md#checks).
