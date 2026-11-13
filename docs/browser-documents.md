# Controlled Documents and article access

`BrowserRuntime` owns Page/WebContents, task claims and navigation. The existing
`DocumentRuntime` sends only the fixed `binding`, `access`, `article` and `extract` operations
to the sandboxed, context-isolated Document preload. It exposes no site API,
generic IPC, arbitrary evaluator, cookies or Node capability. Main validates the
reply sender, native process/frame, current navigation generation, exact URL and
preload-generated Document ID before accepting a bounded DTO. Pending calls end
on cancellation, navigation, destruction, crash or the remaining deadline; their
listeners and references are removed. Same-URL Pages do not share identity. An owned authentication read superseded
by an in-flight redirect returns loading and discards the old observation; it
does not end Login or replay any credential/selection action. Cancellation,
renderer failure and lost ownership remain terminal.

A native binding proves which Document produced facts. Article identity proves
whether that Document corresponds to a target Paper. Neither grants task, Service,
institution-credential or file authority. Same-document URL changes invalidate
captured bindings; primary-object changes are checked afresh at an article use
boundary. There is no permanent DOM observer or cached input-DOI proof.

## Fixed observations

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
  DOM turn. At most 32 values of 1,024 characters from the six scholarly head Meta
  keys and the scoped SciELO article DOI link locator. Multiple main articles or
  evidence overflow is unconfirmed; a matching subset never defeats a conflict.

URL bindings are limited to 4,096 characters. Access predicates inspect script
markers, individual DOM text nodes and iframe locations locally without truncation,
serializing or retaining page content. The host deadline bounds the native call;
invalid/incomplete DTOs are refused with `page_probe_unconfirmed`. Ordinary Cloudflare assets/embedded Turnstile resources,
or a bare 403/503, do not identify an automatic main challenge. Hidden hCaptcha
resources on an ordinary page do not themselves require verification; recognized
main challenge pages with hCaptcha retain the manual boundary. Existing title
rules and localized page-options plus challenge-page orchestrator combinations
remain. HTTP errors, 418, CPE00001 and Imperva denial remain failures; hCaptcha,
Imperva CAPTCHA (`edet=12`), institution login and MFA retain manual waiting.
Only validated fixed fields enter diagnostics, never raw queries or page content.

## Internal Paper entry

`openPaperPage(data, identity, options)` remains an internal capability with no
production business caller or public IPC/button. A DOI string or `{doi}` starts
at `doi.org`; it does not establish the redirected article's identity. DOI-free
callers must supply an upstream-established `{confirmed_article_url}` relation.
A request URL alone is insufficient. Established article URLs retain their
fragment routes during navigation and identity comparison. Background collection stays disabled and no
collection-completed state is written.

The order is controlled navigation → access checks/manual waiting/necessary solver
→ fresh current-Document article evidence → fixed identity result. Reuse and page
rebuild follow the same order. `confirmArticlePage` is the revalidation boundary
for a caller holding a prior result; a previously returned proof is not permanent
DOM authority. Identity confirmation remains independent of Date/Abstract content;
no author, Item or Translator operation is involved.

DOIs use the shared prefix/validity rules, reliable head Meta and applicable
current-article DOI `id`/`doi` parameters at an `/article` endpoint or DOI-suffix
paths, including multi-segment DOI suffixes. URL-only evidence requires a single article object; scholarly DOI Meta
also permits checking conflicting article URL facts. Generic main/search layouts
do not prove an article; resolver URLs do not count. Euclid journal `.full` and
SciELO article DOI links are scoped by host/structure, not Translator ID. IOP's
known `/article/DOI/meta` and `/pdf` views (and trailing route slash) are separated
from its multi-segment DOI by the explicit IOP host/route rule. References,
recommendations, arbitrary body text and unrelated frames supply no DOI evidence.
Conflicting main DOIs return `article_identity_conflict`. Missing/overflow/multiple
object evidence returns `article_identity_unconfirmed`, with a fixed internal
identity outcome/reason. DOI-free absence is `not_applicable`; a trusted established
article URL can confirm the current Document. This does not discover new platforms.

## Solver, recovery and terminal ownership

The retained chain is Browser `inspectPage`/`waitForPage` → real access preload →
Main's production target dispatcher → ElectronBridge → Pydoll on the existing
Electron CDP endpoint → fresh access check. Main captures the exact target and
checks task/Page/frame/Document/URL and navigation; full or same-document
navigation, crash, close, expiry and cancellation invalidate the solve. Same URLs
never select a target. Pydoll's supported challenge-frame ownership checks remain.

