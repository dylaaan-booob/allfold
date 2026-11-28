# Architecture

Allfold is one desktop product: an Electron host, a Python application and a Web UI. Electron owns startup and shutdown; Python is not an independently supported Web service.

## Runtime data flow

```mermaid
flowchart LR
    UI[Web UI] -->|local HTTP| WEB[FastAPI adapters]
    WEB --> APP[Python application workflows]
    APP -->|BrowserGateway| BRIDGE[ElectronBridge]
    BRIDGE <-->|authenticated WebSocket| MAIN[Electron Main]
    UI -->|restricted Preload| MAIN
    MAIN --> BROWSER[Native browser and Session]
    APP --> DATA[SQLite Paper library and configuration]
    APP --> PROVIDERS[Provider adapters]
```

Main starts one Python process. The HTTP origin remains loopback-only on port 18767; one authenticated WebSocket carries native operations, progress and Solver submessages. Remote pages have no Node or host IPC capabilities.

## Ownership

| Source | Responsibility |
| --- | --- |
| `frontend/ui/` | Workspace, Workflows, Journals and Settings UI, source assets and notices |
| `src/allfold/application/` | Use cases, guarded operations and process-local workflow coordination |
| `src/allfold/providers/` | Provider retrieval, queries and source-specific formats |
| `src/allfold/persistence/` | Production SQLite Paper library and projections, safe file operations, Registry and local state |
| `src/allfold/integrations/` | Credential and Pydoll adapters |
| `src/allfold/web/` | HTTP projection, validation, composition and Electron WebSocket transport |
| `src/allfold/http_client.py` | Shared synchronous Python HTTP client, proxy parsing, bypass rules and per-request transport routing; independent of Chromium Session |
| `electron/src/main.cjs` | Application lifecycle, trusted IPC and native dispatch |
| `electron/src/browser/` | Native pages, main-window presentation, document identity, navigation and shared Session |
| `electron/src/auth/` | Task-scoped institution authentication and credentials |
| `electron/src/workflows/` | Login, Service preparation, Covers and WoS native page operations |
| `electron/src/preload/`, `native-ui/` | Restricted capabilities and local native-window UI |

Models, configuration definitions, identifiers and query primitives remain shared Python modules. Application code does not depend on Web adapters; its BrowserGateway exposes connected/execute and exact cancel_workflow/cancel_task interfaces. ElectronBridge adapts it to transport. Each Request ID owns its operation context, progress, cancellation, page claims and terminal result. BrowserTaskLock admits explicit shared saved-Service data use while keeping overlapping controls and exact physical Page claims exclusive. Login, Covers and WoS each retain one active coordinator state; Browser admission is separate from the Workspace collection registry. Native operations settle before their Futures release ownership. WoS keeps its captured workflow/task loan across Query→Export gaps; a finally-issued release_workflow_pages maintenance request releases that same loan only after native settlement, including cancellation and input loss. Shutdown stops admission and drains Run, WoS, Login, Covers and the Workspace host before closing common client resources.

Journal lookup and remote fallback belong to the application layer; persistence only reads the local Registry. WoS export parsing continues to reuse safe file-reading helpers.

Paper native requests release their temporary pages/items before Main sends the
terminal DTO. Their Python owners await that actual terminal and do not send a
second workflow-loan release; only WoS retains a loan across requests. Main sends
Paper results before final diagnostic I/O, and Python does not duplicate those
terminal logs on its receive loop.

FastAPI composes these implementations. Workspace UUIDs and captured Paper eligibility belong to the application; HTTP accepts UUIDs and Workspace identity rather than arbitrary paths. Provider normalization uses shared identifiers rather than application workflow helpers.

## Browser Service associations

Python snapshots saved Journals and Access Services for each invocation. The bridge
carries canonical configuration scope, configuration revision and User State
revision alongside the saved Service ID. ISSN/eISSN matching assigns complete
Papers to Journals and Services; source names do not confer membership. These
snapshots are descriptive, not a second mapping authority. Prepare verifies the
captured institution, credential epoch and selected saved Service records; unrelated
configuration/User State revisions do not renew or revoke that authority. WoS
retains its stricter foreground Run input snapshot and Query→Export binding.

