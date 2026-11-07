# Journal discovery and explicit metadata completion

Allfold exposes three independent operations. **Integrated Run** discovers and saves reviewable journal Papers. **API 补全** operates on selected saved non-Rejected Papers after review, without requiring Keep or a recent Run. **网页 Enrich** retains its independent Translator workflow. Finishing a Run, opening results, changing selection or API completion never starts either of the other operations.

## Provider roles

| Provider | Integrated Run | Explicit API completion |
| --- | --- | --- |
| OpenAlex | Saved ISSNs → verified Source, scoped title/abstract/keywords and publication dates | Known DOI/Work ID and explicit location identifiers |
| Europe PMC | Saved ISSNs, `TITLE_ABS` / `KW`, `FIRST_PDATE`, core results | Known DOI, source/record ID, PMID/PMCID, explicit preprint/version relations |
| Crossref | None | Known DOI metadata, named dates and explicit same-work relations |
| arXiv | None | Known arXiv ID through `id_list`; Atom `published` establishes the first-version date |
| bioRxiv / medRxiv | None | Platform-appropriate `details`/`pubs` lookups for known preprint or formal DOIs |
| DBLP | Disabled | Disabled |
| WoS | Separate existing browser workflow | Outside this operation |

Run's `enabled_providers` defaults to OpenAlex and Europe PMC; either can be selected alone. The separate `completion_providers` defaults to OpenAlex, Europe PMC, Crossref, arXiv, bioRxiv and medRxiv. Saved YAML, autosave, Settings checkboxes, runtime validation and dispatch use these separate lists. No failed/unselected provider silently enables another. OpenAlex credentials retain their explicit submission mechanism; Crossref's optional contact is separate from discovery.

DBLP's offline Conference Registry, Series management, reliable Paper identities and Research Scope exchange remain available. The obsolete journal-to-Stream map is removed; DBLP network retrieval remains disabled. Conference configuration does not become an executable Run scope or produce a missing-DBLP Partial result. A Run needs at least one followed Journal. See [Research Scope](research-scope.md) for offline management.

## Queries and dates

The shared parser accepts `AND`, `OR`, parentheses, adjacent quoted phrases and a word-final `*` with at least four preceding characters. `NOT`, proximity, internal/leading wildcards, `?` and malformed groups fail validation. Compilers preserve Boolean grouping and approved fields; no natural-language generation or full-collection scan is added.

OpenAlex uses `search.title_abstract_keywords` (the scoped `.exact` variant for prefixes), verified `primary_location.source.id`, `from_publication_date` and `to_publication_date`. Europe PMC combines verified ISSNs, `TITLE_ABS`/`KW` and native `FIRST_PDATE:[start TO end]`, requesting core metadata. Both adapters exhaust accessible pages, validate envelopes/cursors and report failures or incomplete pagination without arbitrary application page/record quotas. Legal native hits are not subjected to local keyword or date rechecking.

The requested publication range belongs to discovery. Later preprint, Accepted, online or print dates never remove a Paper from its original Run. A source's year/month precision remains year/month precision; no same-version date lookup rejudges monthly eligibility. [Paper identity](paper-identity.md) defines First public and named journal dates.

## Run results and snapshots

`RunFacts` is the shared source of Paper counts, statistics, issues and completion
time for results and History. Integrated Run records retrieval completeness in
`details.discovery_status` and per-source observations in `provider_runs`.
OpenAlex and Europe PMC failures use the common Discovery category while their
messages and source rows retain the actual provider and Journal. WoS retains its
query completion, Journal Coverage, export batches, date hints and diagnostics.
Cancelled, failed, partial retrieval, capture issues and successful empty results
remain distinct. The old OpenAlex Coverage and standalone discovery contracts
have no production role and are removed.

Snapshot formats have separate versions and readers:

- Integrated Run writes schema **v5** to `Workspace/.allfold/last-integrated-run.json`.
  Its only top-level fields are `schema_version`, `provider`,
  `resolved_date_range`, `outcome` and `facts`; there is no `coverage` array.
- An old Integrated Run **v4** snapshot returns `unsupported` with a rerun prompt.
  Reading leaves it untouched. A new explicit Run writes the current result;
  no migration, Workspace Reset or configuration reconstruction is needed for
  this snapshot-only change.
