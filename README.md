# Allfold

A local-first desktop application for monitoring journals, reviewing DOI-bound papers and importing selected papers into Zotero.

Version **0.1.0** is a pre-release source version. The current development and verification platform is **macOS**. Website access, institutional authentication and Zotero attachments depend on the actual environment; offline checks do not establish compatibility with every site.

## Download app

A packaged macOS app download will be provided with the first desktop release. Until then, use the source setup below.

## Run from source

Install Git, Python 3.12, Node.js 24 and [uv](https://docs.astral.sh/uv/). Clone or extract the source ZIP and run these commands from the project root:

```sh
npm --prefix electron run setup
npm --prefix electron start
```

Setup installs locked dependencies, obtains fixed Zotero sources, builds the UI and assembles Runtime. It creates a missing local configuration from `config.template.yaml`; existing configuration and API keys are preserved. A fresh setup requires access to GitHub and dependency registries. See the [development guide](docs/development.md) for configuration arguments, rebuilding and troubleshooting.

## Basic workflow

1. In **Journals**, manage your followed Journals, Groups, Labels and default Access Services. Each running configuration has its own saved scope. Import a Markdown research scope through Preview / Confirm, or export **User Data** to share it.
2. Set keywords and publication months, save changes, then choose OpenAlex, Crossref, PubMed or Web of Science in **Run**. Runs are independent and create-only; existing Paper files are not rewritten.
3. Review candidates in **Workspace / ARRAY**, using CANDIDATES and KEPT. Keep and Reject are explicit actions; notes and other human-managed content remain in Paper Markdown. Settings defaults **禁用 Archive 视图** on; turn it off to restore ARCHIVE.
4. From ARRAY / KEPT, use **PREPARE & IMPORT** or **IMPORT ONLY**. Zotero Desktop must be running for Import. Use **BROWSER** for manual page interaction when required.

Enrich retrieves eligible missing metadata without saving a Zotero item. Covers Search targets one saved Journal; Upload and Crop use local assets.

**BROWSER** opens a work view inside the main window. Return to Allfold to resume the same business page and draft. Tabs and the collapsible, resizable **Services** panel select the same existing pages; hiding Browser keeps their navigation history, authentication and tasks. Services groups use saved scoped Service identities and existing page associations, including shared authentication and auxiliary pages. Task controls offer **查看任务页面** when manual interaction is needed. Opening a page does not continue or cancel its task.

Settings' **禁用全屏运行界面** keeps Run progress in Run and Prepare / Import controls in ARRAY / KEPT. It defaults off. Both modes use the same task state, confirmation and cancellation rules; Continue is available only when the workflow permits it. The choice applies when a task starts or is restored, so changing it does not restart a task. These two interface preferences are saved locally, independently of configuration Save. The old Run animation preference and system reduced-motion setting remain separate from fullscreen presentation.

ARRAY and Journals keep icon rails on both sides. Hover, focus or click Index/Directory to browse without shifting the content; choose a right-hand tool to open or collapse Info/Details. Journal selection opens Details; Directory filtering closes it. Resize the Sidebar from its left edge; narrow windows use an overlay and restore the preferred width when space returns. ARRAY's Keep/Reject and Kept Import controls remain in the main workspace. Developer Mode adds a horizontally scrolling Layout strip with independent SAVE/RESET/ORIGIN targets; Journals GRID columns always adapt to the available content width.

**HISTORY** shows recent task results across restarts and offers **导出本次诊断**.
Settings also offers **导出最近诊断** for startup or connection problems, limited to
the last seven UTC days across application starts. Task exports keep all retained
evidence for that workflow. Diagnostic packages are local downloads; sharing them
is your choice. See [local history and
diagnostics](docs/logging.md) for retention, privacy and evidence limits.

Parent acceptance and PDF evidence are separate. If a save result is uncertain, inspect Zotero before retrying. CAPTCHA, MFA and ambiguous authentication pages can require manual intervention.

## Local data and privacy

| Location | Content | Included in source |
| --- | --- | --- |
| `config.template.yaml` | Public starting configuration | Yes |
| `config.example.yaml` or a custom root YAML file | Local settings | No |
| `list.md` | Legacy migration seed and importable example | Yes |
| `.allfold/user-data.sqlite` | Journals, Groups, Labels and Services, isolated by configuration | No |
| `.allfold/resources.sqlite` | Shared GOKB and official CARSI resource cache | No |
| `journal-lists/journal-registry.sqlite` | Read-only journal metadata | Yes |
| `workspace/` | Paper Markdown, review status and local diagnostics | No |
| `journal-assets/` | Journal covers | No |
| Electron application logs directory | Bounded configuration-scoped run history and structured diagnostics | No |
| `*.openalex-secrets.json`, `*.pubmed-secrets.json` | API keys beside the configuration | No |

Save API keys through Settings. Optional institution credentials use Electron safeStorage separately from YAML. Discovery and page workflows contact the selected external providers and sites. The application is not a Zotero Library mirror.

Configuration, legacy journal seed and Workspace paths must stay inside the project directory. On first use, each configuration validates and copies its legacy managed Markdown data into SQLite without changing the source file; later changes use SQLite. Include `.allfold/` in local backups. Use **Export User Data** to transfer a research scope to another configuration or application location, since canonical configuration paths identify saved scopes. Export contains no provider credentials, resource caches, Workspace papers or Zotero data. Conferences are outside the new scope model and remain only in the untouched legacy source.

Settings Reset selects one scope without requiring a typed word. **Workspace**
permanently deletes the confirmed Workspace, including its latest Run snapshots;
independent history and diagnostics survive and earlier history is marked as
pre-reset, including when the confirmed Workspace has moved out of its original
path but deletion then fails. A partial deletion remains a reported failure.
**Logs** clears only the current configuration's managed history and
diagnostics. Both preserve configuration, Journals/Services, covers, Zotero,
browser authentication and already downloaded diagnostic packages. Keep independent
backups of important local data before upgrading a pre-release version. See
[research scope exchange](docs/research-scope.md) for Markdown and Service resolution.

## Development and source

- [Development](docs/development.md): prepare, build, test and troubleshoot.
- [Architecture](docs/architecture.md): module ownership and runtime data flow.
- [Safety](docs/safety.md): data and execution invariants.
- [Third-party sources](docs/third-party.md): fixed inputs, notices and corresponding source.
- [Release preparation](docs/release.md): source checks and distribution requirements.
- [AGENTS](AGENTS.md): instructions for repository work.

Python project code is MIT licensed under [LICENSE](LICENSE). Electron host adapters and the Zotero integration have separate AGPL-3.0-or-later licensing; see [Electron notices](electron/NOTICE.md) and [COPYING](electron/COPYING). Frontend assets retain their [individual sources and notices](frontend/ui/SOURCES.md).
