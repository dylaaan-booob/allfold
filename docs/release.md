# Release preparation

## Current delivery

The repository supplies source and a reproducible preparation entry. There is no configured desktop installer build, signing/notarization job or automatic release workflow. Resource builds generate UI; they do not generate an installer. README reserves the future macOS app download entry.

## Source candidate checks

1. Keep project version fields in `pyproject.toml`, the project entry of `uv.lock`, `electron/package.json` and its lockfile consistent. A project version change does not imply a dependency or upstream revision upgrade.
2. Verify candidate files exclude local YAML, API keys, `.allfold/` user-state and resource databases (including SQLite sidecars), Workspace, covers, Obsidian state, Registry raw inputs, environments, vendor/Runtime, generated UI and reports. Include the public template, example `list.md`, read-only Registry SQLite, test sources and necessary non-sensitive fixtures. The example Markdown is a migration/import seed, not a copy of a user's database.
3. Run the [development checks](development.md#checks), including setup in a clean candidate copy. Inspect the actual CI result after a push; local checks are separate evidence.
4. Check document/resource links, source pins, license scope and corresponding-source availability using [third-party sources](third-party.md).
5. Record manual verification and unverified workflows accurately. Do not infer website, actual-PDF acceptance from source tests or parent acceptance alone.

## Before distributing a packaged app

Define and validate the installer build, bundled Python/UI content, platform support and signed/notarized artifact. Deliver applicable corresponding source and dependency notices, then verify an installed artifact with isolated local state. Signing credentials belong in an approved secret channel, not repository files.

Repository creation, commits, tags, publishing and credentials require explicit authorization covering those actions. This document does not configure or authorize a release.

WF02 retires translation-only Runtime assembly and Zotero Local API product paths.
A clean source setup installs locked dependencies and builds UI without fetching
vendor repositories. Existing vendor/Runtime/user data remain excluded from public
candidates and are not deleted by setup. Preserve notices for retained adapted
Browser/Document/Prepare and Cloudflare sources. Public Download and PDF actions
remain future workflow tasks; body-association projection is not file acceptance.
