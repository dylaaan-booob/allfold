# Allfold

A local-first desktop application for monitoring journals, reviewing reliably identified papers in a local SQLite library.

Version **0.1.0** is a pre-release source version. The current development and verification platform is **macOS**. Website access, institutional authentication  depend on the actual environment; offline checks do not establish compatibility with every site.

## Download app

A packaged macOS app download will be provided with the first desktop release. Until then, use the source setup below.

## Run from source

Install Git, Python 3.12, Node.js 24 and [uv](https://docs.astral.sh/uv/). Clone or extract the source ZIP and run these commands from the project root:

```sh
npm --prefix electron run setup
npm --prefix electron start
```

Setup installs locked dependencies and builds the UI. It creates a missing local configuration from `config.template.yaml`; existing configuration and API keys are preserved. A fresh setup requires access to dependency registries. See the [development guide](docs/development.md) for configuration arguments, rebuilding and troubleshooting.

## Basic workflow

1. In **Journals**, manage followed Journals, Groups, Labels and Access Services. Each configuration has its own saved scope. Import a Markdown research scope through Preview / Confirm, or export **User Data** to share it.
2. In **Workflows → Login**, authenticate CARSI once and prepare every saved Access Service. Manual Services offer a Visit action. Check each outcome in Login and use the corresponding Browser group to complete any verification. If the batch ends with Services that still need attention, check them in Browser and select **Manual confirmation of login** when all Services are available.
3. In **Workflows → Discover**, set keywords and publication months, then select PubMed, Web of Science and OpenAlex as needed. WoS uses its prepared Service page when available. After manual confirmation without a prepared page, Discover opens the official WoS query page in the shared Browser session. API discovery continues if WoS needs Login. Shared Work lookup and creation-time metadata completion preserve existing Papers. See [Provider roles and query limits](docs/providers.md).
4. Review **Candidate**, **Downloaded** and **Trash** in **Workspace / ARRAY**. Reject persists exclusion and moves the Paper to Trash. Restore keeps its UUID and existing content. In Trash, clearing metadata removes bibliography, dates, abstract, sources and notes while retaining reliable identities, exclusion and any body association. An identity-only entry can be unexcluded locally; only a later actual Run hit rebuilds its metadata.
5. In **Info**, query linked preprints for a complete, unexcluded formal article. Reader displays the ordinary date set and independent verified Preprint date; Info keeps version-family proof. Developer Mode retains local field clearing and empty-abstract input.

`Workspace/papers.sqlite` is the sole production Paper store. Run/WoS, Reader,
search, local edits, Preprint and Trash share the same repository. An unopened,
uninitialized Workspace reads as empty without silently creating a library; the
first Run initializes it explicitly. Corrupt or unsupported libraries report an
error. Existing WF01 v1 libraries receive the known preserving schema upgrade.
Paper Markdown is no longer created, scanned or read back; old Workspace data is
not migrated or deleted automatically. Repeat Run hits preserve complete saved
records. Stable direct identities also support DOI-free Papers.

Keep, Import to Zotero, Last Import and active webpage Enrich are retired.
Background collection and public Download/PDF actions are not connected in WF02.
An existing body association only classifies a Paper as Downloaded; there is no
PDF download, physical delete, open or locate action. Current Run timing and
creation-time Completion remain; collection stays `not_started`.

**Browser**, **Search** and **History** are available from the header in Workspace, Workflows, Journals and Settings. Search opens local Papers, Journals, saved Services and existing Browser tabs. Enter `>` to find a command. Browser fills the main content area and groups existing pages under CARSI, a saved Service or Other. The Tabs rail opens the grouped directory. Task controls offer **查看任务页面** to open the associated page for inspection or manual verification. Returning keeps the business view, navigation history, shared Session and active task.

Settings' **禁用全屏运行界面** keeps Discover progress inline. Login retains its
own progress and Service preparation concurrency. Login can reenter a CARSI
resource once when its captured preparation evidence remains valid. Browser
pages remain available for inspection; managed pages keep their navigation and
close protections, and idle pages allow refresh.

ARRAY and Journals keep icon rails on both sides. Hover, focus or click Index/Directory to browse without shifting the content; choose a right-hand tool to open or collapse Info/Details. Journal selection opens Details; Directory filtering closes it. Resize the Sidebar from its left edge; narrow windows use an overlay and restore the preferred width when space returns. ARRAY's Reject/Restore and Trash metadata actions stay beside the Reader. Developer Mode adds a horizontally scrolling Layout strip with independent SAVE/RESET/ORIGIN targets; Journals GRID columns always adapt to the available content width.

**HISTORY** shows recent task results across restarts and offers **导出本次诊断**.
Settings also offers **导出最近诊断** for startup or connection problems, limited to
the last seven UTC days across application starts. Task exports keep all retained
evidence for that workflow. Diagnostic packages are local downloads; sharing them
is your choice. See [local history and
diagnostics](docs/logging.md) for retention, privacy and evidence limits.

Supported Cloudflare challenges invoke the existing Solver within their owning
Browser operation. hCaptcha and MFA require manual verification.

## Local data and privacy

| Location | Content | Included in source |
| --- | --- | --- |
| `config.template.yaml` | Public starting configuration | Yes |
| `config.example.yaml` or a custom root YAML file | Local settings | No |
| `list.md` | Legacy migration seed and importable example | Yes |
| `.allfold/user-data.sqlite` | Journals, Groups, Labels and Services, isolated by configuration | No |
| `.allfold/resources.sqlite` | Shared GOKB and official CARSI resource cache | No |
| `journal-lists/journal-registry.sqlite` | Read-only Journal Registry | Yes |
| `workspace/papers.sqlite` | Paper identity, metadata, dates, exclusions and body associations | No |
| `workspace/Documents/`, Run snapshots | Managed body associations and Last Run results | No |
| `journal-assets/` | Journal covers | No |
| Electron application logs directory | Bounded configuration-scoped run history and structured diagnostics | No |
| `*.openalex-secrets.json`, `*.pubmed-secrets.json` | Optional API keys beside the configuration | No |

Submit API key replacement or clearing explicitly from the corresponding Run Provider Sidebar. PubMed and OpenAlex keys are optional. Anonymous OpenAlex queries retain first-page evidence and explicitly report incomplete coverage when cursor paging needs a key. Run settings select Discovery sources. Run uses its fixed API helpers for creation-time identity, date and relationship evidence. Optional institution credentials use Electron safeStorage separately from YAML, through the Login Access toolbar. Ordinary configuration changes save automatically; Pending, failure and conflict states retain the draft. Changes that would invalidate an active task wait until it releases configuration ownership, then recheck saved revisions. Sensitive credential changes and destructive operations keep separate explicit submission and confirmation. Discovery and page workflows contact the selected external providers and sites.

Configuration, legacy journal seed and Workspace paths must stay inside the project directory. On first use, each configuration validates and copies its legacy managed Markdown data into SQLite without changing the source file; later changes use SQLite. Include `.allfold/` in local backups. Use **Export User Data** to transfer a research scope to another configuration or application location, since canonical configuration paths identify saved scopes. Export contains no provider credentials, resource caches, Workspace papers . Legacy Markdown is a first-migration or explicit exchange source, not the live store.

Settings Reset selects one scope without requiring a typed word. **Workspace**
permanently deletes the confirmed Workspace, including its latest Run snapshots;
independent history and diagnostics survive and earlier history is marked as
pre-reset, including when the confirmed Workspace has moved out of its original
path but deletion then fails. A partial deletion remains a reported failure.
**Logs** clears only the current configuration's managed history and
diagnostics. Both preserve configuration, Journals/Services, covers,
browser authentication and already downloaded diagnostic packages. Workspace
Reset includes the SQLite library, all permanent exclusions, Documents and Run
snapshots; it is a whole-Workspace destructive operation with preview/confirmation,
path-replacement checks and task draining. It is separate from Trash actions.
Logs Reset never deletes the library, configuration or Session. Neither Reset nor
Setup overwrites existing YAML. Research Scope Markdown exchange remains
available and separate from retired per-Paper Markdown. Preserve independent
backups before upgrading a pre-release version. See [library](docs/paper-library.md)
and [research scope exchange](docs/research-scope.md).

## Development and source

- [Development](docs/development.md): prepare, build, test and troubleshoot.
- [Architecture](docs/architecture.md): module ownership and runtime data flow.
- [Safety](docs/safety.md): data and execution invariants.
- [Third-party sources](docs/third-party.md): fixed inputs, notices and corresponding source.
- [Release preparation](docs/release.md): source checks and distribution requirements.
- [AGENTS](AGENTS.md): instructions for repository work.

Python project code is MIT licensed under [LICENSE](LICENSE). Electron host adapters have separate AGPL-3.0-or-later licensing; see [Electron notices](electron/NOTICE.md) and [COPYING](electron/COPYING). Frontend assets retain their [individual sources and notices](frontend/ui/SOURCES.md).
