# Allfold repository work

Allfold is an Electron-managed Python application with a Web UI. Keep changes within the requested behavior and preserve unrelated edits and real user data.

## Read by task

- User behavior or supported operations: read [README](README.md).
- Module ownership, source moves or cross-runtime changes: read [architecture](docs/architecture.md).
- Setup, dependencies, builds, tests or CI: read [development](docs/development.md) and the actual scripts being changed.
- Persistence, paths, IPC, browser authority, cancellation or native saving: read [safety](docs/safety.md), then its linked implementation and relevant tests.
- Third-party code, assets or redistribution: read [third-party sources](docs/third-party.md) and the affected module's notices.
- Version or release configuration: read [release preparation](docs/release.md).

## Working requirements

- Use isolated test files and transports. Preserve local configuration, credentials, Workspace, covers and Zotero data unless the user explicitly authorizes their modification.
- Keep official vendor sources pristine. Adapt in host code; generate UI and Runtime through their build scripts.
- For changed behavior, update callers and focused safety checks. Run checks appropriate to the change and distinguish source/build evidence from rendered UI and real-site/Zotero acceptance. Browser control requires task-specific user consent.
- Include source, necessary helpers and non-sensitive fixtures; keep generated resources, environments, local data, credentials and reports out of public candidates.
- Keep dependency pins and product scope unless their change is authorized. Repository initialization, commits, push, tags, publishing and deployment require explicit authorization for the action; existing authorization remains valid within its scope.

## Agent skills

### Issue tracker

Track work in this repository's GitHub Issues. See docs/agents/issue-tracker.md.

### Triage labels

Use the default five triage labels. See docs/agents/triage-labels.md.

### Domain docs

Use the single-context domain layout. See docs/agents/domain.md.