Login starts the first selected available CARSI Service and waits for its final
result. Its saved UUID anchors preparation and business access. Each Service
prepares through the selected WAYFless URL from SQLite or its own CARSI Portal
flow. Portal search, detail and Visit establish the local target. Both entry
paths use the shared page readiness checks. Manual Visit is explicit.

Main applies a short shared delay immediately before new Service entry
navigation, after page admission and cooldown. Once the first Service is ready,
successive entries use uniform 0–1 second gaps and may remain active together.
BrowserRuntime coalesces in-progress recovery by Service and resumes the affected
business step within its parent deadline. Query and Export retain the actual
results Document and native download ownership across the WoS workflow.

Browser Runtime reopens one stable disk-backed business Session on launch.
[Session storage and ownership](browser-session.md)

PDF discovery separates qualified rules, exact-target source facts and a
result-driven P1–P5 coordinator. Run and necessary API responses project reusable
OpenAlex/Crossref facts before bibliography normalization; the existing increment
path persists them in SQLite. Collection reads page clues without following PDF
candidates. PDF-only refresh lets Download reuse the coordinator without reopening
completed metadata collection. [Source rules](pdf-source-discovery.md) own platform
applicability and research evidence; [body downloads](body-downloads.md) owns public
Session/original-response transfer, files, local operations and the accepted native
cancellation limit. Download binds Service access only on the operation that
actually uses that context; its parent retains Workspace/Paper/attempt authority
while independent candidates use the normal Session.

[One Session event owner](browser-session.md) composes native hooks for Browser,
identity, Covers, WoS and body transfer. Request association, shared cooldown and
actual item settlement belong there; physical page admission/retention belongs to
[Browser pages](browser-pages.md). Rules do not install independent native listeners.

Keep/Import/Enrich have no product HTTP/IPC or native dispatch path. Zotero Local
API, attachment writes and full Translator assembly are retired. Setup no longer
fetches translation-only sources; ignored vendor checkouts stay untouched and
retained adaptations keep their [third-party notices](third-party.md).

## History and diagnostics

Python coordinators publish bounded business history independently of their
Workspace result snapshots. The unified Run exposes selected-source counts, statistics, issues and retrieval observations through `RunFacts`; its Integrated snapshot uses v6. Old Integrated v4/v5 reads return unsupported and require a new Run, without migration or Reset. Legacy WoS snapshots remain untouched and are not reconstructed into unified results. Electron and Python write separately owned, rotating
JSONL under a common configuration scope and startup runtime ID. Explicit workflow,
task and request identities link native observations with coordinator-confirmed
results. Page association snapshots are descriptive evidence, never browser or
credential authority. A versioned data-only schema validates producer events and
independently filters exports; neither arbitrary log messages nor raw exceptions
enter this store.

The Web adapter exposes recent history, local diagnostic ZIP export and guarded
Logs Reset. Reset coordinates the native writer, preserves existing Workspace
safety checks and marks surviving history when Workspace is reset. See
[logging](logging.md) for storage limits, field meanings and evidence boundaries.

`bindTaskPage` and explicit `navigate(..., {tab})` control task targets. `select` presents a page in the main-window Browser pane; task navigation and WoS handoff do not select tabs. Background creation does not select even the first page, open Browser or focus a webpage. Task pages remain available for explicit manual login or inspection until their owner finishes; only explicit bounded access contexts survive completion. Service associations confer no document, task or institution-credential authority. Page/frame identity, task signals, navigation recovery and native-save settlement remain separate checks.

## Configuration editing

