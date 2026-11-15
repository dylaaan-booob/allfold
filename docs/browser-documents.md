# Controlled Documents and article access

`BrowserRuntime` owns Page/WebContents, task claims and navigation.
`DocumentRuntime` and its sandboxed, context-isolated preload currently expose
fixed `binding`, `access`, `article`, `extract` and `pdf` observations. Main checks
reply/request, sender and native frame association. No site-facing host IPC,
Node capability or caller-supplied evaluator is exposed. Selecting a tab does not
choose a task target. Cancellation, destruction and pending-call cleanup remain
associated with their actual owner.

Public Download uses PDF-only refresh without recollecting Date/Abstract. A
separate fixed body action hands the original request/item to the body service
for qualified current forms and ScienceDirect readers. See [body downloads](body-downloads.md).

## Current reading limits and planned changes

Current code still rejects same-document URL changes, replaced body/h1/article
objects and failed repeated article/final-read checks. These are existing
limitations, not conditions future implementations must preserve. A confirmed
Paper does not need repeated identity proof at every page-reading boundary.
The chosen follow-up captures the current rendered HTML, URL and needed values,
then parses an independent Document. That snapshot path is not implemented here;
Translator Runtime remains retired. Request/target correlation, cancellation and
protected Paper writes continue to apply.

Current access predicates include broad page markers. Weak strings such as a
password field, CAPTCHA text or `access denied` in otherwise unrelated content
are insufficient as the future basis for denying article access; access
classification will be revised with its behavior tests.

## Current fixed observations

- `binding`: content type, Document ID and host-captured Page/process/frame/URL/
  navigation facts. pageAction, CARSI selection/search/Visit and WoS results use
  this operation without an article DOI requirement. WoS alone can rebind its known
  `(overlay:export/exp)` route within the same original native Document and exact
  summary result route/query. New Documents, different result sets and unknown
  overlay routes remain refused; the export click is never replayed.
- `access`: fixed title/challenge/content-denial/login booleans and
  strictly validated Imperva `edet`/incident fields.
  HTTP status comes from the actual native main-frame navigation. No title,
  HTML, script, iframe URL, query, form value or page text is returned.
- `article`: access markers and limited main-article evidence from one synchronous
  DOM turn, using scholarly head Meta
  keys and the scoped SciELO article DOI link locator. Multiple main articles or
  evidence overflow is unconfirmed; a matching subset never defeats a conflict.

Current probes return typed observations and sanitized diagnostic codes.
Supported Cloudflare challenges can use the existing Solver; hCaptcha, Imperva
CAPTCHA and MFA retain manual verification. Fixed challenge-frame and publisher
markers are implemented in the access preload. Raw page content, queries and
credentials are not diagnostic fields. These observations are not a universal
live-site compatibility guarantee.

## Internal Paper entry

`openPaperPage(data, identity, options)` is an internal capability used by
production metadata/PDF operations, without a standalone public IPC/button. A DOI string or `{doi}` starts
at `doi.org`; it does not establish the redirected article's identity. DOI-free
callers must supply an upstream-established `{confirmed_article_url}` relation.
A request URL alone is insufficient. Established article URLs retain their
fragment routes during navigation and identity comparison. The owning Workspace
branch settles collection; this page helper does not write it.

Current callers navigate through access handling and the article probe before
reading. `confirmArticlePage` is an existing recheck helper; its repeated use is
part of the reading limitation above, not a permanent design obligation.

The current article probe uses reliable head Meta and qualified article URLs,
with explicit platform routing for multi-segment DOI paths. It excludes references,
recommendations and unrelated frames. Missing/conflicting observations currently
return `article_identity_unconfirmed` / `article_identity_conflict`; this describes
the helper, not a requirement to rerun it for an already-confirmed Paper. Reliable
Paper creation/merging is separately owned by [Paper identity](paper-identity.md).

## Solver, recovery and terminal ownership

