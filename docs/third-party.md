# Third-party sources and distribution

Python project code remains MIT under [LICENSE](../LICENSE). Retained Electron
host adapters and adapted Browser/Document sources remain AGPL-3.0-or-later; see
[Electron NOTICE](../electron/NOTICE.md) and [COPYING](../electron/COPYING).
Dependencies and assets retain their individual terms.

- Frontend assets and complete notices: [SOURCES](../frontend/ui/SOURCES.md) and
  [licenses](../frontend/ui/licenses/).
- Browser identity: `browser-identity.cjs` reads the tracked unmodified
  UserAgent-Switcher Agent/Network/override and embedded UAParser files. Their
  notices, full UAParser corresponding source and MPL license remain under
  [third-party](../electron/third-party/useragent-switcher/SOURCE.md); the host
  AGPL COPYING remains included.
- Python/npm locks: `uv.lock`, `electron/package-lock.json`, `tools/package-lock.json`.
- Pydoll 3.0.0: the Python adapter uses public APIs; retain its MIT notice from
  Electron NOTICE. No additional Chromium is supplied by that integration.

Zotero Local API, attachment communication, active Enrich and the full Translator
Runtime are retired. Setup/CI no longer obtain or assemble translation-only
sources. Existing ignored vendor checkouts remain untouched.
[upstream.lock](../electron/upstream.lock) preserves historical attribution for
pinned sources from which retained adaptations were derived; it is not an active
build/download dependency.

BrowserRuntime, isolated Document preload/page inspection, Prepare/WoS/Login/Covers,
Cloudflare and browser identity remain production mechanisms. Their host-owned
code and embedded notices remain included. No upstream source is patched or
silently relabeled when a former product caller is retired.

Redistribution must retain all applicable licenses and supply corresponding
source where required, including retained host adaptations and necessary build
instructions. A lock/notice alone does not replace corresponding-source delivery
obligations. Python's package excludes Electron/vendor trees; see
[release preparation](release.md) before distributing combined artifacts.

The [PDF discovery catalogue](pdf-source-discovery.md#repositories) preserves
R/API/S records, fixed source versions and per-source license/evidence limits.
URL expressions and documented public fields are independently implemented; the
catalogue imports no Translator, Paperlib, pubpatterns or other download runtime.
An unconfirmed code license is not permission to copy source. Retained
Browser/Document/DOM-action adaptations keep their Electron AGPL notices,
regardless of the page-reading representation used by later implementations.