One configuration controller owns the saved revisions and ordinary drafts across
Workflows, Journals and Settings. A shared scheduler serializes safe field patches;
responses acknowledge the submitted snapshot without replacing later edits.
Server-side admission coordinates writes with task starts, retaining the existing
Compare-and-Write and Workspace lock protections. Active tasks continue using
their captured inputs. Foreground Run/WoS snapshot writers currently keep ordinary
edits Pending until settlement; independent Browser owners allow unrelated input,
Journal and Service edits. A change overlapping an executing Service waits for its
owner to settle. Saved Service edits close affected idle targets under scoped
admission. A school change revokes active authentication before the configuration
write. Product parameters apply when the next entry is constructed. Actual
retained-Page destruction releases the matching Python handle.
A new task requires successful
save and validation; a failed or conflicting draft cannot become task authority.
Provider secrets, CARSI credentials and high-impact operations use explicit
submission rather than ordinary autosave. CARSI mutations settle through the
authenticated native bridge and compare encrypted-store revisions. Credential
controls reserve the school scope through native settlement. The bridge wait
runs outside the configuration write lock. Covers commits under the short
configuration/asset guards and compares its target Journal, asset-tree identity and
exact target cover record/image, preserving unrelated edits while refusing replaced
Journal or cover assets.

## Workbench and task presentation

The main Window contains Chrome, a flexible Workbench Content region and Status.
Its business workspaces are Workspace, Workflows, Journals and Settings.
Workflows keeps Login and Discover under one navigation entry.
Browser, Search and History are shared header tools. Quick Open reads the current
local Paper, Journal, saved Service and native tab projections, dispatching each
selection to its owning controller. A `>` prefix searches the command registry.
Browser fills Workbench Content while the business surface retains its state.
The address toolbar and left navigation rail occupy trusted DOM space outside
the native webpage rectangle.

ARRAY, Workflows, Journals and Settings share a presentation-only Navigation Rail,
overlay Index/Directory flyout, Content and Functional Sidebar/Tool Rail. Their
mounted hosts retain expansion and compute docked/overlay geometry from actual
container bounds; targets and measured widths stay separate. Business Controllers
own selection, drafts and shared Reader lifecycle. See [workspace layout](workspace-layout.md)
for size constraints, preference behavior and acceptance boundaries.

BrowserRuntime owns physical pages, task associations and their shared Session. Browser Presentation owns attaching, showing, hiding, sizing and explicitly focusing a selected WebContentsView on the main window. The trusted renderer reports its measured webpage body in CSS pixels through a restricted, sequenced IPC. Main converts with the host's actual Zoom Factor to Electron logical pixels, independently of display DPR, and validates sender, main frame, command, Page ID and rectangle against the host content bounds. Hiding Browser or suspending it for a trusted dialog does not destroy pages or cancel operations. Fullscreen task surfaces can be suspended for explicit Browser interaction and resumed without restarting their player or changing task state.

One Tabs flyout groups Page IDs under CARSI, a scoped saved Service, or Other.
A Service group is keyed by scope ID and saved Service ID; saved names supply
labels. Unassigned and shared pages use explicit roles and recorded provenance.
The directory uses the shared layout controller for flyout size, focus and scroll.
Grouping grants no task, document or authentication authority.

Archive availability and fullscreen task presentation are local UI preferences, outside YAML Save and business SQLite. Archive defaults disabled while its existing resources and layout preference remain available. Legacy Paper links resolve against the current ARRAY Candidate/Downloaded/Trash projection or report a missing Paper. Login and Discover keep their existing coordinators. Discover captures its display preference at start. Login retains their progress and controls in Workflows independently of Browser visibility.

## Resources and third-party code

The UI build copies sources into Python's ignored static delivery tree. Served UI URLs and API endpoints do not depend on the editable source directory.

Electron package metadata and scripts remain at the package root. `src/shared/paths.cjs` resolves project, native UI, Preload and native UI locations. Existing official vendor checkouts stay pristine in ignored directories. They are
not setup/build inputs after translation-only Runtime retirement. See
[third-party sources](third-party.md).

## Data ownership