The current chain is Browser `inspectPage`/`waitForPage` → access preload →
Main's target dispatcher → ElectronBridge → Pydoll on Electron's CDP endpoint →
access observation. Exact native targets and owned challenge frames prevent
same-URL tabs from being confused. A click is an action result, not proof that
access succeeded.

Solver is currently attached to business operations and fixed Documents, with
navigation invalidation and a limited attempt ledger. Those restrictions are
scheduled for replacement by tab-wide solving; that capability is not implemented
yet. Document/URL changes and a fixed order/count are not future Solver constraints.

Bridge currently serializes Solver work through an application slot and joins
actual workers on cancellation/shutdown. Queued cancelled work cannot execute;
other requests and exact cancellation remain routable. Browser recovery and
cooldowns currently share the operation deadline. Numeric attempt/refresh limits
are implementation details, not platform guarantees. Unknown POST/authentication/
one-time actions are not replayed. Background pages keep a usable viewport without
selecting or focusing the user's tab. PDF-only ScienceDirect reads currently allow
its toolbar to hydrate before declaring a complete empty observation.

## Validation and page ownership

The serial Electron suite uses real BrowserRuntime/DocumentRuntime/preload,
production Main/Bridge dispatch and Pydoll/CDP with temporary profiles and local
responses. These prove controlled mechanisms, not universal publisher access.
Live Cloudflare, hCaptcha, Imperva and MFA completion remains unverified by those
fixtures. Historical CARSI/WoS/Cover samples are recorded in their PRs.
[PR #76](https://github.com/dylaaan-booob/allfold/pull/76) observed intermittent
Service-opening failures with an undetermined cause; universal batch reliability
has not been established, and that old sample is not proof of a current failure.

[Browser Session](browser-session.md) owns original-response routing;
[Browser pages](browser-pages.md) owns temporary pages, retained access targets
and WoS Query→Export loans. An ordinary Document registration currently refuses
main-frame form-download navigation; the separate body action supplies supported
original-response handoff. That limitation is not a requirement to invalidate
already-bound DownloadItems on incidental page changes.

Retained host adaptations keep their [third-party notices](third-party.md).

## Internal combined Document operation

The internal authenticated Bridge action is `extract_paper_metadata`, called by a
captured Workspace branch through `BranchContext.execute_native()` after base
Paper admission. It has no standalone public extraction button. Date/Abstract and
independent PDF clues share the current page. The parallel necessary-API branch
has separate resources; only all planned branch results and actual cleanup settle the Paper.
Foreground Run has its own serial slot and ends independently. Explicit Preprint
uses the same Paper occupation gate without impersonating collection.

The payload carries the existing workflow/task/Paper association,
`workspace_identity` (the existing 64-hex live Workspace path/inode hash, **not**
the SQLite Workspace UUID), `identity:{doi?,confirmed_article_url?}`, a strictly
boolean `wantAbstract`, and absolute integer `deadline_ms`. It currently opens/recovers
through `openPaperPage` and uses the owning operation's recovery-authority callback.
It does not borrow a foreground Run snapshot. A Service call additionally carries the captured
`service_scope`, `service_id`, `preparation_key` and `target_page_id`. A retained
target must match the actual native access context/key/Page; it is pinned through
actual work-page cleanup without being navigated or closed. A captured explicitly
manual preparation with no target instead requires `manually_confirmed:true` and
the same captured key; Python's task authority and recovery check retain that
policy. No Service fields are needed for public access.

The runtime action is `extract` with exactly `{wantAbstract:boolean}`. Other args,
unknown actions and non-booleans fail before dispatch; the sandboxed preload
validates them again. `readDocument` forwards these fixed args. It accepts no
caller-supplied evaluator, selector or webpage request. The pure DOM observation only reads the current Document: no network, page creation,
navigation, API lookup, click, source-DOM modification or Paper write.

Successful Main results use:

```json
{
  "outcome": "retrieved",
  "metadata_status": "complete",
  "metadata": {"dates": [], "abstract": null},
  "extraction_diagnostics": [],
  "pdf_clues": {
    "status": "complete",
    "landing_url": "https://journal.example/article/1",
    "observed_at": "2026-11-14T00:00:00.000Z",
    "platform": "generic",
    "content_type": "unknown",
    "identifiers": [],
    "candidates": [],
    "diagnostics": []
  },
  "document": {
    "pageId": 1,
    "processId": 2,
    "frameToken": "opaque-native-token",
    "documentId": "preload-generated-id",
    "navigationGeneration": 1
  }
}
```

`metadata` has two fields: valid sorted unique month/day `dates` and a plain-text
`abstract` or null. Same-month qualified day records suppress the month; distinct
days remain. The document envelope carries native evidence, without credentials
or new task/storage authority. Current validators enforce field/count/size budgets;
those arbitrary numeric caps are not extraction rules to perpetuate.

A valid empty DTO is `retrieved`. Fixed local diagnostics distinguish JSON-LD or
abstract failure from empty success. An independent PDF-reader failure can leave
valid Date/Abstract data and vice versa; the collection branch reports partial
failure explicitly. Current final-read/subject validation is covered by the
limitation above. Normal owned-page cleanup does not retroactively revoke a
returned result; Python commits using original Workspace/Paper/attempt eligibility.

### Independent PDF clues and refresh

The Date/Abstract `metadata` contract above stays unchanged. The native envelope
additionally carries `metadata_status` and independent `pdf_clues` containing
the actual final `landing_url`, `observed_at`, platform/content type, bounded
identifiers, ordered P3/P4 candidates and finite diagnostics. A local metadata
failure can leave valid PDF facts, and a local PDF failure can leave valid
Date/Abstract values. Failure remains explicit; a legal complete-empty PDF read
is normal. The collection adapter emits a single combined increment, then
settles a partial branch as failed. It never returns that increment for a second
commit. Cancellation and task authority remain owned by the captured operation.

The fixed runtime `pdf` action accepts only a validated reader kind, never a
caller-supplied selector/evaluator. It reads Meta in citation-then-fulltext order,
qualified platform selectors and unambiguous article PDF entrances, with explicit
supplement/reference/recommendation exclusions. Known ScienceDirect/LWW state
uses fixed bounded read-only fields; it does not assume isolated world 999 sees
main-world variables. Explicit platform selectors retain the same supplement,
whole-issue and conflicting article-DOI exclusions as generic entrances. LWW AN
is taken only from the current article outside peripheral regions and must be
unique; an ambiguous stored AN set cannot select a reader.
PDF entry identity reuses the fixed article probe's bounded DOI values and
recognized scholarly metadata sources, including equivalent duplicate fields.
The private fixed PDF message carries the existing host-owned Unicode casefold
data used by article identity; Meta, control DOI and DOI-path comparisons share
those semantics. Public operation arguments cannot supply normalization data.
Current validators report overflow rather than returning truncated successful
facts. Article precollection reads candidates without fetching, probing, clicking
or submitting them.

`extract_paper_pdf_clues` and Python `read_document_pdf_clues()` provide an
independent PDF-only refresh. They do not execute Date/Abstract or emit metadata,
renew a collection token, reopen a completed collection or run necessary APIs.
A known reader has separate rule/Host/path/internal-ID/source-chain qualification
bound to the original target. It uses the captured request/target, access context and cancellation even when
article DOI/h1 proof is absent.
Challenges still use the shared access/solver boundary. Actions and one-time
responses remain typed refresh facts. The separate fixed body action capability
submits qualified live R059 forms and follows R024 ScienceDirect entries once,
binding the original response to the exact request/frame/DownloadItem. Public
reusable-URL transfer uses the Session body service; both paths share managed
publication and SQLite completion. Native staging retains the
[accepted Chromium cancellation risk](body-downloads.md#native-output-and-accepted-cancellation-risk).
See the [complete adopted rules](pdf-source-discovery.md).

The same internal `extract_paper_pdf_clues` action accepts the fixed
`reader_access_only: true` mode instead of a reader. It returns
`{outcome:"retrieved", reader_access:{oce:boolean}}`, without opening a page,
reading content or exporting a URL, handle or secret. The bit describes only the
captured Service/key/retained target's actual `oce.ovid.com` Host; a CARSI entry
URL or Service name is not the decision. It is operation-local and grants no
authority by itself. An OCE read subsequently requires that same live prepared
target again, the original Paper binding and a qualified AN. Only the fixed
`https://oce.ovid.com/article/{AN}/HTML` and its known
`/pdfviewer/web/viewer.html?file=...` carrier are accepted; the file value must
point to `assets.ovid.com` and retains its complete signature. An empty LWW
viewer can reach this conditional alternative, keeping its original discovery
phase and recording a fallback. Missing OCE access skips it. The OCE reader itself does not bootstrap access or receive PDF bytes.

### Shared extraction scope

Body traversal excludes script/style/noscript/template subtrees, navigation
semantics, page-level footer, `hidden`, `aria-hidden=true`, and explicit inline
`display:none`; it performs no inferred CSS visibility or simulated expansion.
An article-internal footer remains eligible for dates. The DOM root is the sole
legal top-level article only when it contains the first legal h1; no article,
multiple articles or an outside h1 falls back to legal body. Abstract additionally
excludes explicit recommendations and peripheral UI in that same root. Head Meta
and JSON-LD remain independent of this root. The host identity probe currently has a separate multiple-article refusal,
covered by the reading limitation above.

Date matching follows source order and preserves continuous inline text. Complete
li/tr records are indivisible, including nested p/div/td; semantic p/headings,
dt/dd, blockquote and figcaption use their whole block. Ordinary containers split
at independent block children and preserve remaining inline runs. Independent
links introduce matching boundaries, without turning their short text into a
shorter enclosing li/tr context. After whitespace normalization, a complete
record of at most **150 Unicode code points** qualifies its dates/time values;
151 does not. One legal short occurrence suffices, while out-of-root appearances
do not participate. Abstract has neither this threshold nor a shortest-record
rule.

Only `application/ld+json` scripts are parsed. Allowed entrances are a top-level
object/array, direct `@graph` members and an inline `WebPage.mainEntity` article.
Schema.org context (including inherited graph context) or a complete Schema.org
type URI is required; string/array `Article` and `ScholarlyArticle` types are
supported. One stable article is required. Identical repeated information or the
same stable `@id` can deduplicate; multiple articles, conflicting copies and
complex references give this channel no contribution. Only the article's direct
`datePublished`, `dateModified` and `abstract` are read. Publisher/WebSite/page
fields, recommendations, citations, ordinary JSON caches and global state are not
walked. A damaged script cannot erase DOM/Meta or another valid script's result.

### Dates

Supported finite grammars are year-first hyphen/slash year-month/day, English
full/common abbreviated months in day-month-year, month-day-year or year-month
order, Chinese year-month/day, complete-day ISO timestamps, and numerically
unambiguous year-last slash dates. Years and months must be explicit. Calendar
validation checks leap years and month/day ranges. Invalid full candidates never
degrade to month-only results. Ambiguous `04/02/2020` is refused; `13/02/2020` and
`02/13/2020` have one valid order. Token boundaries reject URL/DOI/identifier
substrings, suffixes such as `2020-04junk`, and manuscript/page ranges such as
`SS-2025-0362`/`1023-1042`. Complete URL and supported raw DOI tokens, including
query and fragment suffixes, cannot contribute dates. Missing range endpoints
are not filled. ISO
`T`/`Z` markers are case-insensitive and all variants receive the same full time
validation, retaining their written calendar day without a timezone conversion.

`time[datetime]` and displayed text are parsed independently, sharing their whole
record's 150-point limit; a short attribute has no exemption. Pure times and
durations contribute nothing. Head Meta reads the entire `content`, with
case-insensitive `name`/`property`: `citation_publication_date`,
`citation_online_date`, `citation_cover_date`, `dc.date`,
`prism.publicationDate`, `citation_date`, and `article:published_time` only with
`og:type=article`. No other maintenance/year/itemprop fields are scanned. Meta
and qualified JSON-LD bypass the DOM length rule as separate channels. All four
channels filter first, then union/deduplicate/suppress month/sort; a rejected long
record's day cannot suppress an accepted Meta month. Explicit future ordinary
dates remain, without Run-range filtering or publication/first-public inference.

### Abstracts

The fixed preference is **A1 → A2 → B → C**, with no API-versus-DOM write priority:

- **A1:** exact case-insensitive IDs `abstract`/`abstracts`, class tokens
  `abstract`/`abstract-content`/`abstractInFull`, or a section/region with a unique
  strict Abstract aria label/title association. Substrings are insufficient.
  Nested markers share one explicit semantic owner, whose full content is read
  once, including paragraphs around marked children. Identical complete marked
  candidate copies merge, including nested copies; ordinary repeated paragraphs
  remain intact and conflicting complete copies fall through. Graphical/Video/Lay
  or author summaries, navigation, recommendations,
  footer/hidden areas and title/button-only regions are refused.
- **A2:** strict Abstract h2–h6 or explicit section-heading labels, normalizing
  surrounding whitespace, trailing colon and decorative punctuation. Summary is
  eligible only when no Abstract heading exists and a finite current-paper
  section is established. Prefer a small independent section/aria region;
  otherwise require an ending sibling section. Stop at same/higher headings or
  independent Keywords/Introduction/References markers, even with inconsistent
  levels; preserve lower Background/Methods/Results/Conclusions headings. An
  unbounded heading cannot consume the rest of the article.
- **B:** head academic Meta in order `citation_abstract`, `dcterms.abstract`,
  `dc.description.abstract`. Normalize same-field equal duplicates; different
  valid texts conflict and fall through to another decidable source. Different
  fields are never concatenated or compared by length.
- **C:** the unique qualified article's direct `abstract` string/safely purified
  text. JSON-LD `description`, ordinary/OG/Twitter/DC description never fill it.

Text keeps original paragraph order and newline-separated independent blocks,
internal scientific headings and inline scientific content. Structured text
interprets only known markup in an inert template, preserving literal `<T>`,
`E<T>` and `x<y` notation. Only standalone
Abstract/Summary wrapper headings and explicit buttons/action links,
figure/table labels and keyword UI are removed. Short complete texts are valid.
Explicit previews, unexpanded Read more/Show more fragments, ellipsis-only text
and empty notices are refused without a click in DOM, Meta and JSON-LD alike;
invalid structured peers do not create a conflict with a valid candidate.
Notice matching collapses whitespace without changing accepted paragraph text.
Preview scanning shares the abstract-subtree exclusions: hidden/peripheral UI,
figures and keyword lists do not disqualify visible content or narrow Date scope.
Different valid same-level DOM
candidates fall through to independent structured sources; no first/longest
choice, source concatenation, generation, translation or Title fallback exists.
`wantAbstract=false` skips the abstract scanner entirely and still extracts
dates. Abstract/JSON-LD local faults do not erase successful date work.

`document-extraction.test.cjs` runs real Electron 45, production Main dispatch,
BrowserRuntime, DocumentRuntime and preload against local HTTP and disposable
profiles. It covers grammar/scope/Unicode/record/Meta/JSON-LD/abstract cases,
actual normal cleanup, replacement/navigation/cancellation and local/whole read
failure. An optional explicit temporary output path to
`document-extraction.fixture.cjs PROFILE OUTPUT_JSON` exports the actual verified
structured DTO for cross-language integration; append `--sample-only` to execute
just that real Main/Document sample. Generated profiles/results are
not source artifacts. No institution account, live publisher acceptance, actual
PDF or production collection concurrency is established by these fixtures.
