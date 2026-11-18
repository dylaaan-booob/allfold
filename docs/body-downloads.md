# Paper body downloads and local files

`BodyDownloadService` owns the public single-Paper Download/Cancel path. One
Workspace host reservation owns lazy P1–P5 discovery, the selected Session stream
or qualified original form DownloadItem response,
file publication, the SQLite completion transaction and actual cleanup. There is
one current body per Paper and no separate save, receive or commit task.

A fixed current-form action retains its original method/body and Session, including
GET form submissions. It does not emulate POST or one-time responses with a GET.
Ordinary URLs, including signed R024 GETs, use the Session stream consumer. Browser
may establish access or obtain a URL before another ordinary GET; saving that GET
does not require its navigation's original response or a DownloadItem.
Original form output retains the measured
[native cancellation limitation](#native-output-and-accepted-cancellation-risk).

## Public input and admission

The authenticated local HTTP request contains Workspace/Paper identity and finite
current qualification. New downloads carry the observed metadata, operation and
body generations plus the observed download attempt; abstract generation is
deliberately absent. Cancel also carries the actual task ID and attempt. Renderer
input cannot supply candidates, paths, headers, cookies, scripts or credentials.
CSRF, trusted-origin checks and maintenance admission remain in force.

Admission uses the current host, Paper gate and bounded scheduler:

| Current facts | Result |
| --- | --- |
| A current body exists | Capture its local-file qualification before candidate construction, Prepare or new-download checks. Existing identity-only and Trash bodies can be read locally. |
| A real body owner is queued, running or still cleaning up | Return its original task/attempt, progress and deadline; do not change sources, Service or writer. |
| Full unexcluded metadata, no body and no conflicting work or cleanup | Recheck the captured generations/observed attempt, resolve actual access and admit one body attempt. A complete idle `not_started` collection needs no invented completed-history prerequisite. |
| Queued/running work, read-only discovery or genuinely unsettled resources | Refuse new body work until actual settlement. A missing owner alone is not an eligibility shortcut; a known ended attempt with a failed terminal write is settled precisely on the next explicit operation. |
| Failed/cancelled/interrupted download explicitly retried | Attempt cleanup of its recorded temporary output, then use the next attempt's distinct path. Failed temporary unlink alone does not block admission; an existing permanent target still causes a real no-clobber conflict. Completed metadata is not recollected. |
| Excluded or metadata-free Paper without a body | Do not start a new download, restore content or prepare access. |

`body` reservations remain distinct from read-only discovery's `download`
reservations. Production Download does not nest a read-only reservation inside its body owner. A matching new Run reuses the UUID
and current facts without registering collection intent that revokes the body
attempt. Foreground Run cancellation and reader selection do not own the body.

Download admission does not require a mapped or prepared Service. Ordinary URLs,
stable cached candidates and public Reader/native entries use the normal shared
Session, with its ordinary Cookie behavior. No OA preflight, candidate partition,
Cookie copying or automatic Login/Prepare is introduced.

Only an operation that actually consumes a retained institutional capability
captures the Paper's unambiguous saved Service and prepared context. The OCE
Reader capability check is one such operation. Missing, ambiguous, removed or
unprepared mappings skip that path with a specific source reason; they never
select another Service or reject independent sources. Observed descendants of a
bound Reader/form/request retain its captured binding, including HTTPS/CDN
continuations. Independent sources start without it.

Each access operation has its own native task identity under the original
Download workflow. It releases its Browser owner, Service scope and native pins/
loan after actual item/page settlement. Service changes cancel and drain only
the currently dependent operation; the parent can continue independent sources
after cleanup. A previous Service cannot cancel a later OA operation. Workspace,
Paper/attempt loss, user cancellation and parent expiry still end the Download.
Completed transfers go directly to the existing publication/association path,
without a Service post-check. Collection and Run retain their own admission rules.

The captured Workspace root/UUID/lifecycle, direct identity closure and
metadata/operation/body generations stay authoritative through completion.
Reject invalidates the original token before exact cancellation outside write
locks; Restore cannot renew it. Notes, Abstract edits, ordinary Run inputs and
unrelated Services do not revoke the task. Optional Provider authority is
captured without making P1 depend on unused credentials; it is checked and
registered as a used dependency only when the corresponding query is reached.

## One lazy source coordinator

The public service builds `PdfTarget` from saved direct identity and validated
target-bound discovery facts. Arbitrary `MetadataSource` URLs, another Work and
related Preprint identity cannot become the target. Preserve qualified URL/DOI
spelling, multiple DOI path segments, signatures and necessary Referer.
Ordinary discovery entries without an explicit Referer inherit the current
qualified article URL, including a resolved Document route, without another
page request. Explicit Referer, native actions and trusted initial candidate
context remain unchanged. Session transport keeps its existing origin and
HTTPS downgrade projection. Reader/response continuations retain their supplied
context, including an intentional absent Referer.

`PdfDiscovery` owns source order, de-duplication, reader/redirect chains and the
remaining parent budget. P1 templates run first. Among already qualified P2,
saved P3 Meta and stable saved P4 entries, direct PDF candidates precede Reader
or form work and optional missing-input API queries. Equal kinds keep their
source order; this preference applies to every platform. Existing P4 URLs need no article reload for
a partial snapshot, missing Meta field or unrelated refresh locator. After
failure/missing or a dynamic entry requirement, PDF-only refresh supplies current
P3/P4 with the same direct-before-Reader preference; exact-target OpenAlex P5 remains last. P1 success makes later
queries/pages zero. Known Atypon journal Hosts without a dedicated P1 template
share the R039 direct DOI entry; a failed direct entry retains ordinary later
sources. Current Document entries and newly qualified templates use the same
direct-before-Reader preference, including candidates qualified by an API result.
Optional Reader work after an HTML response waits for the batch's other direct
entries; it resumes with its original response/context if needed. A valid response
chain, including the existing ScienceDirect article-backlink recovery, stays in
its source. Query variants of the same rule/endpoint remain that source's
fallbacks rather than interrupting its Reader. Refresh never repeats tried P1/P2 URLs, restarts the
missing-input API sequence or turns an action/refresh locator into a stable GET.
It retains the current Document's observed content URL and identifiers. After
its current P3/P4 clues, these may qualify previously unavailable templates before
P5, still bound to the original Paper.
The [source catalogue](pdf-source-discovery.md) owns rule applicability. Conditional interfaces are skipped when their actual prerequisites
are absent; no publisher-key settings product or generic header capability is
added.

Python may perform bounded API/JSON/HTML discovery reads, but the selected
Chromium Session receives the first actual reusable PDF request. It does not
follow an HTTPX PDF GET/HEAD probe. PDF-only refresh uses [Document access](browser-documents.md) and never recollects
completed Date/Abstract. Known Reader entry/HTML parsers retain their platform
qualification. Actual ordinary GET HTTP redirects use the common Session chain;
their target need not match a filename, PII or publisher CDN list.
Unknown pages are not a crawler. Login/access refusals, missing entries and Reader failures are recorded for that source and allow other qualified candidates after actual cleanup. Only the fixed qualified native entries execute actions; inapplicable
entries are finite condition skips, not pending or successful transfers, and do
not manufacture `fallback_used`.

Only a normal transfer whose small content prefix identifies PDF permits completion. Ordinary candidate failures
may advance sources within the same remaining budget; cancellation, task revocation,
expiry and local file/database failure stop the operation. A completed body is
protected even if a later guard, notification or cleanup reports failure.
`pdf_source` and `fallback_used` are committed with the successful association:
conditional skips, reader/redirect continuation and same-candidate retries do
not count as fallback. Historical bodies retain unknown provenance rather than
deriving it from their origin-only source URL.

`submit_body_download(..., candidates=...)` remains a trusted internal fixture/
caller seam. Its finite confirmed candidate mode is not the public discovery
algorithm, and no public endpoint accepts that input.

## Session stream and resource settlement

Authenticated Main dispatch alone accepts `stream_paper_body`. Private bridge
data contains the captured root, output proof and limited candidate context;
PDF bytes never cross the bridge. Main waits for the existing business Session,
pins only an explicitly bound access context and uses the unique `SharedSessionEvents.fetch`
with Chromium credentials. Cover omission and a default Session are not reused.

Stream targets require public URLs and public DNS preflight. Main stops an origin
or explicit API-credential-scope escape before the next request and returns the
observed HTTP redirect to Python. The same candidate chain issues the next GET
after target/DNS checks, retaining source and actual Service authority.
Destination cookies come from the business Session; explicit source API keys do
not follow outside their fixed HTTPS Host/path. Ordinary redirects do not count
as source fallback. Invalid protocols, internal targets and actual loops remain
refused; no CDN URLs are guessed. Referer uses
`strict-origin-when-cross-origin`, including HTTPS-to-HTTP suppression. Private
request markers leave no outbound header. Renderer cannot configure API secrets.

Already received bounded HTML/JSON is parsed for qualified next hops first.
A necessary fixed Reader uses the Browser and its Solver. Its operation-local
`reader_result` carries the actual owned main-frame GET URL, observed Referer
(including absence), Cookie-context change and an opaque equality key separately
from persistable facts. Main keys Cookie states with a Session-local secret;
neither Cookie values nor these keys enter durable facts or diagnostics. Final body/CDN navigation
does not have to retain the starting Reader template. New navigation, changed
access context or a completed access barrier can permit Session continuation,
including the same URL without a new DOM link. Repeated unchanged responses/edges
stop, including a cycle back to a previously seen Cookie state; actual new Cookie
progress remains distinguishable without a fixed hop count.
Entry-request and Reader context keys remain separate observations, since an HTTP
redirect can lead to a Reader with a different Cookie path. One cannot overwrite
the other's progress.
An observed redirect without a context key retains the last known request state;
absence of new context evidence does not erase actual progress.
Reader, stream and subsequent redirects retain the captured access binding;
independent sources start without it. No Cookie values cross the bridge.

Main uses backpressured `pipeline`, flush and actual writer close. Its
`stream_complete` reports transport, not Downloaded. Progress is throttled and
projected as finite received/total bytes with task/attempt/sequence; zero or
absent total means unknown. File proofs, roots, signed URLs and exceptions stay
private. The same response supplies exactly one five-byte `%PDF-` type observation,
independent of HTTP MIME. The prefix is replayed into the original backpressured
pipeline without losing bytes or issuing GET/HEAD again. HTML carrying PDF MIME
cannot become a body. No Content-Length equality, minimum size, EOF/structure/text/
identity/hash/version validation is added. Non-PDF responses return a finite
256 KiB observation with `partial` when truncated, after the output has settled.
Parsers retain qualified links found before local work/field exhaustion; malformed
JSON fields and unrelated large attributes cannot erase those links.
Their access classification uses the exact response's Cloudflare mitigation header,
real authorization/status errors and contextual verification/login/denial structure.
An optional password field, hidden hCaptcha, background Turnstile/jsd script or
ordinary `access denied` text is insufficient. Current CPE/Incapsula denial evidence
remains distinct from auxiliary resources. When discovery reaches a Cloudflare
challenge on an ordinary stream GET outside the fixed Reader routes, the body
owner can request a temporary verification Page for the exact observed URL.
An eligible ready entry can still finish before deferred recovery. Main checks
public DNS, pins the original Service authority and confines the Page's main
request to GET on that origin. Its network scope allows that origin and Cloudflare
challenge resources. The Page uses the common observer and parent deadline.
When it reaches a usable GET after observed access progress or a body response,
Main stops the navigation at headers. A fresh signed URL and observed Referer
belong to that request. Within the same native operation, Main captures that
Page's selected partition context before it drains. If a warm response arrives
before the Page commits a Document, the original native request's still-current
Cookie selection applies once to that exact GET in the same Session. It stays
inside Main and expires with this continuation. The stream receives the actual
PDF bytes and settles its writer before the host can publish and associate them.
Repeated signed variants of the same endpoint and Service do not create more
verification Pages in that attempt. API-key requests, generic authorization
errors and form actions keep their own paths. Solver state cannot revoke a
completed transfer. Access classification remains
local to the current response. Independent sources continue under the original
parent deadline; cancellation, invalid task authority, unfinished resources and
actual file/database failure still stop the task. Missing credentials/native
capabilities are explicit skips rather than invented cancellation or file errors.
Shared origin/Session cooldowns retain Retry-After delta/date instructions and use
the actual supplied parent deadline, without an additional 30-second wait cap.
Python Provider recovery similarly uses its supplied parent deadline; the existing
90-second standalone-operation budget applies only when no parent is supplied.


Once `pipeline` returns normally, the completed writer result is retained. Its
network deadline is retired; late cancellation, Prepare revocation or page
changes cannot revoke that transfer. Python discovery recognizes the complete
result before its generic post-request check and stops the original network timer
before publication/association. Incomplete candidates still check cancellation
and deadlines before following another source or request.

## Native output and accepted cancellation risk

The R059 form selector can identify a download in the article navigation toolbar;
related, reference, supplementary and foreign-identity controls stay excluded.
The current form uses its original fields. Its observed POST→303→PDF path is
supported through original request/frame handoff. Destination checks and scoped
headers preserve that response; no action is copied or replayed. This remains
separate from ordinary R024 Session GET and Reader continuation.

`native_paper_body` uses a separate fixed action capability in Main/BrowserRuntime
and the isolated Document preload. It opens the Paper entry through access waiting
and reads PDF-only snapshot clues. Prepare and dispatch locate the current R059 form
from that candidate; they cache no DOM node or page
identity. Equivalent duplicate controls, hydration and same-frame history changes
do not deny the action. Multiple forms must also have equivalent successful
controls, compared only in the live renderer. A missing current link/form makes
that candidate unavailable. Native
forms retain their current successful controls and Session; POST bodies never leave
the page for reconstruction. The dispatch acknowledgement prepares Main before the
actual action and binds the exact navigation request, frame, owner and item. A named existing form target
is resolved to its unique native frame before dispatch. A matching name in
another Page is refused before action. An absent named target reserves child
capacity and accepts only a new iframe or popup with that exact native name;
an unrelated `_blank` popup cannot consume it.
Every new iframe destination must have the original Document as its native
navigation initiator; creating a child alone grants no download registration. An action-created iframe or
popup registers before its first PDF response; child pages use the same physical
quotas. The scoped attachment override changes only the qualified navigation's
headers and retains its response body. Read-only probes stay read-only, and
unrelated frame activity has no file authority. Registration has no independent
frame-count veto: earlier unrelated child frames cannot exclude a later proven
action target. Once a DownloadItem is bound, its transfer follows the actual item/request result;
subsequent source-page navigation or control removal cannot revoke it. New requests
cannot acquire the item by reusing a URL or frame name.

The unique Session listener synchronously sets the managed save path, reports
bounded progress and waits for actual DownloadItem terminal. Interrupted updates
defer cancellation out of Chromium's observer callback and retain the interrupted
reason; no resume or automatic action replay is added. Sources remain owned until
item terminal and actual page destruction, including no-item/late-item cleanup.
A remote interruption is a source failure only after those resources settle and
the owned private output is cleaned. An observed local output error takes
precedence, including when the item also reports interrupted. User cancellation,
parent expiry, stale task authority and unconfirmed resource close retain their
task boundaries; none is reclassified as a remote failure.
The item's deadline timer and abort listener retire at `done`. Actual final
`completed` outranks an earlier interrupted observation and late page/access/
deadline signals; the actual owned output must still be obtained. Progress is
optional: a terminal DTO can supply the first actual inode observation.
At actual item completion, the verified no-follow output descriptor supplies the
same single five-byte type observation. MIME and filenames are only hints;
non-HTML qualified navigation responses may become managed items regardless of
MIME. Fixed form destinations also retain HTML-mislabeled PDF bytes through the original item. Ordinary Reader HTML executes through Document access rather than this form capability. A non-PDF item is an owned
candidate failure and its temporary output is cleaned before another source.
In the current item implementation, only a normal completed PDF item with verified
actual output enters the common publication/SQLite path. The private success DTO
requires `native_complete`, `pdf_type`, `transfer_complete`, actual `output_file`
identity and `final_url`; it does not require a DownloadItem or a prior progress
event. Ordinary GET uses the existing `stream_complete` contract and writer close.
A filename, viewer display,
`will-download` or stream EOF alone cannot complete the Paper.

Native output reserves an exclusive `0700` directory at
`Documents/.downloads/<paper UUID>.<attempt>.<physical-output UUID>.native/` and initially leaves
`body.part` absent. Chromium does not promise to reuse a precreated stream inode;
Main observes its actual regular-file inode and Python independently checks it
before publication. Before any inode is adopted, a progress observation may see
Chromium's empty destination reservation already unlinked (`nlink=0`); it remains
pending and supplies no output proof. Final output and every observation after
adoption still require the same regular, singly linked inode. Each attempt has a
distinct path for each physical native candidate, so a cancelled item cannot later unlink a fallback candidate's output. Existing recorded temporary capabilities remain eligible only for exact owned cleanup. Directory/file replacement,
symlinks, unrelated links and unknown objects still cause application refusal;
final body publication remains no-clobber. Application cleanup never deliberately
unlinks an unproved replacement.

**Accepted limitation:** Electron 45 gives Chromium a pathname, not an output file
descriptor. If another process replaces this private temporary file or directory
during transfer, cancellation/interruption cleanup can delete the replacement,
even after Main detects the change and refuses it. Chromium's asynchronous
path-based deletion may run after `done(cancelled)`; that event confirms the item
terminal, not that every file-worker action is finished. Cancellation therefore
does not carry the stream writer's close guarantee. Unique attempt paths prevent
ordinary retries from reusing the old pathname, but cannot guarantee a manually
or externally installed replacement survives.

This measured race remains an accepted native-output limitation. It does not
grant arbitrary file access, weaken final publication or relax local
open/locate/Trash safeguards. No occurrence rate in ordinary use or general
website ability to delete arbitrary user files has been established. Keep other
programs from editing `.downloads` during an active transfer. Real `/dev/fd` sink
probes failed; fixed sleeps, extra downloads, permanently retained descriptors
and POST replay are not used as substitutes for a cleanup acknowledgement.

## Managed publication and final transaction

New bodies use `Documents/<paper UUID>.pdf`. Streams are staged on the same filesystem
at `Documents/.downloads/<paper UUID>.<attempt>.part`. Existing legal
`Documents/...` body paths remain usable without migration or renaming.
`ManagedBodyFiles` pins no-follow directory descriptors and, for streams,
exclusively creates the regular inode. Native output uses the observed inode
described above. Private output facts record Workspace/Documents/staging and
disposal directory identities plus that actual inode; a planned filename alone
grants no authority. Main verifies live directories and its opened descriptor
without truncating or following the final link.

Publication is atomic no-clobber link, never exists-then-replace or numbered
copies. The created permanent link is checked against this output and synced as
part of publication, with the original Workspace/Documents directory identity
confirmed at that file-operation boundary. Temporary-link removal and empty native-directory cleanup
are auxiliary: failure records a bounded diagnostic and does not revoke the
publication or prevent association. A residual temporary hard link does not make
the associated body invalid for Open/Locate. Removal moves the addressed entry without clobbering to the private
disposal directory, verifies it and unlinks only the proven object; a substituted
object is restored without overwrite. Directory/target replacement in these
application operations preserves unknown objects and fails the operation.
Chromium's separate cancellation cleanup has the accepted exception above.

After transport/writer settlement, `complete_attempt` publishes the output and
uses one short `complete_download` transaction for the body, successful provenance,
completed status and revision. Network and long file work occur outside SQLite
write transactions. The exact original Workspace/Paper/attempt and body write
ownership are checked at this transaction, without replaying network eligibility
or a second publication verification. The returned committed record establishes
success; no final reread, notification, diagnostic or owner-release write is
required. Duplicate terminal delivery is idempotent.
`complete_body` remains a logical repository fixture constructor and authorizes
neither physical opening nor deletion.

Reject winning the final transaction prevents old completion and permits only
its own unassociated output cleanup. Completion winning first protects the body
when Reject follows. Filesystem and SQLite have no shared transaction; local
publication/DB failure stops sources and removes only proven unassociated output.
There is no separate save/commit retry or orphan adoption.

## Local body operations and Trash

Local operations resolve the current association in the trusted application.
They use Workspace lifecycle/body generation and a captured live no-follow
directory/regular-file proof, never historical `download.output`, an arbitrary
renderer path or a filename-derived capability. Local reads need no metadata,
Prepare, network or collection gate. The host/Main ledger retains their actual
terminal work so Workspace maintenance, exit and Logs activity protection can
see them; no settings/SQLite lock spans native waiting.

Open uses the system default and handles a non-empty `shell.openPath` error.
Locate verifies the same file before `showItemInFolder`; it does not claim a
system completion result that API does not provide. Empty `openPath` error text
means `opened`; a normally issued Locate means `locate_requested`. Main and Python
do not recheck the file or Paper to decide whether that action happened. A later
HTTP projection failure returns the successful outcome plus a separate refresh
error, without inventing a revision or asking for another Open. Older successful
receipts retain only their outcome when a newer UI projection already won.
Confirmed absence clears
only the captured current association and advances body generation/revision.
Permission, unsafe path, missing default application and shell failures preserve
the association. Replaced directory/file, changed body or Workspace makes the
old operation stale before dispatch or a conditional missing/delete association
write; they do not undo a successful system call. No content validation, external search, viewer-lifetime
tracking or watcher is added.

Trash permits explicit independent physical PDF deletion after this Paper's
collection/body/native/local work and uncertain cleanup end. Busy state refuses
the destructive action until real settlement. Safe deletion removes only the
captured object and conditionally clears its association; metadata, UUID,
reliable identities and exclusion remain. A system failure does not clear a
valid association. If unlink succeeds and DB clearing fails, return failure;
the next explicit operation can confirm absence and clear idempotently. No
cross-resource atomic-delete promise or recovery queue is made.

Restore/unexclude is local and classification follows surviving content:
metadata without body is Candidate; a surviving body without metadata is
identity-only Downloaded; neither content leaves a hidden identity placeholder
for a later real Run hit. Historical `download.completed` is not current
availability and cannot permanently prevent an eligible new attempt.

## Projection, restart and evidence

Archive and ARRAY share Download/Cancel and local body actions. Admission
releases the page request lock; reader navigation, Reject and unrelated Run stay
available. Existing Workspace refresh continues through body queue/running/
progress/cleanup, not just collection. Classification changes only after the
body/completed transaction, with one UUID and synchronized counts. Workspace
epoch, Paper revision, response order and task/attempt/progress sequence reject
late updates; old progress cannot revive a spinner or deleted association.
Same-Paper selection, reader position, filters and editing drafts are retained
or the existing safe navigation exit applies.

Schema v5 adds only finite successful provenance. Exactly valid v4 and the
existing valid v3 entry path are validated and advanced transactionally without
changing identities, metadata, collection/body facts, paths or revisions; failed
DDL/version changes roll back. Old provenance stays unknown. Retired v1/v2,
unknown/corrupt libraries and Paper Markdown compatibility remain refused.
Older binaries reject v5; real upgrades require a stopped-application backup.

Startup normalizes interrupted old attempts without queue/network/action replay;
completed bodies remain. In the current lifetime, a failed terminal write retains
only the exact ended attempt token, outside active owners. Projection reports
storage failure without changing revision; the next explicit operation retries
that token's necessary terminal write. Persistent storage failure remains a
storage error. Successful increments survive; no new attempt or replacement
Workspace can be modified by the old token. There is no orphan scan, filename-based ownership recovery,
persistent replay queue or resume engine.

### Current evidence and follow-up

R024 ordinary GET uses the production Session pipeline, including real PDF with
HTML/XHTML MIME and no item. Controlled public Download fixtures verify one body
request for direct success, exact permanent bytes, reopened SQLite original
Paper/attempt association and actual resource release. Reader fixtures cover
signed final navigation outside its starting template, repeated actual Cookie
progress without a DOM link and no-progress fallback. Other ordinary URLs use the
same transport; this is not a claim of universal publisher compatibility.

The earlier strict-original-response Fetch limitation remains historical research
and can matter for genuinely one-time actions. It does not block ordinary GET
under the adopted Session strategy. Its explicit opt-in reproduction and original
evidence remain in the [response-capture investigation](pdf-response-capture.md).
No production Fetch capture, PDF buffering or runtime upgrade is added. Real
publisher/Reader timing, institutional and Zotero paired acceptance remain unrun.

Source failures do not stop independent candidates. P1–P5 remains lazy and stops
at the first actual PDF completion. OpenAlex preserves best-first deterministic
order across all qualified distinct locations. At the first refresh locator it
can request fresh results, then merges/deduplicates them with the remaining stable
cached URLs. Provider unavailability, failure, not-found and empty refresh results
cannot erase those URLs or require a successful API request before consumption.
IEEE/Springer/Elsevier records
are matched and deduplicated without whole-list count rejection. Current facts
still have a 64 KiB persistence/IPC byte capacity: qualified increments are retained
and overflow is partial, allowing a current source refresh instead of false
complete-empty data. Discovery's retained candidate/response state has a 1 MiB
memory budget and the original parent deadline; there is no separate operation,
hop or transfer-count expiry.

Reader/HTTP continuations use actual operation results, response observations and
Cookie progress to stop unchanged loops. This does not authorize a form/POST replay
or give unrelated frames/operations output authority. A signed URL is not
classified as a one-time action solely because it has signature parameters.

Completed transport/local actions survive late signals and auxiliary failures.
Actual unfinished I/O retains its original owner; a cancelled Future or returning
callback is not physical settlement. File publication and database association
remain necessary separate operations. There is no local completion phase,
additional business state, second deadline or automatic recovery queue.

Tests use isolated real host/SQLite/files, authenticated production bridge/Main,
temporary-profile Electron, controlled HTTP and shell adapters. Public stream,
public original-item composition and rendered reader evidence are distinct from
real-site and OS effects. Actual default-app/file-manager effects, real
publishers/institution sessions/proxies/CDNs and manual challenges require
separate acceptance and task-specific authorization. Source observations expose only phase/rule, fixed reason, related saved Service ID where applicable, origin, physical candidate-path
index and whether a later candidate was actually attempted. Reader/redirect continuation
and same-candidate retries retain the same index. The current registry
retains 64 recent observations; diagnostics retains 256 in-memory validated
observations for explicit recent export, without blocking the worker on diagnostic
file I/O. These extra observations expire on restart/Logs Reset; normal native
request records and the final SQLite reason/provenance keep their existing
lifetimes. No signed URL, HTML, request body or Cookie is exported. Latest PR CI and remaining
unverified effects are reported in the PR; neither old live samples nor a PDF
viewer display establish success of the current public path.
[PR #107](https://github.com/dylaaan-booob/allfold/pull/107) found Optica clues but
received Radware HTML for its candidates, without successful PDF-transfer evidence.
That historical access result does not establish the current site's behavior.

## Scoped manual acceptance

Use a disposable configuration and Workspace containing only test Papers. Start
from the reviewed PR version and a settled collection; reuse an available access
session where needed rather than retesting institution Login or Prepare itself.
Choose from these effects when a change needs evidence beyond isolated fixtures:

| Affected area | Minimal human check and expected result |
| --- | --- |
| Ordinary GET and original form | From a ScienceDirect test Paper, click **Download** once: direct PDF uses Session, while necessary Reader access may precede another GET. Add an accessible R059 Microbiology example for original-action behavior. The Paper appears once in Downloaded and its managed PDF opens. A viewer alone is not success. Record access denial separately from transfer failure. |
| Retained reusable publisher paths | Use one known IEEE reader example and one Oxford/Silverchair CDN example, because the unified source coordinator and shared Session hooks affect their routing. Both complete through public Download without a second body or new save step. Do not expand this to every publisher. |
| Service-scoped access and independent sources | With a disposable Paper whose Service is unprepared, download an ordinary accessible candidate. For an actually institution-bound Reader, use its correct prepared context, then invalidate that Service during unfinished access: only that access stops, cleanup ends, and an independent available source can succeed. Record the skipped Service reason even when the final download succeeds. |
| Cloudflare modal and ignored input | On an authorized sample with a visible blocking Cloudflare modal over readable content, confirm the common Page solver remains pending until the modal actually clears. A first ignored checkbox click may be tried again while the same unchecked control remains actionable; optional/hidden widgets do not start access handling. Offline fixtures establish mechanics, not live-site success rates. |
| Download interaction and cancellation | On one sufficiently slow test download, switch Papers and return, cancel that exact unfinished attempt, wait for actual settlement, then explicitly retry. Progress follows the right Paper and unrelated work continues. Cancellation before transfer completion creates no Downloaded body; a late cancellation after actual completion preserves it. Reuse this sample for completion/classification/Reader checks. |
| OS and independent body deletion | On a downloaded test Paper, use **打开 PDF** and **定位 PDF** to verify the default viewer and Finder select the same managed body. Move that test Paper to Trash, select **删除 PDF**, then Restore. Only that PDF/association is removed; metadata survives and the Paper is an eligible Candidate. Offline/zero-network, missing-file and permission behavior already have isolated coverage; no system network or permission changes are required. Do not clear unrelated real files or metadata. |

Path/object replacement races, frame/IPC forgery, page quotas, schema forward
changes, SQLite failures and maintenance interleavings belong to isolated
automated tests. Do not manually replace active temporary files to reproduce the
accepted deletion race. No blanket Login/CARSI, WoS Run, Zotero, Settings, Journal,
Cover, installer or all-workspace navigation acceptance is implied by a body change.

For separately authorized Allfold/Zotero paired acceptance, use the same DOI,
platform and access/authentication state, fresh disposable libraries and the exact
reviewed software versions. Record each application's observed source order,
actual PDF receipt, file placement/association, elapsed time, manual intervention
and failure point. Select ordinary OA, institutional full text, misleading MIME,
HTML Reader, repeated navigation, challenge and failed-source/later-success cases
where available. Run each application's ordinary UI once, then its local open/
locate/Trash equivalents; record a visible viewer without saved association as
incomplete. Use explicit retry only after actual cancellation cleanup. Live
publisher/CARSI/institution, user Zotero and default PDF applications require
separate task-specific consent. A blank paired result is pending acceptance;
isolated servers and upstream implementation statements are not paired live data.
