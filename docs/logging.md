# Local history and diagnostics

Allfold keeps two bounded local projections. **History** shows coordinator-confirmed
business tasks and results. Structured **diagnostics** explain the native and Python
operations behind those tasks. Neither store restores Workspace data or grants operation authority.

Discover, Login, Preprint lookup and Cover Search share explicit
workflow/task identities. Native requests have their own request IDs. Service and
page metadata come from the existing invocation snapshots and page associations;
logging does not grant browser or institution-credential authority. Native
completion can precede Python validation and guarded writes, so only the owning
coordinator finishes a business history record. Login includes each saved Service outcome. Retired Import/Enrich product kinds are no longer projected or accepted as new task results.

Recovery uses the same workflow, task and Native request IDs. Provider attempts
carry workflow and task IDs when available and retain their separate physical
request counts. Recovery events record the action, bounded attempt and wait
evidence, reviewed failure classification, and old and new Page IDs where
applicable. Numeric Chromium errors and HTTP statuses remain separate from
stable business codes. Retained page-load events remain readable.

History retains the recovery count and last outcome by action, with the first
and last reviewed evidence. The operation accumulates this summary in memory
and passes it through the final result. Log rotation or a failed event write
cannot remove the summary from a settled result. Manual Browser activity after
settlement cannot change that result.

## Metadata results

Explicit Preprint reports completion, no match, failure and cancellation per
Workspace/Paper/request in ARRAY Info. Collection reports its own persisted
attempt/branch state and runtime cleanup. Neither occupies the foreground Run
slot or changes a settled parent result.
Run results, statistics and links reference repository-returned Paper UUIDs.
Last Run remains an independent execution summary. Last Import and its Item/PDF/
Fallback, keys and attachment verification projection are retired.

No active Enrich task or event-date UI remains. Ordinary dates and separate
Preprint proof come from SQLite. Paper text, raw Provider responses, credentials
and sensitive URLs stay outside diagnostics. Existing log files are not migrated
or deleted by the cutover; retired business shapes are not revived as current UI.

WF07 keeps PDF discovery separate from successful transfer provenance. Local
diagnostics report bounded source/rule/failure categories, never current signed
URLs, Referer secrets, Cookie/Authorization, raw response bodies or DOM. Candidate
construction and a normal HTTP response do not create a successful `pdf_source`.
The PDF-only native action uses the same reviewed operation diagnostics and
actual settlement boundary; it adds no public Download history product. The
[discovery specification](pdf-source-discovery.md) defines stop/fallback semantics.

## Storage and limits

Electron initializes a diagnostics directory inside its standard application logs
directory and passes its absolute root and a new startup `runtime_id` to Python.
Each canonical configuration path has a SHA-256 scope. Its Python and Electron
writers own separate subdirectories under `scopes/<scope_id>/`. Standalone isolated
application fixtures use a supplied root or their own application-data directory.
Logs are independent of Workspace and the Journal/Service SQLite databases.

| Data | Maximum retained per configuration |
| --- | --- |
| User history | 200 records, at most 1 MiB |
| Python diagnostic events | Four JSONL files, at most 1 MiB each |
| Electron diagnostic events | Four JSONL files, at most 1 MiB each |
| Exported event data | 4 MiB, plus bounded history, metadata and README |

Rotation discards oldest files. History discards oldest records. Integrity metadata
reports rotation, omitted or invalid events, evicted history and recording failures.
These limits apply to each configuration separately; separately exported ZIP files
are user-owned and are not automatically removed. Directories use mode `0700` and
managed files `0600`. Writers reject unexpected ownership, links and replaced
targets, and do not retain an open event-file handle across Reset.

Recording failure leaves stderr available and marks evidence incomplete. It cannot
change a decided business result or replay a business action. Normal writes are local;
there is no automatic upload. Abrupt process or power loss can lose events that
were not written. An unfinished task from an earlier runtime is presented as
interrupted, never inferred successful.

## Event schema and privacy

