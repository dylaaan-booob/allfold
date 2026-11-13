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
isolated Document preload stay active. Dedicated Keep/Import/Enrich/Local API
business paths are retired; no native fallback can dispatch them.

Diagnostics use strict allowlists and bounded local storage. Credentials,
Authorization/Cookie values, raw pages and signed URLs stay out of exports.
Logging failure cannot change business results. [Logging](logging.md) defines
retention and Reset. Tests use isolated SQLite, files, HTTP and Electron profiles;
source checks and synthetic fixtures do not prove real provider, institution,
user-library or actual-PDF behavior. See [development](development.md).
