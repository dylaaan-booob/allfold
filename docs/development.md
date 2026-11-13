# Development

## Prerequisites and setup

The supported source-development platform is macOS, with Git, Node.js 24, Python 3.12 and uv. Electron is pinned to 45.0.0. Run from the project root:

```sh
npm --prefix electron run setup
```

Setup checks tools, creates `config.example.yaml` only if absent, installs locked Python/Electron/build dependencies, explicitly installs the Electron binary and builds the UI. Existing ignored vendor/Runtime directories are untouched. Translation-only assembly and Local API saving are retired; remaining Browser/Document/Prepare/Cloudflare helpers have no generated Runtime dependency.

Configure keywords, months and Provider settings in Discover. The Login toolbar owns Institution and Service preparation concurrency. Neutral Paper/PDF workflow values remain in configuration for existing contracts; no Download or retired Import controls are exposed. Application settings remain in Settings. Ordinary edits autosave, while credential replacement/clearing and high-impact operations require explicit submission. The public template is separate from local configuration; setup does not create or copy credentials.

Journal state is stored in `.allfold/user-data.sqlite`, isolated by canonical configuration path. The YAML `venue_whitelist` remains the first-migration source, not the live data store. The Journal Registry rebuilds offline from the existing five source lists with `uv run --locked python tools/build_journal_registry.py`; its shipped rows and indexes are checked against an isolated rebuild. Shared GOKB/CARSI data lives in `.allfold/resources.sqlite`; neither database belongs in a source candidate. Use temporary project/configuration directories and injected HTTP transports for migration, exchange and Resolver tests. Do not launch tests against personal YAML, Workspace, covers or Zotero.

The production [Paper library](paper-library.md) uses standard-library `sqlite3`.
Read-only uninitialized views do not create it; the first Run initializes
`Workspace/papers.sqlite`. Use disposable directories, actual SQLite connections
and local HTTP/DOM fixtures. Existing v1/v2 libraries receive a preserving known
schema-v3 upgrade. Missing, corrupt and unsupported databases have distinct results.

```sh
uv run --locked pytest tests/test_paper_repository.py tests/test_paper_repository_safety.py tests/test_run_commit.py tests/test_preprint_lookup.py
```

Paper MD/Inbox authority, Keep/Import, active Enrich and their dedicated tests have
been replaced or removed. [Task tracking](workflow-refactor-tasks.md) records the
current adoption and later responsibility; no dependency upgrade is involved.

## Start and stop

```sh
npm --prefix electron start
npm --prefix electron start -- --config "$PWD/my-config.yaml"
```

The local origin is `http://127.0.0.1:18767`. An occupied port is an error; close the other instance rather than changing ports. Project configuration, journal list and Workspace must stay under the project root.

Pass an absolute `--config` path. The example expands `$PWD` from the project root before npm runs the Electron package script from `electron/`; a relative configuration argument would otherwise resolve under that directory.

Normal exit stops further dispatch and waits for native operations and Run/Preprint workers to truly settle before closing their owned database connections. Externally killed processes require inspection before restarting.

## Build resources

Editable UI files are in [frontend/ui](../frontend/ui/). Build the complete delivery tree with:

```sh
node tools/build-ui-next.mjs
```

This copies static assets into ignored `src/allfold/web/static/ui_next/`. The served URL remains `/static/ui_next/`. Edit sources, not generated files; the application reports missing UI resources instead of using an old source location.

The full Translator Runtime has no current production caller and is not assembled.
Setup and CI no longer fetch vendor sources or assert that retired inventory.
DocumentRuntime, the isolated Document preload, Browser identity, Prepare and
Cloudflare are still used by the native application. Do not remove those helpers
because a similarly named translation fixture was retired. Existing vendor trees
and historical source pins remain untouched. Building UI does not package an
application; see [release preparation](release.md).

## Checks

```sh
npm --prefix electron run check
uv run --locked pytest
npm --prefix electron test
```

`check` discovers project-owned JS/CJS/MJS in Electron sources and scripts, the UI and tools. It excludes dependencies, third-party assets and generated output; tests parse their own files.

