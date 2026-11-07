# Journal discovery and explicit metadata completion

Allfold exposes three independent operations. **Run** discovers and saves reviewable journal Papers. **API 补全** operates on selected saved non-Rejected Papers after review, without requiring Keep or a recent Run. **网页 Enrich** retains its independent Translator workflow. Finishing a Run, opening results, changing selection or API completion never starts either of the other operations.

## Provider roles

| Provider | Run Discovery | Run automatic / explicit API completion |
| --- | --- | --- |
| PubMed | Merged saved ISSNs, native Title/Abstract keywords and publication dates; ESearch History + EFetch | Confirmed formal PMID, ESummary v2 dates/relations, EFetch only for missing bibliography |
| OpenAlex | Merged `primary_location.source.issn`, native title/abstract/keyword search and publication dates | Shared exact DOI/Work lookup and complete locations |
| WoS | Parallel native ISSN/eISSN, keyword/date query and verified eight-option Plain Text export | Formal bibliography and returned dates; no API completion client |
| Europe PMC | None | Confirmed formal PMID + `HAS_PREPRINT:Y`, known PPR identifiers and explicit preprint relations |
| Crossref | None | Exact DOI metadata, named dates, direct and reverse preprint relationships |
| arXiv | None | Known arXiv IDs through batched `id_list`; Atom `published` establishes the first-version date |
| bioRxiv / medRxiv | None | Known platform preprint DOI `details`; formal DOI `pubs` reverse lookup only in explicit API completion |

Run's `enabled_providers` accepts PubMed, WoS and OpenAlex in any nonempty combination and defaults to PubMed + OpenAlex. WoS never enables institutional Browser access automatically. The independent `completion_providers` defaults to PubMed, OpenAlex, Europe PMC, Crossref, arXiv, bioRxiv and medRxiv. Run always declares its internal Work/date/relationship APIs separately from these Discovery choices and from the independent completion selection. Provider aliases, ordering, Settings forms, expression previews and runtime dispatch use the same IDs.

PubMed and OpenAlex keys are optional, explicitly submitted to revision-checked local 0600 secret files beside the YAML; ordinary autosave, draft recovery, snapshots and diagnostics contain no keys. PubMed anonymous pacing is at least 0.35 seconds and keyed pacing at least 0.11 seconds. Keyed Entrez requests use form POST so the key does not enter request URLs. Crossref contact/mailto remains optional. Obsolete PubMed query fields, Europe PMC Discovery selections and old Provider orders are rejected with `config.template.yaml` reconstruction guidance; no startup or validation deletes user data.

A Run needs at least one followed Journal. See [Research Scope](research-scope.md) for Journal management.

## Queries and dates

The shared parser accepts `AND`, `OR`, parentheses, adjacent quoted phrases and a word-final `*` with at least four preceding characters. `NOT`, proximity, internal/leading wildcards, `?` and malformed groups fail validation. Compilers preserve Boolean grouping and approved fields; no natural-language generation or full-collection scan is added.

PubMed compiles the shared AST into explicit `[Title/Abstract]` terms, including phrases and supported prefixes. It merges followed ISSN/eISSNs with native `[Date - Publication]` bounds, retrieves and validates the complete ESearch PMID set, reuses History Server and batches EFetch. Searches beyond the 9999-ID transport window are split by publication day range; a single day still above the window reports incomplete coverage rather than truncating. Missing DOI does not discard a reliable PMID. EFetch retains direct article identifiers, bibliography, native journal identities, independent publication/history events and explicit version references. Entrez application errors inside HTTP 200 are failures.

OpenAlex uses `search.title_abstract_keywords` (the `.exact` variant for prefixes), merged `primary_location.source.issn`, `from_publication_date` and `to_publication_date`. At most 100 OR values and a 6000-character encoded-parameter budget split batches; normal Discovery does not resolve Sources per ISSN. Returned primary-source ISSNs map each Work to its followed Journal. Missing/mismatched source identity cannot expand scope. Accessible pages validate totals, Work identities and cursor progress. Individual parse or singleton-detail failures retain valid neighboring records and later pages with partial coverage; a valid Work without a title remains an identity candidate for ordinary-field completion. Anonymous basic first-page queries are supported; further cursor paging requires the optional key and reports incomplete coverage when unavailable. Native hits are never subjected to a second local keyword/date filter.

