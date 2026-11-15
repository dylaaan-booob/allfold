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
silently rebuild it. The current Run snapshot also checks configuration, cancellation and
Workspace/database identity. Whole-file configuration equality is a current
restriction scheduled for revision, not a permanent admission requirement.

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
Cancellation flags and a returning callback do not prove actual resource cleanup.
Current fault paths can also retain occupancy after terminal-record or auxiliary
cleanup failure; releasing already-finished work in those cases is a planned fix,
not a requirement to preserve indefinite occupancy.

Info's independent Preprint query still uses this scheduler and a per-Paper
reservation with its own bioRxiv/medRxiv clients, connection and cancellation.
It holds no foreground Run slot, and results do not change collection facts.
The entry and its runtime/tests remain active now, but this standalone query is
scheduled for retirement next. Necessary background Preprint evidence collection
remains supported. User behavior and evidence rules belong to
[Providers](providers.md#info-preprint-lookup).

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

`registry.check_retry` projects eligibility; `registry.retry` admits the explicit
attempt. Both accept the current Paper/attempt qualification, with `retry` also
receiving its deadline. Eligible work has full unexcluded metadata, a settled
failed/cancelled collection, no competing owner and available pending dependencies.
Completed/skipped branch facts and saved increments survive. Public requests keep
CSRF and exact Workspace/Paper/attempt association. Retry grants no body authority.

The production projection uses `host.peek()`; read-only queries cannot bind or
normalize a library that appeared later. Explicit retry may bind through `current()`.
The public route is `POST /api/papers/{paper_id}/collection/retry`; its current
request carries `revision` and the full captured token as well as the attempt.
Repeated full revision/token checks are a current limitation scheduled for
simplification alongside callers and behavior tests, not an invariant to retain.

The necessary API branch currently declares a Provider set at admission, even
though individual requests have narrower needs. Follow-up work will narrow those
dependencies and the propagation of local access failures. Current registration,
clients and tests remain in place. Successful independent increments must survive.

The public collection projection contains status, attempt, cleanup, branch states
and retry qualification. Raw failures, clients, lifecycle authority and private
PDF context are omitted. Actual resources still drain before conflicting work.

## Independent body and local-file work

`body` reservations own public Download on the same host, Paper gate
and bounded scheduler. A queued attempt is persisted before dispatch and remains
visible through lazy discovery, stream/writer, publication, completion and actual
cleanup. Repeated clicks return the original task/attempt/deadline; durable
collection intent and actual unsettled resources block a second writer. Read-only
`download` discovery and manual `legacy` Preprint retain their real consumers,
without nested admission. A Run match reuses the UUID/current facts without new
collection intent; no foreground Run slot or reader selection owns the body.

New-download qualification omits abstract generation but retains original
metadata/operation/body generations, observed attempt, reliable identity closure,
Workspace/lifecycle and actually used access dependencies. A conditional skip is
not a failed transfer or fallback. Qualified original-response entries use the
same body owner through Main and actual DownloadItem terminal, then common file/
SQLite completion. Inapplicable entries skip without inventing a transfer or
fallback; exhausted work ends finitely. The accepted native temporary-file
cancellation risk is documented in [body downloads](body-downloads.md).

Local file operations capture their own current body proof and host-visible
lifetime. Open/locate can coexist with collection and require no Service/Prepare;
they remain visible to maintenance without blocking first Run admission or an
eligible explicit Retry. Destructive or unconfirmed local cleanup blocks both,
including Retry's final admission check.
Destructive Trash PDF/metadata operations remain unavailable until actual Paper
work and cleanup end. Whole-Workspace maintenance stops admission, drains owned
work outside configuration/SQLite locks and preserves the bridge for actual
terminal responses. See [the complete contract](body-downloads.md).
