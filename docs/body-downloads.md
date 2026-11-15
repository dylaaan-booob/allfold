# Paper body downloads and local files

`BodyDownloadService` owns the public single-Paper Download/Cancel path. One
Workspace host reservation owns lazy P1–P5 discovery, the selected Session stream
or qualified original DownloadItem response,
file publication, the SQLite completion transaction and actual cleanup. There is
one current body per Paper and no separate save, receive or commit task.

WF09 merged in [PR #116](https://github.com/dylaaan-booob/allfold/pull/116) at
`029bc9a148170c699dbbe43f63885fc9718656e6`. This branch implements public Download,
qualified original responses and local-file work from
[WF10 #117](https://github.com/dylaaan-booob/allfold/issues/117). The accepted native
boundary below permits Chromium's measured cancellation limitation; it does not
claim that limitation is fixed. A fixed current-form or ScienceDirect action
retains its original method/body and Session. It never emulates POST or one-time
responses with a GET. Reusable URLs keep the existing Session stream consumer.

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
| Durable collection intent/queued/running work, manual Preprint, read-only discovery or unsettled cleanup | Refuse new body work until actual settlement. No-worker-in-memory is not an eligibility shortcut. |
| Failed/cancelled/interrupted download explicitly retried | First dispose only recorded, proven old output; then create a new attempt and run applicable sources from the start. Completed metadata is not recollected. |
| Excluded or metadata-free Paper without a body | Do not start a new download, restore content or prepare access. |

`body` reservations remain distinct from read-only discovery's `download` and
manual Preprint's `legacy` reservations. Production Download does not nest a
read-only reservation inside its body owner. A matching new Run reuses the UUID
and current facts without registering collection intent that revokes the body
attempt. Foreground Run cancellation and reader selection do not own the body.

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

`PdfDiscovery` owns source order, de-duplication, reader/redirect chains and the
remaining parent budget. P1 templates precede conditional P2 identifiers/APIs,
P3 Meta, current P4 entries and finally exact-target OpenAlex P5 candidates.
P1 success makes later queries/pages zero. Saved P3/P4 facts do not reorder it.
The complete [fixed catalogue and applicability](pdf-source-discovery.md) remain
unchanged. Conditional interfaces are skipped when their actual prerequisites
are absent; no publisher-key settings product or generic header capability is
added.

Python may perform bounded API/JSON/HTML discovery reads, but the selected
Chromium Session receives the first actual reusable PDF request. It does not
follow an HTTPX PDF GET/HEAD probe. PDF-only Document refresh retains existing
identity/access/solver, physical-page and cleanup checks and never recollects
completed Date/Abstract. Known IEEE reader, Oxford same-filename Silverchair CDN
and ScienceDirect same-PII response/reader rules keep their narrow qualifications.
Unknown pages are not a crawler, and login/identity/access refusals are not empty
branches. Only the fixed qualified native entries execute actions; inapplicable
entries are finite condition skips, not pending or successful transfers, and do
not manufacture `fallback_used`.

Only a normal PDF-type transfer permits completion. Ordinary candidate failures
may advance sources within the same remaining budget; cancellation, revocation,
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
pins applicable Prepare access and uses the unique `SharedSessionEvents.fetch`
with Chromium credentials. Cover omission and a default Session are not reused.

Stream targets require public URLs and public DNS preflight. Redirects stay
inside the captured origin. An actually observed Oxford `article-pdf` redirect
may continue only to matching `watermarkNN.silverchair.com/<same filename>.pdf`;
ScienceDirect permits only its observed same-PII
`pdf.sciencedirectassets.com/.../1-s2.0-<PII>/main.pdf` relationship. Each new CDN
request repeats target checks and uses destination-scoped Chromium cookies,
never forwarded source credentials. Other origin escapes, protocol downgrades
and filename/PII changes remain refused. Required Referer uses
`strict-origin-when-cross-origin`; private request markers leave no outbound
header. Explicit optional API secrets, when a trusted capability supplies them,
are constrained by fixed HTTPS Host/path/header contracts and redirects; the
renderer cannot configure them.

Main uses backpressured `pipeline`, flush and actual writer close. Its
`stream_complete` reports transport, not Downloaded. Progress is throttled and
projected as finite received/total bytes with task/attempt/sequence; zero or
absent total means unknown. File proofs, roots, signed URLs and exceptions stay
private. No Content-Length equality, minimum size, PDF header/EOF/structure/text/
identity/hash/version validation is added. Bounded current HTML/access responses
return to the same source coordinator after that output has settled.

## Native output and accepted cancellation risk

`native_paper_body` uses a separate fixed action capability in Main/BrowserRuntime
and the isolated Document preload. It opens and verifies the current article,
reads its live R059 form or R024 ScienceDirect entry, then registers before the
controlled action. A one-shot handoff binds the verified Document to the exact
original navigation request, frame, owner and item. An action-created iframe or
popup registers before its first PDF response; child pages use the same physical
quotas. The scoped attachment override changes only the qualified navigation's
headers and retains its response body. Read-only probes stay read-only, and
ordinary Document registrations still refuse unrelated navigation.

The unique Session listener synchronously sets the managed save path, reports
bounded progress and waits for actual DownloadItem terminal. Interrupted updates
defer cancellation out of Chromium's observer callback and retain the interrupted
reason; no resume or automatic action replay is added. Sources remain owned until
item terminal and actual page destruction, including no-item/late-item cleanup.
Only a normal completed PDF-type response with a verified actual output enters
the common publication/SQLite path. A filename, viewer display or `will-download`
event alone cannot complete the Paper.

Native output reserves an exclusive `0700` directory at
`Documents/.downloads/<paper UUID>.<attempt>.native/` and initially leaves
`body.part` absent. Chromium does not promise to reuse a precreated stream inode;
Main observes its actual regular-file inode and Python independently checks it
before publication. Each attempt has a distinct path. Directory/file replacement,
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

This measured race is an accepted WF10 risk. Once disclosed, it blocks neither
acceptance nor WF10 task completion; eliminating it is not a passing criterion. It
does not grant arbitrary file access, weaken final publication or relax local
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
copies. Removal moves the addressed entry without clobbering to the private
disposal directory, verifies it and unlinks only the proven object; a substituted
object is restored without overwrite. Directory/target replacement in these
application operations preserves unknown objects and fails the operation.
Chromium's separate cancellation cleanup has the accepted exception above.

After successful transport/writer settlement, `complete_attempt` checks original
authority, publishes the output, checks authority/final inode again, then uses
one short `complete_download` transaction for the body, successful provenance,
completed status and revision. Network and long file work occur outside SQLite
write transactions. Duplicate terminal delivery is idempotent.
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
system completion result that API does not provide. Confirmed absence clears
only the captured current association and advances body generation/revision.
Permission, unsafe path, missing default application and shell failures preserve
the association. Replaced directory/file, changed body or Workspace makes the
old operation stale. No content validation, external search, viewer-lifetime
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
completed bodies remain. Unconfirmed writer/native cleanup conservatively keeps
occupancy. Once resources are closed, a known scoped fragment deletion failure
can persist finite output facts while freeing idle capacity. Explicit retry
must settle those facts before another request. There is no orphan scan,
filename-based ownership recovery, persistent replay queue or resume engine.

Tests use isolated real host/SQLite/files, authenticated production bridge/Main,
temporary-profile Electron, controlled HTTP and shell adapters. Public stream,
public original-item composition and rendered reader evidence are distinct from
real-site and OS effects. Actual default-app/file-manager effects, real
publishers/institution sessions/proxies/CDNs and manual challenges require
separate acceptance and task-specific authorization. Latest PR CI and remaining
unverified effects are reported in the PR; neither old live samples nor a PDF
viewer display establish success of the current public path.

## Scoped manual acceptance

Use a disposable configuration and Workspace containing only test Papers. Start
from the reviewed PR version and a settled collection; reuse an available access
session where needed rather than retesting institution Login or Prepare itself.
These checks cover effects changed by WF10 that isolated fixtures cannot prove:

| Affected area | Minimal human check and expected result |
| --- | --- |
| Original publisher response | From a ScienceDirect test Paper that needs the original browser response, click **Download** once. If testing the form path, add one accessible R059 Microbiology example. The transfer completes from the original action, the Paper appears once in Downloaded and its PDF opens. A browser viewer alone is not success. Record access denial separately from a transfer failure. |
| Retained reusable publisher paths | Use one known IEEE reader example and one Oxford/Silverchair CDN example, because the unified source coordinator and shared Session hooks affect their routing. Both complete through public Download without a second body or new save step. Do not expand this to every publisher. |
| Download interaction and cancellation | On one sufficiently slow test download, switch Papers and return, cancel that exact attempt, wait for its displayed cleanup to end, then explicitly retry. Progress and terminal state follow the right Paper; unrelated work continues, cancellation creates no Downloaded body, and retry creates one body. Reuse this sample for completion/classification/Reader checks rather than a separate whole-UI pass. |
| OS and independent body deletion | On a downloaded test Paper, use **打开 PDF** and **定位 PDF** to verify the default viewer and Finder select the same managed body. Move that test Paper to Trash, select **删除 PDF**, then Restore. Only that PDF/association is removed; metadata survives and the Paper is an eligible Candidate. Offline/zero-network, missing-file and permission behavior already have isolated coverage; no system network or permission changes are required. Do not clear unrelated real files or metadata. |

Path/object replacement races, frame/IPC forgery, page quotas, schema forward
changes, SQLite failures and maintenance interleavings belong to isolated
automated tests. Do not manually replace active temporary files to reproduce the
accepted deletion race. No blanket Login/CARSI, WoS Run, Zotero, Settings, Journal,
Cover, installer or all-workspace navigation acceptance is required for WF10.