Selected PubMed, WoS and OpenAlex Discovery overlap within one parent Run, slot, workflow, cancellation signal and captured configuration/Workspace. WoS retains CARSI, Browser ownership and the [native export contract](wos-export.md). Verified PubMed/HTTP pages and WoS batches feed formal DOIs into a shared bounded Work-location queue while discovery continues. Exact DOI/Work batches map returned identities independently of response order, cache confirmed full evidence/no-match/failure and drain the final short batch. Discovery and locator share OpenAlex full details, in-flight exact requests and host pacing. Shortened authorships/locations require a verified exact Work singleton; unresolved caps and failed pages remain limitations. Work lookup only adds evidence for discovered candidates. Work-level PMID/PMCID values on formal records remain related identifiers and cannot overwrite a directly confirmed formal PMID.

Before creation, all saved Papers including Rejected participate in direct-identity conflict checks. Run completes only new candidates and preserves existing Paper bytes. Ordinary fields use fixed source priority with formal WoS bibliography first; author lists remain whole. Completion responses and version relationships never become extra Discovery candidates. Only reliable direct identifiers establish ownership; conflicting saved owners are skipped and reported. Counts derive from distinct candidates, completion activity and actual protected creates.

Ordinary-field gaps use the same direct formal-identity chain as final creation. A related preprint or association-only Work cannot satisfy a formal root's missing title, authors, abstract or source, even when that Work is labelled journal. A formal PMID with such gaps requests EFetch; complete formal bibliography needs only ESummary for remaining date/relationship goals. Independently selected preprint Papers retain their own ordinary-metadata completion.

Completion activity distinguishes **Base API completion** from **Native version verification** per provider. Actual HTTP dispatches and responses refresh activity, including paginated batches; the counters count requests rather than Papers. Cache reuse emits no HTTP activity or request count. Cancellation stops new dispatch and prevents cancelled responses from reporting completion activity.

Each HTTP Discovery source reports its settled status and retained-record count as soon as it finishes, even while WoS is waiting for user verification. A finished or failed source therefore does not retain its initial discovery activity until the whole phase ends.

The requested publication range belongs to discovery. Later preprint, Accepted, online or publication dates never remove a Paper from its original Run. A source's year/month precision remains year/month precision; no same-version date lookup rejudges monthly eligibility. [Paper identity](paper-identity.md) defines First public and named journal dates.

## Run results and snapshots

`RunFacts` is the shared source of Paper counts, statistics, issues and completion
time for results and History. Integrated Run records retrieval completeness in
`details.discovery_status` and per-source observations in `provider_runs`.
PubMed and OpenAlex failures use the common Discovery category while their
messages and source rows retain the actual provider and Journal. WoS retains its
query completion, Journal Coverage, export batches, date hints and diagnostics.
Cancelled, failed, partial retrieval, capture issues and successful empty results
remain distinct. The old OpenAlex Coverage and standalone discovery contracts
have no production role and are removed.

The selected-source Run has one current snapshot contract:

- Integrated Run writes schema **v6** to `Workspace/.allfold/last-integrated-run.json`.
  Its only top-level fields are `schema_version`, `provider`,
  `resolved_date_range`, `outcome` and `facts`; there is no `coverage` array.
- An old Integrated Run **v4/v5** snapshot returns `unsupported` with a rerun prompt.
  Reading leaves it untouched. A new explicit Run writes the current result;
  no migration, Workspace Reset or configuration reconstruction is needed for
  this snapshot-only change.
- Legacy WoS **v4** files in `Workspace/.allfold/last-wos-run.json` remain untouched. They are not reconstructed into the unified Run result; run again with the desired selected sources.

