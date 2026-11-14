# Workspace collection runtime

`WorkspaceTaskHost.current()` binds one verified Workspace lifecycle. Its registry
owns collection attempts and manual/download reservations independently of a
foreground Run. Source Run IDs are diagnostic labels and never cancellation owners.

## Foreground admission

After necessary direct-identity resolution, call `registry.admit` inside the
existing `commit_run_workspace(snapshot, cancel_event=...)` boundary:

```python
handle = registry.admit(
    direct_ids=direct_ids,
    additional_identities=additional_identities,
    metadata=metadata,
    branches=complete_plan,
    service_id=document_service_id,
    expected_token=initial_paper.token if initial_paper is not None else None,
    allow_rebuild=(initial_paper is not None and initial_paper.metadata is None
                   and not initial_paper.excluded),
    source_run_id=run_id,
    deadline=absolute_deadline,
)
```

`initial_paper` must come from the Run's captured initial identity index, before
retrieval. An old Run must never reread a current placeholder token to authorize
reconstruction. A placeholder rebuild requires both its original unchanged token
and explicit rebuild eligibility. A new identity can create a Paper without an
expected token; a new identity that now matches an existing placeholder cannot
silently rebuild it. The Run snapshot still verifies configuration, cancellation,
Workspace/database paths and UUID; registry admission does not replace that guard.

Admission stores base metadata, all reliable direct identities (including extra
values in one namespace), the complete branch plan and queued attempt in one short
transaction. The registry publishes its original owner under the same Paper gate.
It returns a `TaskHandle` for newly admitted or already active work, otherwise the
existing `PaperRecord`. Completed/failed/cancelled collections are reused without
automatic retry. Exclusion and conflicting identity ownership remain explicit.

Call `registry.register(handle)` after releasing the Run commit boundary, only
for a `TaskHandle`. `submit` combines both calls for callers that do not need the
separate boundary. Registration returns promptly; `handle.future` represents the
whole collection through actual cleanup and final durable settlement. Foreground
Run code must not wait for that Future. Failure to submit a worker records an
explicit failed/cancelled collection while preserving the base Paper.

No Service/credential/native initialization runs inside the admission transaction.
The host captures a pure in-memory epoch check for each original branch during
admission. Each branch later captures and verifies external access outside write
locks; it cannot borrow a new epoch after maintenance. A branch-specific capture
failure is failed work, never skipped/empty, and does not discard independent
branches or legal prior increments.

## Complete plans and independent branches

`BranchSpec(name, run=None, skip_reason=None, providers=(), service_id=..., mailto='')`
uses unique bounded names. An omitted `service_id` inherits the admission's legacy
Service argument; explicit `None` declares independent API/public work. Declare
only the Providers a branch actually uses. A skipped branch has an explicit
applicability reason and no runner. An empty plan requires `no_applicable=True`.
The production necessary branch captures saved `crossref_mailto` for its own
client scope; it does not borrow a Run client, cache or configuration guard.

A bounded parent scheduler owns Paper lifetimes. A separate bounded scheduler
runs leaf branches, so parents waiting for children cannot exhaust the children's
worker pool. Production admission groups each parent by its planned Document
Service; the necessary API leaf remains independently grouped under `None`.
Both retain Service fairness; only native operations consume the
shared Session's physical page quotas. Every branch constructs and closes its own
repository, `BranchContext`, clients and request cache in its execution thread.
SQLite's thread guard stays enabled. Application-owned pacing is shared; Run
snapshots, HTTP clients and mutable request caches are not inherited.

Branches use `context.read_paper()`, `context.emit(delta, sequence=...)`, declared
`context.provider(name)` and captured `native_payload`/`execute_native`. These
operations retain the original collection token. Each branch has its own exact
native workflow/task identity. All native Futures, client closes and captured
page releases must actually settle before the parent can release Paper occupancy.
Cleanup or terminal-write uncertainty records a fault and retains conservative
occupancy. Cancellation flags and a returning callback do not prove cleanup.

