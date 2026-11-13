# Controlled Documents and article access

`BrowserRuntime` owns Page/WebContents, task claims and navigation. The existing
`DocumentRuntime` sends only the fixed `binding`, `access` and `article` operations
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
DOM authority. No authors, dates, abstract, Item, Translator detect or body
extraction are required.

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
These prove isolated mechanisms, not live Cloudflare/CARSI/WoS compatibility.

WF03 removes full-page/remoteTranslate-derived serialization, translation-only
frame enumeration, cookie/observer operations and unused Import-only attachment
capture/bypass helpers. Its local Session response-cancel/URL-capture loop is gone.
WF04 owns consolidation of the remaining shared Session listeners, original
DownloadItem capability fixtures, page quotas/scheduling and complete page-close
policy. No replacement downloader is introduced. WF06–WF08 connect article
extraction/collection later. Retained adapted host sources keep their AGPL notices;
official vendor trees, dependency pins and real user data are unchanged.
