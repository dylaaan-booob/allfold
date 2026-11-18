# Local Allfold / Zotero PDF pairing acceptance

Issue: [#140](https://github.com/dylaaan-booob/allfold/issues/140). Baseline:
`a2e511aa86ab5aa292f224301d6609a59c287fa2`.

**Status: incomplete. At the 18 November 2026 checkpoint (Asia/Shanghai), 27
of the 31 frozen Papers have paired observations (65 pair slots including repeats).
One Project Euclid Paper is excluded from saving because it requires a
subscription. The three INFORMS Papers are pending access checks. Twenty-five
earlier low-load publisher pairs, four ScienceDirect pairs and one Project Euclid
pair have reliable local file and association endpoints. Springer has two slower
Allfold points and one
interval overlap; T&F has one slower point requiring swapped repeats. The measured
Cambridge/IEEE prepared-access cohorts show no observed disadvantage; overall
coverage and retests remain incomplete. F18 exposed a publisher-version/latency
gap. Direct-entry and Referer repairs alone still returned a preprint. The first
real retest of the common native partition-context repair at `69b9a41` saved the
correct publisher PDF through P1, but was 3.832–4.644 seconds slower than Zotero.
The control and untouched same-platform Paper also saved correct publisher PDFs,
but their first paired waits were slower; F17/F18 warm repeats favor Allfold.
F19's second pair encountered a new challenge and saved a related preprint. A
subsequent same-Session ePDF visit denied institutional access. Normal resource
reentry restored actual entitlement and the unchanged code saved its publisher
PDF in two new pairs. A remaining large-PDF warm-repeat user-wait disadvantage
has direct cache-reuse evidence and is not declared met. The first formal
ScienceDirect pair, F26, failed on both products after independent institutional
preparation. In F26-2, both native viewers had already displayed the same
publication. Zotero saved the correct PDF in 9.741–10.036 s, while Allfold's
CDN requests encountered challenges and ended without a file. After repair,
F26 saved the publication automatically on Allfold and with user assistance on
Zotero. All three new ScienceDirect first pairs saved the same publication in both
products and showed slower Allfold waits. F28 saved the same related preprint on
both products. F27's original Allfold CDN failure and unobserved Zotero terminal
remain in the table. Both products saved the publication in its revised pair,
where Allfold automatically solved a Reader challenge and used a second source.
That pair was slower on Allfold. Further coverage and affected retests remain
required.
Workspace is retained.**

## Environment and endpoint

The source checkout, rebuilt UI, live process and local API were checked, rather
than inferring the running version from Git. macOS 27.2.1 (26B131); Electron
45.0.0 / Chromium 156.0.8078.48; Chrome 157.0.8103.51, existing Default profile;
Zotero Desktop 10.0.9 / Connector 5.0.217. After sleep, Chrome About was observed
first at 157.0.8103.51 and later at 157.0.8103.79 (also the on-disk version); no
operator-triggered update/restart was performed. The exact running-binary
transition time is unknown and is not claimed as a performance improvement.
Connector could reach Desktop and local
PDF saving was proven with actual imported attachments. A dedicated acceptance
collection holds the trials. PDF saving was enabled; snapshots and automatic
sync were disabled. PDFTranslate 2.4.8 and Style 6.0.111 remained enabled.

The configured Workspace initially contained no Paper database. A normal product
Run created 15 Papers from the existing PU query and configured journals. Original
provider selections were restored. A normal OpenAlex-only Bayesian October Run
then added 57 Papers. The original query, month range and all provider selections
were restored exactly; all 72 collections settled before formal Download. No direct
SQLite writes or injected PDF URLs were used. The local obsolete `kept_workflow`
configuration prevented startup; a private backup was retained and only the local
configuration was updated to its current `workflow` spelling and supported fields.

Both products used the same machine/system proxy and existing lawful access.
An ordinary Chrome window shared its existing profile, cookies and cache. Electron
had its own Session; institutional access was established separately through the
product. No cookies or authorization headers were copied between products.
Article/challenge preparation and repeated warm visits are recorded separately.

The endpoint is a correct permanent local PDF **and** its original Paper/attempt
association, or a Zotero imported PDF file **and** its parent attachment relation.
A read-only observer sampled both at nominal 250 ms, retaining actual preceding
poll times. UI clicks also have bounded timestamps. Displayed times are intervals;
observer restarts do not supply completion timestamps for preexisting files.
Native `stream_complete`, parent creation, progress 100%, and a visible viewer
are insufficient individually. Opening/identity verification followed completion
and is excluded from product wait time. Trials ran sequentially with no builds,
full tests or competing download during the measured interval.

## Pilot observations

The [result table](pdf-pairing-results.json) retains unsuccessful trials and
code-version relationships. No pilot contributes to formal aggregate scores.

| Pilot / DOI | Platform / access | Order | Allfold local PDF | Zotero local PDF | Interpretation |
| --- | --- | --- | --- | --- | --- |
| P01 / 10.1093/bioinformatics/btag263 | Oxford/Silverchair, OA | A→Z | 6.874–7.218 s | Not observed | Article verification/save-session issues; no parity conclusion. |
| P02 / 10.1007/s10618-026-01264-1 | Springer Link, OA | Z→A | 147.498–147.953 s | 151.652–151.975 s | Same published version, 30 pages, 2,728,411 bytes; one pilot pair only. |
| P03 / 10.1016/j.patcog.2026.114755 | ScienceDirect, institutional | A→Z, diagnostic retries | Initial discovery/Reader failures; fix2 retry 10.455–10.816 s | Parent only; PDF not observed | Correct 13-page PDF after repair; different Session/access/cache conditions prevent a code-only timing attribution. |
| P04 / 10.1109/tnnls.2026.3706351 | IEEE Xplore, institutional | Z→A; diagnostic retries; three complete new balanced pairs | Initial expiry about 600 s; later diagnostic 20.481–20.887 s and 17.571–17.946 s; paired repeats 14.558–15.513 s | Initial 17.829–18.220 s; paired repeats 16.061–16.834 s | New same-version pairs support no observed disadvantage on this paper; original expiry remains unexplained, no platform parity claim. |
| P05 / 10.1016/j.neunet.2026.109387 | ScienceDirect, institutional | A→Z | 12.929–13.318 s | First save operator-interrupted; fresh retry required verification, no PDF | Unseen repaired-platform article, 12 pages / 7,803,602 bytes. |
| P06 / 10.1016/j.patcog.2026.114946 | ScienceDirect, institutional | Z→A | 9.532–9.916 s | Verification incomplete; no PDF | Second unseen article, 12 pages / 2,265,082 bytes. |

P02's interval difference is −4.477 to −3.699 s, ratio 0.9705–0.9756. This single
pilot cannot establish platform parity. Both files' titles/DOIs/page counts and
published OA version were checked. P01's Allfold PDF was 10 pages / 2,100,180
bytes; P04's Zotero PDF was 15 pages / 3,459,180 bytes, publisher Early Access.
No transfer-efficiency comparison is made where the other product has no file.

P02's Connector reported a 15-second resolver communication timeout, but Desktop
later saved the actual PDF without intervention. The earlier error was not the
final outcome. P03 required the user's Chrome Cloudflare checkbox during article
preparation; that assistance is retained separately from PDF saving. Allfold's
Cancel→cleanup→Retry was exercised on P03. P01/P02 Open and Locate pointed to the
same managed file. P02's disposable trial PDF was then removed through the
product's Reject/delete/Restore flow; metadata and Download availability survived.

## Formal checkpoint and remaining measurements

The immutable [31-paper manifest](pdf-pairing-manifest.json) was committed before
the first formal click. The [formal results](pdf-pairing-formal-results.json)
retain all original samples, failures, preparation, versions and repetitions.
At this checkpoint Allfold has 59 automatic local-PDF successes, one assisted
success and five failures. Zotero has 53 automatic and one assisted local-PDF
successes, one visible attachment failure and ten operator interruptions with
unknown product terminal state. These are
attempt counts, not independent-paper success rates. Saving a related preprint
is a task result but is not a publisher-version success.

| Actual platform | Papers started / planned | Local PDF observations, including repeats | Conclusion |
| --- | --- | --- | --- |
| IEEE Xplore | 2 / 2 | Allfold5 publisher files,1 original failure; Zotero6 publisher files | Current F01 three controls plus F02 paired retest all correct/same-version and Allfold not slower. Old failure retained; no extrapolation beyond these2Papers. |
| Springer Link | 3 / 3 | Allfold 12 successes; Zotero 11 successes,1 interruption | Three corrected low-load controls: two slower points and one overlap. Cause unresolved; not confirmed. |
| Cambridge Core | 2 / 2 | Allfold9 successes; Zotero9 successes; one body on each side is a preprint | F06 three controls plus F07-3 have comparable publisher PDFs; all favor Allfold. No observed disadvantage in these two Papers; earlier access/version differences retained, no broader extrapolation. |
| Oxford Academic | 3 / 3 | Allfold 2 related preprints,1 access-challenge failure; Zotero 3 interrupted saves without parent/PDF | New native CF Prepare recovery observed; publisher PDF retests outstanding. Not confirmed. |
| Taylor & Francis | 3 / 3 | Allfold 4 successes: original preprint plus3 publisher Accepted Manuscripts; Zotero 2 publisher Accepted Manuscripts,2 interrupted parent-only saves | Same-version F11 retry faster; first F13 slower. Controls/repeats and F12 retry outstanding. Not confirmed. |
| Project Euclid | 2 / 3 | F20 matching related arXiv v4, with in-download Allfold hCaptcha assistance. F22 matching 30-page publisher OA saved automatically by both products. F21 subscription excluded. | F22 favors Allfold. Only one publisher OA pair measured; institutional access is outside the revised scope. |
| Wiley | 3 / 3 | Allfold6 publisher OA successes; Zotero4 successes(1preprint,3publisher),2interruptions | F14 normal publisher controls and F15 favorAllfold. F16 default saves remain parent-only; one bounded diagnostic records citation/PDF403,with terminal unknown. Not confirmed. |
| SIAM | 3 / 3 | Allfold5 related preprints and9 publisher PDFs; Zotero13 publisher PDFs,1 interruption | F17/F18 each have3 publisher pairs:first slower,two warm faster. Normal reauthentication restored F19 publisher access; its new comparable pair is close/favors Allfold,then a warm repeat favors Zotero. Cache reuse is demonstrated; large-PDF warm user-wait parity is not met. |
| INFORMS PubsOnline | 0 / 3 | Not started; configured EBSCO capability is not a platform result | Not confirmed. |
| ScienceDirect | 6 / 6 | F26 publication recovered on Allfold after repair and saved with Zotero assistance. F27 retest and unseen F29/F30/F31 published files saved automatically in both products. F26-1/2 and F27-1 failures and the F28 matching preprints are retained. | Original F26/F27 publisher retrieval recovered. F27's challenge-recovery retest and all three new first pairs were slower on Allfold. Other affected paths and normal controls still require retest. |

After the user rebooted and signed into CARSI in Chrome, the checkout was
launched at `40d4356` with rebuilt UI and the same production code as `69b9a41`.
The prior instance was absent and its port free. In the new runtime, 72 Papers
and 24 managed bodies were present with no active collection or download.
F26 had no body. Zotero 10.0.9 and the dedicated collection were reachable on
the local API. The restarted keys-v2 observer treated all existing items and
files as baseline. Chrome 157.0.8103.79 and Connector 5.0.217 were installed.

Chrome entered ScienceDirect from its normal CARSI resource and passed initial
verification automatically. In Source, the batched Login's ScienceDirect task
reported Opened after a 19.339 s native operation. Its retained target was then
evicted from the managed page budget and the final group reported `target_closed`.
Normal selection of the same CARSI resource in Source re-established the visible
publisher entry. Both fresh F26 article pages displayed institution access, the
exact DOI and the View PDF entry before the first formal click. No PDFs were
opened during that preparation. Preparation times and incomplete observation
bounds are in the result table.

F26-1 used the frozen Z→A order. Zotero's new parent was in the dedicated
collection. Inspection observed a red X on `ScienceDirect Full Text PDF` and a
completed Save popup, with zero attached files. The inspection gives an upper
bound on the observed error. Allfold attempt 1 reached its failed state in
18.439–18.784 s with reason `access-challenge` and no file. Its R024 path read
the article, tried three sources, and reached the assets CDN twice. One Reader
showed a 403 verification page and subsequently reached status 200. The final
CDN responses were still access challenges. The native operation sequence and
both measured outcomes were retained. The later non-scoring normal Source View
PDF opened the matching 12-page publication. The same normal Chrome action
reached a human verification checkbox. After the user completed it, Chrome
returned to the F26 article with institution and Full text access visible. The
PDF itself had yet to appear in that window. The next normal View PDF action on
the returned article reached a second human checkbox. After the user passed it,
the browser subsequently displayed the actual 12-page publisher PDF. The observed
title and DOI matched the Source viewer. Both products therefore had current
viewer access before the control retest, and both had viewed the same body.
Chrome's two manual verification observations remain part of its preparation.

The F26 verification tab was preserved while F28, a frozen open-access sample,
advanced ahead of F27. F28-1 used its declared Z→A order. Both products stored
the related arXiv 2507.18488v2, 44 pages and 5,331,394 bytes. Full title, all three
authors and the saved Paper's explicit preprint relation were confirmed. Allfold
wait was 18.358–18.700 s. Zotero wait was 134.879–135.188 s. The paired difference
was −116.830 to −116.179 s and the ratio 0.1358–0.1386. This point compares time to
the same fallback body. It does not measure publisher attainment or equivalent
network transfer. Allfold used OpenAlex P5 after four publisher entries reached
the same assets CDN origin and returned access challenges. Zotero's imported
attachment origin was arXiv. Its finer resolver phases were not observed.

F27-1 began A→Z with the target article identity, independent institutional
access and ScienceDirect Translator verified. Allfold reached its failed state in
10.537–10.885 s. Three R024 Reader paths reached the assets CDN and received
access challenges. Zotero created the correct parent in the trial collection.
The save popup subsequently disappeared. After 600 s, the common observation
horizon based on the normal Allfold deadline, the observer still had no local
attachment or product terminal state. The operator closed only the trial
article tab after 633.413–633.468 s. The parent still had zero attachments at
that check. The result is an operator interruption with product terminal
state unknown. Neither product opened a full PDF before this pair.

F26-2 used A→Z after both normal viewers had displayed the same 12-page
publication. Chrome's earlier two user verification steps were preparation.
Neither action needed human input during timing. Allfold attempt 2 ended in
19.044–19.416 s without a file. Its article challenge reached the Solver, which
logged an actual checkbox click. The Page next reached HTTP 200 and the pending
Solver stopped. The three subsequent R024 Reader continuations returned
`access-challenge` at the publisher's assets CDN after 625, 525 and 632 ms.
Those Session requests had no corresponding Page verification or Solver event.
The earlier export exposes the classification without the raw HTTP header.
Zotero's new local imported attachment had the exact DOI and title, 12 pages
and 4,834,588 bytes. Both the parent and file were verified in the acceptance
collection. There is no time difference or ratio for this asymmetric outcome.

The per-attempt [challenge audit](pdf-pairing-formal-results.json) covers all
65 recorded slots and identifies the four samples without download starts. The
retained traces show 16 attempts with Cloudflare evidence, 46 without observed Cloudflare
evidence and three with insufficient time bounds or matching traces. Earlier
Oxford, Wiley and SIAM source classifications are retained even when a related
PDF subsequently saved. F20's Imperva/hCaptcha handoff remains separate. An
absent event cannot establish absence of a real challenge. The pilot table
retains the same diagnostic fields for its trials.

Allfold's Cloudflare criterion is automatic passage wherever a challenge remains
active. Check detection, Solver dispatch or the Page's own automatic recovery,
and clearing of the actual blocking state. Record a missed dispatch, Solver
failure or human passage as an unmet observation even if a separate source later
saves. Preserve the attempt and investigate the affected path. Initial access
preparation is part of this audit as well as the timed Download. Zotero's real
manual verification and non-Cloudflare authentication remain separate evidence.

The scoped repair sends a challenged ordinary GET to the existing Browser
observer when it has no fixed Reader route. It keeps the original Service
binding and the actual recovered GET, including a renewed URL or Referer.
The isolated Electron fixture uses HTTPS, actual Chromium partitioned cookies
and a synthetic Solver response. It exercises consecutive verification pages,
including a second challenge observed in the Document, a warm response before
Document commit, a renewed signature, HTML-MIME PDF attachments and inline
bodies, and local Paper association. It preserves an ordinary Cookie rotated
before the stream. It also checks ordinary 403/HTML,
unrelated origin refusal, and cancellation while the Solver waits. The temporary
Page drains before the stream, and the Cookie context stays in the same native
task and Session. Cloudflare documents why the partition matters. [Cloudflare
Cookie documentation](https://developers.cloudflare.com/fundamentals/reference/policies-compliances/cloudflare-cookies/)

The rebuilt Source at `989ad81` repeated F26 in the authorized Workspace while
Chrome's fresh trial awaited manual verification. The non-scoring action F26-D2
automatically saved and associated the correct 12-page publisher PDF in
20.877–21.226 s, 4,834,642 bytes. The original Source Paper, exact title, DOI,
version and local file were verified. One R024 Reader hit HTTP 403. Its Solver
clicked at 01:06:33.106 UTC, the same Page reached 200, and the Solver drained.
The next R024 continuation again hit the assets CDN challenge. It now entered an
owned verification Page. That Page reached a usable response without a second
Solver interaction and drained before the Session request. The native operation
took 2.455 s, including the Page and 0.906 s from first byte to writer closure.
The observer then confirmed permanent file and association on attempt 3.
No human input was used during this action. The file matches the version and
page count of the earlier Zotero F26-2 PDF, with a 54-byte difference. Independent
Session preparation and this separate diagnostic affect later warmth.

F26-3 followed Z→A. Zotero opened a separate Cloudflare verification window
after the normal Save. The user completed it, and the dedicated collection
received the correct 12-page publisher PDF and parent in 62.674–62.969 s.
The human input interval is unknown, so the total remains intact in the
assisted stratum. Allfold's diagnostic PDF was removed through the product
after action-time confirmation, then the original Paper was restored. Attempt 4
saved the same publisher version through R024/P2 in 16.870–17.225 s with no
human intervention. Its challenged assets request reached a normal response in
the owned Page and then closed the managed stream. No blocking widget or
Solver interaction was recorded on that Page. The total-wait difference is
−46.099 to −45.449 s and the ratio is 0.2679–0.2748 for this assisted-only
comparison. It does not contribute to ordinary automatic timing. Both prior
failures remain in the table. The repair recovered the original real F26
publisher retrieval. The normal unassisted control remains open.

F29/F30/F31 were untouched and saved the corresponding publisher PDFs on
`989ad81`. Titles, DOIs, page counts, local files and the original associations
matched. Both products received the PDFs from the ScienceDirect assets CDN.
The reported byte differences are retained. F29 and F31 were OA; F30 showed
current institutional Full text separately in both products. F29's earlier
Chrome verification preceded its Save. F31's Allfold article preparation took
13.558 s from native navigation start to recovered access. It detected a real
Cloudflare page, started Solver at 01:31:55.069 UTC, clicked at 01:32:00.501 UTC,
and recovered access on the same Page at 01:32:03.362 UTC. The valid article and
PDF entry were visible. This preparation time is separate from Download wait.

| Pair / order | Access / version | Allfold wait | Zotero wait | A−Z | A/Z |
| --- | --- | --- | --- | --- | --- |
| F29-1 / A→Z | OA, 19 pages, 3,342,410 / 3,326,247 bytes | 18.705–19.061 s | 13.822–14.272 s | +4.433 to +5.239 s | 1.3106–1.3790 |
| F30-1 / Z→A | Institutional, 22 pages, 4,078,428 / 4,079,168 bytes | 17.337–17.710 s | 16.427–17.000 s | +0.337 to +1.283 s | 1.0198–1.0781 |
| F31-1 / A→Z | OA, 20 pages, 2,471,556 / 2,455,263 bytes | 18.523–18.877 s | 14.552–15.010 s | +3.513 to +4.325 s | 1.2340–1.2972 |

The ScienceDirect OA prepared-access stratum has two Papers and two points.
The interval median paired difference is +3.973 to +4.782 s, and the median
ratio is 1.2723–1.3381. The raw wait ranges are 18.523–19.061 s for Allfold
and 13.822–15.010 s for Zotero. The institutional first-paper stratum has one
point (F30), with its median equal to the row above and no dispersion estimate.

Allfold's CDN responses in these three pairs reported `access-challenge`. Each
owned Page reached HTTP 200 automatically and closed before the completion of
its managed Session stream. There was no observed active CF widget or Solver
interaction on those CDN Pages. Native elapsed time for article extraction was
3.254, 6.730 and 4.779 s, respectively. Reader work took 2.535, 2.878 and 3.964 s.
The challenged response took 3.506, 1.120 and 4.703 s. The recovery Pages reached
HTTP 200 in 0.665, 1.072 and 0.752 s. Actual stream markers and source origins
are retained in the result table.

The installed ScienceDirect Translator (`b6d0a7a-d076-48ae-b2f0-b6de28b194e`,
revision 2026-06-05 15:27:44) can use the already loaded article, including
its PDF link or page metadata, and follows an intermediate page when needed.
Allfold extracted the article during these timed Download attempts. The actual
Connector branch, whether it used an intermediate page, and its transfer phase
are unavailable for these pairs. The observed request costs identify where
Allfold spent time. Further swapped pairs are needed to attribute the paired
difference under similar access and cache conditions.

The final-code F27-2 challenge-recovery retest ran in the exchanged order after
both products independently showed institutional Full text on the target.
Each obtained the same 12-page publisher version. Allfold took 41.746–42.119 s
for 3,156,500 bytes. Zotero took 17.719–18.050 s for 3,140,877 bytes. The paired
difference is +23.696 to +24.400 s and the ratio is 2.3128–2.3771. A separate
brief blank ScienceDirect window was observed during Zotero Save with no
observed manual verification. Allfold's first Reader took 15.773 s. The Solver
clicked and that Page recovered at HTTP 200, then reported no usable PDF entry.
The second Reader took 3.761 s and led to the assets CDN challenge. The exact
owned verification Page recovered automatically, and its native stream closed
after an 11.122 s operation. The first Reader and repeated source work account
for a substantial part of the actual Allfold wait. The two source URLs' exact
request forms and the corresponding Connector stages are unavailable in the
retained traces. This single active Reader challenge point is separate from
the three prepared first-paper points above.

Project Euclid was restricted to public publisher Open Access. F21's normal
article redirected to the short page after the user completed separate
Imperva/hCaptcha preparation. Its full text required subscription or purchase,
so the frozen sample was excluded from downloads. F22 showed Open Access
in both products, and the Euclid Translator saved the verified 30-page publication
to the trial collection in 3.425–3.721 s. Allfold R009/P1 saved and linked the
same title and DOI in 1.460–1.816 s. Both files are 1,199,204 bytes, with
paired difference −2.261 to −1.609 s and ratio 0.3924–0.5302. Native elapsed
stream time was 1.527 s, including 0.354 s from operation start to first byte.
There was no observed assisted step during the two timed actions. Neither
F20's fallback nor the single F22 publisher point establishes broader parity.

At `989ad81`, PR run 44211591848 failed in the existing Workspace lifecycle
fixture. The local field read lacked a `revision` before its response status
was checked. Twelve isolated local repetitions passed, and the runner did not
retain the failed HTTP response. The fixture now explicitly waits for the
captured Paper collection to settle before its separate local read/edit phase
and asserts the HTTP status. Production code and test coverage are unchanged.
[Failed PR run](https://github.com/dylaaan-booob/allfold/actions/runs/44211591848)

**Measurement load:** the original external observer requested full JSON for the
newest20 Zotero items at nominal250ms. An idle A/B check measured Zotero CPU at
20.9–26.6% with it and0% paused. At19:40:21 UTC on16 November it changed to a
keys query and metadata reads only for new/pending items; observations were
1.3% and1.5%. Earlier file/association results remain valid, but their timings
(including pilots) cannot establish normal-load parity. No numerical correction
is subtracted. Restart baselines and missing click timestamps are not completion
times. The observer was absent during F10: its verified failure has no measured
terminal time. A detached observer restarted00:45:25.984 UTC before F11.

Nine older successful pairs have comparable publisher versions: seven have
observer-affected times and two Cambridge repeats lack Zotero click timestamps.
After sleep, corrected low-load controls used unchanged production098288a. The
first current T&F pairs used nativee67e136 and frontenda9663f7; native/Python sources
are identical between those two commits. Actual rebuilt source process and
trusted UI reload were checked. The existing Chrome profile and Electron Session
were separate; no cache clearing was used. Both files of every following pair
were individually checked for title, DOI, version, actual file and association.

| Pair / order | Platform / access / version | Allfold wait | Zotero wait | A−Z | A/Z |
| --- | --- | --- | --- | --- | --- |
| F06-4 / Z→A | Cambridge, institutional FirstView,33pages; warm control | 1.565–1.904s | 2.148–2.443s | −0.878 to−0.244s | 0.6406–0.8864 |
| F03-4 / Z→A | Springer OA publisher PDF,22pages,2636871bytes; first after Electron restart | 2.598–2.952s | 1.717–2.109s | +0.489 to+1.235s | 1.2319–1.7193 |
| F03-5 / A→Z | Same Springer PDF, new body/save, warm sessions | 3.873–4.256s | 2.647–2.960s | +0.913 to+1.609s | 1.3084–1.6079 |
| F03-6 / Z→A | Same Springer PDF, new body/save, warm sessions | 0.597–0.970s | 0.734–1.025s | −0.428 to+0.236s | 0.5824–1.3215 |
| F13-1 / A→Z | T&F OA publisher Accepted Manuscript,34pages,1730654bytes | 5.609–5.996s | 4.760–5.112s | +0.497 to+1.236s | 1.0972–1.2597 |
| F11-2 / Z→A | T&F institutional publisher Accepted Manuscript,27pages,1251965bytes | 3.630–3.985s | 4.805–5.100s | −1.470 to−0.820s | 0.7118–0.8293 |
| F06-5 / A→Z | Cambridge publisher FirstView,33pages; actual new body/save | 1.968–2.320s | 4.273–4.667s | −2.699 to−1.953s | 0.4217–0.5429 |
| F06-6 / Z→A | Same Cambridge version,33pages; actual new body/save | 2.317–2.678s | 3.513–3.887s | −1.570 to−0.835s | 0.5961–0.7623 |
| F07-3 / Z→A | Cambridge target institutional rights separately confirmed,FirstView42pages,571863bytes | 1.831–2.199s | 3.746–4.081s | −2.250 to−1.547s | 0.4487–0.5870 |
| F01-2 / Z→A | IEEE institutional Early Access,16pages; actual rights freshly established | 9.826–10.195s | 12.751–13.176s | -3.350 to-2.556s | 0.7457–0.7995 |
| F01-3 / A→Z | Same IEEE control,new body/save | 10.186–10.558s | 13.652–13.950s | -3.764 to-3.094s | 0.7302–0.7734 |
| F01-4 / Z→A | Same IEEE control,new body/save | 11.271–11.659s | 11.684–12.016s | -0.745 to-0.025s | 0.9380–0.9979 |
| F02-2 / A→Z | IEEE institutional Early Access,14pages | 15.527–15.915s | 18.393–18.984s | -3.457 to-2.478s | 0.8179–0.8653 |
| F15-1 / A→Z | Wiley publisher OA,13pages | 1.081–1.504s | 2.167–2.539s | -1.458 to-0.663s | 0.4258–0.6940 |
| F14-2 / A→Z | Wiley publisherVoR21pages; AllfoldWiley3295222bytes,ZoteroPMC3629614bytes | 1.941–2.323s | 6.382–6.741s | -4.800 to-4.059s | 0.2879–0.3640 |
| F14-3 / Z→A | Same publisherVoR/source split,new body/new parent; warm visits | 0–0.355s | 5.379–5.800s | -5.800 to-5.024s | 0–0.0660 |
| F18-4 / A→Z | SIAM institutional publisher PDF,28pages,3814861bytes; first partition-context repair retest | 15.689–16.033s | 11.389–11.857s | +3.832 to+4.644s | 1.3232–1.4078 |
| F17-2 / Z→A | SIAM institutional publisher PDF,26pages,A487337/Z487368bytes; predeclared control | 7.415–7.760s | 3.481–3.789s | +3.626 to+4.279s | 1.9570–2.2292 |
| F19-1 / A→Z | SIAM institutional publisher PDF,59pages,A11471779/Z11471788bytes; untouched repair check | 39.579–39.943s | 26.158–26.649s | +12.930 to+13.785s | 1.4852–1.5270 |
| F18-5 / Z→A | Same SIAM28-page publisher PDF,new body/new parent,warm visits; cache flags missing | 0–0.218s | 3.552–3.875s | −3.875 to−3.334s | 0–0.0614 |
| F17-3 / A→Z | Same SIAM26-page publisher PDF,new body/new parent,warm visits | 0–0.305s | 3.752–4.033s | −4.033 to−3.447s | 0–0.0813 |
| F18-6 / A→Z | Same SIAM28-page publisher PDF,new body/new parent,warm visits | 0–0.310s | 2.861–3.187s | −3.187 to−2.551s | 0–0.1084 |
| F17-4 / Z→A | Same SIAM26-page publisher PDF,new body/new parent,warm visits | 0–0.172s | 6.887–7.170s | −7.170 to−6.715s | 0–0.0250 |
| F19-3 / A→Z | SIAM59-page publisher PDF,access restored in both products; symmetric ePDF diagnostic prewarming | 24.743–25.102s | 25.164–25.734s | −0.991 to−0.062s | 0.9615–0.9975 |
| F19-4 / Z→A | Same SIAM59-page publisher version,new body/new parent,warm visits | 21.245–21.626s | 3.865–4.507s | +16.738 to+17.761s | 4.7138–5.5953 |

For Springer OA, n=3 paired repeats of **one** Paper: interval median waits are
2.598–2.952s(Allfold) and1.717–2.109s(Zotero), median paired difference
+0.489 to+1.235s, median ratio1.2319–1.6079. Raw wait ranges are0.597–4.256s
and0.734–2.960s respectively. Two slower points exceed measurement precision;
the third overlaps. This is insufficient to claim parity or isolate a cause.
Cambridge has n=3 corrected repeats of one Paper: median waits1.968–2.320s
and3.513–3.887s, median paired difference−1.570 to−0.835s and ratio0.5961–0.7623;
raw wait ranges1.565–2.678s and2.148–4.667s. No slower point was observed in
that control. The two T&F access strata each have n=1; each raw point is its
only median and no dispersion estimate is claimed. No pooled daily-load average, p95, tolerance
percentage or non-significance argument is used.

Existing F03-4 native observations show two response operations(732+620ms) then
stream/writer1284ms; F03-5 has one stream operation4026ms, F03-6 is fast. The
installed Springer Translator uses the same direct `/content/pdf/` DOI entry as
Allfold R001, and also requests citation RIS. No redundant Allfold URL is yet
proven. F12/F13 Allfold each used one P1 stream,5763/5597ms, without fallback.
First byte, response wait, cache response and closed-writer subphases are missing
in these old records; they cannot be invented from the total. Targeted phase
diagnosis and exchanged-order repeats remain required.

To distinguish the observed stream costs, the existing native terminal diagnostic
now has four optional relative monotonic marks for fetch call, response return,
first nonempty prefix bytes and closed writer. No new state/result protocol or
request content is logged. Native regressions verify actual streaming/backpressure,
close-before-terminal and continued saving when the observation callback throws;
strict Node-to-Python export retains only bounded numbers. Logger/native tests
were red before implementation and green afterward. Full local checks passed:
JavaScript63files, Python1622tests(2existing deprecation warnings), Electron244tests
with no skips. The native process was normally restarted at77dfd67, runtime97a7ee2badf06ed80594e7f0b80bb712,
on17November02:56:44.904UTC; the UI was rebuilt and old process/port absence
verified. Later7fd16eb is documentation-only, with identical production code.
Actual phase observations now exist, but do not retroactively fill old gaps.

The predeclared **mechanism** pair F03-7 used the first Springer request of that
new Electron Session versus existing Chrome context: Allfold3.887–4.240s,
Zotero2.007–2.304s, difference+1.583 to+2.233s, ratio1.6871–2.1126. Actual source
observations showed link.springer.com→idp.springer.com→link.springer.com. Two
response operations took1313+1161ms, then a1492ms PDF stream with relative marks
(request5,response654,first bytes654,closed1492ms). The following swapped same-
Electron-session diagnostic F03-8 took Allfold0.620–0.990s versus Zotero1.839–2.175s,
difference−1.555 to−0.849s, ratio0.2851–0.5383: one583ms stream, marks12/573/573/582ms,
with no preceding IdP responses. Every file was independently checked. This bounds
the real first-Session redirect cost and shows no slow local writer in that warm
copy; actual cache flags and the earlier one-stream4s outlier's phase remain
unknown. These two declared diagnostic pairs are separate from representative
scores and do not replace original F03-4/5/6 slower observations.

IEEE's current F01 control has3paired observations of one Paper: median paired
difference−3.350 to−2.556s and ratio0.7457–0.7995; raw Allfold waits9.826–11.659s,
Zotero11.684–13.950s. F02 contributes one independent current paired point.
Before these retests, a cached institutional homepage contradicted actual target
no-access text. Separate fresh normal CARSI resource entries/automatic SSO restored
actual article rights in both products; no PDF was preopened. The original failure
and loaded-observer Z1 records remain, and access restoration is not a code-only
benefit. Prepared-source F01 used one P2 stream per successful attempt.

Wiley F14's normal primary Translator reported an error and automatically fell
back to Embedded Metadata. Zotero ultimately saved verified arXiv2504.12052v3,
32pages/4362024bytes,13.049–13.372s; exact title/all5authors/version match the
Paper's explicit preprint relation. Allfold saved Wiley publisher OA21pages/
3295211bytes,15.075–15.453s,via P5OPENALEX from onlinelibrary.wiley.com after
challenged P1R002/P2API02 paths. Different versions prohibit a same-body transfer
score. F15 then saved publisher OA13pages on both products: Allfold P1 direct
1.081–1.504s versus Zotero2.167–2.539s; no Translator error was observed in its
normal UI. The installed Wiley Translator(fe728bc9-595a-4f03-98fc-766f1d8d0936,
updated2025-06-11) POSTs downloadCitation for BibTeX and rejects a non-BibTeX reply.
That source established a possible failure seam,not the actual F14 response;
the bounded diagnostic below checks the current path. No installed
Translator/Connector code was changed. Chrome human CF during Wiley preparation
is separate; exact original preparation bounds are missing.

One separately declared **non-scoring** F14 diagnostic used temporary Connector
Debug after a new article's human CF: citationPOST200,PDFGET200,Desktop
saveAttachment201/succeeded,then progressdone. Its observed Translator ID/revision
matched the installed file above. The21-page publisher PDF(3295222bytes) and parent
were checked; the original failure did not reproduce. Two preexisting cumulative
citationPOST403 entries and one resolver communication error had no per-entry
time/DOI and cannot be retrospectively assigned. Raw Debug contained sensitive
Cookie data and was not copied/submitted; only the allowlisted sequence was kept.
Debug was restoredOff before normal controls; startup logging was unchanged.

F14-2/3 each used a fresh normal save and actual body deletion/Restore. Allfold
saved the Wiley21-page publisher PDF; Zotero saved the same version of record from
PMC,21pages/3629614bytes. First-page Research Article/Open Access layout,title,DOI,
original CreationDate and actual association were checked. Source/packaging/size
differences remain explicit; these are user-wait comparisons,not pure transfer
throughput. F14-3 completed within the click/poll resolution: its preceding poll
overlapped the click interval,so the lower wait bound is0,not a negative time.
Actual HTTP-cache flags are missing; both Sessions were warm. No code change is
credited for these later faster observations. Current Wiley OA n=3pairs/2Papers
has median waits1.081–1.504s versus5.379–5.800s,median difference−4.800 to−4.059s
and ratio0.2879–0.3640; raw ranges0–2.323s and2.167–6.741s.

Original F14 native operations were two response tasks401+88ms,article PDF-clue
navigation12997ms,and successful stream1527ms(request2,response492,firstbytes493,
closed1526ms). Seven source observations are not seven physical HTTP requests.
The long observed stage was article navigation; finer cause/cache facts are
missing. F15 and F16 successful streams took1073/2092ms respectively.

After user article verification,F16's first Zotero save produced only parent
6X39B8TV and was operator-interrupted05:01:43UTC after more than10min. There was no
imported attachment,temporary storage or visible helper/progress window; product
terminal state remains unknown. A network snapshot included local API observation
traffic and didnot independently prove termination. Allfold then saved correct
publisher OA15pages/2195136bytes in2.084–2.483s. A new Allfold download saved the
same publisher version in0.095–0.503s; its paired fresh Zotero parent76BG244L still
had no attachment and was operator-interrupted05:34:10UTC after more than15min.
Independent SourceSIAM preparation/user login and UI recovery overlapped that
unresolved observation; it is not a normal latency comparison.

One bounded non-scoring F16 Debug Save then showed citationPOST403→automatic
Embedded Metadata fallback→GET `/doi/pdf/10.1002/sim.70808`403,saveItems201 and
hasAttachmentResolvers200. The viewed output didnot establish a final resolver
request/response/timeout,so terminal state remains unknown. The installed Wiley
successful path rewrites `/pdf/` to `/pdfdirect/`; generic Embedded Metadata uses
`citation_pdf_url` unchanged. This identifies a fallback entry difference without
proving why the server rejected403. No installed code was changed. Debug was
restoredOff05:40:47UTC and only that diagnostic tab closed05:41:17UTC. Its parent
M5I37TSV initially went to MyLibrary and was normally added to the trial collection
05:43:01UTC; that membership time is not an attachment endpoint. Sensitive raw
Debug was not copied/submitted. Both original unknown saves remain unchanged.

F17 saved verified related arxiv2409.18415v3,83pages/1226997bytes,in17.252–17.674s;
all3authors/title and the Paper's explicit relation were checked. Its default
Zotero parent7EBJXK9D had matching title/URL but noDOI,authors orPDF and was
operator-interrupted05:57:03UTC. One separately declared Allfold diagnostic
download again saved that preprint. The visible article PDF anchor was in its
article/header and pointed to ePDF; normal DOI-entry navigation resolved the same
article. These observations didnot justify changing DOM filters.

After the user's tab closure,Source/Python/Zotero/observer were found exited;
ChromePID4242 had survived,so this was not a clean profile/cache. The source UI was
rebuilt and actual head21a7e25 relaunched08:40:22.388UTC,runtime02408604e5d6b611dc0d2d433f4e7bb0,
with unchanged77dfd67 production bytes. All72Papers/22existingbodies and no active
download/cleanup were verified. Zotero10.0.9/Connector5.0.217 and the trial collection
were restored. The keys-v2 observer restarted08:42:23.825UTC; all existing files/items
were baselines,never new completions. Both products independently re-entered the
SIAM resource and confirmed actual F18FullAccess before timing.

F18 Zotero saved SIAM/ASA J.UncertaintyQuantification VoR28pages/3814861bytes from
`/doi/pdf/10.1137/25M1735329` in13.238–13.693s. Allfold instead saved related
arxiv2502.20086v2,30pages/4232776bytes,in39.916–40.219s; title/all4authors/explicit
relation were checked. Native operations measured article extraction13542ms,
an entrance response1877ms,and the final preprint stream21512ms. These are not a
complete phase decomposition. Three access-challenge source records do not mean
three physical requests. Different versions prevent a transfer-efficiency score,
but the original task-level delay and publisher-version disadvantage remain.

The initial reading of `no-pdf-entry` as a missing article anchor was incorrect:
`response-observed/no-pdf-entry` follows an attempted candidate's HTML response.
The native article did supply an ePDF entrance. The resulting repair therefore
uses shared candidate selection rather than a speculative DOM exception.

The user required the repair across all supported platforms. Already qualified
direct P2/P3/P4 entries now precede Reader/form work and optional discovery APIs;
current Document entries and newly qualified templates use that same preference.
Equal kinds retain source order and failed direct requests retain later sources.
No page is fetched merely to rank candidates. The existing Atypon parser Host set
also supplies a shared R039 journal DOI entry when no dedicated P1 template exists;
there is no SIAM-only P1 branch. Dedicated URLs/query parameters,original target,
Service authority,Session streaming and actual file/association completion remain.
P5 remains last. A potential ScienceDirect PDF response is not automatically
declared a Reader based on its URL.

The shared regression was red before implementation. The completed current
Python check passes1661tests/2existingwarnings and JS check covers63files. The complete Electron follow-up passes245tests/0skips; focused public native
Download checks and earlier failing outputs are retained. These are offline
regressions,not real-site proof for every Host. Original F18/F17 retests and
untouched F19 at the new code revision remain required.

Affected review and integration tests covered ordinary IEEE Meta without a
Reader marker, API-result ranking, HTML-triggered optional Reader work, explicit
native/action order, and terminal/cancel cleanup. Existing qualified Readers can
finish before optional identifier APIs. Paused chains keep their response,
context and source index; seen/ineligible clues and conditional skips cannot
invent fallback. The actual public native fixture keeps its request,local-save,
association and resource-cleanup assertions.

Independent native review at51c3dea identified two remaining same-endpoint cases:
P2/P3 stage must not distinguish query variants,and a paused source's variants
must wait for the independent direct source and original Reader. Both have red
regressions and corrections: endpoint scope excludes stage; the queue leaves
variants with their pending source. A Reader failure still permits those variants,
without URL rewriting or new retries. Bounded independent native follow-up at79db7d6 confirmed both fixes with no actionable introduced bug.
The Oxford eprint safety case remains independently covered; possible binary
ScienceDirect/Optica/stampPDF responses are not predeclared Readers. Valid
response chains and existing ScienceDirect article-backlink recovery stay intact.

An intermediate full Python run exposed a collection-planner Run-final-snapshot
SQLite sidecar race in unchanged code; focused and later full checks passed.
The initial failed output remains private. The same late Run race recurred during
the article-context check and is addressed below without weakening persistence
protection. Intermediate c1c0ed5 and51c3dea runtimes had no formal
Download. The latter's fresh CARSI resource returned404,then normal Login reached
an unfilled institutional form. No credentials were submitted before normal Quit;
manual login will be requested on the final tested runtime.

At actual79db7d6(runtime28dc6b2633a27679ad89d3fa026c04d4,ready10:46:37UTC),
F18-2 A→Z still saved a related preprint: Allfold18.188–18.536s/arxiv30pages,
Zotero9.194–9.508s/publisher28pages. R039 P1 did run:1101ms/access-challenge;
then article7297ms,R061 entrance163ms/access-challenge,preprintstream9526ms.
These observations do not establish a code speedup. A new Chrome tab had lost
actual rights despite an older cached FullAccess page; a normal CARSI SIAM
reentry restored rights before its new Save. Preparation/cache changes remain.

A separate non-scoring Source Browser diagnostic followed the visible ViewPDF
then DownloadPDF links11:11/11:12UTC. Normal SaveAs produced the actual publisher
28page PDF(3814854bytes,DOI checked),without a visible challenge or Solver. This
file is private,outside Workspace,unassociated with the Paper,and supplies no
formal Download timing. Same Electron Session had lawful PDF access; the
background Session request context remains defective,not simply a missing licence.

Installed Connector5.0.217 `_setAttachmentReferer`/`_fetchAttachment` supply an
article referrer(full same-origin,origin cross-origin). Current ordinary Allfold
candidates could supply none; native streaming only forwards an explicit Referer.
Commit3a551ea supplies missing qualified article context at normal discovery roots
across platforms. Explicit Referer,trusted initial/native actions and Reader
continuations are preserved,including a Reader that intentionally returns none.
Existing strict-origin/downgrade policy is unchanged. Its effect on the real CF
failure is not assumed. The installed Connector also contains partition-cookie
handling,but current-site partition evidence was not obtained; the external CDP
probe was not executed under the CUA boundary and no Cookie values were read or
copied. No cookie-policy patch was justified at that checkpoint; the later native probe and community evidence below support the targeted adaptation. Canonical DOI spelling is already
preserved from the saved Crossref landing; that path was not changed speculatively.
F19 remains unvisited. Exact3a551ea local checks passed JS63,Python1669/2existing
warnings,Electron245/0skips. A bounded independent native review found no actionable
introduced bug. ActualSource3a551ea started12:33:22.767UTC(runtime1105f3441769c614134a45c8933b334a),
72Papers/23bodies/0Trash; the user completed normal independent institution login.
F18-3 has now completed; controlF17 and unseenF19 remain paused for diagnosis.
Latest3a551ea PR-associated full [Safety44083751309](https://github.com/dylaaan-booob/allfold/actions/runs/44083751309)
passed JS63,Python1669/4CIwarnings,Electron245/0skips on actual test merge2f49c00;
this does not replace unresolved real retests.

F18-3 Z→A on actual3a551ea again differs: Zotero12.713–13.051s for the correct
publisher28pages/3814861bytes; Allfold23.120–23.480s for the relatedarxivv2
30pages/4232776bytes. Both new local files/parent or attempt associations and
actual title/DOI or all4authors+explicitpreprintrelation were checked. R039P1
returnedaccess-challenge after163ms; article extraction8592ms; R061ePDFresponse
389ms/access-challenge; P5stream14087ms(request8,response1171,firstbytes1197,
closed14086ms). These are observed native phases,not a complete stage timeline.
No improvement is attributed to the Referer change.

The same3a Electron Session then normally opened ViewPDF12:54:15UTC and displayed
the actual28page publisher body. Its visibleDownloadPDF3.8MB link12:55:11UTC
saved3814818bytes through normalSaveAs outsideWorkspace; DOI/pages checked.
No visiblechallenge/Solver occurred. This unassociated diagnostic is not scored.
It confirms the current Session/background request-context difference; F17/F19
remain paused while that specific gap is investigated. Installed Atypon Journals
5af42734-7cd5-4c69-97fc-bc406999bdba,lastUpdated2022-10-25 uses the ordinary
`/doi/pdf/` entry for SIAM; its specialdownload query is confined to EMBO.

The subsequent common native repair uses the existing qualified source page's
isolation context to select partitioned Cookies, then supplements only the
controlled Session request after its normal Cookie jar selection. SameSite,
origin/path, native page ownership and header ordering remain enforced; values
stay in Main and no Cookie jar is changed. The [versioned research and isolated
regressions](partitioned-cookie-research.md) document the mechanism and boundaries.
Final production `69b9a41` passed local JS64/Python1669/Electron253 checks, its
bounded independent native follow-up, and the full PR-associated
[Safety run44114394462](https://github.com/dylaaan-booob/allfold/actions/runs/44114394462).

The rebuilt actual source started17November15:38:03.615UTC at `69b9a41`, runtime
`3019b48a868edf284bca5258c5803d9b`. After separate normal institutional preparation
(including user QR login in Electron), both fresh F18 article pages showed actual
rights; no PDF was preopened. F18-4 used a new Allfold Download after normal trial
body deletion/Restore and a new Zotero save/parent in the dedicated collection.
Both local associated PDFs have28pages,3814861bytes and the correct title/DOI.
Allfold used R039/P1 with no fallback. Its native operation took15741ms: fetch
call12ms, response/first bytes2859ms, closed writer15739ms, with one eligible
partitioned Cookie selected. The file/association endpoint was observed at
15:58:10.011–10.271UTC, after the earlier native terminal event. Zotero's endpoint
was16:01:00.751–01.192UTC. The corresponding waits and paired difference are in
the table above. This confirms the repaired request can obtain the publisher
body; it does not establish parity or isolate a code-only speed benefit across
the restart/access/cache change. The remaining difference needs exchanged-order
repeats and request/transfer evidence. No Cookie name or value was recorded.

The predeclared F17 control then also saved the correct publisher body in both
products:26pages with the exact title/DOI,487337/487368bytes respectively. The
original83-page preprint and parent-only save remain separate. Allfold's formal
pair2 uses attempt3 because diagnostic attempt2 was never a scored pair. Its
native R039/P1 operation took7440ms(request11,response354,first bytes767,closed
writer7440ms),again with one eligible partitioned Cookie and no fallback. Actual
local association waits were7.415–7.760s versus3.481–3.789s. Thus a second Paper's
first point is slower,primarily inside the transfer operation; a second complete
source-discovery sequence or slow local association is not observed. Version-
matched repeats and untouched F19 remain required before assigning a cause.

Untouched F19 subsequently saved the same59-page publisher version on both sides,
11471779/11471788bytes with title/DOI and local associations verified. Allfold
used one R039/P1 operation39650ms(request9,response611,first bytes723,closed
writer39647ms),one eligible partitioned Cookie,no fallback. Its39.579–39.943s
wait exceeded Zotero's26.158–26.649s by12.930–13.785s. These three first paired
points cover different file sizes and both execution orders,but are insufficient
to separate network/cache variation from a continuing transport disadvantage.
The predeclared original/control repeats continue; two exchanged-order F19 repeats
were added because of its observed slow result. The Paper is not replaced.

F18-5 exchanged the order and used normal body deletion/Restore plus a new normal
Zotero save/parent. Both actual files again matched28pages/3814861bytes/title/DOI.
Allfold completed within0–0.218s(the preceding poll overlaps the bounded click),
Zotero3.552–3.875s. Native R039/P1 took21ms(request10,response/first bytes11,
closed writer19ms),with one eligible partitioned Cookie and no fallback. This is
consistent with warm-cache reuse; actual HTTP-cache flags are missing. It also
shows that streaming and closing this file do not invariably take seconds. It
does not erase the slower initial point or establish uncached transfer parity.

F17-3/4 and F18-6 completed with individually verified publisher files and new
attempt/parent associations. Their native operations took18/18/20ms through
R039/P1,one selected partitioned Cookie,no fallback. The corresponding intervals
are above; HTTP-cache flags remain unavailable. F17-3's small evidence-only Git
push might overlap its short Allfold interval and is disclosed in the raw result.
F18-6's new Chrome article briefly verified automatically before Save; exact
preparation bounds are missing. Neither is invented as a code-only speedup.

F19-2 Z→A produced a new discrepancy: Zotero saved the59-page publisher PDF in
6.695–7.188s; Allfold saved related arXiv2505.12836v2,69pages/7656835bytes,in
86.334–86.690s. Exact title,all5authors and the saved Paper's preprint relation
were verified. Native P1 encountered access-challenge after4991ms despite one
selected partitioned Cookie; normal article recovery took21573ms and reached
page_ready200 after a403 verification page. No subsequent publisher candidate
attempt was observed; the P5 stream took59933ms(request7,response1117,first1237,
closed59933ms). No human input occurred during this Download. Intermediate and
terminal diagnostics were separately retained; the alternative version is not
eligible for a same-body comparison.

A non-scoring normal Browser ViewPDF click17:06:01.354–01.453UTC reached F19's
ePDF but displayed “Previews are depleted”/GET ACCESS,without the institution or
FULL ACCESS label and without a publisher viewer/DownloadPDF. No diagnostic PDF
was saved. This establishes current missing PDF rights; it does not establish
the exact expiry time or retrospectively prove rights at the16:55 Download click.
The older article's FullAccess label is insufficient. Normal CARSI→SIAM resource
reentry and fresh actual entitlement confirmation are now the first diagnostic
step. F19-3 is paused; the observed fallback is preserved and has not been
classified as a confirmed same-access product defect or dismissed as a site limit.
The same access-first check applies to subsequent403/alternative-body cases.

Normal Source CARSI resource selection17:12:29.068–29.169UTC and VisitResource
17:13:19.345–19.443UTC required a fresh institutional enterprise QR login. After
the user completed it,the unchanged69b9a41 returned to SIAM with institution at
17:16:18.640UTC. A fresh F19 article showed actual title/DOI/institution/FULLACCESS
at17:16:48.950UTC; its normal ViewPDF click17:17:26.421–26.502UTC yielded the
publisher reader Page1/59 with correct title/DOI and DownloadPDF11.1MB,observed
17:17:53.279UTC. No standalone PDF was saved and the A2 preprint was retained.
Thus normal reauthentication restored actual publisher access without a code
change,supporting eligibility loss as the working cause of this recurrence.
Exact expiry and human input duration remain unknown; tool/operator time is not
reported as product latency. The ePDF diagnosis prewarmed F19; the next paired
repeat will retain that preparation and independently recheck Chrome rights.

Chrome's normal SIAM resource reentry likewise required independent institutional
QR authentication. Returned SIAM/institution was observed17:28:27.780UTC; fresh
F19 title/DOI/FULLACCESS/Atypon at17:29:01.896UTC; ordinary ViewPDF then showed the
publisher Page1/59/Download11.1MB at17:30:25.207UTC. Neither product's diagnostic
ePDF was separately saved. This symmetric prewarming and user preparation are
recorded separately from the measured Save/Download intervals.

F19-3 then saved the correct59-page publisher PDF on both products,with new
attempt/parent associations and title/DOI verified. Allfold used R039/P1 with no
fallback,24879ms(request7,response/first bytes345,closed writer24878ms),one selected
partitioned Cookie. Its24.743–25.102s wait is close to and below Zotero's
25.164–25.734s interval. This confirms access restoration at unchanged69b9a41;
it is not a code-only improvement. The final exchanged-order F19-4 also saved
correct publisher PDFs,but its warm waits were21.245–21.626s versus3.865–4.507s.
Allfold again made one R039/P1 operation,21260ms(request9,response/first1151,
closed21259ms),one selected partitioned Cookie,no fallback. The warm user-wait
disadvantage remains explicit; the following diagnosis separates cache reuse
from an equivalent real-body network transfer.

During evidence reconciliation,two optional late-file notes(F04-1/F11-1) were
found to belong to later fresh parents. They were removed and the original
parent/Allfold attempt binding made explicit. Every earlier outcome,wait and
endpoint was compared and unchanged; missing historical failure timing remains
missing. Raw observations and the pre-correction checkpoint are retained privately.

F03 publisher files are22pages/2636871bytes; F04 are57pages/5103901bytes; F05
are29pages/7842498bytes. F04's first Zotero save created only a parent; its trial
tab was closed19:11:53 UTC after no observed activity/temporary file. Two later
fresh saves obtained publisher PDFs. Temporary Connector Debug produced zero
lines and was restored off; no causal recovery claim is made.

F06 publisher FirstView has personalized watermarks/small byte differences.
F07 differs in version: Allfold publisher FirstView42pages/572214bytes, Zotero
arXiv2603.07780v1,109pages/1146058bytes. Exact title, all three authors and the
Paper's explicit preprint relation were verified; no transfer comparison is made.

F07-2 was an access/version recovery check after the restart. Allfold saved the
same related arXiv2603.07780v1 as the original Zotero trial,109pages/1146058bytes,
in12.016–12.380s. Current title/all3authors/arXiv version were checked. Electron
had not completed normal institutional preparation or independently confirmed
this target before that click; F06 PDF availability did not prove F07 rights.
This access gap is retained, not treated as an equivalent-permission product
failure or hidden from task results. Chrome initially timed out during Translator checks; after the user restored
its foreground, F07-2 Zotero saved the correct publisher FirstView42pages/572070bytes
in4.276–4.572s. This remains version-divergent. Normal Source Login had begun
03:21:14.169–.275UTC and later ended5/12Opened; actual F07 Source article showed
institutional authentication/You have Access/PDF entry despite its broker
Needs attention. That later preparation is not silently backdated to F07-2.
F07-3 then completed after both target articles were independently confirmed:
Allfold1.831–2.199s and Zotero3.746–4.081s, both correct publisher FirstView42pages/
571863bytes. No PDF was preopened. Normal access preparation changed the outcome;
no Cambridge code fix or code-only speedup is inferred.

F08 Allfold saved arXiv2502.17741v2,61pages/982280bytes under the earlier title
*A Unified Framework for Semiparametrically Efficient Semi-Supervised Learning*.
All three authors and the Paper relation match; the
[coauthor's university page](https://faculty.washington.edu/ashojaie/index.html)
links the accepted Biometrika title to [that arXiv record](https://arxiv.org/abs/2502.17741).
F09 saved [arXiv2504.05240v2](https://arxiv.org/abs/2504.05240),24pages/1968189bytes,
matching title/all3authors/explicit relation. Both are P5 preprints. F10 failed
access-challenge/Document403 before the latest CF fix, no file. All three normal
Silverchair saves were operator-interrupted without observed parent/PDF; their
terminal product states are unknown. PilotP01's fresh save likewise produced no
item. Normal Cite reached a cancelled RIS import prompt; this is not a PDF
baseline. The installed Silverchair Translator(ID3bae3a55-f021-4b59-8a14-43701f336adf,
updated2026-08-10) requests citation RIS before parent completion; the failure
stage still needs diagnosis.

F11 originally saved Allfold arXiv2406.15700v5,70pages/1758603bytes before actual
Electron publisher access was established. Its original Zotero save made only a
parent with missing DOI/authors. That initial result is retained. F12/F13 are
previously untreated same-platform repair checks: Allfold P1 saved publisher
Accepted Manuscripts(35pages/1339576bytes and34pages/1730654bytes). F12 Zotero made
a parent only, initially in My Library; normal Add to Collection corrected its
target afterward. Its original save time, collection-target deviation and later
operator interruption are retained; collection appearance is not the save/PDF
endpoint. F13 and a fresh F11 retry now have valid local PDFs on both products.
Chrome needed separate CARSI T&F renewal and human Cloudflare before saving.
These permission/cache differences prevent attributing all body-version changes
to code. Two swapped F13 repeats, two further preselected F11 controls and F12 recovery
remain outstanding.

F20 Project Euclid saved arXiv2503.14978v4 on both products,34pages/1719653bytes,
exact title/both authors/explicit relation checked. Zotero waited4.293–4.583s.
Allfold waited412.592–413.015s including an in-download Imperva/hCaptcha handoff.
Native manual wait began01:21:47.303 UTC and the page had cleared by01:28:33.157;
actual human input start/end are missing. This span includes late operator/tool
handoff and cannot be called machine Solver/network time or subtracted as a
precise human duration. The total is preserved as assisted first-access recovery,
separate from normal prepared downloads. It does not establish publisher rights.

Each new Chrome Service must first be chosen from the normal CARSI resource page;
actual target rights/Translator are then checked independently. Broker Opened
is not proof of article access. CUA recovered and targets task windows/tabs without
acting on unrelated current pages. Intermittent tool timeouts remain operator
interruptions; no AgentDock UI was used. Chrome native AX and documented
focused-tab reads timed out(-10005/kernel reset); the exact Source app still
responded0.14s. The user restored Chrome foreground, allowing F07-2 to save, but
its fresh F07-3 tab hit another read timeout before Save. After the user restarted
Computer Use, targeted Source and Chrome reads succeeded in2.24s/1.7s, with all
product/observer PIDs and account/cache state preserved. F07-3 then completed real
new saves on both products. Global inventory still timed out, so task-specific
surfaces are used. No Save/time is inferred merely from foregrounding/restarting.
The obsolete alternative-tool question does not block the recovered channel.

At the checkpoint Workspace has72Papers,52Candidates,20Downloaded,0Trash, no
active download. Diagnostics that lost their configured target earlier refused
writes; cause unknown, exports explicitly incomplete. A normal01:11 relaunch
restored logging, and the current native export was saved outside Workspace.
No Logs Reset or guard bypass was performed. Original Run inputs/providers and
debug settings were restored. Annual Reviews had no eligible Paper; Optica/R059/
LWW/OCE and unobserved Reader/stableP4 mechanisms remain uncovered. No Reset has
run because formal measurements and required retests are outstanding.

## Diagnosed changes and remaining work

`1f28dc0840640605c271be8c2e2861c6fe6659a6` retains current Document route host/IDs
and tries newly applicable P1/P2 templates after P3/P4. It does not replay missing
input APIs. The original ScienceDirect retry changed from no candidates to actual
R024 requests, but still did not save a PDF. This is not reported as a successful
fix. Real before/after attempts and SHA are retained in the result table.

`9383359e05a625e027f228873a847b15196e02fa` uses that current route when recognizing
a PDF-entry redirect back to the article, so the existing native Reader can run.
It also refuses DOI-bearing URL transforms that explicitly name another DOI.
Seven focused regressions failed before these changes and passed afterward.
The original ScienceDirect retry on this actual running code saved a correct
13-page / 3,784,880-byte published PDF in 10.455–10.816 s. Diagnostics show current
Document (5.123 s), entry response (0.157 s), existing Reader extraction (2.240 s),
then the existing closed Session stream from ScienceDirect assets (1.966 s).
No DownloadItem was observed on this path. These native operations precede the
verified final association endpoint. Institutional access was visibly confirmed
again, and restarts/Session/cache differed; this does not isolate a code-only
speedup. Two previously undownloaded, unvisited-in-Allfold related Papers were
selected before their outcomes: P05 in Neural Networks and P06 in Pattern
Recognition. Both first Downloads saved the correct publisher PDF through R024,
Reader and the assets CDN without fallback. Corresponding formal controls and
complete same-version pairs remain outstanding.
Zotero still has no PDF for the original pilot. No Zotero runtime/source was copied.

`098288ae32e159811b9c49333b386d1533890862` addresses a follow-up native review
finding: the new DOI guard decoded only the route spelling and rejected matching
escaped Paper DOIs. The comparison now decodes one layer symmetrically, preserving
distinct non-UTF-8 bytes and the original request spelling. Targeted regressions
also distinguish different escape layers and encoded whitespace. 396 related
tests pass. Its affected R029–R034 platforms are not among the current real pilots;
their live-site effect is unverified. The actual runtime was subsequently rebuilt
and restarted at 7c9be1c, containing production code 098288a; process, source path,
port and runtime versions were checked. Full Python checks pass 1622 tests. Fixed-baseline review of
all committed changes through 098288a found no Standards issue or implementation
defect; Spec separately retained four disclosed incomplete categories: formal
coverage, real paired retests, latest full CI and final Reset. An independent
affected bug review found no actionable introduced defect (99 isolated checks).

IEEE's first native request had no reported response/progress before its normal
10-minute parent deadline. Subsequent normal Browser navigation returned article
HTML with HTTP 200 in about 7.8 s and displayed institutional access/PDF controls;
the earlier stalled UI cannot be classified as proven permission denial. A later
pilot uses Chromium's temporary default metadata-only NetLog to identify the
native stop. Two later Allfold downloads saved matching 15-page PDFs with small
byte differences and publisher watermarks. NetLog showed a single R025 GET, HTTP 200,
first body at about 2.4–2.8 s and stream end at about 17.7–20.6 s. These later
successes followed normal Session/access preparation; they do not explain the
first expiry or establish code benefit. A fresh Chrome article lacked the prior
PDF permission. The IdP's default QR page also offered ordinary account login;
existing saved credentials and a fresh normal resource entry restored access
without human MFA. The old SAML nonce had expired. Three new complete pilot pairs
then saved PDFs on both products at the final production code version 098288a.
Their midpoint medians are 14.838 s (Allfold), 16.491 s (Zotero), with median paired
difference −1.4985 s and ratio 0.9078. Raw interval points and genuine new-file
checks are retained. One Allfold repeat was deleted before its individual text
inspection; its association/PDF prefix/source/size were observed, but version is
inferred from neighboring inspected copies and strict transfer comparison is
excluded. All other repeat files were individually checked. One paper cannot
establish IEEE parity or explain the earlier deadline expiry.

P05's initial unresolved Zotero save was explicitly operator-interrupted by
reloading only the same Connector version; enabled/pinned/permissions were
restored, no profile/cookie reset occurred, and that trial is not a timed failure.
Its new save and P06 both exposed a real ScienceDirect verification popup. User
assistance was requested, no user action was observed, and the windows later were
no longer listed. Local API/Desktop still showed zero PDF attachments and actual
temporary storage was empty. Exact final failure times are missing; popup
disappearance and a resolver communication error are not invented PDF endpoints.
Connector debug was restored off without clearing/submitting output. The ordinary
same-version source uses a 60-second attachment GET and existing browser recovery;
that mechanism was inspected locally, not copied or changed.

NetLog excludes sensitive capture modes and is kept private. This uses
Electron's existing [supported switch](https://www.electronjs.org/docs/latest/api/command-line-switches#--log-net-logpath)
and [default capture mode](https://www.electronjs.org/docs/latest/api/net-log).

The68journal/12Service inventory drove the frozen31Paper/10platform manifest.
IEEE and Cambridge each supplied two eligible untreated Papers, ScienceDirect six,
and the other seven platforms three each. Configured EBSCO is an access capability,
not proof of INFORMS full-text routing. Unavailable mechanisms are not imputed.

The full PR-linked run for 098288a failed in the isolated native Cancel fixture's
five-second public-progress wait, after the earlier 603f02f full run had passed.
The original failed run is retained at
[run 43912807839](https://github.com/dylaaan-booob/allfold/actions/runs/43912807839).
No production timeout or assertion was changed. An isolated local reproduction
on the same source passed all 41 public native cases in about 12.7 s; full native
checks also passed all 241 tests on the same 098288a source, with no skips, in
120.7 s; JavaScript checks passed 63 files. The subsequent full PR-linked
[run 43921980119](https://github.com/dylaaan-booob/allfold/actions/runs/43921980119)
passed every Safety checks step at head 7c9be1c. The subsequent full PR-linked
[run43934292137](https://github.com/dylaaan-booob/allfold/actions/runs/43934292137)
also passed every step for fb7fdbd. Latest-head verification is recorded in the
PR checks and PR Evidence; earlier green runs are not substitutes for it. The earlier failure’s cause is not
established, so it is not described as repaired.

Earlier head `fdad2a3`'s full PR-linked [run 43976157092](https://github.com/dylaaan-booob/allfold/actions/runs/43976157092)
failed: attempt 1 reached a DocumentRuntime probe deadline; the isolated same-source
probe passed locally. One bounded rerun passed that probe but failed Quick Open
because History remained modal. A controlled isolated response/click replay then
showed the History Close button moving 17.26 CSS pixels between measuring and
sending input, leaving the click on the dialog background. Waiting for the initial
History response before measuring the click fixed the replay. The existing shipped
native fixture now waits on that rendered state and asserts History closes;
both scrollbar modes pass locally (about 8.2 s). No production code, timeout or
assertion was weakened. The exact first failure's cause remains unestablished;
the full PR-linked run43989863281 succeeded at92f6492 after this fixture fix.

## Service grouping and real Cloudflare repair

User-reported failed Services disappeared from Browser groups, and manually opened
publishers remained in CARSI. `e67e136` keeps every configured Service group even
when its pages failed/closed. An otherwise unassigned CARSI-descended page may be
displayed under one unique configured publisher access origin. Explicit authority
associations win; ambiguous/shared CARSI origins remain unassigned. This is display
grouping only: native association, Service binding and Prepared status are unchanged.
Real retests showed all12 groups, including failed/empty Oxford and T&F, and both
manually opened publishers under their proper configured groups.

The original T&F Chinese verification page was visibly blocked but never started
a Solver. Its native main response carried `cf-mitigated: challenge`, yet localized
`<main>` text looked like content and vetoed challenge detection. `e67e136` trusts
that authoritative header before the content heuristic, retaining widget/subframe/
ordinary-content guards. Isolated regression and normal real Prepare now show
T&F solver_started02:07:49.960, checkbox_clicked02:07:54.829 and page recovery
02:08:11.122 UTC. Oxford/Wiley/SIAM also recovered real CF pages automatically.
Later `not_executed/canceled` child replies followed successful page recovery and
polling abort; they are not evidence that no checkbox was clicked. hCaptcha still
required the user and is reported separately. Broker cache eviction can later
close pages/change Prepared status; it does not negate the observed recovery.

Independent native review found a related focus defect: when a focused CARSI row
moved into a collapsed Service group it lost focus. `a9663f7` now focuses the
collapsed group's summary. A red→green DOM regression and actual shipped native
fixture in both scrollbar modes passed; association/selection stayed unchanged.
The trusted UI reload preserved existing native pages and Session. Native code is
unchanged between e67e136 and a9663f7. Full e67 local checks passed JS63, Python1622
and Electron243/0skips; a966 affected DOM/native checks passed12cases. Full PR-linked
[Safety run44002168127](https://github.com/dylaaan-booob/allfold/actions/runs/44002168127)
succeeded for actual PR head a9663f778c920c588414f2e8816b8a962faffcc0. The diagnostic/evidence
increment then passed separate Standards/Spec reviews; disclosure/control wording
findings were corrected in7fd16eb and confirmed. An independent native Bug review
of the committed stream diagnostic increment found0introduced bugs. The latest
PR-associated [Safety run44006784262](https://github.com/dylaaan-booob/allfold/actions/runs/44006784262)
succeeded for head7fd16ebb1ac3147e8c828d0f4b085d1862cced1f, including the full
244-test Electron suite. Subsequent commits require their own latest-PR result;
CI success does not complete real acceptance or authorize an early Reset.

Raw diagnostics, runtime proofs, click records and local file/association observations
are outside Workspace in a private evidence directory. Public tables contain no
PDFs, cookies, credentials, signed URLs, sensitive institutional pages or raw auth
requests. Workspace Reset has **not** run: mandatory acceptance/retests remain.
The dedicated Zotero collection retains all trial materials and the original
library is preserved.

## CI execution cleanup checkpoint

PR-linked run44012054791 at8aa4b8b failed the body-stream fixture65s timeout,
then retained Electron/Python processes/output pipes until the20min job limit.
This was not a20min normal suite runtime. The committed test-only cbe1b7b cleanup
shares one POSIX process-group runner across existing native wrappers,retains
all deadlines/output limits/assertions,and streams case stdout once. A synthetic
SIGTERM-ignoring parent/descendant regression failed before and now confirms
actual termination and released pipes. Full local Electron245passed; final affected
UI wrappers/regression3passed; JS63passed. Standards/Spec increment reviews found0.
Original body-stream's internal intermittent stop point is still unknown; better
case output and fail-fast cleanup do not prove that internal cause fixed.

The cbe1b7b full PR run44017379916 stopped earlier,in Python:1621passed,
1collection-planner fixture failed opening SQLite while its collection worker
was active. The test now reads through its normal Workspace owner gate; production
single-link/path guards remain intact. Focused20tests and full local Python1622
pass(2existing warnings,39.33s). The committed78e7ea0 fix then passed affected
Standards/Spec reviews with0findings. Its complete PR-associated
[Safety run44019129180](https://github.com/dylaaan-booob/allfold/actions/runs/44019129180)
passed JS63,Python1622(4CIwarnings),Electron245/0skips in about5min20s. Actual test
merge9e149b89 was associated with head78e7ea0; later evidence commits require their
own latest-PR check. Production bytes remain identical to the running77dfd67.
No workflow deadline,necessary assertion,dependency or production safety guard was
removed. CI success doesnot complete real acceptance or permit early Reset.

The late Run sidecar race recurred in two full offline checks while a background
collection could close SQLite sidecars during Run materialization/final snapshot.
Commit3a551ea takes the existing Paper owner gate in those two late commit contexts;
strict link-count/path checks remain. The existing four-parameter collection test
now asserts the gate during the affected verification; red/green and the full
1669-test run are retained. No new retry,scan or production completeness check was
added. The latest full PR Safety passed in about5min50s; its Electron step took
about3min24s. A macOS arm64 queue-capacity notice is not a product failure.

## Native partition-context repair and real retests

[Community and fixed-version research](partitioned-cookie-research.md) supports
missing page-partition cookies as the working cause. The same Electron45 isolated
fixture proves ordinary credentials/include and Referer are insufficient, and a
fetch Cookie header is overwritten. A final controlled beforeSendHeaders addition
restores the correct partition while retaining ordinary cookies. A foreign-partition
negative and actual origin/path redirects keep their scope. This is mechanism
validation,not an additional successful real sample.

The shared body path now obtains only partitioned cookies from an existing
same-Session native Page matching the qualified source origin. Chromium selects
its native isolation key; it does not merge every partition or navigate a page.
The task/Service guards and existing Session stream/writer/file association remain.
Values stay within Main. Explicit no-referrer continuations do not acquire a
guessed context. An optional count in the existing terminal diagnostic records
the selected partition-cookie count,not names/values/headers or a new product state.

Exact local commands pass JavaScript64files,Python1669tests/2existingwarnings,
Electron251tests/0skips(117.976s). Functional controlled-header regression was red
before implementation. The original native file/association/cleanup assertions
remain. ActualSource3a was normally quit13:40:57UTC after evidence export; its
Workspace remained72Papers/23bodies at that checkpoint. The evidence-onlyc6c4ac2
Safety run44092406853 was not CI for the subsequent repair. New-code review,
startup,CI and first real retests have since completed as recorded below;
Workspace Reset has not run.

The submitted9fa independent native review found oneP2: uniformly prefixing
partitioned cookies could put a root-path credential before an ordinary longer-path
credential. An actual native regression failed on that wire ordering before the
correction; both directions now pass. The merge retains ordinary order,uses scoped
path metadata for longer-path insertion,and leaves ordinary-first ties or unknown
current ordinary same-name values intact.

Primary-source checking also confirmed the Cookie query is SameSite-inclusive.
The corrected adapter verifies the native top-level security origin and separately
restricts cross-origin additions to explicitSameSite=None; no site/PSL guess is
made. Native controls show CDP reads cross-siteStrict but both Browser fetch and
controlled supplementation omit it,while None remains usable. Exact corrected
full checks pass JS64,Python1669/2existingwarnings(36.00s),Electron253/0skips
(118.895s). The submitted-delta follow-up then identified the separate metadata
ranking defect below; this intermediate green run did not establish live success.

A second affected native follow-up found that blocked partition metadata could
still give an ordinary identical name/value a false longer-path rank. The exact
cross-origin native wire case failed before correction. Only ordinary unpartitioned
metadata now ranks ordinary header pairs; opaque/nonce partition markers are
excluded, and ambiguous duplicate ordinary descriptors remain unknown. The native
case now passes. Exact final local JS64,Python1669/2existingwarnings(36.61s),
Electron253/0skips(118.623s) pass. The final bounded native review at69b9a41
confirmed the prior finding resolved and reported no actionable introduced bug.
The complete PR-associated Safety44114394462 passed JS64,Python1669/4CIwarnings,
Electron253/0skips on test merge0aab998d34f2b30d9648b0115f30bde087684d0b.
Actual rebuiltSource69 is used for F18-4/5/6,F17-2/3/4 and F19-1/2/3/4 above. Publisher
versions now save successfully,while first-versus-repeat timing variation still
requires the remaining paired repeats and transport investigation. No overall
parity or Workspace Reset is claimed.

## Large-PDF warm-cache diagnosis

A one-shot90-snapshot,1s OS receive-counter observation accompanied F19-4 without
another download,UI input or cache/setting change. Browser process input grew
18057426bytes; subtracting6547989bytes of concurrent local Python UI-server output
leaves approximately11509437bytes,close to the11471779-byte PDF plus transport/
control traffic. Ordered counters grow through the transfer window and plateau
near completion. They do not show a whole body received early followed by many
seconds of local publication. Counters include incidental background traffic and
are not exact per-request packet totals.

One additional **non-scoring** normal Zotero Save,D2,used a new article tab,parent
and imported attachment in the dedicated collection. It saved the same59-page
11471788-byte publisher PDF in4.901–5.352s; title/DOI/file/parent were individually
checked. Across its60-snapshot,1s capture Chrome received only51413bytes and sent
11835464bytes. In the coarse Save window,incoming was about40199bytes while
outgoing was11482380bytes,consistent with importing the PDF to Desktop without
receiving a new11.47MB body from the publisher. The sole Chrome network-socket
owner was checked before and after. Together with the installed normal fetch
path,this supports warm Browser HTTP-cache reuse rather than reuse of an old
attachment or Save session. Exact `fromCache` and disk-versus-memory tier were
not captured; D2 is excluded from ordinary paired aggregates. No cache was cleared.

Both OS tools buffered stdout until exit. Their Python receipt timestamps are
**not** sample times. Only ordered1s snapshots and approximate offsets from the
capture span support the network trend; main product times still come from the
independent bounded click/file/association observations. The initial all22-PID
Chrome counter invocation returned64 with no samples; that auxiliary failure was
retained and a supported selection was made only after actual socket ownership
was checked. It is not a product failure.

The size pattern also has a versioned explanation worth retaining: current
BrowserRuntime uses a cache-enabled in-memory Session. Electron45 leaves its HTTP
cache size unspecified; Chromium156 on this24GiB machine defaults to50MiB total
with ordinary `MaxFileSize = max_size / 8`,6553600bytes. F17/F18 are below this
ordinary-entry bound and F19's file/observed received body are above it. This is
a calculated upstream cache budget,not measured resident RAM or a PDF download
limit; range/sparse and HTTP caching conditions must be distinguished. Final PDF
size alone was not used to infer a hit or miss.
[Chromium156 memory backend](https://github.com/chromium/chromium/blob/156.0.8078.48/net/disk_cache/memory/mem_backend_impl.cc)

Electron45 has no public desktop API to change that in-memory budget or entry
bound. Its cache option is boolean,and `getCacheSize()` queries occupancy;
`--disk-cache-size` is applied only for `!in_memory`. No persistent partition,
credential storage,lifecycle,Vendor,dependency or cache-size change was introduced.
The measured large-PDF warm user-wait gap remains open,while the demonstrated
cache mismatch cannot serve as a pure network-priority throughput comparison.
[Electron45 propagation](https://github.com/electron/electron/blob/v45.0.0/shell/browser/net/network_context_service.cc#L81),
[Session API](https://github.com/electron/electron/blob/v45.0.0/docs/api/session.md#sessionfrompartitionpartition-options)

## Request-priority investigation

Versioned Electron45 `fetchWithSession` does not forward `RequestInit.priority`
to ClientRequest; its native default is idle. The installed ChromeMV3 Connector
5.0.217 uses browser fetch and `arrayBuffer()`,rather than its alternateXHR path.
These are specific implementation differences,not proof of the observed first-
request throughput cause.[Electron45 implementation](https://github.com/electron/electron/blob/v45.0.0/lib/browser/api/net-fetch.ts#L76)

Eight targeted community queries found the adjacent [Electron46828 report](https://github.com/electron/electron/issues/46828):
35.2.1/macOS15.1/arm64,`protocol.handle`→`net.fetch` allegedly changes H2 toH1 and
blocks; it includes a minimal example but no priority-adjustment experiment or
HTTPS-body before/after measurement,and was closed for inactivity. It neither
proves an Electron45 defect nor applies directly to Allfold's current request path.

RFC9218 reserves lowest urgency for background work and advises against it for
responses affecting user interaction; servers may ignore priority signals. Current
Chromium156 preserves an explicit standard Priority header instead of generating
one from internal priority. This permits a minimal future verification within the
existing Session stream,while keeping a server hint distinct from native request
scheduling. Actual wire priority,H2/H3,cache hits and a causal speed effect have
not been captured. No priority header,transport replacement,dependency or UA/proxy
change has been made. Institution eligibility currently takes priority for F19.
[RFC9218](https://www.rfc-editor.org/rfc/rfc9218.html#section-4.1),
[Chromium156 header generation](https://github.com/chromium/chromium/blob/156.0.8078.48/net/spdy/spdy_http_utils.cc#L204)
