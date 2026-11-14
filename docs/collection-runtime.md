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

`BranchSpec(name, run=None, skip_reason=None, providers=(), service_id=...)`
uses unique bounded names. An omitted `service_id` inherits the admission's legacy
Service argument; explicit `None` declares independent API/public work. Declare
only the Providers a branch actually uses. A skipped branch has an explicit
applicability reason and no runner. An empty plan requires `no_applicable=True`.

A bounded parent scheduler owns Paper lifetimes. A separate bounded scheduler
runs leaf branches, so parents waiting for children cannot exhaust the children's
worker pool. Both retain Service fairness; only native operations consume the
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
expected_token=None, expected_attempt=None)` performs read-only qualification and
returns the current `PaperRecord`. It requires full unexcluded metadata, settled
failed/cancelled collection, no occupation, the complete original branch names
and currently available dependencies for pending branches only.

`registry.retry` accepts the same qualification arguments plus `deadline`. It
prechecks pending access outside write locks, then atomically rechecks the original
Paper token, attempt facts and host epochs before creating an attempt. Workers
verify the captured dependencies again. Completed/skipped branch facts and saved
increments survive; their historical Service/Provider conditions are not new
prerequisites. Public callers must require the exact Workspace/Paper/attempt and
CSRF before invoking this service. No retry path grants Download or body authority.
