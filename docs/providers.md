# Journal discovery and Paper collection

**Run** discovers journal Papers, confirms necessary direct identities, establishes
basic Papers and registers complete collection plans. Workspace continues each
Paper's combined webpage and necessary API/Preprint branches after foreground
cleanup. **ARRAY Info** also offers independent explicit bioRxiv/medRxiv queries.
Ordinary field-gap Completion, active Enrich and Import are retired.

## Provider roles

| Provider | Run Discovery | Necessary identity / collection capabilities |
| --- | --- | --- |
| PubMed | Merged saved ISSNs, native Title/Abstract keywords and publication dates; ESearch History + EFetch | Batched DOI-to-PMID lookup, ESummary v2 dates/relations and selective EFetch |
| OpenAlex | Merged `primary_location.source.issn`, native title/abstract/keyword search and publication dates | Shared exact DOI/Work lookup and complete locations |
| WoS | Parallel native ISSN/eISSN, keyword/date query and verified eight-option Plain Text export | Formal bibliography and dates from the verified export |
| Europe PMC | None | Confirmed formal PMID + `HAS_PREPRINT:Y`, known PPR identifiers and explicit preprint relations |
| Crossref | None | Exact DOI metadata, named dates, direct and reverse preprint relationships |
| arXiv | None | Known arXiv IDs through batched `id_list`; Atom `published` establishes the first-version date |
| bioRxiv / medRxiv | None | Native `details` for a known platform and preprint DOI |

Run's `enabled_providers` accepts PubMed, WoS and OpenAlex in any nonempty combination and defaults to PubMed + OpenAlex. WoS never enables institutional Browser access automatically. Discovery selection governs journal searches. Necessary identity and relationship purposes have independent eligibility; no Paper blindly probes all services. OpenAlex collection credentials are declared only for an explicit Work purpose. Provider aliases, ordering, Settings forms, expression previews and runtime dispatch use the same IDs.

PubMed and OpenAlex keys are optional, explicitly submitted to revision-checked local 0600 secret files beside the YAML; ordinary autosave, draft recovery, snapshots and diagnostics contain no keys. PubMed anonymous pacing is at least 0.35 seconds and keyed pacing at least 0.11 seconds. Keyed Entrez requests use form POST so the key does not enter request URLs. Crossref contact/mailto remains optional. Obsolete PubMed query fields, Europe PMC Discovery selections and old Provider orders are rejected with `config.template.yaml` reconstruction guidance; no startup or validation deletes user data.

A Run needs at least one followed Journal. See [Research Scope](research-scope.md) for Journal management.

## Queries and dates

The shared parser accepts `AND`, `OR`, parentheses, adjacent quoted phrases and a word-final `*` with at least four preceding characters. `NOT`, proximity, internal/leading wildcards, `?` and malformed groups fail validation. Compilers preserve Boolean grouping and approved fields; no natural-language generation or full-collection scan is added.

PubMed compiles the shared AST into explicit `[Title/Abstract]` terms, including phrases and supported prefixes. It merges followed ISSN/eISSNs with native `[Date - Publication]` bounds, retrieves and validates the complete ESearch PMID set, reuses History Server and batches EFetch. Searches beyond the 9999-ID transport window are split by publication day range; a single day still above the window reports incomplete coverage rather than truncating. Missing DOI does not discard a reliable PMID. EFetch retains direct article identifiers, bibliography, native journal identities, independent publication/history events and explicit version references. Journal Discovery treats `phrasesnotfound` entries that exactly match the current batch's ISSN/eISSN terms as gaps in PubMed coverage and continues to validate the returned PMIDs. Empty error lists are valid responses. Other Entrez application errors inside HTTP 200 still fail.

OpenAlex uses `search.title_abstract_keywords` (the `.exact` variant for prefixes), merged `primary_location.source.issn`, `from_publication_date` and `to_publication_date`. At most 100 OR values and a 6000-character encoded-parameter budget split batches; normal Discovery does not resolve Sources per ISSN. Returned primary-source ISSNs map each Work to its followed Journal. Missing/mismatched source identity cannot expand scope. Accessible pages validate totals, Work identities and cursor progress. Individual parse or singleton-detail failures retain valid neighboring records and later pages with partial coverage; a valid Work without a title remains an identity candidate for necessary Work location; no field-gap query is added. Anonymous basic first-page queries are supported; further cursor paging requires the optional key and reports incomplete coverage when unavailable. Native hits are never subjected to a second local keyword/date filter.

