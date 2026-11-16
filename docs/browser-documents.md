# Controlled Documents and article access

`BrowserRuntime` owns Page/WebContents, task claims and navigation.
`DocumentRuntime` and its sandboxed, context-isolated preload currently expose
fixed `binding`/`access` observations and `extract`/`pdf` snapshot reads. Main checks
reply/request, sender and native frame association. No site-facing host IPC,
Node capability or caller-supplied evaluator is exposed. Selecting a tab does not
choose a task target. Cancellation, destruction and pending-call cleanup remain
associated with their actual owner.

Public Download uses PDF-only refresh without recollecting Date/Abstract. A
separate fixed body action hands the original request/item to the body service
for qualified current forms and ScienceDirect readers. See [body downloads](body-downloads.md).

## Detached page snapshots

After navigation and access waiting, a fixed controlled read captures the current
rendered HTML, its URL and the supported ScienceDirect/LWW runtime PDF values in
one synchronous turn. The isolated preload builds an inert `DOMParser` Document,
resolves its first `<base href>` against the captured URL (or installs that URL as
the base), and runs Allfold's fixed rules there. Date/Abstract and PDF clues share
that input. PDF-only reads skip Date/Abstract entirely. Reader pages capture their
own snapshots after their source-chain qualification.

HTML and runtime values stay within the renderer/preload. No HTML, cookies,
site scripts or authentication material crosses host IPC, enters storage or
appears in diagnostics. The detached Document has no browsing context or host API;
it neither executes its scripts nor loads resources. No caller evaluator or
selector is accepted, and Translator Runtime remains retired.

Main accepts a reply only for its pending request and captured sender/process/frame.
It does not reread the page or compare URL, navigation generation, Document ID or
DOM node identity after parsing. Later hydration, history changes, reload or page
closure cannot revoke a received snapshot result. Closure, renderer exit or
cancellation before a result still fails the pending operation. The original
Workspace/Paper/attempt and field generations govern persistence.

A missing delayed ScienceDirect toolbar can prompt another PDF-only snapshot
within the existing task window. Previously captured content survives an optional
read failure. This does not add a replay, recovery state or snapshot identity gate.
Access classification uses the current main response and live visible structure.
Hidden CAPTCHA resources, optional sign-in fields in readable content and ordinary
error words do not independently block access. These observations are separate
from captured Date/Abstract/PDF results and never invalidate completed snapshots.

## Current fixed observations

- `binding`: content type, Document ID and host-captured Page/process/frame/URL/
  navigation facts. pageAction, CARSI selection/search/Visit and WoS results use
  this operation without an article DOI requirement. WoS alone can rebind its known
  `(overlay:export/exp)` route within the same original native Document and exact
  summary result route/query. New Documents, different result sets and unknown
  overlay routes remain refused; the export click is never replayed.
- `access`: fixed title/challenge/content-denial/login booleans and
  strictly validated Imperva `edet`/incident fields.
  HTTP status and `cf-mitigated: challenge` come from the actual native main request;
  unrelated iframe/script responses cannot challenge the main page. No title,
  HTML, script, iframe URL, query, form value or page text is returned.
- `extract`: one detached snapshot for Date/Abstract and PDF facts.
- `pdf`: one detached snapshot for PDF facts only, optionally for a qualified Reader.

Current probes return typed observations and sanitized diagnostic codes.
Supported Cloudflare challenges can use the existing Solver; hCaptcha, Imperva
CAPTCHA and MFA retain manual verification. Fixed challenge-frame and publisher
markers are implemented in the access preload. Raw page content, queries and
credentials are not diagnostic fields. These observations are not a universal
live-site compatibility guarantee.

## Internal Paper entry

`openPaperPage(data, identity, options)` is an internal capability used by
production metadata/PDF operations, without a standalone public IPC/button. A DOI string or `{doi}` starts
at `doi.org`; Run has already established the Paper identity. DOI-free
callers must supply an upstream-established `{confirmed_article_url}` relation.
A request URL alone is insufficient. Established article URLs retain their
fragment routes during navigation. The owning Workspace
branch settles collection; this page helper does not write it.

