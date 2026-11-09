# Allfold

A local-first desktop application for monitoring journals, reviewing reliably identified papers and importing selected papers into Zotero.

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

1. In **Journals**, manage your followed Journals, Groups, Labels and Access Services. Each running configuration has its own saved scope. Import a Markdown research scope through Preview / Confirm, or export **User Data** to share it.
2. In **Run**, set the Monitor name, keywords and publication months. Select any nonempty combination of PubMed, Web of Science and OpenAlex for one journal-only Run. PubMed and OpenAlex are the defaults. WoS is opt-in through the institutional Browser flow. Discovery runs in parallel with shared OpenAlex Work lookup. Run resolves missing formal PubMed identities, fills available metadata and settles transient failures before protected creation of new Papers. Ordinary configuration changes save automatically. Repeat Runs leave existing Paper files untouched. See [Provider roles and query limits](docs/providers.md).
3. Review candidates in **Workspace / ARRAY**. Use Keep and Reject to manage your review. For a Paper with a formal DOI, use **查询 bioRxiv / medRxiv** in **Info** to check its publication-to-preprint links and verified version dates. Notes and other human-managed content remain in Paper Markdown. Settings defaults **禁用 Archive 视图** on. Turn it off to restore ARCHIVE.
4. Open **Kept** for the Service queue, **PREPARE & IMPORT** or **IMPORT ONLY**. Run Zotero **10.0.6 or later** with its Local API enabled, authorize Allfold with **Always Allow**, and select a Library and optional Collection in Queue. This default saves with the current configuration. Select All Services or one saved Service before starting; the batch retains its original Zotero instance, target and Service scope through Prepare, waiting and Import.

Paper Markdown is the only persisted literature object. Papers carry a primary DOI and directly saved reliable provider IDs, including DOI-free identities. First public requires an established earliest linked preprint date. The reader displays First public, Received, Accepted and Published at their verified precision. Info shows the underlying date events and sources, including separate online and print evidence. Temporary version relations and request caches end with the operation. The manual preprint lookup appends only verified preprint evidence and can fill an empty First public. Independent webpage Enrich retrieves eligible missing Abstract, Authors and publication date, retains month-to-day upgrade, and can save dates already in its response without saving a Zotero item. While verification is pending, **打开 Browser 验证** opens that task's page; returning to the Reader preserves the same Enrich task. Covers Search targets one saved Journal; Upload and Crop use local assets.

Kept opens the shared **Browser** inside the main window. Compact and Focus change its available viewport; returning to Queue retains the same pages, navigation history, authentication and tasks. Tabs and the **Services** panel select existing pages. Service groups use saved scoped identities and page associations, including shared authentication and auxiliary pages. Task controls offer **查看任务页面** when manual interaction is needed. The selected WoS stage uses its task page within the same Run; 查看任务页面 opens it for login or verification. Opening a page does not continue or cancel its task.

Settings' **禁用全屏运行界面** keeps Run progress in Run and Prepare / Import controls in Kept. It defaults off. Both modes use the same task state, confirmation and cancellation rules; Continue is available only when the workflow permits it. The choice applies when a task starts or is restored, so changing it does not restart a task. These interface preferences are saved locally. The old Run animation preference and system reduced-motion setting remain separate from fullscreen presentation.

ARRAY and Journals keep icon rails on both sides. Hover, focus or click Index/Directory to browse without shifting the content; choose a right-hand tool to open or collapse Info/Details. Journal selection opens Details; Directory filtering closes it. Resize the Sidebar from its left edge; narrow windows use an overlay and restore the preferred width when space returns. ARRAY's Keep/Reject and Kept Import controls remain in the main workspace. Developer Mode adds a horizontally scrolling Layout strip with independent SAVE/RESET/ORIGIN targets; Journals GRID columns always adapt to the available content width.

**HISTORY** shows recent task results across restarts and offers **导出本次诊断**.
Settings also offers **导出最近诊断** for startup or connection problems, limited to
the last seven UTC days across application starts. Task exports keep all retained
evidence for that workflow. Diagnostic packages are local downloads; sharing them
is your choice. See [local history and
diagnostics](docs/logging.md) for retention, privacy and evidence limits.

