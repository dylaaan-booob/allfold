# Paper identity

The production Paper store is `Workspace/papers.sqlite`. A repository-generated
UUID identifies a Paper across Runs, exclusion, metadata clearing and rebuilding.
The application, HTTP projections, Reader, search, counts and actions use that
returned UUID. Paper Markdown, YAML workflow status and `Inbox.base` are retired;
there is no dual write, mixed read, migration or Markdown fallback.

Reliable direct namespaced identifiers establish ownership. Existing normalizers
handle DOI, PubMed, OpenAlex, WoS and other supported reliable IDs. Related
Preprint identifiers remain separate and cannot become formal-article ownership.
Titles, authors, source-name similarity and temporary upstream UUIDs never merge
records. If multiple direct identities belong to different saved UUIDs, the
operation reports a conflict and rolls back the whole identity change.

A primary identity is selected explicitly and persisted. Its DOI, when present,
is the formal-article DOI used for eligible Preprint lookup and links. Multiple
saved DOI values do not make dictionary order a primary-identity policy. DOI-free
Papers remain readable and locally editable when complete and unexcluded.

| Existing match during Run | Result |
| --- | --- |
| None | Create only with valid title and reliable direct identity; repository supplies UUID |
| Full metadata, unexcluded | Reuse UUID and return the saved record unchanged |
| Excluded, including identity-only | Keep excluded and stop avoidable subsequent work |
| Cleared metadata, unexcluded | Only an actual Run hit may call `rebuild_from_run`, reusing UUID and body association |

Early filtering avoids unnecessary helper requests. Final short transactions
repeat the classification and identity-conflict checks. Ordinary repeat hits do
not become metadata completion. Current Run/Completion timing is preserved; a
Run result does not register background collection completion.

`PaperMetadata` keeps stable `discovered_at`, title, journal/conference/type,
bibliographic publication date, authors, keywords, ISSNs, indexed terms, sources,
abstract and existing user notes. ISSN/eISSN matching determines saved Journal and
Service assignment. Clearing metadata deletes those fields; identity-only rows
are unassigned and display a reliable identifier instead of a fabricated title.

Ordinary dates are a normalized set of qualified target-article API and confirmed
Document month/day values: deduplicate, supersede a month with its known days, retain distinct days
and valid future values. A year remains bibliographic precision and manufactures
no month/day. `publication_date` retains its explicit bibliographic source.
Preprint dates and version-family proof are independent; a date with separate
formal-article evidence remains an ordinary date even when also present in
Preprint. `first_public_at` requires verified earliest linked first-version proof.
Unresolved relations, later versions and provider provenance remain available
without being promoted to first-version proof.

Automatic results use the Workspace UUID and Paper generations captured when
processing began. Reject, restore, clear and rebuild revoke older operation
eligibility. Manual abstract editing has an independent generation: old abstract
candidates become ineligible while valid date/source increments may still merge.
HTTP response order uses a separate persisted library revision, never `WriteToken`
as a complete UI revision. See [library](paper-library.md) and [safety](safety.md).

The internal Document task uses the saved primary DOI or an explicit upstream
`confirmed_article_url` supplied by its owning task for DOI-free work. An arbitrary
source/related-Preprint URL cannot become that confirmation. Native payload
`workspace_identity` is the existing SHA256 of live Workspace path/device/inode;
it is distinct from the SQLite Workspace UUID, captured Paper UUID, attempt and
field generations. Public work omits Service fields. Prepared Service work uses
the original `TaskAuthority.native_access()` projection (scope, Service, key,
target and manual policy), forwarded by `WorkspaceTaskHost`; normal and recovery
guards still validate that exact captured access. Reading a current Paper does
not renew it or its abstract generation, and native deadlines consume the
remaining parent budget. Verified native document IDs are operation-local
evidence, never persistent identity or authority to reopen a closed page.
