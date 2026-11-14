# Internal body download lifecycle

WF09 supplies `submit_body_download(host, paper, candidates=..., service_id=...,
deadline=...)` for caller-confirmed saved Papers and immutable `PdfCandidate`s.
It installs no HTTP trigger, button, automatic Run download or second save task.
Public Download/open/locate/physical deletion and original action/POST/one-shot
DownloadItem adoption remain WF10. The fixed P1–P5 catalogue and Python bounded
API/HTML consumers remain available; the new entry consumes a bounded confirmed
candidate sequence directly, without a Python PDF GET or HEAD.

## Qualification and occupancy

The Workspace host and existing bounded Paper scheduler own queued through cleanup
work. `body` reservations are distinct from the still-used read-only `download`
reservation and manual Preprint `legacy` reservation. Repeated body requests reuse
the same owner/attempt without changing candidates, Service or deadline. Collection,
manual queries, discovery and uncertain cleanup are mutually exclusive. A new Run
reliably matching a downloading Paper returns the original UUID/current state and
registers no collection intent. Unrelated Papers and foreground Runs remain usable.

Admission persists the queued attempt under the same Paper gate that publishes its
owner. Its captured Workspace/lifecycle, metadata/operation/body generations and
primary identity remain mandatory; abstract generation, notes and ordinary Run
inputs are independent. Service/Prepare and host epochs remain scoped. Reject's
transaction revokes the original token before exact cancellation outside write locks;
Restore cannot renew it. Existing complete bodies are returned without replacement.
No failed/cancelled state or unoccupied complete `not_started` collection invents a
new collection prerequisite.

## Session and transport

Authenticated Main dispatch alone accepts `stream_paper_body`. There is no renderer
IPC or generic HTTP writer. Its private payload contains the captured root, exact
attempt-owned output proof and limited candidate context; PDF bytes never traverse
the bridge. Main waits for the existing business Session identity, pins applicable
Prepare access, then uses the single `SharedSessionEvents.fetch` with Chromium
credentials. No default Session, Cookie export or Cover `omit` contract is reused.

Targets require controlled public URLs and public DNS answers. Current direct-stream
redirect scope is the captured request origin; an origin escape fails before it can
forward credentials. The original signed query remains in the current request only.
Referer is set only from the confirmed candidate, with `strict-origin-when-cross-origin`.
Actual final URLs come from associated native response facts. Random private markers
are stripped before outbound headers. Request/task/attempt identity separates equal URLs.

PDF MIME plus successful pipeline completion is the transport condition. Main uses
`Readable.fromWeb` and awaited `pipeline` with backpressure, flush and actual writer
close. Parent expiry and exact cancellation stop the same stream and writer; cleanup
is awaited without an expired cleanup race. Progress is throttled to 100 ms with
received bytes; totals may be unknown. Content-Length equality, minimum size, PDF
headers/EOF/structure/text/identity/hash/version checks are absent. HTML is bounded to
256 KiB and returned as the current response with access classification; action/POST
and explicit API-credential candidates remain pending rather than GET emulation.
Only ordinary candidate failures permit the next confirmed candidate; a completed
stream stops sources, and any local finalization error ends that task.

## File ownership and final transaction

New bodies use `Documents/<paper UUID>.pdf`, staged on the same filesystem at
`Documents/.downloads/<paper UUID>.<attempt>.part`. Directory components are opened
without following links. Python uses pinned directory descriptors for exclusive
creation, link/unlink publication and removal. Private SQLite output facts record
Workspace/Documents/staging device/inode identities plus the actually created
regular inode; planned names alone confer no authority. Main opens without truncate
or following the final link and verifies both descriptor inode and live directories
before any write. Publication uses atomic no-clobber link, never exists-then-replace.
Conflicts and replacements preserve unknown files and never choose numbered names.

`complete_attempt` is shared completion service for a closed qualified transport:
recheck original authority, publish the owned output, recheck, then use a short
`complete_download` transaction to atomically add the unique body, completed state,
byte count, origin-only source projection and revision. Network and publication are
outside SQLite transactions. Candidate becomes Downloaded only after this commit.
Duplicate terminal delivery is idempotent. `complete_body` remains a logical fixture
constructor and cannot replace an existing association or authorize file operations.

Reject winning the final transaction prevents completion and cleans only that
attempt's unfinished output. Completion winning first protects the body even if
Reject, a late guard, notification or cleanup later fails. Filesystem and SQLite
have no common transaction: a failed database completion removes only proven,
unassociated output and never tries another source or offers a save/commit retry.

## Failure, restart and evidence

Native Future/writer-close uncertainty retains conservative host occupancy. Once
resources are closed, an unlink/identity cleanup failure persists bounded output
facts and failed state while freeing idle execution and Browser budgets. The next
explicit request must clean those known facts before creating another attempt or
request. No orphan scan, filename-based ownership recovery or automatic deletion is
performed. Unknown files created before reliable ownership recording remain unknown.

Startup normalizes other lifecycles' queued/running downloads to failed/interrupted,
keeping completed bodies and proven output facts. It starts no network, queue or page.
Explicit retry cleans known fragments and starts a new attempt from scratch.

Schema v4 adds only the current download row. Opening an exactly valid v3 library
validates its complete structure/integrity/references and transactionally creates the
new table/version; all prior Paper/Workspace identities, metadata, collection/branch
facts, bodies, exclusion and revisions remain. Failure rolls back DDL and version.
Unknown/corrupt schemas and v1/v2 remain refused; there is no generic migration engine.

`tests/test_body_downloads.py` covers real temporary file/repository publication,
conflicts, directory and object replacement, Reject order, unlink/DB/submission
faults, interruption subprocesses, v3 rollback and reservation exclusion.
`body-stream.test.cjs` composes the real application service, production Bridge/Main
dispatch, Electron 45 Session, local HTTP, files, SQLite and Workspace projection.
Its isolated DNS routing and synthetic Cookie establish mechanism evidence only.
Real institutions, publisher/CDN/proxy access, manual challenges and installed app
acceptance require separate authorization. Existing native original-response,
WoS, Cloudflare and page-lifetime regressions remain separate evidence.
