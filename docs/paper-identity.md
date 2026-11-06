# Paper identity and creation metadata

A Paper's internal identity is its UUID. `external_ids.doi` and the top-level
`doi` contain the same primary DOI, or both are null. `related_dois` contains
other confirmed DOI identities of the same work. DOI is optional: reliable
DBLP publication keys, Europe PMC `SOURCE:ID`, OpenAlex Work IDs,
arXiv IDs, PMID/PMCID and WoS accession numbers can identify a Paper.
Unknown external namespaces are retained as metadata and do not establish a
merge. `identity_aliases` retains additional known IDs as bounded
`{provider: namespace, record_id: identifier}` entries in the Paper itself.
There is no external alias table.

Canonicalization groups only connected shared reliable IDs, including explicit
same-work DOI relationships supplied by adapters. It does not compare titles or
authors to establish identity. OpenAlex Work identity reuses OpenAlex's existing
association. Conflicting existing files are reported, never merged or modified.
The invocation-local index includes primary and related DOIs and all reliable
aliases. Materialization rescans under the same Workspace operation lock used
for atomic creation. An existing match skips creation and leaves all saved bytes
unchanged, including metadata, Notes, Tags and workflow status.

## Fixed selection and missing fields

New records use this fixed order, independent of request completion time:

1. Formal records before records explicitly identified as preprints.
2. Records attributed to a monitored Journal or Conference before supplements.
3. Discovery evidence before supplemental evidence.
4. Crossref, Europe PMC, OpenAlex, arXiv, bioRxiv, medRxiv, then
   other providers ordered by provider and record ID.

Duplicate snapshots use deterministic serialized payload order excluding the
retrieval timestamp. Retrieval time and field completeness do not score metadata.
The first valid nonempty value is retained. Authors and Author Keywords are
whole lists; authors from different versions are not spliced together.
Publication dates are selected within each source's bibliographic record before
moving to another source. The primary DOI belongs to the selected formal record
when one is present; a preprint DOI does not fill a DOI-free formal target.
All confirmed related DOIs remain available for duplicate prevention.

`journal` and `conference` are separate source fields. `conference_id` refers to
the saved series identity; conference names are never saved as journal names or
assigned fake ISSNs. `publication_type` distinguishes journal, conference and
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
future public event, formal online/print/publication, Accepted, database indexing,
retrieval/update times or Translator generic date cannot supply a fallback.
Sufficient first-stage evidence can fill it at creation. Explicit API completion
fills an empty value but never recalculates a nonempty one; later evidence still
appends. Missing version history is not evidence of a single version.
Each known preprint version family needs its own first-version proof. One family's
date cannot settle another family's later-only or undated record. Conflicting
first-version facts or an evidently earlier version leave the value unresolved;
partial dates are compared as intervals without changing their saved precision.
Related identifiers retain explicit preprint and same-family version roles.
Aliases returned within one relation identify one target family; saved aggregate
Paper identifiers alone do not join independent preprint families.
An added alias does not duplicate an already saved event.

The UI's **期刊日期** is a chronological collection of journal-version events:
Accepted, Published online, Published print, Published/Issued and unspecified
source dates. Sources and precision remain visible, with record/version/URL in
the basis. Preprint dates have their own First public basis. Bibliographic
`publication_date` remains available independently and can serve as a list-sort
fallback without becoming a First public value. Old approximate Accepted fields
are not read or converted into this collection.

Run creates new Papers and leaves existing bytes untouched. Its separate
Workspace Evidence records retain rediscovery facts for later explicit API
completion, including across restart. API completion updates selected saved
non-Rejected Papers through exact-content and identity checks, fills ordinary
empty fields only, keeps authors whole and appends deduplicated date/source
facts. It never changes a primary DOI/UUID, merges saved files, overwrites notes
or restores a Reject decision. API completion does not require Keep.

## Local editing and external actions

DOI-free Papers can be read, kept/rejected and edited through existing local
field operations, subject to UUID, exact-content revision and path checks.
Webpage Enrich requires a valid primary DOI and an ordinary field gap. It retains
the existing month-to-valid-day publication-date upgrade exception and can save
already-returned date events without an ordinary-field change. It never starts
for missing First public or journal events alone. Prepare and Import require that
same primary DOI and exclude unsupported preprint targets. Related DOIs never
become an arbitrary fallback target. Native translator DOI checks remain bound
to the primary DOI. No change here grants browser, institution or Zotero write
authority.

Isolated regressions: [Paper identity](../tests/test_paper_identity.py),
[materialization](../tests/test_materialize.py),
[API completion](../tests/test_api_completion.py),
[webpage Enrich](../tests/test_paper_enrichment.py) and [WoS](../tests/test_wos.py).