The operation ledger gives one effective Document at most two attempts, the second
only after the first `not_found`. Reentering a wait does not reset it. `clicked`
means an action occurred: persistent challenge/login/error remains waiting/failure,
and article access must still confirm identity. Unavailable/failed solvers and
manual waits end under the same parent deadline or cancellation.

Bridge's application solver slot stays held through actual worker cleanup. Queued
canceled/expired work cannot execute. Other requests and exact cancellation keep
flowing. Shutdown/disconnect stop queued/running work and join workers before
completion; no late callback is accepted. Covers and WoS Export now establish one
absolute request deadline across navigation, probes, business polling and waits.
WoS cancellation still cancels an original DownloadItem and waits for its actual
terminal before releasing native-save ownership; expiry cannot fabricate save
settlement. Document-scoped cleanup has its own short cleanup bound.

Existing two-refresh navigation budgets, origin cooldowns, attributable one-time
CARSI resource reentry and eligible Paper-page rebuild remain inside the original
parent budget. Unknown POST/authentication/one-time actions are never replayed.
Hidden pages retain nonzero viewports and do not select/focus the user's tab.
Readiness uses host time and main-frame state, not unlimited network idle.

## Validation and following tasks

The normal Electron test entry runs real BrowserRuntime/DocumentRuntime/preload
fixtures with temporary profiles and controlled local responses, public Bridge
queue/cancel tests, and the real Pydoll/CDP target fixture. The latter also connects
the production Main dispatcher to the real Python Bridge through a fixture-only
framed transport; WebSocket multiplex/settlement has separate Bridge tests.
These fixtures prove isolated mechanisms. Scoped live acceptance additionally
completed fresh CARSI Login with user QR authentication, Oxford/WoS preparation,
one 28-record native WoS export, one Cover Search and cancellation/restart in a
test copy. This is sample-specific compatibility evidence. No live Cloudflare,
hCaptcha or Imperva challenge, or separate MFA step, was observed; their live completion remains
unverified. See [WF03 status](workflow-refactor-tasks.md#wf03-document-access).

WF03 removes full-page/remoteTranslate-derived serialization, translation-only
frame enumeration, cookie/observer operations and unused Import-only attachment
capture/bypass helpers. Its local Session response-cancel/URL-capture loop is gone.
WF04 owns consolidation of the remaining shared Session listeners, original
DownloadItem capability fixtures, page quotas/scheduling and complete page-close
policy. No replacement downloader is introduced. WF06 adds the internal Date/Abstract operation below; production collection
registration and orchestration remain deferred to WF08. Retained adapted host sources keep their AGPL notices;
official vendor trees, dependency pins and real user data are unchanged.

The shared Session entry and measured original-response behavior are documented
in [Browser Session](browser-session.md). WoS uses that native router while
retaining all Document, known-overlay and real-terminal rules above. Missing
frame/source facts never become current-page or URL-based Document authority.

## WF04 page ownership boundary

Document authority does not grant resource ownership or extend a page lifetime.
Temporary article/Covers/helper pages close after their operation; retained Portal
and Service targets have explicit bounded access-context owners. WoS result loans
protect the original native Document through Query→Export gaps. Actual close and
key invalidation revoke preparation state. See [Browser pages](browser-pages.md).

The fixed resource fixture records a current unsupported BrowserRuntime entry:
main-frame form POST download starts a new navigation generation, so its old
Document registration is refused and the original item is canceled to actual done,
without a new GET. The shared Session original-POST fixture is a separate capability
seam, not permission to relax these checks or claim all Runtime entries supported.


## WF06 internal Date/Abstract operation

The internal authenticated Bridge action is `extract_paper_metadata`, called by a
captured Workspace task through `BranchContext.execute_native()`. It has no public
HTTP/button entry and is not installed in production Run. Run still owns its
ordinary Completion, creation/completion timing and single slot; the public
Preprint entry retains its gate. This operation supplies no PDF fact and does not
mark a real Paper's complete collection group finished.

The payload carries the existing workflow/task/Paper association,
`workspace_identity` (the existing 64-hex live Workspace path/inode hash, **not**
the SQLite Workspace UUID), `identity:{doi?,confirmed_article_url?}`, a strictly
boolean `wantAbstract`, and absolute integer `deadline_ms`. It opens/recovers only
through `openPaperPage`, checks access before fresh independent Paper identity,
and uses the owning operation's recovery-authority callback. It does not borrow a
foreground Run snapshot. A Service call additionally carries the captured
`service_scope`, `service_id`, `preparation_key` and `target_page_id`. A retained
target must match the actual native access context/key/Page; it is pinned through
actual work-page cleanup without being navigated or closed. A captured explicitly
manual preparation with no target instead requires `manually_confirmed:true` and
the same captured key; Python's task authority and recovery check retain that
policy. No Service fields are needed for public access.

The runtime action is `extract` with exactly `{wantAbstract:boolean}`. Other args,
unknown actions and non-booleans fail before dispatch; the sandboxed preload
validates them again. `readDocument` forwards these fixed args. It never accepts an
evaluator, selector, HTML string, Provider response or webpage request. The pure
DOM observation only reads the current Document: no network, page creation,
navigation, API lookup, click, source-DOM modification or Paper write.

Successful Main results use:

```json
{
  "outcome": "retrieved",
  "metadata": {"dates": [], "abstract": null},
  "extraction_diagnostics": [],
  "document": {
    "pageId": 1,
    "processId": 2,
    "frameToken": "opaque-native-token",
    "documentId": "preload-generated-id",
    "navigationGeneration": 1
  }
}
```

`metadata` has exactly two fields; dates have exactly `value` and `precision`.
Dates are valid, sorted, unique `YYYY-MM`/`month` or `YYYY-MM-DD`/`day` records,
at most 256. Same-month qualified day records suppress the month; distinct days
remain. Abstract is nonempty plain text or null, capped at 65,536 UTF-16 code
units for IPC (a separate limit from date context code-point counting). C0 controls
other than ordinary whitespace are refused. No event, source, evidence, platform,
HTML, raw block, author or DOM path enters this DTO. The document envelope is
bounded native evidence, has no URL or credential, and grants no new task or
storage authority. Main can append its existing sanitized recovery/diagnostic
status annotations.

A valid empty DTO is `retrieved`, not `no_result`. Local diagnostics are unique,
limited to four fixed codes: `json_ld_invalid`, `json_ld_ambiguous`,
`abstract_candidate_failed`, `abstract_budget_exceeded`. A locally failed or
over-budget abstract candidate can leave qualified dates and this explicit
partial diagnostic; it never becomes a truncated successful abstract. The caller
must retain that distinction. A missing/challenged/wrong-identity/cancelled/expired
or wholly failed Document returns a failure diagnostic and no metadata. Date
result overflow and the fixed five-second local scanning budget fail the whole
read instead of truncating output. The parent deadline can be shorter. JSON-LD
scripts exceeding the 262,144 UTF-16-unit parsing input bound contribute no facts
and carry `json_ld_invalid`; their contents are never truncated into valid JSON.

Reading and final access/article revalidation occur while the exact Document is
live. An isolated-world WeakMap assigns opaque identities to the body, legal first
h1 and unique top-level article. Captured, extracted and final subject identities
must agree. Body/root/h1 replacement, even at the same DOI and URL, invalidates
both fields; native Document ID, exact URL, frame/process, navigation generation
and cancellation remain independently checked. Only after this final check does
`runTask` close its temporary page and Main send the small result. Normal owner
cleanup does not retroactively revoke verified metadata; Python commits under its
captured Workspace/Paper/attempt token without reopening a closed page. This
same-operation, pre-cleanup seam can later compose WF07 PDF clues, but WF06 has no
empty PDF collector or fabricated skipped/completed PDF outcome.

### Shared extraction scope

Body traversal excludes script/style/noscript/template subtrees, navigation
semantics, page-level footer, `hidden`, `aria-hidden=true`, and explicit inline
`display:none`; it performs no inferred CSS visibility or simulated expansion.
An article-internal footer remains eligible for dates. The DOM root is the sole
legal top-level article only when it contains the first legal h1; no article,
multiple articles or an outside h1 falls back to legal body. Abstract additionally
excludes explicit recommendations and peripheral UI in that same root. Head Meta
and JSON-LD remain independent of this root. The algorithm-only multi-article
fallback does not relax the host identity probe's existing multiple-article
refusal.

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
`SS-2025-0362`/`1023-1042`. Complete URL tokens, including query and fragment
values, cannot contribute dates. Missing range endpoints are not filled. ISO
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
  once, including paragraphs around marked children; independent identical
  copies merge. Graphical/Video/Lay or author summaries, navigation, recommendations,
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
Hidden/peripheral preview markers and controls do not disqualify visible content.
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
