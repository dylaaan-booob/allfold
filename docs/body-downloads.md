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

Targets require controlled public URLs and public DNS answers. Direct-stream
redirects stay inside the captured request origin. An origin escape is stopped
before forwarding headers; an actually observed Oxford `article-pdf` redirect to
a matching `watermarkNN.silverchair.com/<same filename>.pdf` can become the next
candidate. A ScienceDirect `pdfft`/`pdf` redirect can likewise reach only
`pdf.sciencedirectassets.com/.../1-s2.0-<same PII>/main.pdf`. That request repeats public DNS/target checks and uses Chromium's
destination-scoped cookies, never source headers. Other cross-origin redirects,
filename changes and protocol downgrades remain refused. The original signed
query remains in the current request only.
Referer is set only from the confirmed candidate, with `strict-origin-when-cross-origin`: cross-origin values keep only origin and HTTPS→HTTP omits the header.
Actual final URLs come from associated native response facts. Random private markers
are stripped before outbound headers. Request/task/attempt identity separates equal URLs.

PDF MIME plus successful pipeline completion is the transport condition. Main uses
`Readable.fromWeb` and awaited `pipeline` with backpressure, flush and actual writer
close. Parent expiry and exact cancellation stop the same stream and writer; cleanup
is awaited without an expired cleanup race. Progress is throttled to 100 ms with
received bytes; totals may be unknown. Content-Length equality, minimum size, PDF
headers/EOF/structure/text/identity/hash/version checks are absent. HTML is bounded to
256 KiB and returned as the current response with access classification. The body
owner consumes the existing qualified current-response parser, with at most 16
Session stream dispatches, six next hops and no repeated URL/action. A known reader without
inline PDF clues uses the existing bounded Document/PDF-clue operation and its
automatic Cloudflare/manual-verification rules, under the same captured body
authority. An unsigned ScienceDirect reader first refreshes its live confirmed
article's current entrance before any stream request. Only same-PII toolbar
reader/assets links may bypass generic navigation exclusion; other Papers,
supplements, references and related regions stay excluded. A ScienceDirect response returning its confirmed article origin/path may
use the same live-Document reader to refresh the current signed PDF entrance,
ignoring tracking query/fragment differences but retaining independent article
identity checks. Actual native cleanup ends before transfer continues; no collection
is registered or written. Cloudflare background resources and ordinary Sign in
navigation do not identify a main challenge or login page. Unknown HTML is not
a generic crawler. Empty ordinary branches retain queued alternatives; access
barriers still stop, and reader cancellation/expiry is rechecked after native
cleanup before recording the terminal result. Action/POST
and explicit API-credential candidates remain pending rather than GET emulation.
A reader may resolve current HTML PDF clues, but an original browser PDF response
is not canceled and replayed as a new GET. Publishers requiring that original
response remain a WF10 native-adoption boundary; displaying a PDF viewer or
finding a signed entrance alone is not a completed body download.
Only ordinary candidate failures permit the next confirmed candidate; a completed
stream stops sources, and any local finalization error ends that task.
Native Document access refusals remain terminal. HTTP 418, visible paired
CPE00001 denial text and a same-origin Imperva main iframe shell cannot become
ordinary empty branches; background error strings or embedded side frames alone
do not establish these barriers.

## File ownership and final transaction

New bodies use `Documents/<paper UUID>.pdf`, staged on the same filesystem at
`Documents/.downloads/<paper UUID>.<attempt>.part`. Directory components are opened
without following links. Python uses pinned directory descriptors for exclusive
creation, link/unlink publication and removal. Private SQLite output facts record
Workspace/Documents/staging device/inode identities plus the actually created
regular inode and a private disposal-directory identity; planned names alone confer no authority. Main opens without truncate
or following the final link and verifies both descriptor inode and live directories
before any write. Publication uses atomic no-clobber link, never exists-then-replace.
Removal first atomically moves the addressed entry without clobbering into the
service-private `.downloads/.cleanup` directory, verifies the moved inode, then
unlinks it. A concurrently substituted entry is restored without overwriting; it
is never deleted. A recorded inode stranded in the deterministic disposal slot is
handled on explicit retry. macOS uses standard-library ctypes with native
`renameatx_np(RENAME_EXCL)`; no helper executable/dependency is required.
Conflicts and replacements preserve unknown files and never choose numbered names.

`complete_attempt` is shared completion service for a closed qualified transport:
recheck original authority, publish the owned output, recheck authority and final
inode at the completion boundary, then use a short
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
Its saved Service/manual-confirmation authority, controlled slow writer/backpressure
and held-close barrier, normal application drain, isolated DNS routing and synthetic
Cookie establish mechanism evidence only. It also covers actual Oxford-style
cross-origin handoff with distinct source/CDN cookies and an IEEE reader-to-PDF
chain without a second request to the source.
Real institutions, publisher/CDN/proxy access, manual challenges and installed app
acceptance require separate authorization. Existing native original-response,
WoS, Cloudflare and page-lifetime regressions remain separate evidence.
