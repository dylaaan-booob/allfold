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
    MAIN --> ZOTERO[Translator and ItemSaver]
    APP --> DATA[Paper and configuration files]
    APP --> PROVIDERS[Provider adapters]
```

Main starts one Python process. The HTTP origin remains loopback-only on port 18767; one authenticated WebSocket carries native operations, progress and Solver submessages. Remote pages have no Node or host IPC capabilities.

## Ownership

| Source | Responsibility |
| --- | --- |
| `frontend/ui/` | Workspace, Run, Journals and Settings UI, source assets and notices |
| `src/allfold/application/` | Use cases, guarded operations and process-local workflow coordination |
| `src/allfold/providers/` | Provider retrieval, queries and source-specific formats |
| `src/allfold/persistence/` | Paper/Markdown projection, safe file operations, Registry and local state |
| `src/allfold/integrations/` | Python-side Zotero, credential and Pydoll adapters |
| `src/allfold/web/` | HTTP projection, validation, composition and Electron WebSocket transport |
| `electron/src/main.cjs` | Application lifecycle, trusted IPC and native dispatch |
| `electron/src/browser/` | Native tabs, document identity, navigation and shared Session |
| `electron/src/auth/` | Task-scoped institution authentication and credentials |
| `electron/src/workflows/` | Prepare, Covers and WoS native page operations |
| `electron/src/zotero/` | Translation/saving VMs and host document/HTTP adapters |
| `electron/src/preload/`, `native-ui/` | Restricted capabilities and local native-window UI |

Models, configuration definitions, identifiers and query primitives remain shared Python modules. Application code does not depend on Web adapters; its BrowserGateway describes the existing connected/execute/cancel interface. ElectronBridge adapts it to transport. A pending Future preserves the distinction between cancellation and an already-started save reaching a terminal result.

Journal lookup and remote fallback belong to the application layer; persistence only reads the local Registry. WoS export parsing continues to reuse safe file-reading helpers.

FastAPI composes these implementations. ImportTarget belongs to the application so workflow identity checks do not depend on HTTP forms. Provider normalization uses shared identifiers rather than application workflow helpers.

## Browser Service associations

Python snapshots the saved Journals and Access Services for each invocation. The browser bridge carries an opaque hash of the canonical configuration path, the configuration revision and User State revision alongside the saved Service ID. Import matches saved ISSN/eISSN identifiers with the existing Workspace rules: every matching Journal must select the same nonempty Service; otherwise the Paper remains unassigned. These are invocation snapshots of SQLite state, never a second authoritative mapping. Preparation and subsequent Import dispatches verify the original snapshot, while WoS retains its existing configuration and Workspace checks. Detected changes stop further work without migrating it to a new mapping. Already-dispatched native saves still settle through the existing result protocol.

BrowserRuntime keeps one current association per physical page, including the task/request, role, optional Paper/DOI and source page. `pageAssociation(pageId)` returns descriptive metadata with an explicit active flag; `servicePages(scopeId, serviceId)` filters existing pages without creating them. Task completion clears live ownership while retaining the page's last association for inspection. Destruction removes its association and live source/opener references; renderer exit invalidates the association. No history store, new Session, page recycling or automatic closure is involved.

Prepare's CARSI Portal is shared and unassigned; resource and observed target pages carry the saved Service, and popups inherit their attributable source. Query and Export validate that the original prepared page still has the expected scoped Service/revisions, in addition to the existing document checks. Import replaces the reused ImportPage's association for each Paper, including an explicit unassigned Service. Covers and Enrich remain temporary auxiliary pages. Generic Manual Service URL opening retains its existing behavior.

`bindTaskPage` and explicit `navigate(..., {tab})` control task targets. `select` only presents a page in the existing Browser window; task navigation and WoS handoff do not select tabs. New task pages are registered without replacing an existing selection, and remain available for manual login or inspection through the existing tabs. Service associations confer no document, task or institution-credential authority. Page/frame identity, task signals, navigation recovery and native-save settlement remain separate checks.

## Resources and third-party code

The UI build copies sources and generates Kept bundles into Python's ignored static delivery tree. Runtime URLs and API endpoints do not depend on the editable source directory.

Electron package metadata and scripts remain at the package root. `src/shared/paths.cjs` resolves project, native UI, Preload, vendor-notice and Runtime locations. Official Zotero checkouts stay pristine in ignored vendor directories; the Runtime assembler is their only production assembly path. Project adaptations stay in host sources. See [third-party sources](third-party.md).

## Data ownership

Local YAML owns monitor settings. The private `.allfold/user-data.sqlite` owns Journals, Groups, Labels, direct Access Services and default Service assignments, isolated by the canonical configuration path. Existing valid `list.md` files seed each configuration once; subsequent Markdown edits do not change saved user state. Migration validates the complete managed data, records its source and digest, and leaves the original file intact. Paper Markdown owns identity, workflow status and human content.

The private `.allfold/resources.sqlite` shares complete GOKB snapshots and the CARSI official Catalog across configurations. It holds external evidence, not users' Service preferences. Refresh commits only validated, complete data and retains the previous cache on failure. The Journal Resolver follows Journal → GOKB Platform → CARSI Resource, retaining multiple identities and products. Only a unique, reliable candidate can fill an empty default; saved user choices take precedence. Ordinary Run never requires GOKB.

Both databases live outside Workspace. Within the application project, configurations in subdirectories use the same application data directory; their canonical paths still identify separate user scopes. Registry remains read-only during normal use and retains source-specific evidence. Browser tasks and coordinators are transient, while Zotero owns its Library and attachments. Generated UI and Runtime are rebuildable resources, not user data.

[Safety](safety.md) states the cross-module invariants. Types, parsers and validators in code define fields and interfaces; [development](development.md) defines preparation and verification. Historical plans and investigations are not current implementation authority.
