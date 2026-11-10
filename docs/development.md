# Development

## Prerequisites and setup

The supported source-development platform is macOS, with Git, Node.js 24, Python 3.12 and uv. Electron is pinned to 45.0.0. Run from the project root:

```sh
npm --prefix electron run setup
```

Setup checks tools, creates `config.example.yaml` only if absent, installs locked Python/Electron/build dependencies, explicitly installs the Electron binary, fetches exact official Zotero revisions, builds the UI and assembles Runtime. Existing modified or incorrect required vendor checkouts are rejected; setup does not reset or clean them. Only the named `src/translate`, `src/utilities` and `src/zotero-schema` submodules are initialized, without recursion. Unused Desktop and Google Docs checkouts may remain absent or retain local changes without being touched. The production revisions are in [upstream.lock](../electron/upstream.lock).

Configure keywords, months and Provider settings in Discover. The Login toolbar owns Institution and Service preparation concurrency. Import exposes the Paper, Translator, PDF and Zotero writer limits. Application settings remain in Settings. Ordinary edits autosave, while credential replacement/clearing and high-impact operations require explicit submission. The public template is separate from local configuration; setup does not create or copy credentials.

Journal state is stored in `.allfold/user-data.sqlite`, isolated by canonical configuration path. The YAML `venue_whitelist` remains the first-migration source, not the live data store. The Journal Registry rebuilds offline from the existing five source lists with `uv run --locked python tools/build_journal_registry.py`; its shipped rows and indexes are checked against an isolated rebuild. Shared GOKB/CARSI data lives in `.allfold/resources.sqlite`; neither database belongs in a source candidate. Use temporary project/configuration directories and injected HTTP transports for migration, exchange and Resolver tests. Do not launch tests against personal YAML, Workspace, covers or Zotero.

## Start and stop

```sh
npm --prefix electron start
npm --prefix electron start -- --config "$PWD/my-config.yaml"
```

The local origin is `http://127.0.0.1:18767`. An occupied port is an error; close the other instance rather than changing ports. Project configuration, journal list and Workspace must stay under the project root.

Pass an absolute `--config` path. The example expands `$PWD` from the project root before npm runs the Electron package script from `electron/`; a relative configuration argument would otherwise resolve under that directory.

Normal exit stops further dispatch and waits for an already-started native save and guarded Paper result write. If the process was externally killed or the save result is uncertain, inspect Zotero and remaining processes before restarting or saving again.

## Build resources

Editable UI files are in [frontend/ui](../frontend/ui/). Build the complete delivery tree with:

```sh
node tools/build-ui-next.mjs
```

This copies static assets and bundles Kept JS/CSS into ignored `src/allfold/web/static/ui_next/`. The served URL remains `/static/ui_next/`. Edit sources, not generated files; the application reports missing UI resources instead of using an old source location.

With existing pristine vendor sources, rebuild the translation Runtime using:

```sh
npm --prefix electron run prepare-runtime
```

The assembler validates fixed revisions, HEAD/index gitlinks and consumed bytes against tracked pinned Git blobs, including hidden `assume-unchanged` edits. Runtime ownership requires the exact current generated inventory and hashes, or the bounded PR #26 manifest profile during migration. That profile permits removal of the exact old ItemSaver/BotBypass files and old entry HTML. Unknown, incomplete or modified Runtime trees are rejected; unverifiable pre-manifest trees are preserved and require manual inspection. Building resources does not package an application; [release preparation](release.md) describes the distribution boundary.

The main repositories retain fixed-commit shallow acquisition. Sparse/partial checkout is not added: sparse index membership can describe absent worktree inputs, submodules still need separate initialization, and converting old full checkouts would remove files. Partial clones add promisor/lazy-fetch states without reducing checked-out input requirements. Native named submodule selection provides the needed download reduction while preserving existing full checkouts.

## Checks

```sh
npm --prefix electron run check
uv run --locked pytest
npm --prefix electron test
```

`check` discovers project-owned JS/CJS/MJS in Electron sources and scripts, the UI and tools. It excludes dependencies, third-party assets and generated output; tests parse their own files, and esbuild handles Kept TypeScript.

The real-source Runtime checks assemble all 752 Translators at the locked revision and verify deterministic manifests, selective native submodule initialization, preserved legacy extra checkouts, trusted PR #26 migration and refusal of unsafe inputs. A hidden Electron fixture runs official Web translation, DOI Content Negotiation with dynamically loaded CSL JSON and read-only Enrich against synthetic HTTP. It verifies that only the virtual JSON saver remains and exercises article history parsing, delayed snapshots, the 30-second budget, cancellation and source replacement.

For live Enrich checks, use a disposable Electron profile and public articles. Use the existing Browser navigation and Solver flow and record the article response after verification. A Solver result describes an attempt on a recognized verification page. A generic HTTP 403 or persistent challenge can still block access to the article. Compare the extracted events with the actual Translator source document and distinguish access, translation, capture and parsing failures from a source without dates.

The retained suite covers data preservation, path/identity safety, authority, cancellation, concurrent settlement and uncertainty, fixed-source ownership and source preparation. Tests use isolated fixtures and transport doubles. UI build and module dependency checks cover the directory layout. Use [package scripts](../electron/package.json), the [UI build tool](../tools/build-ui-next.mjs) and [CI](../.github/workflows/ci.yml) as the executable command definitions.