Public explicit Preprint queries use this same bounded Paper scheduler and an
independent reservation per Workspace/Paper/request. They declare only bioRxiv
and medRxiv, use the shared application factory and pacing, and open their own
client scope and SQLite connection in the worker. They do not hold a foreground
Run slot or a Run input snapshot. The exact reservation guards every request and
commit using its original Paper token; a local Abstract edit cannot invalidate
independent Preprint proof. Repeated clicks during activity/cleanup return that
same request; a new explicit query after settlement is allowed even when the
collection completed empty. Manual results never change collection facts.

Preprint status requires the current Workspace UUID and may select an exact
request ID. Unknown requests are Idle, and another Workspace is refused. Reader
navigation only changes presentation. Cancellation and Reject capture the exact
reservation, so a delayed old action cannot cancel a replacement. The reservation
Future settles only after the actual scheduled worker, client scope, repository
and Browser owner have closed; the host drains it for matching Provider epochs
or whole-Workspace maintenance. Ordinary Run input edits remain available.

## Manual reservations and maintenance

A first complete plan for a `not_started` Paper may wait behind its already
accepted `legacy` manual reservation. Queued facts and the original host-visible
owner block competitors. Repeated hits reuse that same intent. The exact manual
reservation's `guard()` and original write token remain valid; adding the intent
does not renew or revoke them. Actual release sets the scheduler readiness event.
An unready intent owns no worker/client/page, permits later ready work in its
Service group, and still expires/cancels normally. This is process-local intent;
startup only fails interrupted persistent work and never replays it.

Reject and whole-Workspace maintenance revoke the complete original Paper task
and any exact manual reservation before signalling outside write locks. Service
or Provider maintenance cancels and drains only matching unfinished branches;
independent branches continue. A captured late cancellation cannot target a later
owner. Shutdown closes admission, drains parents and leaf branches plus manual
reservations, then permits shared factory closure.

## Explicit retry

`registry.check_retry(paper_id, branches=complete_plan, service_id=None,
expected_token=None, expected_attempt=None, expected_revision=None)` performs read-only qualification and
returns the current `PaperRecord`. It requires full unexcluded metadata, settled
failed/cancelled collection, no occupation, the complete original branch names
and currently available dependencies for pending branches only.

`registry.retry` accepts the same qualification arguments plus `deadline`. It
prechecks pending access outside write locks, then atomically rechecks the original
Paper token, Paper revision, attempt facts and host epochs before creating an attempt. Workers
verify the captured dependencies again. Completed/skipped branch facts and saved
increments survive; their historical Service/Provider conditions are not new
prerequisites. Public callers must require the exact Workspace/Paper/attempt and
CSRF before invoking this service. No retry path grants Download or body authority.

The production `ProductionCollectionService.check_retry` uses the already bound
`host.peek()` lifecycle; read-only projections cannot bind or normalize a library
that appeared later. The explicit `retry` operation may bind through `current()`.
HTTP uses `POST /api/papers/{paper_id}/collection/retry` with CSRF, Workspace UUID,
exact attempt, Paper revision and the captured metadata/operation/abstract/body
generations. It constructs the original `WriteToken` from that request. Pending
access is checked outside Paper/SQLite write locks, and revision/attempt ownership
is rechecked before admission; a stale request cannot borrow newer generations.
The public `collection` projection contains status, attempt, cleanup, branch
name/status and the same read-only retry qualification. Raw failure messages,
clients, lifecycle authority and PDF discovery context are omitted.


## WF09 internal body service

WF09 adds distinct internal `body` reservations on the same host, Paper gate and bounded scheduler. They persist a queued download attempt before dispatch and remain visible through stream/writer/publication/commit/cleanup. Read-only `download` discovery and manual `legacy` Preprint retain their consumers. A Run match during body work returns the original Paper without new collection intent; no foreground Run slot owns the download. See [the complete contract](body-downloads.md).
