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
2. WoS, PubMed, Crossref, Europe PMC, OpenAlex, arXiv, bioRxiv,
   medRxiv, then other providers ordered by provider and record ID.
3. Within a Provider, records attributed to a monitored Journal before supplements,
   then Discovery evidence before supplemental evidence.

Duplicate snapshots use deterministic serialized payload order excluding the
retrieval timestamp. Retrieval time and field completeness do not score metadata.
The first valid nonempty value is retained. Authors and Author Keywords are
whole lists; authors from different versions are not spliced together.
Publication dates are selected within each source's bibliographic record before
moving to another source. The primary DOI belongs to the selected formal record
when one is present; a preprint DOI does not fill a DOI-free formal target.
Only direct identifiers selected into `external_ids` survive for later deduplication.

Run retains each final Discovery root and builds its ordinary fields and direct
identifiers from verified formal records. Bound related versions contribute only
date facts, First public and source provenance; they cannot supply a formal
Paper's title, authors, primary DOI or PMID, become saved identity owners or
create another Paper. Exact OpenAlex location bindings with a different top DOI
remain association evidence. Independently saved preprints remain independent.
Distinct relation notes on the same Provider record are retained in stable order.

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
version, preprint version family, version type, original source label, source URL and whether the source establishes a first
public preprint version. Equal facts deduplicate independently of fetch time;
new events and conflicting source facts append. Same-day events with different
types remain distinct. Sorting placeholders never enter saved/display dates.
Snapshot date conflicts compare the same native source label. Distinct native
fields such as Crossref `published` and `published-print` retain their dates
under Published without being reported as contradictory snapshots.

`first_public_at` requires a reliably linked preprint system and evidence for its
first/earliest public version. A later version alone, unknown preprint date,
future public event, formal online/publication, Received, Accepted, database indexing,
retrieval/update times or Translator generic date cannot supply a fallback.
Sufficient evidence fills it at creation. The Info preprint lookup can fill
an empty value and append later evidence while retaining a recorded First public. Missing version history is not evidence of a single version.
Each known preprint version family needs its own first-version proof. One family's
date cannot settle another family's later-only or undated record. Conflicting
first-version facts or an evidently earlier version leave the value unresolved;
partial dates are compared as intervals without changing their saved precision.
Operation-local related identifiers retain explicit preprint and same-family version roles.
Aliases returned within one relation identify one target family; saved aggregate
Paper identifiers alone do not join independent preprint families.
An added alias does not duplicate an already saved event.

The reader shows First public, Received, Accepted and Published. Received and
Accepted use the earliest reliable explicit history event of the corresponding
kind on the formal journal record. Published uses the earliest normalized
Published or Published online event for that journal record. Native labels such
as WoS EA and PD/PY and Crossref issued remain in the underlying facts.
A missing date stays blank. Info lists all saved date facts in date order with
their labels, precision, source, version and safe source links. The separate
bibliographic `publication_date` stays available as metadata and for list sorting.

Date precision defines a calendar interval. Disjoint intervals sort by which
ends before the other begins. Overlapping valid ISO dates share a prefix, so
their enclosing year or month sorts first. For example, `2026-03` takes
precedence over `2026-03-13`. The reader shows that verified month, and Info
retains both facts. Selection uses display strings with their actual precision
and makes no changes to stored evidence.

Run groups and excludes saved identities before batching missing formal
DOI-to-PMID associations. PubMed verifies each DOI using a direct returned
identifier. Ambiguous or incomplete responses cannot establish a new binding.
Only an unambiguous confirmed formal PMID can enter the new Paper's identity.

The Info preprint lookup verifies explicit bioRxiv/medRxiv relations and their
native versions for the selected Paper. Related versions contribute dates and
source facts while the Paper's UUID, primary identifiers, bibliography and
workflow state remain protected. Every known version family needs first-version
proof before an empty First public can be filled. Request caches and temporary
relations are scoped to the operation. Response capabilities distinguish
PubMed summary from full EFetch evidence. Europe PMC relation notes are source
provenance. Crossref posted dates and version suffixes alone cannot prove native
first-version publication.

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
[preprint lookup](../tests/test_preprint_lookup.py),
[webpage Enrich](../tests/test_paper_enrichment.py) and [WoS](../tests/test_wos.py).