CI starts from a fresh checkout without Vendor caches, runs full Setup and asserts the selective source/runtime inventory before offline checks on macOS. It does not publish or use real credentials. A local pass does not prove that GitHub Actions ran, that the UI is visually correct or that real institutional access and Zotero/PDF saving work. Changes to those paths need relevant manual acceptance with explicit browser authorization.

The Electron test command runs files serially. Its native input fixtures briefly
show their own windows, and Electron's
[`sendInputEvent()`](https://www.electronjs.org/docs/latest/api/web-contents#contentssendinputeventinputevent)
requires the containing window to have focus. Concurrent fixture processes can
otherwise steal that focus and invalidate mouse/keyboard acceptance.

Shipped Workflows and Enrich Browser acceptance use separate fixtures. Enrich's target
Paper is part of its initial Workspace, and its readiness check verifies that Paper
and enabled controls. It does not replace synthetic Workspace data after finishing
Run. Both fixtures keep their task/page assertions and report Workspace reads,
candidate IDs and renderer/native state on failure. The normal `npm test` glob
includes both; no CI skip or workflow-specific opt-in is needed.

### Workbench manual acceptance reference

ARRAY/Journals rails, Sidebar allocation, the isolated rendered DOM test and remaining pointer/touch/low-height checks are documented in [workspace layout](workspace-layout.md). The full Electron test command includes its hidden-window fixture after UI build; it uses synthetic HTTP responses and a temporary profile.

Select checks from this matrix according to the changed behavior and gaps in automated coverage; the full matrix is not a prerequisite for every PR. In particular, result-contract cleanup does not require unrelated real WoS, CARSI, Zotero, PDF or complete Browser workflows.

Use a disposable configuration and Workspace. Browser control, external accounts and Zotero operations require task-specific authorization beyond isolated test fixtures. Offline tests do not establish the following real-workflow results:

1. From each business workspace, open Browser and return. Verify Paper/Journal selection, reading scroll and unsaved Settings drafts; resize the window, vary Header/Footer content and change the main UI zoom. Confirm no overlap between native webpages, trusted controls and scroll regions, and that Browser keyboard navigation leaves the hidden business selection unchanged.
2. Create/select/close ordinary pages; use URL entry, back/forward/reload, many tabs and loading/error states. Hide/show Browser and verify the same Page IDs, history and Session. Check CARSI, scoped Services with identical names, and Other, including popups and reused Paper pages.
3. Open and dismiss the Browser Tabs flyout using pointer and keyboard. Collapse a Service group and verify scroll and focus on return. Search for local Papers, Journals, Services and tabs from the four workspaces; use `>` for commands.
4. With an authorized task, check background page creation/navigation does not switch or focus the user's current page, while explicit **查看任务页面** reaches the existing task page. Check that a managed page rejects toolbar navigation and close, and allows reload when idle. Inspect popup and context-menu behavior in the main host.
5. Open Search and History while Browser is visible; verify the native view is hidden while needed and restores the same page. During a Discover or Login manual handoff, Browser remains usable and returning restores the workflow controls.
6. Test Archive disabled on fresh preferences, legacy Paper links, missing Papers, Workspace refresh and busy guards. Re-enable Archive and verify its existing layout/resources and ARRAY's shared reader remain usable.
7. Run WoS-only, API-only and mixed selected-source Runs in both presentation modes, including cancellation and interrupted polling recovery. Verify inline mode allows safe navigation, records completion/history and refreshes results without forcing a workspace change.
8. With authorized CARSI and Manual Services, check one login, independent preparation pages, partial results and the exact manual verification page. Test managed Paper page reuse and a fixed Import into an isolated Zotero target. Check explicit skips, cancellation and uncertain write settlement. Inspect actual parent-item and PDF results separately; never retry an uncertain save solely because presentation changed.

Python HTTPX callers share the [HTTP client and proxy layer](http.md). Its focused
tests cover isolated request routing, TLS, transport lifecycle and cache failures;
Chromium authentication remains a separate manual acceptance boundary.

## Troubleshooting

- Missing `.venv`, UI, vendor or Runtime: complete setup and inspect the failing step.
- Modified vendor or Runtime: inspect the reported path. Preserve unknown files; do not use reset/clean to make verification pass.
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

Focused regressions use `tests/test_integrated_run.py`, `tests/test_two_stage_run.py`,
`tests/test_preprint_lookup.py`, `tests/test_metadata_completion.py` and
`tests/test_paper_enrichment.py`. They exercise create-only rediscovery,
batched PubMed identity validation, HTTP settlement, exact Paper and Workspace
authority, cancellation, deduplication and event-only Enrich saves. The
Electron workspace fixture renders the four date values, full Info evidence,
and the one-Paper lookup with isolated API responses.
Snapshot regressions in `tests/test_run_state.py`, `tests/test_run_commit.py` and
`tests/test_wos.py` cover unified Integrated v6, unsupported Integrated v4/v5, preserved legacy WoS v4,
invalid/I/O cases, bound atomic writes and truthful write-failure counts.
Synthetic Chromium Run results cover source failures, status/count rendering and
WoS batches/date hints. Rare Accepted/event-only Translator responses and unusual
version/date conflicts belong in synthetic automated tests; real samples are
supplementary when available. These checks do not establish real-site,
real-Workspace or Zotero acceptance.

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
while the application is running. Paper data is untouched; retired Paper identity
fields require a separately chosen, backed-up Workspace Reset as described in
[Paper identity](paper-identity.md).