Local YAML owns monitor settings. The private `.allfold/user-data.sqlite` owns Journals, Groups, Labels, direct Access Services and default Service assignments, isolated by the canonical configuration path. Existing valid `list.md` files seed each configuration once; subsequent Markdown edits do not change saved user state. Migration validates the complete managed data, records its source and digest, and leaves the original file intact. The production [SQLite Paper library](paper-library.md) owns stable UUID/direct
identities, explicit primary identity, metadata, exclusions and one optional body
association at `Workspace/papers.sqlite`. HTTP handlers and workers open separate
thread-confined connections. Read-only uninitialized views create nothing; Run
performs explicit initialization. Paper storage supports only its current schema; corruption and
unknown schemas fail without replacement. Current-attempt, branch and body-output facts are bounded. Schema v5 transactionally advances exactly valid v4 and the supported v3 entry path, preserving current content and unknown historical body provenance; retired/unknown formats and Markdown shadow/fallback remain refused.

Workspace UI uses separate library revisions for response order. WriteToken
remains captured asynchronous eligibility, with separate abstract generation.
Reject persists exclusion before exact-Paper cancellation outside write locks;
restoration cannot revive old work. Clearing metadata waits for actual cleanup.
See [identity](paper-identity.md) and [Workspace runtime](collection-runtime.md).

The private `.allfold/resources.sqlite` shares complete GOKB snapshots and the CARSI official Catalog across configurations. It holds external evidence and the selected default entry fields. Offline initialization
and upgrades attach those fields by official product identity. Refresh replaces
validated official fields and retains matched entry evidence. Removed or conflicted
evidence remains in the same snapshot. UserState owns the enabled Service UUIDs. The Journal Resolver follows Journal → GOKB Platform → CARSI Resource, retaining multiple identities and products. Only a unique, reliable candidate can fill an empty default; saved user choices take precedence. Ordinary Run never requires GOKB.

The two application-level databases live outside Workspace; the independent Paper library belongs to its Workspace. Within the application project, configurations in subdirectories use the same application data directory; their canonical paths still identify separate user scopes. Registry remains read-only during normal use and retains source-specific evidence. Browser handles and scheduler queues remain transient; current collection qualification and branch completion belong to Paper SQLite. Generated UI is rebuildable, not user data.

[Safety](safety.md) states the cross-module invariants. Types, parsers and validators in code define fields and interfaces; [development](development.md) defines preparation and verification. Historical plans and investigations are not current implementation authority.

## Foreground Run and Paper collection

The Python application process owns Provider cooldowns across clients, keyed by
actual HTTP origin and authentication context. Short-lived clients retain active
cooldowns until they expire or the process exits. Application-owned pacing is
injected into current Run and independent attempt clients;
request/response caches and mutable client state remain operation-local.

Provider adapters emit operation-local `ProviderWorkEvidence`; canonicalization groups
explicit strong identities and selects missing metadata in a fixed order.
One Integrated Run overlaps selected PubMed/WoS/OpenAlex journal Discovery under the parent slot and workflow identity. PubMed batches ESearch History/EFetch; OpenAlex merges native source-ISSN filters. Verified pages/native export batches stream DOI targets to shared exact Work lookup. Provider clients share operation-local capability caches, in-flight full Work details and host pacing. A bounded producer/consumer queue coalesces DOI inputs while sources remain active, then drains the final short batch after every producer settles. Work lookup responses enrich discovered roots and never add Discovery candidates. Formal PubMed identity remains separate from a merged Work’s potentially preprint PMID. The Browser worker retains the same captured configuration/Workspace/cancellation authority and never writes a separate Run snapshot or History result.

After Discovery and Work lookup settle, Run deduplicates and excludes saved Papers
including Rejected. Necessary batched PubMed article-ID lookup confirms missing
direct formal PMIDs before first creation. Original responses retain qualifying
formal bibliography, dates, abstracts and source facts. Ordinary missing fields
never schedule a generic Completion request. Retained client/lookup/batch/binding
helpers live in `application/provider_lookup.py`.
Native publication-date filters determine its range; subsequent evidence never
rejudges inclusion. Commit rechecks the captured query AST, publication months,
enabled Discovery source sequence, Journal ISSN scope/Service allocation, request
contact and output Workspace. The selected WoS Service remains captured through the parent stage. YAML bytes, log level, display metadata,
page quotas and unrelated UserState revisions are not Run authority. Standalone
WoS checks only its consumed query/date/ISSN/access/output inputs. Workspace/database
identity and the complete identity index remain checked before atomic creates.
Existing full matches preserve their metadata and acquire any new verified direct
aliases. Excluded matches stop avoidable follow-up
work; a cleared unexcluded placeholder can be rebuilt only from a real Run hit,
using its existing UUID. Final short transactions recheck identity conflicts and
captured Workspace/database eligibility. Run snapshots/logs use repository UUIDs,
not temporary Provider IDs or Markdown paths. `ProductionCollectionService`
composes the entire stable `document` and `necessary-api` plan. Registry admission
atomically creates/matches base metadata and queued qualification with original
tokens; registration runs outside the Run commit boundary. A matched complete
`not_started` Paper is admitted on this actual hit, independently of unknown-only
helper suppression. Active work is reused, normal completion never reopens, and
failed/cancelled work requires explicit retry.

