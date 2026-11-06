# Integrated discovery and metadata

Run has one ordinary **Integrated Run** entry. Its saved Provider checkboxes apply
to both discovery and creation-time metadata requests. Selecting one discovery
provider uses the same path. **Run WoS** remains a separate authorized browser
workflow; it uses the same input language and Paper identity/persistence model.

| Provider | Journal discovery | Conference discovery | Identifier-only completion |
| --- | --- | --- | --- |
| OpenAlex | Saved ISSNs → verified Source; scoped title/abstract/keywords | None | Known DOI or Work ID, including existing Work relationships |
| Europe PMC | ISSN, `TITLE_ABS` / `KW`, publication date | None | DOI, source + record ID, PMID/PMCID |
| DBLP | Vetted ISSN → Stream mapping | Followed series' exact DBLP Stream | Reuse retrieved bibliographic metadata |
| zbMATH Open | Verified ISSN → serial, title/keywords/MSC, publication year | None | DOI or zbMATH record ID |
| Crossref | None | None | DOI, bibliographic dates and explicit same-work relationships |
| arXiv | None | None | Known linked arXiv ID through `id_list` |
| bioRxiv / medRxiv | None | None | Known DOI through original `details` / `pubs` APIs |

Europe PMC, DBLP and zbMATH need no API key. OpenAlex retains its explicit key
settings. The application never enables another provider to replace a failed or
unselected provider. A metadata-only selection cannot start a Run. Conference-only
Runs require DBLP; a mixed Run can retain valid Journal results while reporting an
unexecuted Conference scope.