Malformed or mismatched records and unsafe paths remain invalid; missing files
remain not found, and I/O failures retain their error. Snapshot writes retain
Workspace binding, directory/path identity checks and atomic create/replace.
A snapshot failure is reported without reversing Paper creates or changing the
actual counts. History remains independent of Workspace snapshots.

## Paper-only persistence and API completion

Paper Markdown is the only persisted literature object. Run creates new Papers
and never updates existing Papers or independent Evidence files. Provider records
are temporary normalization/query/date inputs; there is no cross-operation Evidence
handoff, permanent relation graph, request cache, background sync or response archive.
Run snapshots, configuration, Registry, History/Diagnostics and Zotero state retain
their separate business storage.

In Workspace, open **API 补全**, select one or more saved non-Rejected Papers and explicitly start. The current Paper is selected initially when available; the selection also includes older saved and exported Papers. Rejected Papers are excluded. After restart, the operation rebuilds its task from current Paper fields and direct external identifiers. There is no permanent Paper-complete flag: another explicit invocation remains possible.

Completion reads only the selected Paper Markdown as its persistent input. It can run with no enabled completion providers. Received, Accepted, Published online and Published are four independent journal-date goals. One existing event, complete ordinary bibliography, partial precision or a future formal publication date does not satisfy the other event goals. Ordinary title/authors/source/abstract fill only actual gaps; optional keywords, indexed terms and affiliations do not create requests. A nonempty saved `first_public_at` satisfies First public directly. Typed saved preprint dates restore temporary query/binding targets on restart, and sufficient saved version facts can fill an empty First public without another response.

The shared completion engine collects exact identifier sets across Papers. Confirmed formal PMIDs use PubMed ESummary v2 for dates/relations, or selective EFetch when full bibliography is missing; complete EFetch evidence satisfies summary capability. Europe PMC uses `SRC:MED AND HAS_PREPRINT:Y` with batched PMID clauses, plus direct known PPR IDs/DOIs. It does not read every PMID core record for ordinary metadata. Crossref exact DOI batches and reverse `relation.type:is-preprint-of` / repeated `relation.object` batches run alongside the other necessary base APIs. Exact target relations bind reverse results to each formal DOI, independently of response order; cursors exhaust every group and failed pages retain verified earlier facts with partial status. Crossref Received/Accepted assertions require explicit history semantics and valid ISO or English dates, preserving source labels and precision. Deposit, registration and indexing times never become manuscript history.

Operation-local caches distinguish PubMed summary/fetch, Crossref exact/reverse and complete Work evidence, including success, empty and failure responses. They are shared by selected Papers and discarded at completion. Already-dispatched partial facts and attributable failures settle before goal completion; cached failures never gain authority over another Paper. OpenAlex Work/locations already obtained during Discovery are reused. Every new relation enters the next shared native-version wave before final First public coverage is calculated. arXiv `id_list` spans Papers in bounded groups of 200; each group drains without a total quota. Explicit bioRxiv/medRxiv preprint DOI targets, including `10.64898/`, use native `/details` version lists. Automatic Run never makes blind formal-DOI `/pubs` probes; the independent API Completion retains this deeper fallback when no preprint family is known. Selecting a server does not establish that an unknown preprint belongs to it.

Every known family needs first-version proof. Native arXiv Atom `published`, never `updated`, establishes its first public date. Europe PMC explicit PPR version facts can establish v1; native platform details supply missing proof. Crossref `posted`, version text or a DOI suffix alone do not establish native v1. OpenAlex `related_works`, `acceptedVersion`, `is_accepted` and repository locations cannot prove First public. Only explicit validated DOI/arXiv/official-URI relations are followed; there is no title similarity matching. Europe PMC keeps `Preprint in`/`Preprint of`, version identities and native relation notes, including automatic title/first-author matching notes, in source provenance. Missing history, conflicting dates or future preprint dates remain unresolved. Cancellation and configuration/Workspace checks guard every subsequent request and batch.