The versioned, data-only [schema](../src/allfold/diagnostic_schema.json) defines the
allowed field names, types, enums and identifier formats. Producers validate
before persistence; the exporter independently validates stored records again.
Arbitrary strings are excluded rather than merely truncated.

| Field | Meaning |
| --- | --- |
| `schema_version`, `time`, `level`, `event`, `source` | Event format, UTC time, detail level, reviewed event name and emitting runtime |
| `runtime_id` | One application startup |
| `scope_id` | Opaque canonical configuration scope; no configuration path |
| `workflow_id`, `task_id`, `parent_task_id` | Explicit business grouping and parent/child identity |
| `request_id` | One native invocation, separate from its business task |
| `service_id`, `paper_id` | Reviewed saved identities, without names, DOI or content |
| `workspace_id`, `attempt`, `collection_status` | Captured Workspace UUID, bounded current attempt and collection state |
| `page_id`, `source_page_id`, `role`, `generation` | Descriptive page association and navigation generation |
| `stage`, `step`, `code`, `status`, `net_error` | Reviewed operation stage, stable failure code and bounded network evidence |
| `imperva_edet`, `imperva_incident_id` | Optional numeric code and support reference from a recognized Imperva response. The event's UTC time records when Allfold reported restricted access or began waiting for verification. |
| `outcome`, `parent`, `pdf` | Business/native result, parent-save evidence and separate PDF evidence |

Default diagnostics exclude credentials, Cookie/Authorization, request and response
bodies, full URLs, research content, DOM/HTML, screenshots, raw Console output,
raw exception objects and unreviewed stacks. Page destruction or reuse does not
remove already retained events. Associations are never reconstructed from time
proximity or a page's domain.

The saved Settings Log Level controls optional technical detail on application
startup; changes take effect after restarting. Settings also shows the active
level for the current startup. An explicit
`ALLFOLD_LOG_LEVEL` environment value overrides it for both runtimes. Necessary
task starts, final results, state transitions and failures remain recorded at all
levels; user history is independent of technical verbosity. Configuration changes
retain existing workflow-stop rules and do not migrate active Service mappings.

## Local export

History offers **导出本次诊断** for a retained task. Settings offers **导出最近诊断**
for problems without a selected task. Exports use recorded identities and retained
files, so the original page need not still exist. A task export collects its
explicit workflow across all retained dates and startups. Recent export collects
current-configuration evidence within the last seven UTC days, including several
startups when applicable. One captured export time defines the inclusive start
and end of that window for both history and events. History is selected by its
latest recorded start, finish or interrupted-task recovery time; events by their
recorded UTC time. Older and future-dated evidence is excluded from recent export.

The ZIP contains `manifest.json` (version, environment, scope, limits and integrity),
`summary.json` (recorded task relations, known results and uncertainty),
`events.jsonl` (validated events ordered by UTC time), and `README.md` (field
meanings, privacy and evidence limits). Summaries are deterministic and do not use
AI. The manifest's `collection_range` states the intentional recent-export window;
`time_range` states the actual included event range. `range_excluded_history` and
`range_excluded_events` count intentional range exclusions separately from
rotation, capacity omissions and writing failures that limit completeness. Task
exports do not apply the seven-day window. Missing or rotated evidence is disclosed; a confirmed parent remains separate
from PDF persistence. Export creates a local download only. Users decide whether
to share it, and Reset never deletes previously downloaded packages.

## Reset boundaries

Settings Reset selects **Workspace** or **Logs**, then previews and confirms that
one scope. Neither action requires typing `RESET`. Confirmations do not expire
with elapsed time. CSRF validation, one-use confirmation, current
configuration/target identity checks, path safety and active-work exclusion
remain enforced. A changed scope, target, configuration or managed log content,
a replacement preview, a consumed confirmation, or an application restart
requires a new preview. Waiting alone does not invalidate it. A partial deletion
is reported as partial and does not authorize a business retry.