Callers navigate through access handling before the fixed snapshot read. Missing,
repeated or conflicting page DOI Meta and multiple article elements do not deny
collection. There is no article reauthentication action or final page recheck.
Candidate-specific DOI/URL, supplement and recommendation exclusions still protect
PDF selection. Reliable Paper creation/merging is separately owned by
[Paper identity](paper-identity.md).

## Solver, recovery and terminal ownership

Every BrowserRuntime Page installs a current-access observer at creation, including
user tabs, temporary task pages, retained Service/login targets, Readers and popups.
Observation runs outside business async context and survives operation completion.
Ordinary pages do not start Pydoll. `inspectPage`/`waitForPage` consume the same access
facts and retain their caller's cancellation/deadline; they do not own Solver.

A detected supported Cloudflare page or blocking visible widget enters Main's tab dispatcher
→ authenticated ElectronBridge → Pydoll on the existing Electron CDP endpoint.
The transient challenge ID, physical Page ID and exact native CDP target correlate
requests, progress, terminal replies and cancellation. Same-URL tabs cannot substitute
for each other. The dispatcher verifies that WebContents belongs to the managed
Session; Python finds frames only from that target, including accessible shadow
roots and attributable OOPIFs. Frame-tree/owner IDs establish ancestry; OOPIF
candidate IDs require a native owner in that parent before attachment. No full-DOM
shadow-root enumeration or whole-page HTML read is used. It never selects a page
by URL.
The observer and business waits use the same access evidence. A visible optional
Turnstile alongside readable content does not independently start interaction.

The current control must be connected, enabled, visible and hit-testable before
interaction. A transparent native checkbox can use its explicitly associated,
visible and hit-testable label; the original checkbox and label association are
rechecked before that click. Native hit-testing follows the actual control point
through its frame/target ancestry, rather than testing each iframe's center.
The point must hit that control or its descendants. Input uses those checked
coordinates without a later automatic scroll or position recalculation.
Pseudo-element hits use their originating element for the same ownership check;
an offscreen/stale native input does not veto its visible associated label.
Hidden or rebuilding auxiliary frames do not veto a known actionable control.
Ambiguous actionable controls wait. Pydoll reobserves current controls
across navigation, history changes and replacement; it does not require a fixed
Document, title/frame/checkbox order, attempt count or total 30-second window.
A clicked unchanged node is not clicked repeatedly; a replacement or observed
return to an actionable state can be handled again. Individual CDP calls have
resource timeouts, followed by cancelable observation. A click is not passage:
access waiting ends only when current challenge evidence clears/normal content
is available. Later challenges on the same live tab remain eligible.
Completed access messages clear on navigation to a new page; active challenge
interaction continues across redirects on the same native tab.

Each tab owns at most one active interaction through actual cleanup. Independent
Pydoll tasks use async I/O, with no global serial Solver slot or occupied shared
thread-pool worker during waits. Page destruction, renderer exit, temporary-task
cancellation immediately stops interaction, independently of slower download cleanup.
Page cleanup, Browser shutdown and Bridge loss also stop the corresponding work. Terminal
replies follow actual CDP cleanup. If the authenticated socket is lost, the owned
Python child pipe acknowledges the solver drain (or process exit proves it) before
Main releases waiting page cleanup. This fixed lifecycle acknowledgement carries
no page data or executable request. Retained user pages do not inherit an ended
business deadline. Per-solve global logger changes are removed; application startup
suppresses raw third-party transport logging.

The Browser's existing message area shows page-local waiting, Cloudflare handling,
manual authentication/verification, restored access or failure. These states and
bounded diagnostic reasons describe the current Page, not a Paper/Run state or a
retroactive verdict on completed extraction/download. Login/CARSI still own their
existing credential/consent actions. Solver never submits credentials, MFA or
business forms. Other CAPTCHA vendors remain manual. No HTTP API/stream response
opens an authentication tab or replays a POST for Solver.

