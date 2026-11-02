# Third-party sources and distribution

## Scope and notices

Python project code remains MIT under [LICENSE](../LICENSE). Electron host adapters and the Zotero translation/saving implementation are separate AGPL-3.0-or-later code; see [Electron NOTICE](../electron/NOTICE.md) and [COPYING](../electron/COPYING). Folder names alone do not determine license scope. Dependencies and assets retain their individual terms.

- Frontend source assets and complete notices: [SOURCES](../frontend/ui/SOURCES.md) and [licenses](../frontend/ui/licenses/).
- Browser identity: unmodified UserAgent-Switcher source and embedded UAParser notices under [third-party](../electron/third-party/useragent-switcher/SOURCE.md).
- Python and npm dependencies: `uv.lock`, `electron/package-lock.json` and `tools/package-lock.json`.
- Pydoll 3.0.0: public APIs are used by the Python adapter; retain the MIT notice described in Electron NOTICE. No separate Chromium is supplied by this integration.

## Fixed official Zotero inputs

[upstream.lock](../electron/upstream.lock) is the sole production revision authority for official Zotero inputs. It records the public sources and exact revisions for Connectors, its five submodules and Translators.

Run `npm --prefix electron run setup` from the project root to obtain the public repositories and exact revisions. The assembler validates revisions, Connector gitlinks and pristine tracked/untracked status. Modified or unknown source is rejected rather than reset. Full [preparation instructions](development.md) and the [assembler](../electron/scripts/prepare-runtime.cjs) are included.

Official inputs remain unchanged under ignored `electron/vendor/`. Project HTTP/document, browser and saving adaptations live in Electron host source. Runtime preserves individual headers and fills the upstream schema placeholder with pinned schema data. Its manifest records generated-file ownership, not source authority or functional acceptance. No extension overlay or private upstream patch is applied.

## Corresponding source

Redistribution must preserve applicable licenses and provide corresponding source when required, including host adaptations, exact upstream source, locks and necessary assembly instructions. Public lock URLs and setup describe the source inputs; a lock file alone does not replace corresponding-source delivery obligations. A packaged distribution must verify source availability, notices and the materials actually delivered with the binary.

The Python package does not contain Electron source or its vendor tree. Consult [release preparation](release.md) before distributing combined application artifacts. Historical acquisition and investigation records remain outside the source distribution and are not build inputs.
