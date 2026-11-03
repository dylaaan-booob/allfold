# Local history and diagnostics

Allfold keeps two bounded local projections. **History** shows coordinator-confirmed
business tasks and results. Structured **diagnostics** explain the native and Python
operations behind those tasks. Neither store restores Workspace data, confirms a
Zotero save, nor authorizes an Import retry.

Run, CARSI Prepare, Kept/Batch Import, Enrich and Cover Search share explicit
workflow/task identities. Native requests have their own request IDs. Service and
page metadata come from the existing invocation snapshots and page associations;
logging does not grant browser or institution-credential authority. Native
completion can precede Python validation and guarded writes, so only the owning
coordinator finishes a business history record.

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
change a decided business result or replay a native save. Normal writes are local;
there is no automatic upload. Abrupt process or power loss can lose events that
were not written. An unfinished task from an earlier runtime is presented as
interrupted, or uncertain for Import/Kept, and never inferred successful.

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
| `page_id`, `source_page_id`, `role`, `generation` | Descriptive page association and navigation generation |
| `stage`, `step`, `code`, `status`, `net_error` | Reviewed operation stage, stable failure code and bounded network evidence |
| `outcome`, `parent`, `pdf` | Business/native result, parent-save evidence and separate PDF evidence |

Default diagnostics exclude credentials, Cookie/Authorization, request and response
bodies, full URLs, research content, DOM/HTML, screenshots, raw Console output,
raw exception objects and unreviewed stacks. Page destruction or reuse does not
remove already retained events. Associations are never reconstructed from time
proximity or a page's domain.

The saved Settings Log Level controls optional technical detail. An explicit
`ALLFOLD_LOG_LEVEL` environment value overrides it for both runtimes. Necessary
task starts, final results, state transitions and failures remain recorded at all
levels; user history is independent of technical verbosity. Configuration changes
retain existing workflow-stop rules and do not migrate active Service mappings.

## Local export

History offers **导出本次诊断** for a retained task. Settings offers **导出最近诊断**
for problems without a selected task. Exports use recorded identities and retained
files, so the original page need not still exist. A task export collects its
explicit workflow; recent export collects bounded retained evidence for the current
configuration, which can span several startups.

The ZIP contains `manifest.json` (version, environment, scope, limits and integrity),
`summary.json` (recorded task relations, known results and uncertainty),
`events.jsonl` (validated events ordered by UTC time), and `README.md` (field
meanings, privacy and evidence limits). Summaries are deterministic and do not use
AI. Missing or rotated evidence is disclosed; a confirmed parent remains separate
from PDF persistence. Export creates a local download only. Users decide whether
to share it, and Reset never deletes previously downloaded packages.

## Reset boundaries

Settings Reset selects **Workspace** or **Logs**, then previews and confirms that
one scope. Neither action requires typing `RESET`. CSRF validation, expiring
one-use confirmation, current configuration/target identity checks, path safety
and active-work exclusion remain enforced. A changed scope or target requires a
new preview. A partial deletion is reported as partial and does not authorize a
business retry.

- **Workspace** retains its existing deletion boundary, including its latest Run
  snapshots. Independent logs survive. History records from before a successful
  Workspace Reset are marked as historical and do not represent current results.
- **Logs** removes only the current configuration's verified managed history and
  diagnostic files. It coordinates the active native writer and rejects active
  tasks or unconfirmed writer ownership. Other configuration scopes, Workspace,
  settings, Journals/Services, Zotero, browser sessions/Cookie and downloaded
  diagnostic packages are outside its deletion targets. New events can be recorded
  after a successful Reset.

Offline tests cover isolated persistence, privacy, correlation, rotation and Reset.
They do not establish real Electron dialog/download behavior or CARSI, WoS,
publisher and Zotero/PDF acceptance; those require explicit manual validation.