Run finishes after all base results are registered or explicitly failed and its
own queries/native Futures/clients/snapshot have ended. Workspace owns transferred
tasks and cancellation independently, allowing another foreground Run. Source Run
IDs are diagnostic labels; cancelling Run B does not cancel A or Papers already
handed over by B. History/Last Run describe only foreground retrieval, identity,
created/matched/excluded and admission outcomes; background writes do not change
those results or their completion time.

The internal necessary-query service has a separate request planner. Ordinary
abstract, author and event-date gaps do not create requests. It consumes verified
capability-labelled facts, resolves explicit identity/Preprint relationships and
queries known native version families with execution-owned clients. Formal
increments and independent Preprint proof are separate; a new `first_public_at`
is offered only after all applicable relationship/native work and every known
family settle successfully. Production plans explicitly declare Providers,
records, complete/partial capability facts and required purposes. They transfer
immutable evidence, never Run clients/caches or replay callbacks. Base metadata
cannot seal partial native proof; truly complete foreground proof may be reused.

Ordinary dates are independent normalized month/day sets. Bibliographic
publication date retains its explicit source. Preprint evidence preserves version
families, verified first-version proof and unresolved relations; it never becomes
a formal direct identity or an ordinary date solely through association. Reader
and Info display these new library projections without old event/source columns
or active Enrich buttons. Production collection uses Document and necessary API
branches. Info's standalone query is retired; saved proof and read-only historical
results remain. See [Providers](providers.md#preprint-evidence).

## Workspace collection runtime

FastAPI composes one `WorkspaceTaskHost`, its shared Provider pacing/factory and
the current Workspace registry. Workspace switching/Reset first reserves admission,
revokes the old lifecycle and drains outside short configuration/Paper/SQLite
locks, then revalidates the save/deletion target. Ordinary input edits do not stop
independent collection; sensitive access changes drain only affected scopes.
Application shutdown joins owned work before closing the common factory, while
the authenticated bridge continues to deliver native resource terminal results.

The Workspace-owned `WorkspaceRegistry` has an immutable Workspace UUID,
path/inode identity and lifecycle ID. Reliable identity create/match/rebuild and
queued collection admission commit together before registration. Parent and leaf
schedulers permit independent Paper and same-Paper branch execution. Each leaf
owns its thread-confined repository, client/cache scope and native identity.

One Paper gate coordinates collection, body work and destructive
local actions. Run cancellation does not cancel transferred Paper tasks; reader
selection has no ownership effect. Startup marks interrupted attempts without
queue/network replay. Retry retains successful branch facts and checks only the
original Paper lifetime and failed attempt at admission. Necessary API work binds
each Provider when used; unrelated credential changes leave other sources running.
Finished work releases occupancy even when terminal storage or diagnostics fail.
See [runtime interfaces](collection-runtime.md).

## Physical Browser resource lifetime

One Session-wide `PageBudget` jointly admits global and trusted Service/public
capacity before native page creation. Task execution, retained access resources
and user ownership are separate; actual WebContents destruction and native-item
cleanup return slots. WoS keeps an exact workflow/Document loan between native operations. Main waits physical cleanup before the
shared Session event entry is disposed. See [page counts, retention and live
configuration](browser-pages.md), including user-page bounds and rollback.