Repository/API checks exercise real temporary libraries, thread ownership,
Run/WoS commits, local fields, Preprint proof and exact-Paper cancellation.
Rendered Electron fixtures use local HTTP and temporary profiles for
Candidate/Downloaded/Trash, identity-only Reader, ordinary/Preprint dates,
Reject/Restore/metadata clearing, late response guards and retained layout.
They contact no personal library, account, institution or PDF.

The retained suite covers data preservation, path/identity safety, authority, cancellation, concurrent settlement and uncertainty, configuration and source ownership. Tests use isolated fixtures and transport doubles. UI build and module dependency checks cover the directory layout. Use [package scripts](../electron/package.json), the [UI build tool](../tools/build-ui-next.mjs) and [CI](../.github/workflows/ci.yml) as the executable command definitions.

CI starts from a fresh checkout without Vendor caches, runs Setup and the offline checks on macOS. It does not publish or use real credentials. A local pass does not prove that GitHub Actions ran, that the UI is visually correct or that real institutional access work. Changes to those paths need relevant manual acceptance with explicit browser authorization.

The Electron test command runs files serially. Its native input fixtures briefly
show their own windows, and Electron's
[`sendInputEvent()`](https://www.electronjs.org/docs/latest/api/web-contents#contentssendinputeventinputevent)
requires the containing window to have focus. Concurrent fixture processes can
otherwise steal that focus and invalidate mouse/keyboard acceptance.

The shipped Browser fixture retains Login/Discover handoff, task/Page identity,
focus and Session assertions. The Library/layout fixture checks the built Reader
and Trash projection independently of a Run. Dedicated Import/Enrich fixtures
are removed; their former product operations cannot be dispatched.

WF03 adds `document-probes.test.cjs` (real BrowserRuntime/DocumentRuntime/preload
and internal Paper entry), bounded sender/Document tests, neutral Bridge queue
regressions and production-dispatch/Bridge/Pydoll/CDP recheck in the existing
Cloudflare native fixture. Covers and WoS Export expiry tests retain real-terminal
ownership. See [controlled Documents](browser-documents.md) for payload limits,
identity evidence and fixture/live-service boundaries.

WF04's normal Electron entry also runs `session-downloads.test.cjs`: a real
Electron 45.0.0/local-HTTP fixture for original POST/inline/frame/popup downloads,
same-URL isolation, expiry/late/ambiguous events, cancellation/interruption,
source-close stages and controlled host-fetch association. See the measured
[capability boundary](browser-session.md#electron-4500-capability-evidence).

### Workbench manual acceptance reference

ARRAY/Journals rails, Sidebar allocation, the isolated rendered DOM test and remaining pointer/touch/low-height checks are documented in [workspace layout](workspace-layout.md). The full Electron test command includes its hidden-window fixture after UI build; it uses synthetic HTTP responses and a temporary profile.

Select checks from this matrix according to the changed behavior and gaps in automated coverage; the full matrix is not a prerequisite for every PR. In particular, result-contract cleanup does not require unrelated real WoS, CARSI, Zotero, PDF or complete Browser workflows.

Use a disposable configuration and Workspace. Browser control, external accounts and real data operations require task-specific authorization beyond isolated test fixtures. Offline tests do not establish the following real-workflow results:

1. From each business workspace, open Browser and return. Verify Paper/Journal selection, reading scroll and unsaved Settings drafts; resize the window, vary Header/Footer content and change the main UI zoom. Confirm no overlap between native webpages, trusted controls and scroll regions, and that Browser keyboard navigation leaves the hidden business selection unchanged.
2. Create/select/close ordinary pages; use URL entry, back/forward/reload, many tabs and loading/error states. Hide/show Browser and verify the same Page IDs, history and Session. Check CARSI, scoped Services with identical names, and Other, including popups and reused Paper pages.
3. Open and dismiss the Browser Tabs flyout using pointer and keyboard. Collapse a Service group and verify scroll and focus on return. Search for local Papers, Journals, Services and tabs from the four workspaces; use `>` for commands.
4. With an authorized task, check background page creation/navigation does not switch or focus the user's current page, while explicit **查看任务页面** reaches the existing task page. Check that a managed page rejects toolbar navigation and close, and allows reload when idle. Inspect popup and context-menu behavior in the main host.
5. Open Search and History while Browser is visible; verify the native view is hidden while needed and restores the same page. During a Discover or Login manual handoff, Browser remains usable and returning restores the workflow controls.
6. Test Archive disabled on fresh preferences, legacy Paper links, missing Papers, Workspace refresh and busy guards. Re-enable Archive and verify its existing layout/resources and ARRAY's shared reader remain usable.
7. Run WoS-only, API-only and mixed selected-source Runs in both presentation modes, including cancellation and interrupted polling recovery. Verify inline mode allows safe navigation, records completion/history and refreshes results without forcing a workspace change.
8. With authorized CARSI and Manual Services, check one login, independent
preparation pages, partial results and the exact manual verification page.
Synthetic fixtures cover recovery paths when real services do not reproduce them.

Python HTTPX callers share the [HTTP client and proxy layer](http.md). Its focused
tests cover isolated request routing, TLS, transport lifecycle and cache failures;
Chromium authentication remains a separate manual acceptance boundary.

## Troubleshooting

- Missing `.venv` or UI: complete setup and inspect the failing step.
- Download failure: correct connectivity to the named registry or GitHub before rerunning setup. Dependency pins remain unchanged.
- Need application diagnostics: use HISTORY's task export or Settings' recent
  diagnostic export. Both runtimes persist bounded, validated JSONL alongside
  stderr, independently of Workspace and SQLite. Settings Log Level controls
  optional detail after restarting; it also shows the current active level.
  `ALLFOLD_LOG_LEVEL=debug npm --prefix electron start` explicitly
  overrides it for both runtimes. Supported levels are debug, info, warn and error;
  necessary task results and errors survive all levels. Raw Chromium stderr can
  contain addresses and is excluded from diagnostic exports. See [logging](logging.md)
  for the schema, paths, limits, privacy and Reset rules.

See [architecture](architecture.md) before changing ownership and [safety](safety.md) before changing data, authorization or settlement paths.

### Integrated discovery acceptance

The [Provider guide](providers.md) describes Discovery, creation-time completion,
the Info preprint lookup and change-scoped acceptance. HTTP fixtures and rendered
Electron tests use synthetic data and isolated configurations. Real Provider
compatibility and Zotero acceptance require separate verification.

Focused application regressions use the Run, Run commit, Paper repository,
Preprint lookup, local-field and Workspace API suites. They verify actual SQLite
reopen/classification, stable UUIDs, bounded short commits, cancellation and
captured generations. The Electron fixture renders ordinary dates and separate
Preprint proof and checks local recycling without file operations. Source/build,
rendered fixture, live-service and latest PR CI outcomes remain distinct evidence.

WF05 component regressions additionally use `test_collection_repository.py`,
`test_dynamic_dispatch.py`, `test_collection_runtime.py`, `test_task_clients.py`
and `test_task_authority.py`. They exercise on-disk SQLite contention/upgrade and
rollback, real worker Futures and cleanup barriers, queued/expired work, branch
idempotence and retry, loopback HTTP with independent clients, common pacing and
narrow access revocation. Scheduler limits count executing Paper jobs, not native
WebContents. Internal fixture work does not enable production cross-Run collection
or public Download/Retry. Existing bounded dispatcher and foreground Run tests
remain applicable.

The current registry executes one Paper's branches sequentially within its worker,
connection and client scope. Tests of API/Document arrival races must instead use
the same captured attempt with a separate repository connection and client scope
in each thread. Sharing a `BranchContext`, SQLite connection or `AttemptClients`
across threads is not supported. Such transaction-level race evidence does not
enable production same-Paper branch concurrency; that orchestration belongs to WF08.

WF06 adds `test_necessary_metadata.py` for purpose-driven requests through actual
registry branches, controlled Provider transports/parsers, immutable capability
handoff, full batch/pagination draining, partial results and complete native
first-version proof. The existing Run/Completion/public Preprint tests remain.
`document-extraction.test.cjs` uses production Main dispatch, BrowserRuntime,
DocumentRuntime and its isolated preload in Electron 45 with local HTTP and a
temporary profile. It covers the complete fixed Date/Abstract algorithms,
strict parameters/DTOs, legal empty results, bounded local diagnostics, live
Document/body validation, captured Service binding and actual cleanup.

In a separate worktree, ensure Python imports resolve to that worktree's `src`
before relying on test evidence. A shared editable environment can still point
at another checkout; use an isolated environment or explicit `PYTHONPATH=src`.

`test_workspace_tasks.py` exercises the actual application host, HTTP projection,
legacy query reaper, signal/join/factory shutdown order, selective credential and
Service invalidation, accepted switch/Reset, partial save and same-path rebind,
refusal before drain and Logs protection with real disposable libraries. The
`page-resources` Electron fixture separately verifies parallel same-Service
physical work pages; it does not enable production collection.

`tests/test_two_stage_run.py` uses controlled Events/Futures to prove overlapping
PubMed/WoS/OpenAlex producers, Work lookup before producer completion, deduplication
and tail drain, fixed helper roles, unknown-only completion, relation-only date
folding, formal/preprint identity isolation, physical request counts, failure
isolation, global dispatch revocation, native-disconnect settlement and parent
shutdown/join. `tests/test_incremental_discovery.py` retains parent slot/partial
export checks, verified-batch refusal for count/path/duplicate-UT failures,
late conflict quarantine, >200 unordered Work IDs, whole-author full-detail
fallback and ambiguous-owner isolation. `electron/tests/task-presentation.test.cjs` covers unified browser-stage recovery and parent cancellation without opening native windows. History keeps sanitized source totals and WoS batch/journal/date hint counts; actual Custom controls and downloaded exports remain a separately authorized live acceptance boundary.

## One-time retired scope cleanup

Existing user databases with the retired `conferences` collection require an
explicit cleanup before the Journal-only runtime can read them. Stop the old
application, then run this command against the exact database to update:

```sh
uv run --locked python tools/remove_conference_data.py /absolute/path/to/.allfold/user-data.sqlite
```

The tool validates every scope and the known schema before changing anything. It
uses the existing safe SQLite path checks, compares the captured rows under
`BEGIN IMMEDIATE`, and creates and verifies a complete private SQLite backup beside
the database before writes. It removes only the retired collection, preserving
Journals, Groups, Custom Labels, Access Services, assignments, migration metadata
and configuration paths. Each changed scope advances its revision once; stale
Settings writes are rejected. A second run does nothing. Unknown structures,
corruption or concurrent changes cause refusal/rollback. The tool is separate from
startup and normal serialization; it does not recreate a Conference configuration
model or migrate Paper identities.

Retain the reported backup until acceptance. To recover, stop Allfold and use
SQLite's backup API from that backup into the original database; preserve the
original and any sidecars until recovery is verified. Never copy over a database
while the application is running. Paper data is untouched. Per-Paper Markdown is no longer read or migrated; the
SQLite library and explicit Workspace Reset follow [Paper identity](paper-identity.md).


### Scoped Browser authority regressions

`tests/test_browser_services.py`, `tests/test_login.py` and
`tests/test_settings_autosave.py` use temporary configuration/User State and explicit
native transports. They cover independent workflow owners, overlapping Service and
control refusal, unrelated input edits, captured recovery authority, exact
cancellation, actual-close notifications and old-key access cleanup without a held
configuration lock. `tests/test_cover_authority.py` exercises final image saving
across unrelated edits and refuses replaced Journal/cover targets.
`tests/test_run_cancel_identity.py` covers required HTTP task identity, late old
cancellation and the lock-outside WoS handoff race. Existing Run commit,
Workspace/diagnostic Reset, Preprint and shutdown checks retain their protections.
The autosave and task-presentation Node fixtures verify draft acknowledgement and
UI-captured parent Run cancellation. These tests do not use real accounts or
establish native/live Service acceptance.

WF04 adds `page-resources.test.cjs` to the normal serial Electron test command.
It checks real WebContents at minimum capacities, native popup/opener lifetime,
multiple temporary batches, retained Portal reuse across unrelated revisions,
queued cancellation, original native-item source retention and user-page bounds.
The existing Document fixture keeps independent cases within separate task
lifetimes and closes dependent-case pages promptly. Delayed-destroy and quota
update checks use BrowserRuntime; configuration/API tests use temporary YAML and
UserState. The rendered layout fixture verifies the visible page-limit controls
and keeps inactive PDF controls absent. [Browser pages](browser-pages.md) records
counts, live effect timing, configuration rollback and the Runtime form-POST
limitation; [Session evidence](browser-session.md) has its separate capability scope.