Selected PubMed, WoS and OpenAlex Discovery overlap within one parent Run, slot, workflow, cancellation signal and captured configuration/Workspace. WoS retains CARSI, Browser ownership and the [native export contract](wos-export.md). Verified PubMed/HTTP pages and WoS batches feed formal DOIs into a shared bounded Work-location queue while discovery continues. Exact DOI/Work batches map returned identities independently of response order, cache confirmed full evidence/no-match/failure and drain the final short batch. Discovery and locator share OpenAlex full details, in-flight exact requests and host pacing. Shortened authorships/locations require a verified exact Work singleton; unresolved caps and failed pages remain limitations. Work lookup only adds evidence for discovered candidates. Work-level PMID/PMCID values on formal records remain related identifiers and cannot overwrite a directly confirmed formal PMID.

Before creation, all saved Papers including Rejected participate in direct-identity conflict checks. Run admits new candidates and actual `not_started` matches, preserving existing Paper metadata. Ordinary fields use fixed source priority with formal WoS bibliography first; author lists remain whole. Necessary responses and version relationships never become extra Discovery candidates. Only reliable direct identifiers establish ownership; conflicting saved owners are skipped and reported. Counts derive from distinct candidates, necessary identities, actual creates/matches/exclusions and collection registration.

Run batches unique new formal DOIs missing a directly confirmed PMID. PubMed ESearch uses quoted `[aid]` clauses without the Discovery date, ISSN or keyword filters. Each result set is checked for completeness, and ESummary or EFetch verifies the returned direct DOI for each PMID. A complete empty lookup is normal. An incomplete response or ambiguous binding reports a limitation. A confirmed formal PMID is available to subsequent helpers and persists in the new Paper. If a later EFetch directly contradicts the binding, Run drops the disputed PMID and facts reached solely through it. [PubMed Article Identifier](https://pubmed.ncbi.nlm.nih.gov/help/#aid), [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25499/).

Only directly bound formal records supply base bibliography or formal increments.
A related Preprint or association-only Work cannot supply the formal article's
fields or direct aliases, even when labelled journal. Missing abstract, authors
or event dates do not request EFetch or any generic Completion. The precreation
DOI confirmation retains its summary-first, missing-direct-DOI fetch fallback.

Foreground activity reports retrieval and necessary identity work. Background
branch status belongs to the Paper. Physical dispatch counts include pagination;
cache reuse adds no HTTP count. Foreground cancellation stops new Run requests
without cancelling already accepted Paper operations.

A safe read has at most three regular attempts under the shared [Provider HTTP policy](http.md#journal-run-and-native-preprint-apis). The absolute deadline also bounds a blocked HTTP read. Run can give each eligible failed physical request one final check within that same request's 90-second budget. Necessary lookups reuse successful pages and confirmed no-matches, and only resends the exact failed request with its original redirect authorization policy. Identity and parse errors, access restrictions and cancellation stop recovery. Newly verified identities can still schedule their necessary dependent metadata requests.

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

## Creation-time evidence

The SQLite Paper library is the only persisted literature object. Run creates
new Papers, preserves existing full records and can rebuild only an unexcluded
identity-only record hit by the current Run. No standalone Evidence file is written. Provider records
are temporary normalization/query/date inputs. WF06 can hand off explicitly
verified immutable capability facts to the Workspace task; it never transfers a
Run client, mutable cache, snapshot or replay callback. There is no permanent
response archive or background sync.
Run snapshots, configuration, Registry and History/Diagnostics retain
their separate business storage.

Received, Accepted and publication evidence remains operation-local data, never a missing-field request goal. Persistence extracts qualified formal-article month/day values into the ordinary date set; Reader no longer exposes old event/source columns. The necessary service follows verified Preprint associations. Incidental directly bound formal fields are retained; missing bibliography, keywords, indexed terms and affiliations create no generic request.

Purpose-driven collection groups exact identifiers within its owned branch. Confirmed formal PMIDs use PubMed ESummary v2 for relations; qualified direct/related Preprint PMID purposes use EFetch. Complete qualified fetch evidence satisfies summary capability; missing bibliography never triggers fetch. Europe PMC uses `SRC:MED AND HAS_PREPRINT:Y` with batched PMID clauses, plus direct known PPR IDs/DOIs. It does not read every PMID core record for ordinary metadata. Crossref exact DOI batches and reverse `relation.type:is-preprint-of` / repeated `relation.object` batches run alongside the other necessary base APIs. Exact target relations bind reverse results to each formal DOI, independently of response order; cursors exhaust every group and failed pages retain verified earlier facts with partial status. Crossref Received/Accepted assertions require explicit history semantics and valid ISO or English dates, preserving source labels and precision. Deposit, registration and indexing times never become manuscript history.

Operation-local caches distinguish PubMed summary/fetch, Crossref exact/reverse and complete Work evidence, including success, empty and failure responses. Foreground caches end with Run; every background branch has a fresh independent scope and may consume immutable verified handoff facts. Verified records from partial batches stay available while attributable failures settle. OpenAlex Work/locations already obtained during Discovery are reused. Every new relation enters the next necessary native-version wave before final First public coverage is calculated. arXiv `id_list` uses bounded groups of 200 identifiers; each group drains without a total quota. Explicit bioRxiv/medRxiv preprint DOI targets, including `10.64898/`, use native `/details` version lists. Native `/pubs` reverse lookup requires an explicit necessary purpose; the public Info query retains its formal-DOI use.

For native bioRxiv/medRxiv `/pubs` and `/details` paths, keep the first DOI slash
literal and encode each suffix slash as `%252F`, including in provenance URLs.
Canonical DOI identities remain unchanged. An empty response must still name the
complete requested DOI where the status supplies a subject; a truncated status
or service error is not NoMatch. See the [routing investigation](biorxiv-doi-routing.md)
for the community fix and live positive/negative controls.

Every known family needs first-version proof. Native arXiv Atom `published`, never `updated`, establishes its first public date. Europe PMC explicit PPR version facts can establish v1; native platform details supply missing proof. Crossref `posted`, version text or a DOI suffix alone do not establish native v1. OpenAlex `related_works`, `acceptedVersion`, `is_accepted` and repository locations cannot prove First public. Only explicit validated DOI/arXiv/official-URI relations are followed; there is no title similarity matching. Europe PMC keeps `Preprint in`/`Preprint of`, version identities and native relation notes, including automatic title/first-author matching notes, in source provenance. Missing history, conflicting dates or future preprint dates remain unresolved. Cancellation and configuration/Workspace checks guard every subsequent request and batch.

Foreground retrieval and each Paper collection report their own complete/partial/failed/cancelled/empty outcomes. First public coverage independently distinguishes recorded, no association, known unresolved, conflicting evidence, service failure and cancellation. Valid evidence survives a source failure and remains eligible for the protected create chain.

## Necessary Provider services

`application.necessary_metadata` supplies `necessary_metadata_branch()` through
`BranchSpec`/`WorkspaceRegistry`. `ProductionCollectionService` installs it with
the complete `document` branch in production. Foreground Run retains its serial
slot only through retrieval, necessary identities, complete admission and its
own cleanup. Necessary clients/lookup types/batching/formal binding live in
`application.provider_lookup`; the ordinary Completion driver is removed.

`necessary_requests()` plans unfinished relationship and native-proof work.
Missing abstract, authors or Received/Accepted/Published online/Published values
never create a request. Formal DOI forward and reverse Crossref capabilities,
direct formal PMID PubMed summary and Europe PMC `HAS_PREPRINT:Y` capabilities
remain independent. Explicit known relations lead to PPR ID/DOI, linked Preprint
PMID EFetch, arXiv or an evidenced bioRxiv/medRxiv platform. A DOI prefix does not
choose between the two native servers. Proven native families do not get queried
again to fill ordinary fields.

Exact OpenAlex Work/DOI location and native `/pubs → /details` reverse lookup
require explicit necessary purposes; there is no per-Paper Work or dual-server
probe for field gaps. The shared `confirm_formal_dois()` service retains quoted
`[aid]` ESearch, direct DOI ESummary verification and the necessary missing-direct-
DOI EFetch fallback before Run creates a base Paper. It does not rebuild a
background Paper UUID. Existing-Paper writes retain repository identity-owner
conflict checks. A Work's related PMID or a related Preprint DOI/PMID never gains
direct formal ownership. New-service WoS handoffs also treat every reported PM
as unverified unless that PMID already belongs to the saved Paper. Same-DOI or
same-WoS metadata and UT remain usable, including DOI-free handoffs, without
promoting PM or planning a formal PMID query. The original parser and Run's
precreation identity confirmation keep their existing contracts.

`VerifiedResponse` carries an immutable tuple of parsed evidence with provider,
namespace, normalized target and explicit capability. Complete fetch can satisfy
summary; summary cannot satisfy fetch, and Crossref exact cannot satisfy reverse.
Incomplete handoffs retain positive facts but cannot suppress the missing work,
even when a partial native v1 proof would otherwise satisfy the family planner.
The unfinished capability stays required and must settle before a new final
`first_public_at` can be committed; a failed completion retains valid increments.
On explicit retry, saved positive native proof does not stand in for a completed
capability: known native targets are revalidated unless a complete capability
handoff in that invocation satisfies them. No capability cache is made durable.
Facts bind through the target's verified identity/relations independently of
arrival order. Caches and failures remain local to the captured invocation.
Batch sizes (arXiv 200; Crossref/Europe PMC 100) limit each request group, not the
total number of targets. Existing pagination checks retain verified earlier
pages when a later page fails. Only an adapter-confirmed exact empty result is
no-match; a raw service 404, malformed envelope, truncated DOI error or identity
conflict is not silently converted to empty success.

The service reads the current Paper through guarded `BranchContext.read_paper()`
without renewing the captured token or abstract generation, uses only declared
`context.provider()` clients and emits positive branch-local sequences.
Same-formal month/day dates and an eligible abstract may arrive incrementally;
related Preprint bibliography and dates stay outside the ordinary date set.
Year-only dates gain no invented precision, and database maintenance timestamps
gain no publication eligibility. Crossref JATS structure and arXiv summary
paragraphs remain intact in raw Provider candidates; Run base normalization
continues to own its existing canonical comparison behavior.

Preprint relations and version proof may also persist incrementally, but a new
`first_public_at` is emitted only after all applicable relationship discovery and
native requests settle successfully and every known family has consistent,
nonfuture native first-version proof. A known family can remain unresolved after
a valid no-match. Partial/error responses prevent a new first-public commit even
when an already-known family is proved; a later response may reveal an earlier
family. Existing `first_public_at` remains protected. Updated/posted/version text,
repository locations and PubMed publication dates do not substitute for native
v1. Partial or failed work retains verified increments and terminates the branch
as failed; cancellation and actual client cleanup remain task-owned.

The registry executes independent Document and API branches concurrently using
separate thread-owned repositories, client/cache scopes and native identities.
Only application pacing/cooldown and explicit captured ownership are shared.
Parent and leaf execution are separately bounded; Paper occupancy survives every
branch and actual cleanup. A failed document does not discard independent API
results, and normal empty work can complete.

## Info preprint lookup

Open **Info** in ARRAY and start a lookup for the current Paper's formal DOI. Each server is queried through `/pubs/{server}/{published_doi}/na/json`. Exact publication-to-preprint matches lead to `/details/{server}/{preprint_doi}/na/json` for native version dates. The relation and server-specific response establish the platform.

A successful lookup appends deduplicated preprint evidence to the selected Paper. Verified first-version evidence can fill an empty First public. A later version can be saved as evidence while First public stays empty. Existing First public, primary identifiers, bibliography, notes and workflow state are protected. No match, failure and cancellation each have their own outcome and leave the Paper untouched. The commit rechecks original metadata/operation generations, narrow Provider authority, Workspace/database identity and cancellation. No Enrich or Markdown helper owns this write. See [Safety](safety.md).

Requests are keyed by Workspace/Paper/request and use the existing bounded registry
execution. They do not take a Run slot, change collection attempts or stop when
the Reader changes. Same-Paper work/cleanup blocks a new operation; different
Papers and another Run can proceed. After actual cleanup, another explicit query
is allowed even when collection completed normally or empty. A first complete
collection intent waits behind an already accepted query without revoking it;
new manual clicks do not queue automatically.

## HTTP and Browser boundary

Run, Info preprint lookup and standalone OpenAlex share the [Provider HTTP policy](http.md#journal-run-and-native-preprint-apis). Recoverable connection failures and temporary HTTP responses can show **Retrying**. An active dependency cooldown can show **Waiting**. Retry-After is enforced across clients for the same origin and authentication context. A request whose remaining budget is shorter ends while the cooldown stays active. Recognized verification pages stop that Provider client. Unexpected HTML and invalid envelopes report failures. Only an adapter-confirmed exact no-match is empty; raw service 404 is a failure. arXiv uses three-second pacing, and bioRxiv and medRxiv share their API host pacing.

Keep/Import and active Enrich have no UI, HTTP or native dispatch path. Their
Local API, attachment communication, Translator sandbox and generated Runtime
assembly are retired. Prepare, WoS, Login, Browser/Document identity and
Cloudflare remain in production. Native background pages retain a nonzero layout
viewport without selecting or focusing them. WF06 supplies internal Date/Abstract
components; WF07 adds separate same-Document PDF clues and source discovery.
WF08 installs production collection; PDF transmission, files and public Download
remain deferred to WF09/WF10.

An Imperva response with the Incapsula incident marker and a single CAPTCHA code (`edet=12`) waits for the user to complete verification in Browser. The existing task resumes when the article loads in the same tab. The Cloudflare Solver is skipped for this challenge. Other recognized Imperva denials are reported as restricted access, including when they return HTTP 200.

## Current storage and manual acceptance

Old per-Paper Markdown and obsolete Evidence directories are no longer read,
created or migrated. Existing files are preserved. An uninitialized Workspace
returns an explicit empty view; the first Run initializes SQLite. Paper libraries use only the current format; old-data upgrades and compatibility are not provided.
Corrupt and unknown libraries report errors and are never cleared automatically.
Workspace Reset is an explicit whole-directory deletion, including SQLite,
exclusions and Documents; Logs Reset keeps all of them. Configuration, UserState,
resources, covers and credentials remain separate. Research Scope Markdown
exchange continues to work.

Run settles discovery and necessary direct identities before atomic base/queued
admission. Exclusions and ownership conflicts are rechecked in that transaction.
Full matches preserve metadata; `not_started` matches are first collected only
when hit by this Run. Active attempts are reused; completed/empty do not reopen,
and failed/cancelled require explicit single-Paper retry after cleanup. Only an
originally qualified released placeholder can be rebuilt with its UUID. A manual
query may hold an accepted first-collection intent until real release. Neither
startup nor later Runs scan the library to fill gaps or replay work.

WF07 projects exact-target OpenAlex/Crossref response facts before ordinary
source normalization loses PDF-versus-landing categories, best-first order or
response completeness. The existing `records` path carries them into Run saves
and necessary-query increments without new Run requests or a changed creation
point. A related Preprint response cannot become the formal target's PDF cache;
the target Work's own repository locations remain eligible. Ordinary
`metadata.sources` is never proof of complete P5 capability. The lazy discovery
service reuses adequate facts and queries missing inputs only when it reaches
their applicable stage. Optional publisher interfaces have separate access
conditions and do not extend Run's Provider enumeration or credential UI. See
the [complete rule/API adoption catalogue](pdf-source-discovery.md#rule-catalog).

Use isolated HTTP/SQLite and rendered Electron fixtures for the cutover. Their
coverage includes native-version proof, unresolved/no-match/failure cases, dates,
identity conflicts, cancellation and safe commits. Real Provider, WoS, CARSI and
other authenticated service behavior requires separately scoped acceptance; old
PR acceptance does not establish this checkout's live compatibility.

Interface references: [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25499/), [PubMed history events](https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/250101/att-PubStatus-c.html), [OpenAlex scoped search](https://help.openalex.org/api/searching/), [OpenAlex filtering](https://help.openalex.org/api/filtering/), [OpenAlex authentication](https://help.openalex.org/api/authentication/), [OpenAlex locations](https://help.openalex.org/data/locations/), [Europe PMC REST](https://dev.europepmc.org/RestfulWebService), [Europe PMC version fields](https://europepmc.org/docs/EBI_Europe_PMC_Web_Service_Reference.pdf), [Crossref metadata](https://github.com/CrossRef/rest-api-doc/blob/master/api_format.md), [arXiv API](https://info.arxiv.org/help/api/user-manual.html), [bioRxiv/medRxiv APIs](https://api.biorxiv.org/).

### Shared WoS source facts

The Plain Text parser exposes `record_evidence` before Paper canonicalization.
It preserves UT, valid DI and optional PM. For DOI-bearing WoS records, Run
requires PubMed to confirm the formal PMID before using it for identity or
metadata lookup. An unresolved reported PMID that overlaps a saved DOI-free
Paper blocks a possible duplicate and reports an identity conflict. DOI-free WoS
records retain their supported direct identifiers. GA and identifiers mentioned
only in titles, abstracts or citations cannot establish identity.
AF takes priority over AU as one ordered list. SO remains the returned source title,
SN/EI remain source ISSNs, and saved scope attribution remains separate. PT,
multivalue DT, DE and ID, dates PD/PY/EA/EY, and returned volume/issue/pages/article
number remain structured facts. Each native field records its returned values and
`unselected`, `absent`, `valid` or `parse-invalid` state; the eight export choices
include their dependent tags and inherent bibliographic/identity fields.

Canonical creation prefers formal versions, then valid WoS ordinary fields, then
deterministic other-source fills. Source retrieval time never decides ordinary
field precedence. Repeated facts deduplicate independent of retrieval timestamps.
Necessary responses retain Received, Accepted, Published online and Published
evidence; those labels never independently drive a query. Native print, issued
and early-access labels remain provenance. Original native date
labels remain provenance. Future formal dates and available year/month precision
are preserved; First public retains its independent version and future-date checks.