- **Workspace** retains its existing deletion boundary, including SQLite, all exclusion identities, Documents and latest Run snapshots. Independent logs survive. Earlier history is marked as historical
  after a successful Reset or after the confirmed directory is verified as moved
  into deletion custody, even if later deletion fails. Such a partial Reset still
  reports failure and does not authorize a retry. Terminal task snapshots and
  retained coordinator snapshots are cleared only after full success. Refusals before
  that verified move do not advance history.
- **Logs** removes only the current configuration's verified managed history and
  diagnostic files. It coordinates the active native writer and rejects active
  tasks or unconfirmed writer ownership. Other configuration scopes, Workspace,
  settings, Journals/Services, browser sessions/Cookie and downloaded
  diagnostic packages are outside its deletion targets. New events can be recorded
  after a successful Reset. Coordinator activity and Run/browser dispatch exclusion
  are checked before taking the diagnostic writer lock; writer exclusion then
  remains held through validated deletion.

Offline tests cover isolated persistence, privacy, correlation, rotation and Reset.
They do not establish real Electron dialog/download behavior or CARSI, WoS,
publisher and actual-PDF acceptance; those require explicit manual validation.

Integrated Run retains one parent History/result and latest snapshot. Discovery
`provider_runs`/`run_sources` contain only selected PubMed, WoS and OpenAlex sources;
automatic helpers do not become extra Discovery sources. Separate allowlisted
`discovery_status` reports complete, empty, partial, failed or cancelled retrieval.
Run ends after necessary identities, base admission, full-plan registration and
foreground cleanup; it does not claim that Paper collection has completed.

Numeric Run statistics distinguish `integrated_candidates` (source hits),
`integrated_deduplicated` (final roots), `work_location_targets` (unique DOI queue
inputs), `identity_targets`, `identity_requests` (foreground physical identity
dispatches), `collection_admitted`, `collection_reused`,
`collection_registration_failed`, `excluded_papers`, `rebuilt_papers` and actual
Paper creates/matches. PMID outcomes separate verified matches, no match,
identity conflicts, failure and cancellation.
Background increments, first-public proof and failures belong to each Paper and
its bounded diagnostics, not a late rewrite of Run totals or finish time.
Cached evidence/per-Paper lookup projections do not increment physical requests.
Source created/existing counts overlap and must not be summed as global Paper
counts. No request URL, response body, API key, relation identifier or arbitrary
Provider error payload is added to persistent History diagnostics.

WF03 page checks add the fixed `page_probe_unconfirmed`,
`article_identity_unconfirmed` and `article_identity_conflict` codes. Probe limits,
missing evidence and identity conflicts remain distinct from HTTP/access failure.
Internal evidence values, HTML, scripts and URL query parameters are not diagnostic
fields. Imperva continues to emit only strictly validated `imperva_edet` and
`imperva_incident_id`; see [controlled Documents](browser-documents.md).


WF04 keeps configuration/User State revision fields as bounded correlation facts;
these whole-document revisions no longer by themselves revoke independent Browser
access. Workflow/task/request IDs remain captured operation identities. Exact
cancellation and access-context cleanup preserve unrelated owners and their
records. Authentication/preparation keys and native Page-close events are private
authority transport, not additional diagnostic export fields.

WF04 retains fixed `invalidate_access`/`release_workflow_pages` action names and
`page_capacity`/`page_capacity_changed` failure codes. `page_admission`/`child_page`
identify bounded capacity waits or refusals. Page-close reasons distinguish normal
task completion, retired attempts, context replacement/eviction/invalidation and
credential cleanup. Authentication/preparation keys, private headers and page
contents are never diagnostic fields. Closed-page history does not imply that a
live task or prepared context still owns that Page.

WF05 collection emits bounded `workflow_started`/`workflow_finished` events with
`kind` and `stage` equal to `collection`, captured workflow/task/Workspace/Paper
identity, attempt and durable collection state. It adds no task-history replay or
background management UI. Source Run identity does not imply cancellation
ownership. Runtime fault evidence keeps bounded phase/type information; raw
exceptions, Provider results and credential/Prepare keys stay outside diagnostics.
Logs Reset protects queued, API-only, writing and cleaning collection work even
when no native Browser owner exists.
