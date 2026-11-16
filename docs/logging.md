# Local history and diagnostics

Allfold keeps two bounded local projections. **History** shows coordinator-confirmed
business tasks and results. Structured **diagnostics** explain the native and Python
operations behind those tasks. Neither store restores Workspace data or grants operation authority.

Discover, Login and Cover Search share explicit
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

Standalone Preprint execution is retired. Its retained historical records remain
readable, filterable and exportable; no query is restored or resumed. Collection
reports its own persisted attempt/branch state and runtime cleanup without
occupying the foreground Run slot or changing a settled parent result.
Run results, statistics and links reference repository-returned Paper UUIDs.
Last Run remains an independent execution summary. Last Import and its Item/PDF/
Fallback, keys and attachment verification projection are retired.

No active Enrich task or event-date UI remains. Ordinary dates and separate
Preprint proof come from SQLite. Paper text, raw Provider responses, credentials
and sensitive URLs stay outside diagnostics. Existing log files remain untouched;
retired business shapes are not revived as current UI.

PDF discovery is separate from successful transfer provenance. Local
diagnostics report bounded source/rule/failure categories, never current signed
URLs, Referer secrets, Cookie/Authorization, raw response bodies or DOM. Candidate
construction and a normal HTTP response do not create a successful `pdf_source`.
The PDF-only native action uses the same reviewed operation diagnostics and
actual settlement boundary; it adds no public Download history product. The
[discovery specification](pdf-source-discovery.md) defines stop/fallback semantics.

`pdf_source_result` adds fixed source phase/rule/reason, origin-only location,
physical candidate-path index and known fallback outcome; Reader/redirect continuation retains its index. The current registry exposes
64 recent observations with whether a later physical candidate was attempted.
Diagnostics buffers 256 validated observations for explicit export, using a small
separate memory lock so file/export I/O cannot retain a Download worker. This
buffer expires on restart and Logs Reset; native request logs and the SQLite
terminal reason/provenance retain their normal lifetimes. No extra Download
business state or persistent attempt history is introduced.

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
Arbitrary strings are excluded rather than merely truncated. Retired Zotero/
attachment-save events and their dedicated fields are no longer accepted by
either producer or export validation; existing files remain untouched and
invalid records are counted. Current `article` page roles, native request IDs,
parent task relations and local-body `attachment` stage remain valid.

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
| `outcome` | Explicit business, native or transport result; native/transport completion does not establish a durable body association |

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
exports do not apply the seven-day window. Missing or rotated evidence is disclosed.
Native or transport completion remains separate from durable body completion in
the Paper library; filenames and response observations do not establish it.
Export creates a local download only. Users decide whether
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

Fixed binding/access probes retain `page_probe_unconfirmed` and native lifecycle
errors. Snapshot parsing reports bounded local metadata/PDF diagnostics and keeps
successful channels. Whole-page article reauthentication codes are retired;
HTTP/access failures still describe actual pre-read availability. The reading
contract is owned by [Document access](browser-documents.md).
Internal evidence values, HTML, scripts and URL query parameters are not diagnostic
fields. Imperva continues to emit only strictly validated `imperva_edet` and
`imperva_incident_id`; see [controlled Documents](browser-documents.md).


Configuration/User State revision fields are bounded correlation facts;
these whole-document revisions no longer by themselves revoke independent Browser
access. Workflow/task/request IDs remain captured operation identities. Exact
cancellation and access-context cleanup preserve unrelated owners and their
records. Authentication/preparation keys and native Page-close events are private
authority transport, not additional diagnostic export fields.

Native maintenance retains fixed `invalidate_access`/`release_workflow_pages` action names and
the `page_capacity` failure code. The retained `page_capacity_changed` diagnostic
value describes historical records; current limit updates preserve granted tickets.
`page_admission`/`child_page`
identify bounded capacity waits or refusals. Page-close reasons distinguish normal
task completion, retired attempts, context replacement/eviction/invalidation and
credential cleanup. Authentication/preparation keys, private headers and page
contents are never diagnostic fields. Closed-page history does not imply that a
live task or prepared context still owns that Page.

Collection emits bounded `workflow_started` admission events with
`kind` and `stage` equal to `collection`, captured workflow/task/Workspace/Paper
identity, attempt and durable queued state. SQLite is the collection terminal
record. The duplicate synchronous `workflow_finished` write is removed: even
after publishing a Future it could block the bounded worker via synchronous
completion callbacks. No asynchronous logging framework or diagnostic retry
queue replaces it. Existing historical terminal events remain readable.
It adds no task-history replay or
background management UI. Source Run identity does not imply cancellation
ownership. Runtime fault evidence keeps bounded phase/type information; raw
exceptions, Provider results and credential/Prepare keys stay outside diagnostics.
Logs Reset protects actual queued, API-only, writing and unsettled-resource work
even when no native Browser owner exists. Ended work with recorded faults is no
longer active merely to protect a final log write.


## Body state and local operations

`stream_paper_body`, `native_paper_body` and fixed `local_paper_body` use the common native/
Python operation ledger. `stream_complete` means PDF transport and closed writer;
only the later repository transaction means body completed/Downloaded. Local
open/locate/delete retain bounded outcomes and actual maintenance visibility,
without declaring a shell error to be missing or manufacturing file-manager
completion.

Main logs successful stream/native/Open/Locate outcomes according to their actual
result, even when an abort arrives later. Main sends that terminal result before
the synchronous final diagnostic write, so Python settlement does not wait for it.
Auxiliary native cleanup uses the bounded
`task_cleanup_failed` event and does not rewrite a successful outcome. The Python
bridge does not duplicate Paper native terminal logs or native-sink status writes
on the result receive path; initial native status and the existing diagnostic
file read remain available. Python records local missing/deletion/failure outcomes
after host lease release; successful Open/Locate already have Main's terminal.
Body/collection projections expose fixed
storage/file/cleanup explanations, never raw exception text or request contents.

Public download state exposes finite status, task/attempt, byte progress,
sequence, cleanup and successful source/fallback. Absolute roots, output proofs,
raw responses, secrets, signatures and exception stacks remain private. Durable
source URL remains origin-only; successful provenance is stored independently,
with unknown values for old bodies. Progress does not write every byte or create
a separate history product. Native transport completion reports the original
response and actual item terminal; only the common repository completion means
Downloaded. The documented native cancellation risk is not hidden by a successful
task result or a claim that `done(cancelled)` closes every file worker. Retired Translator/parent-item saving
enums and producer-less inference are removed; generic parent task ownership,
WoS and current body diagnostics remain. See [the complete contract](body-downloads.md).