- WoS continues to write and read its existing **v4** format in
  `Workspace/.allfold/last-wos-run.json`. Integrated's version does not govern it.

Malformed or mismatched records and unsafe paths remain invalid; missing files
remain not found, and I/O failures retain their error. Snapshot writes retain
Workspace binding, directory/path identity checks and atomic create/replace.
A snapshot failure is reported without reversing Paper creates or changing the
actual counts. History remains independent of Workspace snapshots.

## Evidence handoff and API completion

Run retains compact structured records under Workspace `Evidence/<Paper UUID>.json`, with provider provenance, target Journal/ISSNs, query range, reliable identifiers, explicit related identities, locations, versions and date facts. Rediscovery appends new facts there even when the existing Paper itself is skipped byte-for-byte. No HTTP response archive, persistent task queue, checkpoint engine or background refresh is added.

In Workspace, open **API 补全**, select one or more saved non-Rejected Papers and explicitly start. The current Paper is selected initially when available; the selection also includes older saved and exported Papers. Rejected Papers are excluded. After restart, the operation rebuilds its task from saved Paper identity and evidence. There is no permanent Paper-complete flag: another explicit invocation remains possible.

Completion follows reliable identities and explicit version relations until targets are exhausted. Every provider/namespace/identifier is requested at most once per operation, including shared targets across Papers and failures. Native details returned during a formal-DOI reverse lookup are also reused for a separately selected preprint. Sufficient saved first-version evidence avoids unnecessary native lookups for that version family; another family's later-only, undated or conflicting evidence remains unresolved and can trigger its targeted lookup. New reliable identifiers can generate further queries. arXiv DOI/IDs route to arXiv and share the same writeback identity, while a known bioRxiv/medRxiv platform constrains its details lookup; formal DOI reverse lookup uses platforms that support it. No title/author fuzzy matching is used.

OpenAlex `locations` retains recognizable DOI, arXiv and native preprint URLs, PDF/landing locations, source and version. `related_works`, `acceptedVersion` and `is_accepted` do not establish a version relationship, a preprint or acceptance date. Europe PMC retains only explicit `Preprint in`/`Preprint of` relationships from `commentCorrectionList`; ordinary comments/corrections remain unrelated. Current `firstPublicationDate` and each `versionList.version[].firstPublishDate` keep their own record/version identity. An absent version list does not imply a single version.

API results distinguish updated Paper, unchanged Paper, excluded Paper, failure and cancellation; lookup results distinguish evidence, normal no-match, identity mismatch, failure and cancellation. One failed provider/Paper does not revoke other valid evidence or committed updates. Cancellation stops new dispatch and reports already completed safe writes. API completion has independent progress/results and History, rather than Run supplement counters.

Known bioRxiv/medRxiv preprint DOIs are queried before formal-DOI reverse lookups. Once ordinary metadata and every known preprint family's first-version evidence are sufficient, the existing gap check skips remaining native lookups. Partial results distinguish source-query problems from failed Paper processing, and successful Paper results state whether First public is recorded or still undetermined; failures remain visible.

Ordinary metadata fills empty fields only. Authors remain a whole list. Existing First public, UUID, file identity, primary identifiers, human content and workflow status remain unchanged; new relationships do not merge saved Papers or fill a formal DOI-free Paper with a preprint DOI. Date/source facts append with stable deduplication. Exact content, file/directory/Workspace identity, configuration and cancellation are rechecked before writes. API admission shares the existing Run and workflow exclusion; configuration writes, Reset and local field edits cannot bypass the active task. See [Safety](safety.md).

## HTTP and independent webpage Enrich

Both API operations use the shared HTTP client and operation-local host pacing. Temporary HTTP 500/502/503/504 requests have at most three attempts with 5/10-second default backoff. HTTP 429 uses the existing one-second fallback. Valid delta-seconds and HTTP-date Retry-After are honored without a wait ceiling; waits are cancellable. Recognized verification pages stop that provider client. Unexpected HTML/invalid envelopes are failures; a known-ID HTTP 404 or a valid empty response is normal no-match. No browser fallback or provider/route switching is added. arXiv uses three-second pacing; bioRxiv and medRxiv share their API host pacing.

