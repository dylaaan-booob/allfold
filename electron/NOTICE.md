# Electron / Zotero source and licensing

The Electron-side translation and saving component is separate from the MIT
Python package. This directory's host adapters and assembled Zotero runtime are
distributed under AGPL-3.0-or-later; see [COPYING](COPYING). Electron itself and
other third-party dependencies retain their upstream licenses and notices.

Official source pins:

- Zotero Connectors, all five pinned submodules and Translators: [upstream.lock](upstream.lock).
  This lock is the production source authority.
- Browser identity: UserAgent-Switcher v3 commit
  `ebef999b5996778c0d5a25ced1c45501ceae9437`, retained unmodified under
  [third-party/useragent-switcher](third-party/useragent-switcher/SOURCE.md).
  Its Agent/Network/override files retain MPL-2.0 and its embedded UAParser.js
  2.0.3 retains AGPLv3. Preserve their source, embedded notices and
  [MPL license](third-party/useragent-switcher/LICENSE) alongside this directory's
  AGPL [COPYING](COPYING). The Python wheel does not contain these files.

The runtime assembler reads those exact checkouts and preserves individual
copyright and license headers, including each Translator's source header.
It replaces only the Connector schema placeholder with the pinned schema JSON.
The ItemSaver files are copied unchanged into Layer 2 and loaded from that generated runtime;
none of the old Literature Monitor extension patches or overlays are used.
The project-owned `src/zotero/session-http.cjs` is the shared external Chromium Session
transport for the Translate Host Adapter and ItemSaver attachment adapter; it
is part of this directory's AGPL component. The Host Adapter explicitly sets
`Zotero.isManifestV3=false` and replaces only the XHR transport. The official
HTTP wrapper, Translate, Translators and ItemSaver source files are unchanged;
local Zotero Desktop API calls continue through Session.fetch. Browser identity
continues to use the existing UserAgent-Switcher adapter. Its sole request-header
listener also strips Main-only request markers and merges fresh partitioned Cookie
supplements queried through the existing CDP endpoint; only a translation-time JavaScript-readable document.cookie snapshot may enter the translation renderer; explicit Translator Cookie headers return through the existing request IPC. CDP stores remain Main-only. The project-owned src/browser/partitioned-cookies.cjs and host
adapters are part of this directory's AGPL component. Metadata-only Registry and
ID-named code files retain official Translator headers. runtime-manifest.json
records SHA-256 ownership of generated files; it is not an upstream source lock.

The project-owned CARSI, first-image and WoS DOM actions in `src/workflows/page-actions.cjs`
were retained from the project's AGPL Connector executors. They do not use an
extension runtime; source and attribution remain distributed in this directory.

Corresponding source includes this directory, the Electron lock file, the assembly
script, all locked upstream sources and their notices. Source reconstruction
follows the Electron lock and [source build instructions](../docs/development.md);
the setup entry obtains those exact upstream sources before assembly.
Redistribution must provide the corresponding source and dependency licenses;
packaged distribution must verify delivery of these materials alongside the artifact.

## Cloudflare solver dependencies

- [Pydoll (pydoll-python) 3.0.0](https://pypi.org/project/pydoll-python/3.0.0/):
  MIT, Copyright © 2025 AutoscrapeLabs.
  [Upstream source](https://github.com/autoscrape-labs/pydoll) and
  [license](https://github.com/autoscrape-labs/pydoll/blob/main/LICENSE).

The Python adapter uses Pydoll's public connection, DOM and click APIs; it does
not copy a private solver implementation. Redistributions must retain Pydoll's
MIT copyright and permission notice, including its warranty disclaimer, together
with the licenses and notices of dependencies resolved in `uv.lock`.
No additional Chromium binary is downloaded or distributed by this integration.

## Import compatibility host adapters

Official common/translateWeb.js and common/botBypass.js are copied unchanged from the existing Electron lock. Both VMs use official common/proxy.js, translate/tlds.js and Utilities quotemeta. The Layer 2 document/observer adapter follows browserExt/translateHost/translateHost.js; attachment response detection follows browserExt/browserAttachmentMonitor/browserAttachmentMonitor.js without loading its extension APIs. Host iframe/helper-tab and cancellation adapters do not patch upstream sources. All retain this directory’s AGPL-3.0-or-later and corresponding-source obligations. No upstream revision or dependency is upgraded.