API results distinguish updated, unchanged, excluded, failed and cancelled Papers; lookup results distinguish evidence, no-match, partial, identity mismatch, failure and cancellation, with response capability retained. Completion coverage distinguishes complete, partial, failed, cancelled and empty. First-public coverage independently distinguishes recorded, no association, known unresolved, conflicting evidence, service failure and cancellation. Existing First public is protected and reported recorded; new date facts already returned by other necessary requests can append without recalculating it. History retains these coverage counts. One failed source/Paper does not revoke other valid facts or completed safe writes. No permanent no-match cache, raw HTTP archive or fuzzy matching is added.

Ordinary metadata fills empty fields only. Authors remain a whole list. Existing First public, UUID, file identity, primary identifiers, human content and workflow status remain unchanged; new relationships do not merge saved Papers or fill a formal DOI-free Paper with a preprint DOI. Date/source facts append to Paper with stable deduplication. There is only one guarded Paper commit and no second Evidence write. Unsaved source records and relationships are discarded; a later invocation may query them again. Exact content, file/directory/Workspace identity, configuration and cancellation are rechecked before writes. API admission shares the existing Run and workflow exclusion; configuration writes, Reset and local field edits cannot bypass the active task. See [Safety](safety.md).

## HTTP and independent webpage Enrich

Both API operations use the shared HTTP client and operation-local host pacing. Temporary HTTP 500/502/503/504 requests have at most three attempts with 5/10-second default backoff. HTTP 429 uses the existing one-second fallback. Valid delta-seconds and HTTP-date Retry-After are honored without a wait ceiling; waits are cancellable. Recognized verification pages stop that provider client. Unexpected HTML/invalid envelopes are failures; a known-ID HTTP 404 or a valid empty response is normal no-match. No browser fallback or provider/route switching is added. arXiv uses three-second pacing; bioRxiv and medRxiv share their API host pacing.

Webpage Enrich still runs serially through the existing read-only Translator path, triggered by missing Abstract, Authors, publication date or an existing `YYYY-MM` date eligible for valid day upgrade. Missing First public or journal events alone never triggers it. A legitimate response can additionally contribute its already-returned explicit `accepted` and generic `date` as sourced, typed date facts, including an event-only save. Generic date never becomes First public. No new website extraction, history parser, browser batch pool or Zotero item save is added. DOI/document binding, cancellation/disconnection and exact-revision guards cover both ordinary fields and date events.

Background native pages receive a nonzero layout viewport without selecting, revealing or focusing them. Enrich exposes **打开 Browser 验证** while waiting for verification; it shows the existing task-bound page without leaving Workspace or cancelling the task. Solver targeting, interactability checks and retry limits remain unchanged.

## Old data and manual acceptance

Old Paper `identity_aliases`/`related_dois` fields are explicitly incompatible, even when empty: safe identity scanning and writes are blocked. No migration or automatic cleanup is performed. Obsolete Evidence files are ignored and preserved. This Paper-only change does not require rebuilding valid YAML, user-state SQLite or Run snapshots. Old dates, Provider lists and Run formats are not migrated. Workspace Reset removes only the confirmed Workspace, including Papers, obsolete Evidence files if present, and Run snapshots. It does **not** remove YAML, `.allfold/user-data.sqlite`, resource caches, covers or credentials. Normal startup, read, autosave or a configuration error never deletes these objects.

To adopt the new configuration explicitly:

1. Back up important Papers/configuration; optionally export User Data to preserve a transferable Research Scope. In the current application, preview and confirm **Settings → Reset → Workspace** only if you intend to discard that Workspace.
2. Close Allfold. Back up the selected YAML, then replace its contents with `config.template.yaml` and explicitly set the desired paths, keywords/months and source selections. Setup creates a missing default YAML but never overwrites an existing YAML; merely rerunning Setup does not rebuild an old configuration.
3. Reuse the same canonical YAML path to retain its existing Journals/Services scope in user-state SQLite. A different YAML path owns a new scope; use the existing Research Scope import/first initialization for that scope. There is no need to delete SQLite or use a factory reset. PubMed and OpenAlex secret files remain beside their configuration.
4. Restart with the rebuilt configuration and run a small journal range. No old Accepted approximation or First public fallback is converted into a new event.

