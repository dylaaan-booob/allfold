# Paper identity and creation metadata

Paper Markdown is the only persisted literature object. A Paper's internal
identity is its UUID. `external_ids.doi` and top-level `doi` contain the same
normalized primary DOI, or both are null. Direct reliable namespaces include
OpenAlex Work ID, WoS UT, Europe PMC `SOURCE:ID`, PMID, PMCID and arXiv ID. Unknown namespaces remain descriptive and do not establish a match.

Canonicalization groups records only through common direct reliable identifiers.
It reuses an explicitly returned OpenAlex Work ID, without rebuilding OpenAlex's
matching algorithm. DOI normalization and the deterministic arXiv DOI-to-ID mapping
remain supported. Titles/authors never establish identity. Version/preprint
relations do not join different DOI identities for persistent deduplication.
Each namespace has one saved value; additional same-namespace identities are not
retained in aliases. Some duplicate Papers and reduced recall are accepted.

The invocation-local index covers every saved Paper, including Rejected. Creation
rescans under the Workspace lock. If a record's identifiers point at multiple
saved Papers, it is skipped with the identifiers and Paper UUIDs reported. Saved
Papers are never merged, reassigned or rewritten by Run. Incomplete/unsafe identity
scans block creation. Exact content, UUID, primary DOI, path and concurrent-write
protections remain in force.

The retired `identity_aliases`, `related_dois`, `conference_id` and
`external_ids.dblp` Paper fields are incompatible,
including empty fields. Reads report the incompatibility and block safe indexing
and writes; no identities are silently discarded. Back up before explicitly
rebuilding via **Settings → Reset → Workspace**. Startup and ordinary operations
never migrate, delete or rewrite old data. Obsolete standalone Evidence files
are unused and preserved until a user explicitly resets that Workspace.

## Fixed selection and missing fields

New records use this fixed order, independent of request completion time:

1. Formal records before records explicitly identified as preprints.
2. WoS records before other providers within the same formal/preprint class.
3. Records attributed to a monitored Journal before supplements.
4. Discovery evidence before supplemental evidence.
5. Crossref, Europe PMC, OpenAlex, arXiv, bioRxiv, medRxiv, then
   other providers ordered by provider and record ID.

Duplicate snapshots use deterministic serialized payload order excluding the
retrieval timestamp. Retrieval time and field completeness do not score metadata.
The first valid nonempty value is retained. Authors and Author Keywords are
whole lists; authors from different versions are not spliced together.
Publication dates are selected within each source's bibliographic record before
moving to another source. The primary DOI belongs to the selected formal record
when one is present; a preprint DOI does not fill a DOI-free formal target.
Only direct identifiers selected into `external_ids` survive for later deduplication.

`journal` and `conference` are separate bibliographic source fields. Conference
names do not create followed sources and are never assigned fake ISSNs. `publication_type` distinguishes journal, conference and
preprint records. `indexed_terms` retains value, kind and provider source,
separately from `author_keywords`. `sources` retains provider, record ID,
retrieval time and optional discovery/supplement role, URL, version and licenses.

## Dates

All date strings preserve `YYYY`, `YYYY-MM` or `YYYY-MM-DD` precision.
`publication_date` describes the source's bibliographic publication record and
remains independent of the discovery range and first-public sorting.
`date_evidence` retains event kind, partial components, provider, record ID,
version, preprint version family, version type, source URL and whether the source establishes a first
public preprint version. Equal facts deduplicate independently of fetch time;
new events and conflicting source facts append. Same-day events with different
types remain distinct. Sorting placeholders never enter saved/display dates.

`first_public_at` requires a reliably linked preprint system and evidence for its
first/earliest public version. A later version alone, unknown preprint date,
future public event, formal online/publication, Accepted, database indexing,
retrieval/update times or Translator generic date cannot supply a fallback.
Sufficient first-stage evidence can fill it at creation. Explicit API completion
fills an empty value but never recalculates a nonempty one; later evidence still
appends. Missing version history is not evidence of a single version.
Each known preprint version family needs its own first-version proof. One family's
date cannot settle another family's later-only or undated record. Conflicting
first-version facts or an evidently earlier version leave the value unresolved;
partial dates are compared as intervals without changing their saved precision.
Operation-local related identifiers retain explicit preprint and same-family version roles.
Aliases returned within one relation identify one target family; saved aggregate
Paper identifiers alone do not join independent preprint families.
An added alias does not duplicate an already saved event.

The UI's **期刊日期** is a chronological collection of journal-version events:
Accepted (only an explicit acceptance event), Published online and Published.
WoS EA uses its own year or explicit EY for Published online; PD/PY feeds
`publication_date` and Published, including year-only and future dates. It never
approximates Accepted or borrows PY for EA. Native print/issued labels map to
Published while retaining their original `source_label`; they are not separate
business targets. Equal business events, dates, providers, records and versions
share one visible row, with every raw source label retained in its tooltip.
Sources and precision remain visible, with record/version/URL in the basis. Preprint dates have their own First public basis. Bibliographic
`publication_date` remains available independently and can serve as a list-sort
fallback without becoming a First public value. Old approximate Accepted fields
are not converted into this collection. Retired `published-print`, `issued` and
`early-access` date kinds make an affected Paper explicitly unsupported.
Back up those files and explicitly rebuild them before rerunning discovery;
Allfold never rewrites or silently discards their legacy facts.

Run creates new Papers and leaves existing bytes untouched. There is no independent
Evidence store or cross-operation handoff. Provider records normalize and combine
facts only during the operation. API completion reads selected saved non-Rejected
Paper Markdown, including old, Kept and Exported Papers after restart, without
requiring Keep. It queries only actual gaps, fills ordinary empty fields, keeps
authors whole and appends deduplicated `date_evidence` and `sources` in Paper.
`indexed_terms` retains creation/display support without becoming a request goal.
A saved `first_public_at` satisfies that goal directly; no new first-version
search starts just to discover unknown systems. Existing values are protected.

Responses must match the requested direct identity before explicit relations can
lead to another lookup. Related preprint versions with different DOIs can supply
First public facts within this operation; they do not change the selected target,
primary DOI/UUID, workflow or another Paper. Every known family still needs first
version proof when filling an empty First public. Unsaved relationships are
discarded; another explicit completion may request them again. Shared response
caches, deduplication, arXiv batches and cancellation remain operation-local.
Typed saved preprint date facts can reconstruct temporary query targets after
restart, without entering the Paper identity index. Sufficient dates already in
Paper can fill an empty First public with no network requests or source rewrite.

## Local editing and external actions

DOI-free Papers can be read, kept/rejected and edited through existing local
field operations, subject to UUID, exact-content revision and path checks.
Webpage Enrich requires a valid primary DOI and an ordinary field gap. It retains
the existing month-to-valid-day publication-date upgrade exception and can save
already-returned date events without an ordinary-field change. It never starts
for missing First public or journal events alone. Prepare and Import require that
same primary DOI and exclude unsupported preprint targets. Temporary related DOIs never
become an arbitrary fallback target. Native translator DOI checks remain bound
to the primary DOI. No change here grants browser, institution or Zotero write
authority.

Isolated regressions: [Paper identity](../tests/test_paper_identity.py),
[materialization](../tests/test_materialize.py),
[API completion](../tests/test_api_completion.py),
[webpage Enrich](../tests/test_paper_enrichment.py) and [WoS](../tests/test_wos.py).
