# Workspace collection runtime

`WorkspaceTaskHost.current()` binds one verified Workspace lifecycle. Its registry
owns collection attempts and discovery/body reservations independently of a
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
only the Providers a fixed branch actually uses. The necessary branch's supported
Provider choices describe discovery capabilities, not a fixed authority prerequisite.
A skipped branch has an explicit applicability reason and no runner. An empty
plan requires `no_applicable=True`.
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

Branches use `context.read_paper()`, `context.emit(delta, sequence=...)`,
`context.provider(name)` and captured `native_payload`/`execute_native`. Necessary
metadata discovers requests from preceding responses and captures each Provider's
single retained authority and credential at its first actual use. An unused
Provider change does not revoke that branch; a used Provider's subwork cannot
adopt replacement credentials. Provider failure or revocation stays within its
request group, while independent sources and saved evidence continue. Document
Service preparation remains independent. These operations retain the original
collection token. Each branch has its own exact native workflow/task identity. All native Futures and client closes must actually
settle before the parent can release Paper occupancy. A Paper native request's
terminal already follows Main's actual DownloadItem/page cleanup. Paper work does
not issue an additional `release_workflow_pages` request: that operation releases
WoS's cross-request retained-page loan, which Paper probes and transfers never create.
Cancellation flags and a returning callback do not prove actual resource cleanup.
A client close that has returned with an error or a failed auxiliary native
notification records its fault without retaining finished Paper work. Cancelled
native Futures and explicitly unconfirmed resources remain owned. Independent
cleanup continues even when another auxiliary step fails.

Once actual workers/resources end, owner and scheduler slots are released even if
a terminal database write fails. The public Future reports that storage error.
The registry keeps only the exact ended attempt token for the next explicit
operation on that Paper: it finishes unresolved branches using their original
sequence/token and calls the existing terminal transaction. It never scans the
Workspace, retries on a timer, renews authority or replays successful increments.
Continued storage failure fails the explicit operation; replacement Workspaces
and newer attempts are protected. Read projections can show this known failure
and permit an otherwise eligible Retry/Download without pretending the durable
write succeeded or changing revision.

Release performs no `touch_projection` transaction. Same-revision snapshots use
the existing response order. Collection's duplicate synchronous terminal log was
removed: it cannot occupy an executor thread through Future callbacks. SQLite
owns the collection terminal, while admission and native diagnostics retain their
captured identities; see [logging](logging.md).

## Reservations and maintenance

Read-only PDF discovery uses `download` reservations; public Download uses `body`.
Both exclude competing collection admission on that Paper. Repeated admission of
the same reservation kind reuses its current owner. A Run match during body work
returns the saved Paper without registering a new collection intent.

Reject and whole-Workspace maintenance revoke the complete original Paper task
and its exact reservation before signalling outside write locks. Service and fixed
Provider dependencies cancel and drain only matching unfinished branches. Necessary
API work instead checks each retained Provider epoch when that Provider's subwork
is next used; a changed Provider fails its request group without cancelling the
whole branch. Independent sources and completed work continue. A captured late
cancellation cannot target a later owner. Shutdown closes admission and drains parents, leaf branches and actual
reservations before shared factory closure. No standalone Preprint reservation,
deferred collection intent or scheduler readiness gate remains.

## Explicit retry

`registry.check_retry` projects eligibility; `registry.retry` admits the explicit
attempt. Both retain the caller's original Workspace/Paper UUIDs, failed attempt,
metadata generation and operation generation, with `retry` also receiving its
deadline. Eligible work has full unexcluded metadata, a settled failed/cancelled
collection, no competing owner and available pending dependencies.
Completed/skipped branch facts and saved increments survive. Public requests keep
CSRF and exact Workspace/Paper/attempt association. Retry grants no body authority.

The production projection uses `host.peek()`; read-only queries cannot bind or
normalize a library that appeared later. Explicit retry may bind through `current()`.
The public route is `POST /api/papers/{paper_id}/collection/retry`; its request
carries `workspace_id`, `attempt` and a token containing only `metadata_generation`
and `operation_generation`, alongside CSRF. Notes, abstract/body edits and Paper
projection revisions do not revoke admission. The existing Paper gate and short
SQLite admission transaction recheck the captured metadata/operation lifetime and
attempt before creating work; neither may replace caller authority with a current
token. Reject/Restore, metadata clear/rebuild, a superseded attempt, Workspace/database
replacement and actual unfinished resources still refuse Retry. Only pending
branches qualify access. Public failures distinguish stale/ineligible, access and
storage conditions without exposing raw exception text.

Each new attempt captures the current abstract/body field generations for its own
increments. Older attempts retain their old tokens and cannot write through a
Retry. A manual abstract edit or clear during the new attempt protects that field
while valid independent date/source increments can continue. Retry does not change
ordinary Download qualification.

The public collection projection contains status, attempt, cleanup, branch states
and retry qualification. Raw failures, clients, lifecycle authority and private
PDF context are omitted. Actual resources still drain before conflicting work.

## Independent body and local-file work

`body` reservations own public Download on the same host, Paper gate
and bounded scheduler. A queued attempt is persisted before dispatch and remains
visible through lazy discovery, stream/writer, publication, completion and actual
cleanup. Repeated clicks return the original task/attempt/deadline; durable
collection intent and actual unsettled resources block a second writer. Read-only
`download` discovery retains its separate consumers, without nested admission. A Run match reuses the UUID/current facts without new
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
eligible explicit Retry. Destructive work or genuinely unconfirmed native local work blocks both,
including Retry's final admission check.
Destructive Trash PDF/metadata operations remain unavailable until actual Paper
work and cleanup end. Whole-Workspace maintenance stops admission, drains owned
work outside configuration/SQLite locks and preserves the bridge for actual
terminal responses. See [the complete contract](body-downloads.md).