Journal DBLP mappings are deliberately small: JMLR (`1532-4435`, `1533-7928`) and
Machine Learning (`0885-6125`, `1573-0565`). The [adapter mapping](../src/allfold/providers/dblp_sources.py)
records the official [JMLR](https://dblp.org/db/journals/jmlr/index.html) and
[Machine Learning](https://dblp.org/db/journals/ml/index.html) Stream/ISSN evidence.
Other journals report missing mapping; titles and abbreviations never authorize
whole-database queries. Conference Registry data and reproducible building are
described in [Research Scope](research-scope.md).

## Query language and fields

The shared parser accepts `AND`, `OR`, parentheses, quoted adjacent phrases and a
word-final `*` with at least four characters before it. For example:

```text
("transfer learning" OR "domain adaptation") AND estimat*
```

`NOT`, proximity operators, leading/internal wildcards, `?` and malformed groups
are rejected before retrieval. Provider compilers preserve grouping or report an
explicit capability limit. There is no natural-language generation step and no
SQLite FTS5 requirement for parsing, validation or ordinary discovery.

OpenAlex requests use `search.title_abstract_keywords`; prefix queries use the
scoped `.exact` variant. Unscoped `search` and `search.exact` are not used.
Europe PMC expands each term over approved `TITLE_ABS` and `KW` fields. zbMATH
queries use title, keyword and MSC indexes; review text is neither searched nor
stored as Abstract. Indexed Terms retain their provider and type, separate from
Author Keywords. WoS retains Topic coverage, including Keywords Plus.

DBLP uses `streamid:conf/nips:` for NeurIPS, with the requested years. Its native
query is a bounded conservative candidate query for Boolean groups and phrases;
the complete AST is then evaluated against each title in memory. Phrase matching
requires adjacent words in order within one field. Normal native hits from other
providers do not undergo a second local title/abstract filter: a missing returned
abstract or indexed-term field does not invalidate the remote keyword hit.

Different providers index different metadata and may stem words differently.
Missing abstracts reduce DBLP's title-only recall; there is no compensating full
collection scan, full-text search or unbounded metadata search.

## Dates and partial coverage

The Run date range restricts the publication record in a followed source. A 2026
Journal record can still have `first_public_at: '2022'`; that earlier first-public
date does not remove it from the 2026 discovery scope. Paper browsing uses first
public time separately from bibliographic publication time. Acceptance dates are
marked `≈` when approximated by appropriate post-acceptance publication evidence.
See [Paper identity](paper-identity.md) for the persisted evidence and precision.

DBLP years are Conference/publication years, not invented January dates or verified
acceptance dates. Monthly queries retrieve the intersecting years and display the
precision limitation. zbMATH also reports its year-level range limitation. These
limitations remain visible even after all accessible pages are retrieved. After
completion, confirmed publication dates for the same original formal version
refine year-only candidates against the requested months. A related preprint or
a Work-level date cannot exclude the formal source hit; unresolved precision
remains Partial, and another valid source hit still retains the work.

DBLP pages use `h` (at most 1000) and `f`. The adapter checks `@total`, `@computed`
and `@first`, advances by actual returned records and stops on no progress.
`computed < total` remains Partial after the accessible results are exhausted.
The application does not shard queries around upstream windows. Default adapter
budgets are 50 pages and 5000 records per source; truncation remains explicit.

| Result | Meaning |
| --- | --- |
| Complete | Executable declared scope finished without known retrieval truncation |
| Empty | A legal completed query returned no retained candidates |
| Partial | Usable results exist but retrieval or a declared scope was incomplete |
| Failed | The subtask could not produce valid results |
| Skipped / Not run | Selection, mapping or capability prevented execution; reason shown |
| Cancelled | User cancellation stopped further dispatch and writes |

Results report Provider/source/Stream, candidates, retained/deduplicated records,
new Papers, existing Papers and limitations. Supplement failures are separate from
discovery completeness. A failed provider does not discard successful providers'
results; all-failed discovery is never Empty or success.

## Completion and persistence

All eight Integrated Run discovery/completion providers reuse the shared HTTP
client, timeout/proxy policy, bounded retries and host pacing. HTTP 500/502/503/504
gets at most three attempts for the same request, with 5- then 10-second backoff
when no valid `Retry-After` is supplied. HTTP 429 also honors `Retry-After`, using
the existing one-second fallback. Both delta-seconds and HTTP-date hints are
accepted; a hint over 60 seconds stops the request with an explicit limitation
rather than retrying earlier than requested. Waiting is cancellable and reports
retry progress. Exhausted pagination retains valid earlier pages as Partial.

Ordinary HTML gateway/service errors are not mislabeled as bot verification.
Recognized verification pages (including Anubis at HTTP 200/202/503) stop further
HTTP requests for that Provider client in the current Run. Other selected
providers can finish. Unexpected HTTP 200 HTML, malformed JSON/XML and incomplete
provider envelopes are failures, not normal zero results. No challenge is solved,
and no proxy route, provider or identity is switched automatically.

### DBLP access restrictions

DBLP requests default to a two-second interval, following its official
[automated-access guidance](https://dblp.org/faq/1474706.html). The documented
[search API](https://dblp.org/faq/13501473.html) remains the configured endpoint.
This pacing reduces avoidable request pressure; it cannot remove a bot challenge.

On 2026-11-06, two small, sequential publication-search probes returned HTTP 202,
HTML titled “Making sure you're not a bot!”, and Anubis v1.27.0. The response's
Refresh target was an Anubis verification endpoint, not an ordinary search-page
redirect. No verification endpoint was followed. There was no 429/Retry-After
evidence in these responses, and they do not reveal whether IP reputation,
client characteristics or another server-side rule caused the restriction.

For unresolved restrictions, check normal website access manually and ask the
[DBLP team](https://dblp.org/db/about/team.html) to confirm the supported
programmatic access path or any required exception. Browser success alone does
not establish HTTP API access. Do not repeatedly retry the challenge, rotate
identities/proxies, automatically switch mirrors, or add a full-dataset mirror
to this application. The API remains unavailable until access is actually restored.

Europe PMC's [developer discussion](https://groups.google.com/a/ebi.ac.uk/g/epmc-webservices/c/WUWH9sunsEY)
distinguishes its service-overload 503 responses from explicit rate-limit status.
The service can recover independently; successful probes establish current
reachability, not that client retries repaired the upstream server.

Responses already retrieved in a Run are reused. Identifier lookups run in the
fixed order OpenAlex, Crossref, Europe PMC, DBLP, zbMATH, arXiv, bioRxiv, medRxiv,
restricted to enabled providers. At most two passes and 200 identifier lookups
bound newly discovered relationships; reaching a bound reports a supplement
limitation. There is no date-age cutoff on known preprint provenance.

Only reliable shared IDs or explicit same-work relations link records. Ordinary
references, comments/corrections and similar titles/authors do not. Ordinary
metadata fills missing fields only; author lists remain whole. The selected
formal source record remains primary when a linked preprint also exists. Dates
are selected from the combined evidence before first creation, rather than fixed
by whichever network response finishes first.

Every already-saved Paper is create-only for Integrated Run, including unkept
Discovery Papers. Existing Markdown, UUID, identifiers, metadata and human state
remain unchanged. Conflicting matches to multiple stored files are reported and
left untouched. There is no alias sidecar, Run database, durable queue, pagination
checkpoint or restart recovery. User editing and explicit browser Enrich retain
their own authorization and revision checks.

Network retrieval holds no Workspace exclusion. Commit rechecks the captured
configuration, source revision, original directories and saved identities under
one short cross-process lock, then atomically creates new files. Reset or directory
replacement invalidates old results. Cancellation preserves any already-finished
atomic creates and reports their actual count.

## Old data and manual acceptance

PubMed and its dedicated settings/query mode are removed. Create new settings
from `config.template.yaml` if an old configuration is rejected; choose the
providers explicitly. Old Papers/Run histories are not migrated automatically.
The existing Settings Workspace Reset is available only through its explicit
confirmation and deletes the configured Workspace, not YAML, user state, caches or
credentials. No development or test operation resets real user data.

An old key file is beside its YAML as `<config-stem>.pubmed-secrets.json`. It is no
longer read, written or deleted by Allfold; the user may remove it independently.
OpenAlex credentials and unrelated user scope are preserved.

Use a disposable configuration for manual acceptance:

1. Manage Journals and Conferences in the existing Journals workspace: offline
   search, follow/unfollow, order, Group/Labels, restart and scope import/export.
2. Select discovery and metadata-only checkboxes, including one discovery provider,
   Conference-only without DBLP, and a mixed scope with an unexecuted Conference.
3. Observe per-source progress, genuine empty results, provider failure/truncation,
   cancellation, supplement failures and year-only date limitations (Partial for monthly ranges).
4. Review/Keep/edit a DOI-free Paper and inspect its explicit unavailable external
   actions. Inspect both dates, approximation basis and typed Indexed Terms.
5. Check one primary-DOI Enrich on a Paper containing related DOIs, then inspect
   Prepare/Import eligibility and the selected primary DOI without starting a save.
   Inspect WoS query preview and, when available, one small genuine export through
   the shared parser/save/display model. Existing browser login, Zotero and PDF
   implementations do not require an exhaustive rerun for this discovery change.

Keep manual scenarios representative: one selected discovery provider, a mixed
scope with an unexecuted Conference, three Paper types and a repeated create-only
Run. Reset/concurrent writes, malformed pages and mismatched Translator DOI remain
covered by focused isolated regressions. Use small scoped HTTP probes for live
API contracts; do not repeat a known upstream verification challenge.

Isolated fixtures, source/build checks and CI are not evidence of real API
reachability, browser authentication, Zotero saving or PDF acceptance. Record each
of those outcomes separately when actually exercised.

Interface references: [OpenAlex scoped search](https://help.openalex.org/api/searching/),
[Europe PMC REST](https://dev.europepmc.org/RestfulWebService),
[DBLP API](https://dblp.org/faq/13501473.html),
[zbMATH API](https://api.zbmath.org/v1/),
[Crossref metadata](https://github.com/CrossRef/rest-api-doc/blob/master/api_format.md),
[arXiv ID/version API](https://info.arxiv.org/help/api/user-manual.html),
[bioRxiv/medRxiv original APIs](https://api.biorxiv.org/).