Use the following as a change-scoped manual reference, not a checklist required for every PR. This cleanup primarily uses automated tests and synthetic Electron/Chromium results. Select manual checks only for affected behavior not covered by those tests, using disposable configuration/data:

- Run with PubMed, WoS and OpenAlex individually and in combinations; inspect native date filtering, paging/partial results, source failure and cancellation. Repeat a Run and verify existing Paper bytes and the absence of standalone Evidence writes.
- Reject after discovery; explicitly complete the remaining selected unkept Papers. Restart and complete older/kept/exported Papers; inspect progress, cancel/error/no-match outcomes and unchanged user content.
- For changed date or Reader behavior, inspect source/version tooltips and chronological journal events with available samples. Synthetic responses cover earliest/later-only versions, multiple version families, date conflicts and precision; a formal-only Paper has empty First public.
- For changed webpage Enrich behavior, check an available eligible request and month upgrade. Synthetic Translator responses cover explicit Accepted dates, event-only save/refresh and guarded writeback. Real rare-metadata samples are optional supplementary evidence; do not require finding an Accepted/event-only page or unusual version-conflict combination. Check DOI-free actions and Journal/Research Scope management when those functions change.

Existing [PR #40](https://github.com/dylaaan-booob/allfold/pull/40) acceptance includes real OpenAlex/Europe PMC Runs, linked preprint dates and OUP Enrich in isolated profiles, including task-page entry/return. Real Accepted/event-only samples were waived in favor of isolated regressions; no Zotero save was performed. These are scoped historical results, not proof of every site or this checkout.

Synthetic HTTP, rendered Electron fixtures, builds and CI establish only their tested layers. Real OpenAlex/Europe PMC responses, native preprint APIs, authenticated sites and Zotero outcomes require separately scoped acceptance.

Interface references: [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25499/), [PubMed history events](https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/250101/att-PubStatus-c.html), [OpenAlex scoped search](https://help.openalex.org/api/searching/), [OpenAlex filtering](https://help.openalex.org/api/filtering/), [OpenAlex authentication](https://help.openalex.org/api/authentication/), [OpenAlex locations](https://help.openalex.org/data/locations/), [Europe PMC REST](https://dev.europepmc.org/RestfulWebService), [Europe PMC version fields](https://europepmc.org/docs/EBI_Europe_PMC_Web_Service_Reference.pdf), [Crossref metadata](https://github.com/CrossRef/rest-api-doc/blob/master/api_format.md), [arXiv API](https://info.arxiv.org/help/api/user-manual.html), [bioRxiv/medRxiv APIs](https://api.biorxiv.org/).

### Shared WoS source facts

The Plain Text parser exposes `record_evidence` before Paper canonicalization.
It preserves UT, valid DI and optional PM as reliable identifiers; GA and identifiers
mentioned only in titles, abstracts or citations never establish identity. An invalid
optional DI/PM does not discard a record with another reliable identifier.
AF takes priority over AU as one ordered list. SO remains the returned source title,
SN/EI remain source ISSNs, and saved scope attribution remains separate. PT,
multivalue DT, DE and ID, dates PD/PY/EA/EY, and returned volume/issue/pages/article
number remain structured facts. Each native field records its returned values and
`unselected`, `absent`, `valid` or `parse-invalid` state; the eight export choices
include their dependent tags and inherent bibliographic/identity fields.

Canonical creation prefers formal versions, then valid WoS ordinary fields, then
deterministic other-source fills. Source retrieval time never decides ordinary
field precedence. Repeated facts deduplicate independent of retrieval timestamps.
Date-only requests independently target Received, Accepted, Published online and
Published; native print, issued and early-access labels are retained rather than
becoming additional business goals. Original native date
labels remain provenance. Future formal dates and available year/month precision
are preserved; First public retains its independent version and future-date checks.