Cloudflare's [response header](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/)
and [widget visibility/execution modes](https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/widget-configurations/)
inform these predicates. Resource presence alone is not a blocking challenge.

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
and WoS Query→Export loans. An ordinary Document registration refuses
main-frame form-download navigation; the separate body action supplies supported
original-response handoff. Already-bound DownloadItems follow actual request/item
results across incidental source-page changes.

Retained host adaptations keep their [third-party notices](third-party.md).

## Internal combined Document operation

The internal authenticated Bridge action is `extract_paper_metadata`, called by a
captured Workspace branch through `BranchContext.execute_native()` after base
Paper admission. It has no standalone public extraction button. Date/Abstract and
independent PDF clues share one detached snapshot. The parallel necessary-API branch
has separate resources; only all planned branch results and actual cleanup settle the Paper.
Foreground Run has its own serial slot and ends independently.

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
caller-supplied evaluator, selector or webpage request. The fixed snapshot parser only reads its detached Document: no network, page creation,
navigation, API lookup, click, live-DOM modification or Paper write.

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
  }
}
```

`metadata` has two fields: valid sorted unique month/day `dates` and a plain-text
`abstract` or null. Same-month qualified day records suppress the month; distinct
days remain. There is no terminal Document binding envelope. Validators check
structured content and PDF facts; request correlation remains inside Main. Date
traversal has a local work budget and retains dates found before exhaustion, with
`date_scan_failed`; it does not discard all dates at a count threshold. Abstract
size/work failures and malformed JSON-LD remain local diagnostics.

A valid empty DTO is `retrieved`. Fixed local diagnostics distinguish JSON-LD or
abstract failure from empty success. An independent PDF-reader failure can leave
valid Date/Abstract data and vice versa; the collection branch reports partial
failure explicitly. Page changes and normal owned-page cleanup do not
retroactively revoke a returned result; Python commits using original Workspace/Paper/attempt eligibility.

### Independent PDF clues and refresh

The Date/Abstract `metadata` contract above stays unchanged. The native envelope
additionally carries `metadata_status` and independent `pdf_clues` containing
the captured `landing_url`, `observed_at`, platform/content type, bounded
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
uses two fixed read-only main-world fields captured alongside HTML and URL;
a failed field read cannot erase other snapshot clues. Explicit platform selectors retain the same supplement,
whole-issue and conflicting article-DOI exclusions as generic entrances. LWW AN
is taken only from the current article outside peripheral regions and must be
unique; an ambiguous stored AN set cannot select a reader.
PDF candidate qualification uses the original Paper DOI when available, otherwise
unambiguous scholarly Meta or a supported DOI path. These are candidate exclusions,
not whole-page identity gates. Host-owned Unicode casefold data keeps Meta, control
DOI and DOI-path comparisons consistent; public arguments cannot supply code or
normalization data. PDF clues use the existing IPC byte capacity and local time budget. Oversized individual fields are skipped with a partial diagnostic while qualified earlier and later values survive; candidate/identifier counts are not separate whole-list gates. Article precollection reads candidates without fetching, probing, clicking
or submitting them.

`extract_paper_pdf_clues` and Python `read_document_pdf_clues()` provide an
independent PDF-only refresh. They do not execute Date/Abstract or emit metadata,
renew a collection token, reopen a completed collection or run necessary APIs.
A known reader has separate rule/Host/path/internal-ID/source-chain qualification
bound to the original target. It uses the captured request/target, access context and cancellation even when
article DOI/h1 proof is absent.
Challenges still use the shared access/solver boundary. Actions and one-time
responses remain typed refresh facts. The separate fixed body action capability
submits qualified live R059 forms without replay and follows observed R024 ScienceDirect reader/CDN navigation,
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
and JSON-LD remain independent of this root.

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
