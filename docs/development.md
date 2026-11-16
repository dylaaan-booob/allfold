# Development

## Prerequisites and setup

The supported source-development platform is macOS, with Git, Node.js 24, Python 3.12 and uv. Electron is pinned to 45.0.0. Run from the project root:

```sh
npm --prefix electron run setup
```

Setup checks tools, creates `config.example.yaml` only if absent, installs locked Python/Electron/build dependencies, explicitly installs the Electron binary and builds the UI. Existing ignored vendor/Runtime directories are untouched. Translation-only assembly and Local API saving are retired; remaining Browser/Document/Prepare/Cloudflare helpers have no generated Runtime dependency.

Configure keywords, months and Provider settings in Discover. The Login toolbar owns Institution and Service preparation concurrency. Single-Paper Download/Cancel and local PDF controls live in the existing reader; retired Import controls remain absent. Original DownloadItem body output retains the accepted [native cancellation limitation](body-downloads.md#native-output-and-accepted-cancellation-risk). Application settings remain in Settings. Ordinary edits autosave, while credential replacement/clearing and high-impact operations require explicit submission. The public template is separate from local configuration; setup does not create or copy credentials.

Journal state is stored in `.allfold/user-data.sqlite`, isolated by canonical configuration path. The YAML `venue_whitelist` remains the first-migration source, not the live data store. The Journal Registry rebuilds offline from the existing five source lists with `uv run --locked python tools/build_journal_registry.py`; its shipped rows and indexes are checked against an isolated rebuild. Shared GOKB/CARSI data lives in `.allfold/resources.sqlite`; neither database belongs in a source candidate. Use temporary project/configuration directories and injected HTTP transports for migration, exchange and Resolver tests. Do not launch tests against personal YAML, Workspace, covers or Zotero.

The production [Paper library](paper-library.md) uses standard-library `sqlite3`.
Read-only uninitialized views do not create it; the first Run initializes
`Workspace/papers.sqlite`. Use disposable directories, actual SQLite connections
and local HTTP/DOM fixtures. Create current-format v5 databases for acceptance; exactly valid v4 and the supported v3 path have transactional forward changes preserving saved data and unknown historical provenance. Retired/unknown formats remain refused. Missing, corrupt and unsupported databases have distinct results.

```sh
uv run --locked pytest tests/test_paper_repository.py tests/test_paper_repository_safety.py tests/test_run_commit.py
```

Paper MD/Inbox authority, Keep/Import and active Enrich are retired. Current
production collection is described in [Workspace runtime](collection-runtime.md).

## Start and stop

```sh
npm --prefix electron start
npm --prefix electron start -- --config "$PWD/my-config.yaml"
```

The local origin is `http://127.0.0.1:18767`. An occupied port is an error; close the other instance rather than changing ports. Project configuration, journal list and Workspace must stay under the project root.

Pass an absolute `--config` path. The example expands `$PWD` from the project root before npm runs the Electron package script from `electron/`; a relative configuration argument would otherwise resolve under that directory.

Normal exit stops admission and waits for foreground Run, all Workspace branches,
native operations to actually settle before closing owned
connections and the shared factory/Session. Restart fails interrupted attempts
without replaying the queue or opening pages.

### Isolated source-startup smoke

In a disposable source copy with no environments, dependencies, generated UI,
Workspace or local configuration, run setup above. Its first configuration is
inside that copy. With port 18767 free, create a profile there and run:

```sh
mkdir -p "$PWD/.startup-smoke/profile"
electron/node_modules/.bin/electron electron/tests/source-startup.fixture.cjs \
  "$PWD/.startup-smoke/profile" --config "$PWD/config.example.yaml"
```

The opt-in fixture requires the normal Main entry without replacing its Python
bootstrap, HTTP origin, bridge or shutdown. It checks an uninitialized empty
Workspace, built UI, authenticated bridge, native Browser navigation/closure
against its own local HTTP server and normal quit. Profile/Session/logs and a
QA screenshot belong to this disposable copy. It adds no product configuration
or port policy. If a personal instance occupies 18767, leave it running and
defer this smoke. The complete collection/stream/original-item compositions run
separately in the standard suites. Record actual versions and results in the PR;
real-service and OS evidence remains separate from source startup.

Fixture-only `--fail-after-ready` and `--timeout-after-ready` exercise assertion
and watchdog failure after Python has started. Both must return status 1 only
after normal Main shutdown; verify the reported Python PID has exited and 18767
is free. They never change production configuration or bypass Main drain.

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

Local validation follows the changed behavior. Use the existing file/name selectors
for relevant checks and regression tests. Cross-Python/Electron protocols,
persistence or task-lifecycle changes need the corresponding combined fixtures
and both sides of the interface. Existing behavior tests stay active until their
own implementation changes; a retired requirement alone is not grounds to hide
or delete a test that still covers production code.

From the repository root, for example:

```sh
# Python: file selection, then a narrower existing test name.
uv run --locked pytest tests/test_ci_scope.py tests/test_pdf_rules.py
uv run --locked pytest tests/test_pdf_rules.py -k adoption_catalogue

# Electron/Node: select files; keep native fixture processes serial.
node --test --test-concurrency=1 electron/tests/setup.test.cjs electron/tests/ui-build.test.cjs
node --test --test-concurrency=1 --test-name-pattern='repeated setup' electron/tests/setup.test.cjs
```

After UI source changes, build with `node tools/build-ui-next.mjs` before rendered
fixtures. Pick related files from the component guide below; these examples are
not a compulsory list for every edit. Unrun relevant checks must be identified
with their reason and impact. Live-site and large Zotero comparisons are outside
routine offline validation and require separately scoped work/authorization.

The complete offline suite remains explicitly available:

```sh
npm --prefix electron run check
uv run --locked pytest
npm --prefix electron test
```

`check` discovers owned JS/CJS/MJS in Electron sources/scripts, UI and tools. It
excludes dependencies, third-party assets and generated output; tests parse their
own files. Full Python and Electron suites are not mandatory after every local
edit, and a local full pass need not be repeated unconditionally when relevant
latest-PR CI already supplies that evidence. Production-code, test and CI changes
require the latest PR's actual full offline CI, even when local validation is targeted.

The Electron entry stays serial: native input fixtures briefly show their own
windows, and Electron's
[`sendInputEvent()`](https://www.electronjs.org/docs/latest/api/web-contents#contentssendinputeventinputevent)
requires focus. Parallel native processes can steal that focus. Use isolated
files, SQLite, local HTTP and temporary profiles, never personal configuration,
Workspace, covers, accounts or Zotero. Source/build, rendered fixtures, live-service
acceptance and GitHub CI are distinct evidence.

### GitHub Actions scope

[Safety checks](../.github/workflows/ci.yml) runs on PRs, pushes to `main` and manual
`workflow_dispatch`. New versions of the same PR cancel its obsolete runs;
different PRs and main/manual runs have separate groups. The required
`Safety checks / safety` job always runs to a result. It has no workflow path filter.

Before setup, [ci_scope.py](../tools/ci_scope.py) uses the event's commit SHAs and
local Git history. PRs compare their merge base to head, covering the whole PR;
pushes compare `before` to `after`, covering the whole push. Rename detection is
disabled so both paths count, including deletions. Missing history, ambiguous or
empty diffs, unrecognized events and unclassified paths choose full validation.

Only a complete diff consisting of the explicitly listed explanatory documents
skips dependency installation, UI build and heavy Python/Electron checks.
`README.md` is Python build metadata, `list.md` is a runtime/test seed, and UI
notices are build assets: Markdown is not automatically documentation-only.
New documentation paths need an input-usage review before joining the allowlist.
Any code, test/fixture, CI, script, dependency, lock or runtime-configuration change
runs existing locked setup plus all three commands above. Mixed changes do too.
Manual dispatch always runs full validation. Scope and reason appear in the log
and Job summary; failures in executed steps remain failures.

This keeps the required workflow present as described by GitHub's
[required-status guidance](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)
and isolates cancellation using [concurrency groups](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
Verify the latest PR-associated check and run link, including GitHub's test-merge
commit when used; a prior push success is not evidence for the current PR version.
Do not change branch protection or create temporary PRs to exercise event variants.

### Workbench manual acceptance reference

ARRAY/Journals rails, Sidebar allocation, the isolated rendered DOM test and remaining pointer/touch/low-height checks are documented in [workspace layout](workspace-layout.md). The full Electron test command includes its hidden-window fixture after UI build; it uses synthetic HTTP responses and a temporary profile.

Select checks from this matrix according to the changed behavior and gaps in automated coverage; the full matrix is not a prerequisite for every PR. In particular, result-contract cleanup does not require unrelated real WoS, CARSI, system PDF or complete Browser workflows.

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

### Component selection

Use actual package scripts and test selectors; no separate scheduler or test
classification framework is needed. The following entry points help select
related verification without turning every row into a requirement for every PR.

| Changed area | Existing focused verification |
| --- | --- |
| CI scope | `tests/test_ci_scope.py`: disposable Git histories and workflow-command outputs, including full PR/push, docs, mixed, deletion/rename and unavailable diff |
| Paper storage / Run admission | `test_paper_repository.py`, `test_paper_repository_safety.py`, `test_run_commit.py`, `test_run_library.py`; actual temporary SQLite reopen and ownership |
| Run / WoS inputs | `test_run_commit.py`, `test_two_stage_run.py`, `test_wos.py`; captured search semantics, unrelated settings edits, actual input revocation and Workspace replacement |
| Collection / retry / lifecycle | `test_collection_repository.py`, `test_collection_runtime.py`, `test_collection_planner.py`, `test_collection_http.py`, `test_task_clients.py`, `test_task_authority.py`; real workers with isolated transports |
| Provider queries / HTTP | `test_necessary_metadata.py`, `test_integrated_discovery.py`, `test_http_client.py`, `test_provider_resilience.py`; independent clients and synthetic responses |
| Page limits / settings effects | `test_page_limits.py` and `browser-runtime.test.cjs`; unchanged limits, granted tickets across decreases, queue wakeup and actual cancellation |
| Document extraction / PDF sources | `test_document_metadata.py`, `test_pdf_rules.py`, `test_pdf_source_facts.py`, `test_pdf_discovery.py`, `test_pdf_http.py`; serial `document-probes`, `document-extraction`, `pdf-clues` Electron tests |
| Native IPC / resources / Solver | `test_electron_bridge_solver.py`, `test_browser_services.py`, `test_login.py`; serial `cloudflare-solver`, `session-downloads`, `page-resources`, `browser-workspaces-dom` Electron tests |
| Download / local files | `test_body_downloads.py`, `test_body_download_http.py`, `test_native_body_downloads.py`, `test_local_body.py`; serial `body-stream`, `body-native`, `local-body`, `native-output` Electron tests |
| Reader / layout | `workspace-layout-dom.test.cjs`, `browser-presentation-dom.test.cjs`; built UI and temporary profiles, with `document_metadata_pipeline.py` for real cross-language extraction/persistence composition |

Python names are under `tests/`; Electron names are under `electron/tests/` and
end in `.test.cjs`. Combined body fixtures exercise public HTTP → Main/Session →
managed files → SQLite → Workspace. Document/Reader fixtures exercise actual
native DTOs, independent connections, incremental updates and retained selection.
Their source code defines the assertions; module guides define supported behavior.
Completion regressions exercise actual completed transports after late signals,
temporary hard-link cleanup failure, successful shell receipts with failed
projection refresh, and ended attempts whose terminal storage write failed.
They also retain the contrary cases: unfinished writers/items/native Futures,
original-token/Workspace protection, no-clobber output and real association
failure. Owner release needs no extra revision; a single-slot collection test
guards against diagnostics retaining scheduler execution capacity. Reader fixtures
check storage-error controls and successful actions with refresh-only errors.
Real institutions, publishers, default PDF apps and file managers require separate
acceptance. The [body matrix](body-downloads.md#scoped-manual-acceptance) and
[workspace layout](workspace-layout.md) describe relevant human checks.

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
