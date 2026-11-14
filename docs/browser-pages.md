# Browser pages and physical capacity

BrowserRuntime owns one page ledger for the `allfold` Session. Execution ownership
and physical resource ownership are separate. Tab selection, hiding, a renderer
crash, task cancellation, removing an association and requesting close do not
return a physical slot. A slot returns once the WebContents is actually destroyed
and its tracked native download cleanup has finished, exactly once.

## Counts and admission

Python workflow admission distinguishes shared data use from exclusive controls.
Every data owner keeps its trusted saved-Service scope and explicitly requests
shared admission. Multiple Papers may use the same valid Prepare authority within
the task scheduler's global/Service limits. Login/Prepare, confirmation and captured
access cleanup exclude overlapping data owners through their real cleanup;
credential and Workspace/Logs Reset controls remain globally exclusive. Unrelated
Services can continue independently. Known physical Page claims remain exclusive,
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
| Access context | One Portal per configuration/authentication context and one prepared target per saved Service; these use the same managed limits | Replacement, exact-key invalidation, idle eviction, physical close or Session shutdown |
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
require the saved Service/preparation key, rather than adopting an arbitrary user
tab.

The page ledger jointly reserves global and scoped capacity **before** creating
WebContents. A queued task creates no page. Cancellation/deadline removes the
queued admission; failure before WebContents exists returns its unused reservation.
Failed adoption of an already created native WebContents retains the slot and task
cleanup until that contents is actually destroyed. Background
pages retain a nonzero viewport and do not select, present or focus Browser.

Prepare reserves three managed slots for its resource/search page, detail page
and possible Visit target. With global minimum 4 and Service minimum 3, one
retained CARSI Portal and this complete tree fit together. Login and Manual
Service entry reserve bounded popup headroom too. A synchronous popup handler
consumes a dedicated reservation; it denies an absent, expired or retired owner,
invalid source, or unavailable capacity. Child capacity is checked before Visit.
A denied popup has a finite failure result and never authorizes replaying an
unknown click or POST. An idle retained managed page has no execution authority
to open a new child. Explicit user popup creation uses the separate user limit.

Managed popups set `outlivesOpener: true`. This prevents closing a temporary Login
entry or Prepare detail page from destroying a successfully transferred Portal or
target. Every child that was not explicitly transferred still closes with its
captured task owner.

## Retention and authorization

Successful Login transfers only the actual CARSI Portal. Successful Prepare or
Manual Visit transfers only the actual target. Resource/search/detail/IdP pages
remain temporary. The Portal has explicit shared read-only pins while dependent
Prepare work uses it; a mutable target has one execution borrower. Replacing an
in-use context is refused. An idle old context closes before its replacement is
admitted, including repeated Prepare/Login at minimum capacity.

Idle contexts form a bounded cache within the same physical limits. Under page
pressure, unused targets are evicted before unused Portals; pinned prerequisites,
active borrowers and current WoS workflow loans are protected. Actual destruction
rechecks queued admission, so a newly idle target can make room for the next
Prepare tree. Multi-batch temporary work falls back to the retained access
contexts and explicit user pages, rather than growing with completed Papers.

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

Retained access validity uses scope and captured authentication/preparation keys.
Unrelated configuration/UserState revision changes do not invalidate it. Native
Prepare still checks its original Portal/frame and actual CARSI route. WoS retains
the stricter same-Query→Export snapshot and supported overlay checks. The
`invalidate_access` maintenance action matches **old captured keys**, so a late
cleanup cannot close a new-key context. Actual retained-page destruction sends
only its exact Page ID to Python; Login clears matching preparation state and
refuses a late result for an already closed page. Credential mutation remains an
exclusive control and waits for retained access cleanup before success returns.

## Configuration and effect timing

| `workflow` field | Default | Legal range | Meaning |
| --- | ---: | ---: | --- |
| `prepare_service_concurrency` | 5 | 1–5 | Prepare workers, separately constrained by physical capacity |
| `managed_page_global_limit` | 16 | 4–64 | All managed task and access-context pages together |
| `managed_page_service_limit` | 4 | 3–16 | Managed pages in one trusted Service/public bucket |

The authenticated bridge sends one initial limit pair with `ready`. Successful
Settings saves publish an explicit `page_limits` pair to Main's existing ledger;
business requests cannot create or raise their own limits. The visible Browser
pages controls use these names and ranges. Inactive PDF controls remain hidden.
Ordinary drafts, validation failures and Compare-and-Write conflicts retain their
existing behavior.

A limit update revokes unconsumed reservations. Existing physical pages are not
forcibly closed; while their occupied slots exceed a lowered limit, new admission
waits or fails within its parent deadline. It cannot use an old reservation to
create above the new limit. An operation must reacquire child capacity before a
new action when its old headroom was revoked. Normal idle cache eviction still
applies; active work is not force-closed to enforce a lower number.

## Native evidence and limits

`page-resources.test.cjs` runs fixed Electron 45.0.0 with a temporary profile,
local HTTP and a controlled CARSI HTTPS protocol. It proves actual business
Session WebContents counts at global 4/Service 3, real popup transfer surviving
opener destruction, six temporary batches returning to Portal/target baseline,
queued cancellation without creation, original slow-download source retention to
actual `done`, user limit 16, and final close to zero before Session disposal.
WF05 extends this fixture with two simultaneous same-Service Paper owners,
independent navigated work pages and a shared Portal pin at the same minimum
capacity. Actual cleanup destroys A's page while B remains live, then returns to
the retained baseline. This is native component evidence; production Run still
does not register collection.
It also calls production `prepareLoggedInService` using the same real Portal with
changed unrelated revisions/workflow and unchanged access keys; controlled resource
search terminates explicitly while preserving that Portal.

The slow source-retention case uses one same-Document `<a download>` original GET.
A separate regression records BrowserRuntime's current main-frame form POST
boundary: starting that navigation invalidates the captured WF03 navigation
generation, so strict current-Document validation refuses the item, cancels it to
actual terminal, writes no managed file and sends no replacement GET. This entry
is **not supported by production BrowserRuntime**. The independent
[shared Session fixture](browser-session.md) proves original POST and inline
response capability at its tested Session registration seam; it does not establish
that every BrowserRuntime entry meets Document authority.

`browser-runtime.test.cjs` additionally controls delayed `destroyed`, creation
failure, lowered limits, independent owners, exact old-key cleanup and workflow
loans. The Document/native preload, article identity, Cloudflare and WoS regression
fixtures remain. These isolated results do not establish real CARSI/WoS/account or
CAPTCHA compatibility. WF05 registry, background/cross-Run collection and WF09/10
PDF files/Download UI remain outside WF04.

Normal shutdown stops admission, drains current native operations/items and closes
owned pages before disposing the common Session entry. It does not replay work,
resume downloads or release a solver slot before its worker actually exits.

WF07 reuses these same physical quotas, prepared access pins and exact cleanup for
combined article metadata/PDF-clue reads and PDF-only refresh. Precollection reads
one article work page and follows no PDF candidate. A later qualified reader uses
its owning task and source chain, rather than a new unowned page or per-platform
network listener. Identifying a form/reader does not add main-frame POST or
one-time-response transfer support. See [Document contracts](browser-documents.md)
and the [complete discovery specification](pdf-source-discovery.md).
The fixed OCE access-capability mode opens no page. Its later reader uses the
same captured retained preparation, normal work-page quotas and exact cleanup;
it never bootstraps a second institutional Service from LWW authority.
