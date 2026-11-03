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

Python HTTPX callers share the [HTTP client and proxy layer](http.md). Its focused
tests cover isolated request routing, TLS, transport lifecycle and cache failures;
Chromium authentication remains a separate manual acceptance boundary.

## Troubleshooting

- Missing `.venv`, UI, vendor or Runtime: complete setup and inspect the failing step.
- Modified vendor or Runtime: inspect the reported path. Preserve unknown files; do not use reset/clean to make verification pass.
- Download failure: correct connectivity to the named registry or GitHub before rerunning setup. Dependency pins remain unchanged.
- Need application diagnostics: use `ALLFOLD_LOG_LEVEL=debug npm --prefix electron start`. Supported levels are debug, info, warn and error. Application logs go to stderr; no automatic log file is created. Raw Chromium stderr can contain addresses, so inspect output before sharing.

See [architecture](architecture.md) before changing ownership and [safety](safety.md) before changing data, authorization or settlement paths.
