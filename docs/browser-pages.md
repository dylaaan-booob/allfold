# Browser pages and physical capacity

The public body service reuses these physical quotas for necessary reader and
solver pages. Pure Session streams and local open/locate/delete create no blank
WebContents. Qualified original DownloadItem body saving holds its source and
action-created child pages through actual item terminal and owned destruction.
The accepted [native cancellation limitation](body-downloads.md#native-output-and-accepted-cancellation-risk)
does not relax Document ownership or release page slots on a cancellation flag.

BrowserRuntime owns one page ledger for the `allfold` Session. Execution ownership
and physical resource ownership are separate. Tab selection, hiding, a renderer
crash, task cancellation, removing an association and requesting close do not
return a physical slot. A slot returns once the WebContents is actually destroyed
and its tracked native download cleanup has finished, exactly once.

## Counts and admission

Python workflow admission distinguishes shared data use from exclusive controls.
Every data owner keeps its trusted saved-Service scope and explicitly requests
shared admission. Multiple Papers may use the same saved Service within the
task scheduler's global and Service limits. Explicit Prepare and access cleanup
exclude overlapping data owners through their real cleanup. Credential
replacement reserves the school scope. Browser Session, Workspace and Logs
Reset reserve global Browser admission. Unrelated Services can continue during
scoped maintenance. Known physical Page claims remain exclusive,
even between different Services; native Page/Document navigation and workflow
loans retain their exact checks. Shared Service admission never grants concurrent
navigation of a single physical page.

Accepted maintenance can reserve affected admission before draining existing
owners. The reservation blocks replacement work without granting execution or
page authority; normal control admission still waits for captured users to settle.
Cancellation and joins occur outside configuration admission, and cleanup releases
only its captured reservation. Global reservations also protect Workspace/Logs
controls; scoped access replacement leaves unrelated Service users independent.

The task scheduler counts executing tasks, while this native ledger counts
physical WebContents and reservations. These are independent bounds. Shared
Python admission creates no pages or registry-private page pool, and never
removes the native limits below.

| Resource | Ownership and counting | End of use |
| --- | --- | --- |
| Task page | Work pages, helpers, popups, intermediate pages and retained download sources count against both managed limits | The captured task resource owner closes them on success, failure and cancellation |
| Access context | One retained target per saved Service; these use the same managed limits | Replacement, scoped invalidation, idle eviction, physical close or Session shutdown |
| User page | Explicit user creation has its own fixed limit of 16; a task cannot relabel its residue as user-owned | Explicit user close or shutdown |
| Manual wait | Keeps the original task/access resource owner and its existing slots | The original parent deadline/cancellation and cleanup still apply |

The managed global count includes **task and access-context pages together**.
The Service bucket is the trusted configuration scope plus saved Service ID; a
CDN or redirect does not change it. A task without a Service uses that scope's
`public` bucket, or the Session public bucket when no scope exists. Public pages
also use the Service-sized bound and global bound. Display names and presentation
associations do not assign or change a budget.

At the default limits there can be at most 16 managed Browser WebContents plus
16 explicit user pages. The main application UI is outside the business Browser
Session. Frames and the Document preload do not create additional page entries.
Borrowing or transferring one WebContents never creates a second count. Borrowed
user pages keep user resource ownership; current production prepared access paths
use the saved Service identity and the native resource owner.

The page ledger jointly reserves global and scoped capacity **before** creating
WebContents. A queued task creates no page. Cancellation/deadline removes the
queued admission; failure before WebContents exists returns its unused reservation.
Failed adoption of an already created native WebContents retains the slot and task
cleanup until that contents is actually destroyed. Background
pages retain a nonzero viewport and do not select, present or focus Browser.

Prepare reserves capacity for its entry and possible native popups. Portal flows
also use their own detail page. Resource acquisition finishes before entry jitter.
A Portal popup that has reached the resource catalog releases its temporary
authentication opener before allocating the detail and Visit pages.
A synchronous popup handler consumes a dedicated reservation and validates the
opener and current operation. Child capacity is checked before Visit.
A denied popup has a finite failure result and never authorizes replaying an
unknown click or POST. An idle retained managed page has no execution authority
to open a new child. Explicit user popup creation uses the separate user limit.

Managed popups set `outlivesOpener: true`. This prevents closing a temporary Login
entry or Prepare detail page from destroying a successfully transferred target. Every child that was not explicitly transferred still closes with its
captured task owner.

## Retention and authorization

Successful Prepare and Manual Visit may retain the actual Service target. Search,
detail and IdP pages close at settlement. Service targets that a business step
needs can be borrowed or pinned for that step. Regular readers and reusable
streams use the Session independently of retained tabs.

Idle targets form a bounded cache in the physical page ledger. The ledger can
evict the least recently used eligible target to admit work. Actual destruction
releases its slot. An active borrower, an EBSCO record context in use and a WoS
results loan keep their required pages until settlement.

Internal article pages are reused only inside the active operation. They close
on every terminal outcome; no completed-Paper cache remains. Eligible recovery
waits for the old attempt's actual destruction before creating a replacement.

WoS Query pins the exact native results Document under its captured workflow/task
identity across the gaps between native Query and Export operations. Python's
WoS `finally` waits for native results/items to settle, then sends
`release_workflow_pages` with that same identity. Release is idempotent and does
not affect a newer workflow. It removes the workflow loan while leaving a valid
prepared access context available for ordinary reuse or bounded eviction.
An export action that ends without receiving an item instead invalidates and
closes its retained source at operation cleanup. No timer can make that ambiguous
source reusable; its owner-free late-item guard leaves only on actual destruction.

The native access context is indexed by configuration scope and Service UUID.
The actual Page ID is sent to Python when a retained page closes. This releases
the displayed handle and preserves the Service's last observed Prepare result.
WoS Query can open a fresh query page after the previously visited Manual target
is evicted. The workflow still requires an explicit Manual Visit before admission.
WoS Export validates its exact workflow results Document and supported overlay.
Before a native export is issued, a recognized authentication block can restore
the same results route. The workflow checks the original result count, loans the
new Document and uses its current Page ID in later batches.
A scoped Service edit drains affected uses before `invalidate_access` can close
that Service's target.

## Configuration and effect timing

| `workflow` field | Default | Legal range | Meaning |
| --- | ---: | ---: | --- |
| `managed_page_global_limit` | 16 | 4–64 | All managed task and access-context pages together |
| `managed_page_service_limit` | 4 | 3–16 | Managed pages in one trusted Service/public bucket |

The authenticated bridge sends one initial limit pair with `ready`. Successful
Settings saves publish an explicit `page_limits` pair to Main's existing ledger
only when either managed page limit actually changes;
business requests cannot create or raise their own limits. The visible Browser
pages controls use these names and ranges. Inactive PDF controls remain hidden.
Ordinary drafts, validation failures and Compare-and-Write conflicts retain their
existing behavior.

Saving the same pair is a no-op. An increase wakes eligible queued admissions.
A decrease preserves existing physical pages and all already-granted unconsumed
tickets, including a popup ticket split before or after the update. Those tickets
remain with their original owners through consumption, cancellation, owner exit
or Session close. Usage may temporarily exceed a lowered limit; only new ticket
requests must fit the effective global and Service caps. Queue deadlines, owner
validation and cancellation still apply, and every created page consumes a real
grant.

## Native evidence and limits

`page-resources.test.cjs` runs fixed Electron 45.0.0 with a temporary profile,
local HTTP and a controlled CARSI HTTPS protocol. It verifies native capacity and popup transfer, queued cancellation, live limit
decreases, original-download source retention through actual `done`, user-page
bounds and cleanup to zero. The fixture also exercises a Portal search with no
matching product and simultaneous Paper pages scoped to the same Service.


The slow source-retention case uses one same-Document `<a download>` original GET.
A separate regression records BrowserRuntime's current main-frame form POST
boundary: starting that navigation invalidates the captured navigation
generation, so strict current-Document validation refuses the item, cancels it to
actual terminal, writes no managed file and sends no replacement GET. This entry
remains refused by that ordinary Document registration. The separate fixed
body-action handoff supports only its qualified request/frame chain. The independent
[shared Session fixture](browser-session.md) proves original POST and inline
response capability at its tested Session registration seam; it does not establish
that every BrowserRuntime entry meets Document authority.

`browser-runtime.test.cjs` additionally controls delayed `destroyed`, creation
failure, lowered limits, independent owners, exact old-key cleanup and workflow
loans. The Document/native preload, article identity, Cloudflare and WoS regression
fixtures remain. These isolated results do not establish real CARSI/WoS/account or
CAPTCHA compatibility. Registry, background collection and body files/UI have separate composition
fixtures; these page tests alone do not establish those results.

Normal shutdown stops admission, drains current native operations/items and closes
owned pages before disposing the common Session entry. It does not replay work,
resume downloads or release a solver slot before its worker actually exits.

PDF discovery reuses these same physical quotas, prepared access pins and exact cleanup for
combined article metadata/PDF-clue reads and PDF-only refresh. Precollection reads
one article work page and follows no PDF candidate. A later qualified reader uses
its owning task and source chain, rather than a new unowned page or per-platform
network listener. Identifying a form/reader does not add main-frame POST or
one-time-response transfer support. See [Document contracts](browser-documents.md)
and the [complete discovery specification](pdf-source-discovery.md).
The fixed OCE access-capability mode opens no page. Its later reader uses the
same captured retained preparation, normal work-page quotas and exact cleanup;
it never bootstraps a second institutional Service from LWW authority.

Run, collection branches and internal read-only discovery
share one Workspace occupation boundary. Only tasks that actually dispatch native
operations acquire work pages. API-only work creates no page; scheduler capacity
does not replace the physical ledger. New Runs reuse
valid retained Prepare contexts without replacing active Paper resources. Branch
native identities and exact cleanup remain independent of the source Run and of
the currently selected Browser/Reader page.


## Body service

Pure Session streams reserve no blank WebContents. Reader and challenge
continuations retain their physical page and Solver limits. A recognized
institutional block can recover the saved Service before one retry of a
reusable GET. A completed transfer retains its original Paper and output. See [the complete contract](body-downloads.md).
