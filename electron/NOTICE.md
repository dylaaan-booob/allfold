# Electron / Zotero source and licensing

The Electron-side host component is separate from the MIT
Python package. This directory's host adapters and retained adapted Browser/Document sources are
distributed under AGPL-3.0-or-later; see [COPYING](COPYING). Electron itself and
other third-party dependencies retain their upstream licenses and notices.

Official source pins:

- Zotero Connectors, the three required pinned Translate/Utilities/Schema submodules and complete Translators: [upstream.lock](upstream.lock).
  This lock records historical source attribution for retained adaptations.
- Browser identity: UserAgent-Switcher v3 commit
  `ebef999b5996778c0d5a25ced1c45501ceae9437`, retained unmodified under
  [third-party/useragent-switcher](third-party/useragent-switcher/SOURCE.md).
  Its Agent/Network/override files retain MPL-2.0 and its embedded UAParser.js
  2.0.3 retains AGPLv3. Preserve their source, embedded notices and
  [MPL license](third-party/useragent-switcher/LICENSE) alongside this directory's
  AGPL [COPYING](COPYING). The Python wheel does not contain these files.

WF02 retires the dedicated Local API, attachment communication, active Enrich,
Translator sandbox and full generated Runtime assembly. Setup/CI no longer fetch
or assemble those exclusive sources. Existing ignored vendor checkouts are not
changed. The historical upstream lock remains source attribution for retained
adaptations, after WF03 removes the remoteTranslate-derived full-page serializer. Browser identity uses the
existing UserAgent-Switcher adapter, and partitioned Cookie/CDP state stays Main-only.
No source/license obligation for remaining adapted code is removed.

The project-owned CARSI, first-image and WoS DOM actions in `src/workflows/page-actions.cjs`
were retained from the project's AGPL Connector executors. They do not use an
extension runtime; source and attribution remain distributed in this directory.

Corresponding source includes this directory, the Electron lock file, all retained adapted sources and their notices, plus [source build
instructions](../docs/development.md).
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

## Retained host adapters

Document binding, isolated bounded preload probes, Browser/Session, Prepare,
WoS and Cloudflare remain in production. Their project-owned adaptations retain
AGPL notices. UserAgent-Switcher, UAParser and Pydoll retain their terms above.
The retired generated Translator Runtime is not an installation dependency.
No upstream revision or dependency is upgraded.
