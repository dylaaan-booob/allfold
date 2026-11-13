# Data and execution safety

Production Paper reads and writes use one [SQLite library](paper-library.md),
with stable Workspace/Paper UUIDs and reliable direct identity uniqueness. A Run
uses the repository-returned UUID. Full repeat matches remain unchanged;
excluded records stay excluded; only an actual Run hit can rebuild an unexcluded
identity placeholder. Different direct-identity owners are an explicit conflict.
No Markdown fallback, shadow store, dual write or old Workspace migration exists.

Each HTTP handler/worker owns a thread-confined connection and closes it in that
execution context. Short rollback-safe transactions contain no network/browser
wait. Library schema, integrity, UUID and live directory/database identity are
validated. Symlinks and multiple-link main/sidecar paths are refused. Missing,
corrupt, unknown-schema, unsafe-path and busy/commit failures remain distinct;
none authorizes replacement or clearing. Known v1 upgrades preserve records.

Async writes use eligibility captured when the Paper is first claimed, including
Workspace UUID and metadata/operation generations. Results cannot reread current
tokens to renew old authority. Manual abstract edits/clears invalidate only older
automatic abstract candidates; legal date/source increments remain eligible.
Library revision and response ordering separately prevent stale UI snapshots.

Reject persists exclusion and invalidates tokens before exact-Paper cancellation.
The transaction and Workspace write lock are released before cancellation or
worker join. Shared Run requests keep serving other Papers. Restore is local and
may precede cleanup, but old tokens stay invalid and new mutually exclusive work
cannot overlap it. Destructive metadata clearing waits for real Paper cleanup.
Clearing deletes bibliography, abstract, dates, Preprint proof, notes, ISSNs and
sources; UUID, reliable identities, exclusion and body association survive.
Restore/unexclude never fetches or recreates deleted content. Exclusion has no
expiry or ordinary bulk-clear action.

A body association classifies Downloaded but grants no physical file authority.
WF02 does not download, delete, open or locate PDF files. `Documents/` relative
paths reject traversal/absolute paths; the later landing service must validate
live filesystem ownership. Clearing metadata leaves associated file bytes intact.

Shutdown stops admission and waits for Run, Preprint, WoS, Login, Covers and
in-flight native bridge results before closing their owned connections. Teardown
is idempotent. Switching output directories drains and invalidates old work;
connections are never retargeted to a new path. Workspace Reset remains an
explicit preview/confirm deletion of the entire verified Workspace, including
library, exclusions, Documents and snapshots. Its path/replacement/concurrency
protections remain. Logs Reset removes only owned history/diagnostics and keeps
library, configuration, Session and credentials.

Reset accepts configured custom Workspace directories within the project; it does
not require the directory to be named `workspace`. Project source/runtime trees,
shared UserState, Registry/covers and active configuration/Journal inputs remain
protected, including their ancestors and case variants. Directory identity,
symlink refusal and preview/confirmation checks still apply before deletion.

Journals/Groups/Labels/Services live in canonical-configuration-scoped UserState.
Compare-and-write revisions preserve newer edits; corrupt state is not replaced
by defaults. Research Scope Markdown exchange and its first-migration seed remain
separate from retired per-Paper Markdown. Resource cache refresh replaces only
validated complete snapshots and never user Service choices. Setup preserves
configuration, credentials and existing vendor trees.

Native operations remain bound to exact request, task, Page and Document.
Selecting a Browser tab never retargets a task. Prepare retains scoped recovery,
manual verification and Session behavior. Cloudflare uses the owning CDP target;
hCaptcha/MFA keep their manual boundary. CARSI credential authority applies only
to the saved institution and attributable authentication chain. Remote pages have
no Node or host IPC capabilities. Trusted UI IPC, main-frame sender checks and
isolated Document preload stay active. Fixed binding/access/article probes return
bounded DTOs, never HTML/full text/scripts/forms/iframe URLs. Sender/frame, random
Document ID, navigation generation and current URL are checked across async calls.
Paper identity is rechecked independently at use boundaries after access checks;
it grants no task or institutional authority. Overflow, absent and conflicting
evidence cannot confirm a Paper. Solver attempts remain operation/Document scoped,
and queue cancellation/shutdown joins actual workers. Covers/Export share absolute
parent deadlines; original DownloadItem ownership outlives cancellation until
actual terminal. See [controlled Documents](browser-documents.md). Dedicated Keep/Import/Enrich/Local API
business paths are retired; no native fallback can dispatch them.

Independent Browser admission is scoped by canonical configuration and saved
Service ID. Reprepare cannot replace a context while an executing owner uses it;
credentials, Workspace Reset and Logs Reset retain control exclusivity. Config and
User State revisions remain Compare-and-Write/diagnostic facts, while Prepare
access checks capture institution, credential epoch and the selected Service.
Unrelated edits preserve that captured access. Foreground Run/WoS and Preprint keep
their input snapshots, commit checks and single Run slot.

Settings access cleanup carries captured old preparation/authentication keys and
waits outside the configuration write lock, holding only its affected admission
owner until actual settlement. It cannot close a new-key context. Actual native
retained-Page destruction revokes matching prepared authority; an in-flight Login
result cannot restore an already closed Page. Covers final saves verify the target
Journal and captured managed asset identity/record under the final write guards,
allowing unrelated User State edits and refusing deleted/replaced targets.
A saved cover whose image was already missing may be repaired by Search only if
the captured manifest record and missing-file state still match at final save;
a newly appeared file, replacement, unsafe path or changed target is refused.

Ordinary Login, Covers and WoS cancellation uses the workflow/task ID captured at
start. Public Run cancellation carries the UI-captured task ID through HTTP; the
coordinator compares and sets its signal atomically, then forwards that same
captured ID to WoS outside its lock. Old cancellation cannot target a replacement
Run. Cancellation signals do not release native Futures, workflow admission or
solver slots before actual settlement. Shutdown closes admission, joins business
workers and waits remaining credential/access-cleanup owners while the bridge can
still deliver native terminal results.

Diagnostics use strict allowlists and bounded local storage. Credentials,
Authorization/Cookie values, raw pages and signed URLs stay out of exports.
Logging failure cannot change business results. [Logging](logging.md) defines
retention and Reset. Tests use isolated SQLite, files, HTTP and Electron profiles;
source checks and synthetic fixtures do not prove real provider, institution,
user-library or actual-PDF behavior. See [development](development.md).

WF04 page admission is Session-wide and jointly reserves both managed dimensions
before native creation, including popups. Close requests, retired flags, crashes
and cancellation do not return slots. Cleanup uses captured resource ownership
even after execution authority is revoked, waits actual DownloadItem terminal
and WebContents destruction, and touches no other task/user resources. Successful
Portal/targets transfer ownership without releasing physical counts; stale-key
cleanup and physical-close feedback cannot invalidate a newer context. Lowered
limits revoke unused headroom and defer new creation without forcing active pages
closed. Normal exit disposes common Session listeners only after physical cleanup.
See [exact counts and rollback](browser-pages.md).
