# Third-party sources and distribution

## Scope and notices

Python project code remains MIT under [LICENSE](../LICENSE). Electron host adapters and the Zotero translation/saving implementation are separate AGPL-3.0-or-later code; see [Electron NOTICE](../electron/NOTICE.md) and [COPYING](../electron/COPYING). Folder names alone do not determine license scope. Dependencies and assets retain their individual terms.

- Frontend source assets and complete notices: [SOURCES](../frontend/ui/SOURCES.md) and [licenses](../frontend/ui/licenses/).
- Browser identity: unmodified UserAgent-Switcher source and embedded UAParser notices under [third-party](../electron/third-party/useragent-switcher/SOURCE.md).
- Python and npm dependencies: `uv.lock`, `electron/package-lock.json` and `tools/package-lock.json`.
- Pydoll 3.0.0: public APIs are used by the Python adapter; retain the MIT notice described in Electron NOTICE. No separate Chromium is supplied by this integration.


## Fixed official Zotero inputs

[upstream.lock](../electron/upstream.lock) is the sole production revision authority for official Zotero inputs. It records the public sources and exact revisions for Connectors, its three required submodules (Translate, Utilities and Zotero Schema) and the complete Translators repository. Connectors retains its official five Gitlinks and `.gitmodules`; Desktop and Google Docs Integration are unused and are neither initialized nor deleted by Setup.

Run `npm --prefix electron run setup` from the project root to obtain the public repositories and exact revisions. The assembler validates revisions, required Connector Gitlinks in HEAD and index, pristine tracked/untracked status and actual input bytes against the pinned Git blobs. Unused existing Desktop/Google Docs directories are excluded from superproject status; each required child is checked independently. Modified or unknown source is rejected rather than reset. Full [preparation instructions](development.md) and the [assembler](../electron/scripts/prepare-runtime.cjs) are included.

Official inputs remain unchanged under ignored `electron/vendor/`. Project HTTP/document, browser and saving adaptations live in Electron host source. Runtime preserves individual headers and fills the upstream schema placeholder with pinned schema data. Its manifest records generated-file ownership, not source authority or functional acceptance. No extension overlay or private upstream patch is applied.

## Corresponding source

Redistribution must preserve applicable licenses and provide corresponding source when required, including host adaptations, exact upstream source, locks and necessary assembly instructions. Public lock URLs and setup describe the source inputs; a lock file alone does not replace corresponding-source delivery obligations. A packaged distribution must verify source availability, notices and the materials actually delivered with the binary.

The Python package does not contain Electron source or its vendor tree. Consult [release preparation](release.md) before distributing combined application artifacts. Historical acquisition and investigation records remain outside the source distribution and are not build inputs.

## Retained translation components

Runtime retains official Web/Search/Import Translate, the complete 752-entry Translator registry at the locked revision and dynamically loaded ID-named Translator code. `translate/translation/translate_item.js` supplies the virtual `Zotero.Translate.ItemSaver`; the host converts its output to JSON only. It has no Connector/Desktop/cloud writer. Common `itemSaver.js`, `itemSaver_background.js` and their exclusive BotBypass dependency are no longer shipped.

Shared `common/http.js`, `inject/http.js` and the ordered Translate HTTP bootstrap remain for official Translator utilities, document parsing and HTTP behavior. Common Utilities provides DOM selectors; Proxy/TLD data provides URL normalization; Schema, date formats, Utilities and the RDF stack support dynamically loaded Web/Search/Import translators. The project-owned document/charset and HTTP adapters remain outside pristine Vendor source. See [Electron NOTICE](../electron/NOTICE.md) for license scope and [Local API behavior](zotero-local-api.md) for current saving compatibility.

Preserve the original per-file notices: most Zotero modules and Translators are AGPL-3.0-or-later, XRegExp embeds MIT notices, and RDF files retain their own notices including the W3C notice in `rdfparser.js`. The Runtime contains the official `COPYING`; the lock and manifest do not replace these licenses or corresponding-source obligations.
