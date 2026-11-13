# Third-party sources and distribution

Python project code remains MIT under [LICENSE](../LICENSE). Retained Electron
host adapters and adapted Browser/Document sources remain AGPL-3.0-or-later; see
[Electron NOTICE](../electron/NOTICE.md) and [COPYING](../electron/COPYING).
Dependencies and assets retain their individual terms.

- Frontend assets and complete notices: [SOURCES](../frontend/ui/SOURCES.md) and
  [licenses](../frontend/ui/licenses/).
- Browser identity: unmodified UserAgent-Switcher and embedded UAParser notices
  under [third-party](../electron/third-party/useragent-switcher/SOURCE.md).
- Python/npm locks: `uv.lock`, `electron/package-lock.json`, `tools/package-lock.json`.
- Pydoll 3.0.0: the Python adapter uses public APIs; retain its MIT notice from
  Electron NOTICE. No additional Chromium is supplied by that integration.

WF02 retires Zotero Local API and attachment communication, active Enrich, the
uncalled Translator sandbox and its generated Runtime assembly. Setup and CI no
longer obtain or assemble those exclusive dependencies. Existing ignored vendor
checkouts remain untouched. [upstream.lock](../electron/upstream.lock) retains
historical source attribution for pinned sources from which retained adaptations
were derived; it is not an active build/download dependency.

BrowserRuntime, isolated Document preload/page inspection, Prepare/WoS/Login/Covers,
Cloudflare and browser identity remain production mechanisms. Their host-owned
code and embedded notices remain included. No upstream source is patched or
silently relabeled when a former product caller is retired.

Redistribution must retain all applicable licenses and supply corresponding
source where required, including retained host adaptations and necessary build
instructions. A lock/notice alone does not replace corresponding-source delivery
obligations. Python's package excludes Electron/vendor trees; see
[release preparation](release.md) before distributing combined artifacts.

WF03 removes the remaining remoteTranslate-derived full-page serializer and
translation-only frame/cookie/observer helpers. No Translator source/build input
is restored. Bounded probes replace serialization; retained Browser/Document and
project-owned DOM action adaptations continue under the Electron AGPL notice.
The historical lock/other component notices remain applicable; official vendor
files and dependency pins are unchanged.

WF04 removes the unused Translator/item-saver partitioned Cookie/CDP adapter.
Browser identity, Chromium's native shared Session, credentials and the retained
Browser/Document/Cloudflare host notices continue unchanged in scope.
