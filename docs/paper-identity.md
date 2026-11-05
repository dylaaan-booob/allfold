# Paper identity and creation metadata

A Paper's internal identity is its UUID. `external_ids.doi` and the top-level
`doi` contain the same primary DOI, or both are null. `related_dois` contains
other confirmed DOI identities of the same work. DOI is optional: reliable
DBLP publication keys, Europe PMC `SOURCE:ID`, zbMATH IDs, OpenAlex Work IDs,
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
4. Crossref, Europe PMC, DBLP, zbMATH, OpenAlex, arXiv, bioRxiv, medRxiv, then
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
`date_evidence` retains kind, partial components, provider and record ID.

`first_public_at` is the earliest confirmed public-version date. Explicit
preprint and online evidence participates alongside confirmed formal publication
records. Without linked preprint evidence, `date_note` records that absence;
it does not assert that the formal publication was the work's first preprint.
`accepted_at` uses explicit formal acceptance evidence first. Platform acceptance
of a preprint is excluded. Otherwise the earliest confirmed post-acceptance
formal online, early-access or publication evidence provides an approximation,
marked by `accepted_approximate` and its basis in `date_note`. The UI shows `≈`
for that approximation. Acceptance may precede first public; no artificial order
is imposed.

OpenAlex's generic Work publication date does not establish first-public or
acceptance timing. DBLP's conference year is retained as `conference-year`
evidence and never becomes an acceptance or precise publication date. Missing
dates remain null. Creation finalizes available date evidence once; later Runs
never refresh a saved Paper's dates or versions.

## Local editing and external actions

DOI-free Papers can be read, kept/rejected and edited through existing local
field operations, subject to UUID, exact-content revision and path checks.
External Enrich requires a valid primary DOI. Prepare and Import require that
same primary DOI and exclude unsupported preprint targets. Related DOIs never
become an arbitrary fallback target. Native translator DOI checks remain bound
to the primary DOI. No change here grants browser, institution or Zotero write
authority.

Isolated regressions: [Paper identity](../tests/test_paper_identity.py),
[materialization](../tests/test_materialize.py),
[Enrich](../tests/test_paper_enrichment.py) and [WoS](../tests/test_wos.py).