Webpage Enrich still runs serially through the existing read-only Translator path, triggered by missing Abstract, Authors, publication date or an existing `YYYY-MM` date eligible for valid day upgrade. Missing First public or journal events alone never triggers it. A legitimate response can additionally contribute its already-returned explicit `accepted` and generic `date` as sourced, typed date facts, including an event-only save. Generic date never becomes First public. No new website extraction, history parser, browser batch pool or Zotero item save is added. DOI/document binding, cancellation/disconnection and exact-revision guards cover both ordinary fields and date events.

Background native pages receive a nonzero layout viewport without selecting, revealing or focusing them. Enrich exposes **打开 Browser 验证** while waiting for verification; it shows the existing task-bound page without leaving Workspace or cancelling the task. Solver targeting, interactability checks and retry limits remain unchanged.

## Old data and manual acceptance

Old dates, Provider lists and Run formats are not migrated. Workspace Reset removes only the confirmed Workspace, including Papers, Evidence and Run snapshots. It does **not** remove YAML, `.allfold/user-data.sqlite`, resource caches, covers or credentials. Normal startup, read, autosave or a configuration error never deletes these objects.

To adopt the new configuration explicitly:

1. Back up important Papers/configuration; optionally export User Data to preserve a transferable Research Scope. In the current application, preview and confirm **Settings → Reset → Workspace** only if you intend to discard that Workspace.
2. Close Allfold. Back up the selected YAML, then replace its contents with `config.template.yaml` and explicitly set the desired paths, keywords/months and source selections. Setup creates a missing default YAML but never overwrites an existing YAML; merely rerunning Setup does not rebuild an old configuration.
3. Reuse the same canonical YAML path to retain its existing Journals/Services scope in user-state SQLite. A different YAML path owns a new scope; use the existing Research Scope import/first initialization for that scope. There is no need to delete SQLite or use a factory reset. OpenAlex secret files remain beside their configuration.
4. Restart with the rebuilt configuration and run a small journal range. No old Accepted approximation or First public fallback is converted into a new event.

Use the following as a change-scoped manual reference, not a checklist required for every PR. This cleanup primarily uses automated tests and synthetic Electron/Chromium results. Select manual checks only for affected behavior not covered by those tests, using disposable configuration/data:

- Run with both sources and with either alone; inspect native date filtering, paging/partial results, source failure and cancellation. Repeat a Run and verify existing Paper bytes plus new evidence handoff.
- Reject after discovery; explicitly complete the remaining selected unkept Papers. Restart and complete older/kept/exported Papers; inspect progress, cancel/error/no-match outcomes and unchanged user content.
- For changed date or Reader behavior, inspect source/version tooltips and chronological journal events with available samples. Synthetic responses cover earliest/later-only versions, multiple version families, date conflicts and precision; a formal-only Paper has empty First public.
- For changed webpage Enrich behavior, check an available eligible request and month upgrade. Synthetic Translator responses cover explicit Accepted dates, event-only save/refresh and guarded writeback. Real rare-metadata samples are optional supplementary evidence; do not require finding an Accepted/event-only page or unusual version-conflict combination. Check DOI-free actions and offline Conference/Research Scope management when those functions change.

Existing [PR #40](https://github.com/dylaaan-booob/allfold/pull/40) acceptance includes real OpenAlex/Europe PMC Runs, linked preprint dates and OUP Enrich in isolated profiles, including task-page entry/return. Real Accepted/event-only samples were waived in favor of isolated regressions; no Zotero save was performed. These are scoped historical results, not proof of every site or this checkout.

Synthetic HTTP, rendered Electron fixtures, builds and CI establish only their tested layers. Real OpenAlex/Europe PMC responses, native preprint APIs, authenticated sites and Zotero outcomes require separately scoped acceptance.

Interface references: [OpenAlex scoped search](https://help.openalex.org/api/searching/), [OpenAlex locations](https://help.openalex.org/data/locations/), [Europe PMC REST](https://dev.europepmc.org/RestfulWebService), [Europe PMC version fields](https://europepmc.org/docs/EBI_Europe_PMC_Web_Service_Reference.pdf), [Crossref metadata](https://github.com/CrossRef/rest-api-doc/blob/master/api_format.md), [arXiv API](https://info.arxiv.org/help/api/user-manual.html), [bioRxiv/medRxiv APIs](https://api.biorxiv.org/).
