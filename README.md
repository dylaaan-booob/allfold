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

1. In **Journals**, edit the example journal list, Groups, Labels and assigned Access Services.
2. Set keywords and publication months, save changes, then choose OpenAlex, Crossref, PubMed or Web of Science in **Run**. Runs are independent and create-only; existing Paper files are not rewritten.
3. Review candidates in **Workspace**, using ARCHIVE or ARRAY. Keep and Reject are explicit actions; notes and other human-managed content remain in Paper Markdown.
4. From ARRAY / KEPT, use **PREPARE & IMPORT** or **IMPORT ONLY**. Zotero Desktop must be running for Import. Use **BROWSER** for manual page interaction when required.

Enrich retrieves eligible missing metadata without saving a Zotero item. Covers Search targets one saved Journal; Upload and Crop use local assets. Closing BROWSER hides its window and does not cancel an active workflow.

Parent acceptance and PDF evidence are separate. If a save result is uncertain, inspect Zotero before retrying. CAPTCHA, MFA and ambiguous authentication pages can require manual intervention.

## Local data and privacy

| Location | Content | Included in source |
| --- | --- | --- |
| `config.template.yaml` | Public starting configuration | Yes |
| `config.example.yaml` or a custom root YAML file | Local settings | No |
| `list.md` | Editable journal example, Groups, Labels and Services | Yes |
| `journal-lists/journal-registry.sqlite` | Read-only journal metadata | Yes |
| `workspace/` | Paper Markdown, review status and local diagnostics | No |
| `journal-assets/` | Journal covers | No |
| `*.openalex-secrets.json`, `*.pubmed-secrets.json` | API keys beside the configuration | No |

Save API keys through Settings. Optional institution credentials use Electron safeStorage separately from YAML. Discovery and page workflows contact the selected external providers and sites. The application is not a Zotero Library mirror.

Configuration, journal list and Workspace paths must stay inside the project directory. Workspace Reset permanently deletes the entire configured Workspace after confirmation; it does not reset configuration, covers or Zotero data. Keep independent backups of important local data before upgrading a pre-release version. No cross-version migration guarantee is declared for this pre-release.

## Development and source

- [Development](docs/development.md): prepare, build, test and troubleshoot.
- [Architecture](docs/architecture.md): module ownership and runtime data flow.
- [Safety](docs/safety.md): data and execution invariants.
- [Third-party sources](docs/third-party.md): fixed inputs, notices and corresponding source.
- [Release preparation](docs/release.md): source checks and distribution requirements.
- [AGENTS](AGENTS.md): instructions for repository work.

Python project code is MIT licensed under [LICENSE](LICENSE). Electron host adapters and the Zotero integration have separate AGPL-3.0-or-later licensing; see [Electron notices](electron/NOTICE.md) and [COPYING](electron/COPYING). Frontend assets retain their [individual sources and notices](frontend/ui/SOURCES.md).
