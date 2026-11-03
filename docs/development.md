# Development

## Prerequisites and setup

The supported source-development platform is macOS, with Git, Node.js 24, Python 3.12 and uv. Electron is pinned to 45.0.0. Run from the project root:

```sh
npm --prefix electron run setup
```

Setup checks tools, creates `config.example.yaml` only if absent, installs locked Python/Electron/build dependencies, explicitly installs the Electron binary, fetches exact official Zotero revisions, builds the UI and assembles Runtime. Existing modified or incorrect vendor checkouts are rejected; setup does not reset or clean them. The production revisions are in [upstream.lock](../electron/upstream.lock).

Configure keywords, months and optional credentials through Settings. The public template is separate from local configuration; setup does not create or copy credentials.

Journal state is stored in `.allfold/user-data.sqlite`, isolated by canonical configuration path. The YAML `venue_whitelist` remains the first-migration source, not the live data store. Shared GOKB/CARSI data lives in `.allfold/resources.sqlite`; neither database belongs in a source candidate. Use temporary project/configuration directories and injected HTTP transports for migration, exchange and Resolver tests. Do not launch tests against personal YAML, Workspace, covers or Zotero.

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

The assembler validates fixed revisions, gitlinks and generated-file ownership. Unknown or modified Runtime files are rejected. Building resources does not package an application; [release preparation](release.md) describes the distribution boundary.

## Checks

```sh
npm --prefix electron run check
uv run --locked pytest
npm --prefix electron test
```

`check` discovers project-owned JS/CJS/MJS in Electron sources and scripts, the UI and tools. It excludes dependencies, third-party assets and generated output; tests parse their own files, and esbuild handles Kept TypeScript.

The retained suite covers data preservation, path/identity safety, authority, cancellation, single-save settlement, fixed-source ownership and source preparation. Tests use isolated fixtures and transport doubles. UI build and module dependency checks cover the directory layout. Use [package scripts](../electron/package.json), the [UI build tool](../tools/build-ui-next.mjs) and [CI](../.github/workflows/ci.yml) as the executable command definitions.

CI prepares sources and runs offline checks on macOS. It does not publish or use real credentials. A local pass does not prove that GitHub Actions ran, that the UI is visually correct or that real institutional access and Zotero/PDF saving work. Changes to those paths need relevant manual acceptance with explicit browser authorization.

### Workbench manual acceptance

Use a disposable configuration and Workspace. Native/browser automation, external accounts and Zotero operations require task-specific authorization. Offline tests do not establish the following results:

1. From each business workspace, open Browser and return. Verify Paper/Journal selection, reading scroll and unsaved Settings drafts; resize the window and vary Header/Footer content. Confirm no overlap between native webpages, trusted controls and scroll regions.
2. Create/select/close ordinary pages; use URL entry, back/forward/reload, many tabs and loading/error states. Hide/show Browser and verify the same Page IDs, history and Session. Check shared CARSI, scoped Services with identical names, Manual, Popup, reused ImportPage and attachment helper pages without creating placeholder pages.
3. Resize/collapse Services and restart; verify valid preferences restore, narrow windows constrain effective size, and returning to a wide window restores the user width. The app starts in Allfold without creating pages solely to restore preferences.
4. With an authorized task, check background page creation/navigation does not switch or focus the user's current page, while explicit **查看任务页面** reaches the existing task page. Active task pages cannot be closed. Check popup, context menu, DevTools and guarded cache/site-data commands against the main host.
5. Open History, Settings and Paper Tools dialogs while Browser is visible; verify the native view is hidden while needed and restores the same page. During fullscreen Run/Kept manual handoff, Browser must remain fully usable and returning must retain the current workflow and legal Continue/Cancel controls.
6. Test Archive disabled on fresh preferences, legacy Paper links, missing Papers, Workspace refresh and busy guards. Re-enable Archive and verify its existing layout/resources and ARRAY's shared reader remain usable.
7. Run OpenAlex, Crossref, PubMed and authorized WoS in both presentation modes, including cancellation and interrupted polling recovery. Verify inline mode allows safe navigation, records completion/history and refreshes results without forcing a workspace change.
8. Prepare/Import in both modes with authorized CARSI/Manual Service/CAPTCHA and Zotero. Check login waiting, explicit Continue, Cancel, transition, success/error, terminal acknowledgement and restart restoration. Inspect actual parent-item and PDF results separately; never retry an uncertain save solely because presentation changed.

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
