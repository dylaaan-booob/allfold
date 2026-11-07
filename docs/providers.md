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

OpenAlex uses `search.title_abstract_keywords` (the `.exact` variant for prefixes), merged `primary_location.source.issn`, `from_publication_date` and `to_publication_date`. At most 100 OR values and a 6000-character encoded-parameter budget split batches; normal Discovery does not resolve Sources per ISSN. Returned primary-source ISSNs map each Work to its followed Journal. Missing/mismatched source identity cannot expand scope. Accessible pages validate totals, Work identities and cursor progress. Anonymous basic first-page queries are supported; further cursor paging requires the optional key and reports incomplete coverage when unavailable. Native hits are never subjected to a second local keyword/date filter.

Selected PubMed, WoS and OpenAlex Discovery overlap within one parent Run, slot, workflow, cancellation signal and captured configuration/Workspace. WoS retains CARSI, Browser ownership and the [native export contract](wos-export.md). Verified PubMed/HTTP pages and WoS batches feed formal DOIs into a shared bounded Work-location queue while discovery continues. Exact DOI/Work batches map returned identities independently of response order, cache confirmed full evidence/no-match/failure and drain the final short batch. Discovery and locator share OpenAlex full details, in-flight exact requests and host pacing. Shortened authorships/locations require a verified exact Work singleton; unresolved caps and failed pages remain limitations. Work lookup only adds evidence for discovered candidates. Work-level PMID/PMCID values on formal records remain related identifiers and cannot overwrite a directly confirmed formal PMID.

Before creation, all saved Papers including Rejected participate in direct-identity conflict checks. Run completes only new candidates and preserves existing Paper bytes. Ordinary fields use fixed source priority with formal WoS bibliography first; author lists remain whole. Completion responses and version relationships never become extra Discovery candidates. Only reliable direct identifiers establish ownership; conflicting saved owners are skipped and reported. Counts derive from distinct candidates, completion activity and actual protected creates.

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

Completion reads only the selected Paper Markdown as its persistent input. It can run with no enabled completion providers. Network requests serve only empty title/authors/source/abstract, missing-all journal dates, or unresolved First public families; optional keywords, indexed terms, PMID and affiliations never create requests. A nonempty saved `first_public_at` already satisfies First public and does not initiate a new search for unknown preprints. Any valid Accepted, Published online or Published date suppresses date-only queries, including partial and future formal dates. Necessary responses can still contribute dates returned with other metadata. Typed saved preprint dates can restore temporary query/binding targets on restart. If those saved facts already establish First public, completion commits that empty field without a new response; it does not require standalone Evidence.

Known arXiv, explicitly identified bioRxiv/medRxiv and Europe PMC preprint targets run before aggregation. After every response, all returned relationships enter the known-family set before coverage is checked. Every known family needs acceptable first-version proof; an empty family set is unresolved. Once known families and ordinary/date goals are satisfied, completion stops instead of searching other systems. Otherwise enabled, identity-supported routes use saved OpenAlex work/location facts, PMID/Europe PMC records, and Crossref formal-DOI named relations. A formal-DOI native reverse lookup is an association fallback; a known preprint DOI never causes guesses at another platform. Selecting one native provider does not establish that a DOI belongs to it.

Every provider/namespace/identifier, including failures and cyclic relations, is reused within the operation across selected Papers. Native details returned during a formal-DOI reverse lookup also serve separately selected preprints. Known arXiv IDs across Papers share `id_list` batches, using local groups of at most 200 IDs and draining every group without truncation. Responses map by normalized ID rather than order: missing IDs remain no-match, wrong/error entries and conflicting duplicates remain failures, and unaffected siblings survive. Atom `published`, never `updated`, establishes v1. Cancellation and configuration/Workspace checks guard subsequent requests and batches; host pacing/retry remain shared.

OpenAlex locations retain validated official preprint identities but `related_works`, `acceptedVersion`, `is_accepted` and repository location alone do not prove a first-version date. Crossref accepts only permitted named same-work/preprint/version relationships with validated DOI, arXiv or anchored official URI identifiers; arbitrary URLs and unrelated references are ignored. A response must establish its own requested primary identity before its related records can contribute. Europe PMC keeps explicit `Preprint in`/`Preprint of` relationships and version-bound dates. Missing version lists or version numbers do not prove v1. Explicit bioRxiv/medRxiv publisher plus PPR/DOI facts can direct native lookup without inventing a version number.

API results distinguish updated, unchanged, excluded, failed and cancelled Papers; lookup results distinguish evidence, no-match, identity mismatch, failure and cancellation. First-public coverage independently distinguishes recorded, no association, known unresolved, conflicting evidence, service failure and cancellation. Existing First public is protected and reported recorded; new date facts already returned by other necessary requests can append without recalculating it. History retains these coverage counts. One failed source/Paper does not revoke other valid facts or completed safe writes. No permanent no-match cache, raw HTTP archive or fuzzy matching is added.

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
Date-only requests use Accepted, Published online and publication_date; print,
issued and early-access are not independent completion goals. Original native date
labels remain provenance. Future formal dates and available year/month precision
are preserved; First public retains its independent version and future-date checks.
