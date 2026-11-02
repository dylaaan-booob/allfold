# UserAgent-Switcher identity source

- Repository: https://github.com/ray-lothian/UserAgent-Switcher
- Commit: `ebef999b5996778c0d5a25ced1c45501ceae9437` (v3 manifest version 0.7.1).
- Included unmodified: `v3/agent.js`, `v3/network.js`,
  `v3/data/inject/override.js`, `v3/external/ua-parser.min.js`, and `LICENSE`.
- UserAgent-Switcher files retain MPL-2.0; the embedded UAParser.js 2.0.3 file
  retains its AGPLv3 notice (see the Electron component's `COPYING`). Its upstream
  source is https://github.com/faisalman/ua-parser-js/tree/2.0.3. The unmodified
  preferred source from `src/main/ua-parser.js` at that tag is included as
  `ua-parser.source.js`; it is not loaded by the host.
- The Electron host reads the same Agent/Network payload used in the diagnostic.
  It applies only UA and three low-entropy CH set operations, preserving high-entropy
  fields. It embeds unmodified override.js in a sandboxed session frame preload.
- Before injection, the host captures native UAData. Its high-entropy method delegates
  to Chromium, preserving missing fields and failures; only returned full browser versions
  are aligned to the Chromium runtime and the retained upstream brand order/GREASE.
- No extension worker, DNR, UI, download-on-startup, or Python dependency is added.

To reconstruct these files, download the archive for the exact commit above and
copy only the listed paths from its root. Preserve this source and its notices in
any Electron distribution; these files do not belong in the Python package.