Parent acceptance and PDF evidence are separate. Import tries Translator PDFs first, then OpenAlex's direct public PDF locations when needed. **Last Import** shows Item, PDF and Fallback results for the latest execution, using read-only queries for the exact newly created items. A query failure shows unable to verify; a PDF attachment shell does not count as an uploaded file. Results can be filtered by their execution-time Service and are not restored after restart. Allfold does not inspect saved PDF paths or files. If a save result is uncertain, inspect Zotero before retrying. CAPTCHA, MFA and ambiguous authentication pages can require manual intervention.

## Local data and privacy

| Location | Content | Included in source |
| --- | --- | --- |
| `config.template.yaml` | Public starting configuration | Yes |
| `config.example.yaml` or a custom root YAML file | Local settings | No |
| `list.md` | Legacy migration seed and importable example | Yes |
| `.allfold/user-data.sqlite` | Journals, Groups, Labels and Services, isolated by configuration | No |
| `.allfold/resources.sqlite` | Shared GOKB and official CARSI resource cache | No |
| `journal-lists/journal-registry.sqlite` | Read-only Journal Registry | Yes |
| `workspace/` | Paper Markdown, review status and Run snapshots | No |
| `journal-assets/` | Journal covers | No |
| Electron application logs directory | Bounded configuration-scoped run history and structured diagnostics | No |
| Electron application user-data directory, `zotero-local-key.bin` | Protected, Server-ID-bound Zotero authorization | No |
| `*.openalex-secrets.json`, `*.pubmed-secrets.json` | Optional API keys beside the configuration | No |

Submit API key replacement or clearing explicitly from the corresponding Run Provider Sidebar. PubMed and OpenAlex keys are optional. Anonymous OpenAlex queries retain first-page evidence and explicitly report incomplete coverage when cursor paging needs a key. Run settings select Discovery sources. Run uses its fixed API helpers for creation-time identity, date and relationship evidence. Optional institution credentials use Electron safeStorage separately from YAML, through Kept Access. Ordinary configuration changes save automatically; Pending, failure and conflict states retain the draft. Changes that would invalidate an active task wait until it releases configuration ownership, then recheck saved revisions. Sensitive credential changes and destructive operations keep separate explicit submission and confirmation. Discovery and page workflows contact the selected external providers and sites. The application is not a Zotero Library mirror.

Zotero authorization keys also use Electron protected storage, associated with the Local API's Server ID. A one-use **Allow** key can expire during a multi-request import; **Always Allow** supports the complete operation. Reauthorization never replays an uncertain write. Group metadata does not establish item or file write permission: Zotero checks these separately when saving. Deleted targets, permission failures and a changed Zotero instance do not redirect imports to another Library or Collection. See the [Local API protocol and compatibility notes](docs/zotero-local-api.md) for metadata and attachment boundaries.

Configuration, legacy journal seed and Workspace paths must stay inside the project directory. On first use, each configuration validates and copies its legacy managed Markdown data into SQLite without changing the source file; later changes use SQLite. Include `.allfold/` in local backups. Use **Export User Data** to transfer a research scope to another configuration or application location, since canonical configuration paths identify saved scopes. Export contains no provider credentials, resource caches, Workspace papers or Zotero data. Legacy Markdown is a first-migration or explicit exchange source, not the live store.

Settings Reset selects one scope without requiring a typed word. **Workspace**
permanently deletes the confirmed Workspace, including its latest Run snapshots;
independent history and diagnostics survive and earlier history is marked as
pre-reset, including when the confirmed Workspace has moved out of its original
path but deletion then fails. A partial deletion remains a reported failure.
**Logs** clears only the current configuration's managed history and
diagnostics. Both preserve configuration, Journals/Services, covers, Zotero,
browser authentication and already downloaded diagnostic packages. Rebuilding an old configuration requires explicitly backing up/replacing its YAML from the new template; Workspace Reset and rerunning Setup do not overwrite that YAML or delete user-state SQLite. Follow the [configuration reinitialization steps](docs/providers.md#old-data-and-manual-acceptance). The unified Run snapshot-only v6 upgrade requires a new Run; it does not require Workspace Reset or configuration reconstruction. Older snapshots are preserved and unsupported Integrated snapshots show a rerun prompt. Legacy WoS files are not converted into unified results. Paper identity fields `identity_aliases` and `related_dois` are unsupported, even when empty: affected old Papers explicitly block safe indexing and writes. No old Workspace is automatically migrated, deleted or rewritten; obsolete Evidence directories are unused and preserved. Back up important data before explicitly rebuilding through Settings → Reset → Workspace. This does not require configuration reconstruction. Keep independent
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
