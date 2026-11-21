# Local Allfold / Zotero PDF pairing acceptance

Issue: [#140](https://github.com/dylaaan-booob/allfold/issues/140). Baseline:
`a2e511aa86ab5aa292f224301d6609a59c287fa2`.

## Targeted follow-up

The follow-up on PR #141 uses the same success and timing criteria adopted on
20 November. The field route can read an already-published Paper during
collection. An isolated regression reproduced a 409 when the read observed an
unlinked SQLite journal during a normal commit. This documents the controlled
interleaving. The earlier field fixture did not retain the failed response.

Cross-origin recovery, verification POST ownership, partitioned cookies,
EBSCO record selection and fallback, and the removed response limits have
isolated regression coverage. Live comparisons and Workspace cleanup are
tracked as a separate increment in the [results](pdf-pairing-formal-results.json).
The historical SIAM F19 large-PDF cache gap remains open. The old Oxford
navigation refusal has no confirmed trigger or attribution.

### First targeted F23 attempt

On production code `c8529aff8f6d3b3f38bed0597b04fa450712bd71`,
ordinary Allfold Download took 25.811–26.169 seconds and saved a 34-page P5
alternative with an arXiv marker. The saved file did not match the target DOI
or title on the inspected pages. Zotero took 46.396–46.701 seconds and
imported the 29-page licensed INFORMS PDF. The EBSCO detail page loaded its
inline PDF before the Connector click. The different files make this an
ineligible timing pair. The alternative file and both verification records
were preserved outside Workspace before clearing the trial body through the
product and restoring its original Paper for a repeat.

After the publisher attempt, the EBSCO action stopped at `resource_ready`
after 2.335 seconds. Inspection of the retained Community page found multiple
distinct native controls that submitted to the same form endpoint. The
follow-up selects an observed eligible link or native control first and uses
the journal-search label to disambiguate those opaque controls. An isolated
regression exercises that observed page shape.

### Targeted F24 on `8441641`

Allfold and Zotero saved byte-identical 39-page INFORMS Just Accepted
attachments with the target DOI and title. Allfold's click-to-association
wait was 42.026–42.391 seconds against Zotero's 17.740–18.075 seconds
(+23.951 to +24.651 seconds, 2.3251–2.3896×). Allfold first used the direct
publisher path and continued with the independently prepared EBSCO Service.
Native evidence measures 9.255 seconds through the Community/profile handoff,
11.107 seconds to locate the record, 0.613 seconds to read its link, a
0.597-second link response and 9.178 seconds for the successful stream.
These phases are part of the total wait. Chrome automatically loaded its
inline PDF before the Connector click. The result records an observed wait
gap with that preparation and limited cache evidence.

### Targeted new EBSCO record on `8441641`

Allfold saved the verified 62-page PDF for `10.1287/moor.2024.0818` in
42.574–42.926 seconds. The same Service reused the profile in 0.002 seconds,
with no Community visit. The record search took 15.447 seconds, the link
lookup 0.742 seconds, and its indirection 0.573 seconds. The successful
21.882-second stream was the largest measured phase. In Chrome the independently
authenticated record detail displayed an unavailable inline PDF. Connector
created the matching parent in the acceptance collection. The observed
parent had no attachment about 118 seconds after the click, and there was no
terminal error message to attribute. This attempt supplies no timing comparison.

## Historical acceptance through `d237ee7`

**Acceptance uses the criteria revised on 20 November 2026
(Asia/Shanghai).** 30 of the 31 frozen Papers were started. The subscription
requirement excluded one Project Euclid Paper under the agreed publisher-OA
scope. Four supplemental Papers were also measured. The results retain
97 pair slots including repeats, alongside separate pilot and diagnostic records.
The first EBSCO details-link retest on `a921407` stopped at the Community entry.
The final production code at `d237ee7491c421aaa07aef289ed33db12618db6d`
saved the authorized EBSCO edition on both original Papers and a new Paper
through the verified details link. EBSCO and the large SIAM warm repeat retain
material wait gaps.

A difference of about five seconds is acceptable for comparable user waits.
Materially longer waits still require investigation and an attempted repair.
Remaining delays and branches that did not recur are recorded below with their
evidence. These timing criteria leave the correct authorized local PDF and its
item association as the success endpoint. Earlier checkpoints retain the state
at each recorded revision.

## Environment and endpoint

The source checkout, rebuilt UI, live process and local API were checked, rather
than inferring the running version from Git. macOS 27.2.1 (26B131); Electron
45.0.0 / Chromium 156.0.8078.48; Chrome 157.0.8103.51, existing Default profile;
Zotero Desktop 10.0.9 / Connector 5.0.217. After sleep, Chrome About was observed
first at 157.0.8103.51 and later at 157.0.8103.79 (also the on-disk version); no
operator-triggered update/restart was performed. The exact running-binary
transition time is unknown and is not claimed as a performance improvement.
For the final EBSCO original retests, the active Chrome framework and the
installed bundle both showed 157.0.8103.80. Connector 5.0.217 and Zotero
Desktop 10.0.9 were unchanged. Connector could reach Desktop and local
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

## Formal results and coverage

The immutable [31-paper manifest](pdf-pairing-manifest.json) was committed before
the first formal click. The [formal results](pdf-pairing-formal-results.json)
retain all original samples, failures, preparation, versions and repetitions.
Across those slots Allfold has 90 automatic local-PDF successes, one assisted
success and six failures. Zotero has 71 automatic and three assisted local-PDF
successes, one visible attachment failure, eleven attempts with no local PDF
at the observation horizon, ten operator interruptions and one observation
interruption with unknown product terminal state. These are
attempt counts, not independent-paper success rates. Saving a related preprint
is a task result but is not a publisher-version success.

| Actual platform | Papers started / planned | Local PDF observations, including repeats | Conclusion |
| --- | --- | --- | --- |
| IEEE Xplore | 2 / 2 | Allfold5 publisher files,1 original failure; Zotero6 publisher files | Current F01 three controls plus F02 paired retest all correct/same-version and Allfold not slower. Old failure retained; no extrapolation beyond these2Papers. |
| Springer Link | 3 / 3 | Allfold 14 successes. Zotero 13 successes and 1 interruption. | The slowest comparable Allfold point has a difference no greater than 1.609 s. F03-6, F05-2 and F04-4 overlap within measurement precision. |
| Cambridge Core | 2 / 2 | Allfold9 successes; Zotero9 successes; one body on each side is a preprint | F06 three controls plus F07-3 have comparable publisher PDFs; all favor Allfold. No observed disadvantage in these two Papers; earlier access/version differences retained, no broader extrapolation. |
| Oxford Academic | 3 / 3 | Allfold saved three publisher PDFs and two related preprints, with one original access-challenge failure. Zotero had three interrupted saves and three complete observations with no new parent or PDF. | After both institution checks, Allfold saved F10-2 in 5.523–5.886 s, F08-2 in 30.521–30.870 s, and F09-2 in 54.554–54.897 s. Subsequent Allfold diagnostics on both originals and an untouched Paper obtained publisher PDFs directly. The old navigation block did not recur. No same-version paired timing. |
| Taylor & Francis | 3 / 3 | Allfold saved one related preprint and eight publisher Accepted Manuscripts. Zotero saved three publisher Accepted Manuscripts, had two interrupted parent-only saves, and four parent-only saves through the horizon. | The largest observed comparable Allfold delay was 1.236 s. The latest F11–F13 retests saved the publisher PDF in Allfold. Zotero had no local PDF at the observation horizon. |
| Project Euclid | 2 / 3 | F20 matching related arXiv v4, with in-download Allfold hCaptcha assistance. F22 matching 30-page publisher OA saved automatically by both products. F21 subscription excluded. | F22 favors Allfold. Only one publisher OA pair measured; institutional access is outside the revised scope. |
| Wiley | 3 / 3 | Allfold saved seven publisher OA files. Zotero saved one preprint and three publisher files, with two interrupted attempts and one parent-only save through the horizon. | F14 same-publication controls and F15 favor Allfold. F16-3 saved on Allfold in 7.079–7.434 s after both institution checks. No comparable F16 timing point. |
| SIAM | 3 / 3 | Allfold saved five related preprints and nine publisher PDFs. Zotero saved thirteen publisher PDFs, with one interruption. | F17/F18 satisfy the revised timing criterion in all six same-version pairs. F19 has longer first and large-file warm waits. Its publisher PDF saved after normal reauthentication. See the cache diagnosis below. |
| INFORMS PubsOnline | 3 / 3 target Papers | Allfold's direct publisher sources returned authorization denials on F23/F24/F25. Zotero's direct F25 saved the parent only. | No verified direct-publisher PDF pair. The separate EBSCO records for F23/F24 provide their own authorized access. |
| EBSCO Business Source Complete | 2 matching representative records, 2 supplemental | Seven comparable pairs saved identical licensed copies. Earlier preprint saves remain in the table. | The Viewer repair restored licensed saves. The new details link worked on both originals and a new Paper. F24-7 exercised the changed source order during a real publisher challenge. Allfold took 15.487–19.949 s longer across the three direct-link pairs. |
| ScienceDirect | 6 / 6 plus two supplemental mechanism Papers | Earlier paired files, failures and substitutes are retained. With the last ScienceDirect fix, F27, both untouched Papers and the F26 Allfold-only control each saved the verified publisher publication automatically through the first Reader. | F29/F30/F31 were within about five seconds. The older F27 challenge pair was materially slower. The fixed Reader passed real saving on the four Papers, with no comparable Zotero completion for those retests. |

### Paired wait by platform and observed access

The representative strata below use automatic, comparable-version pairs from
the [formal results](pdf-pairing-formal-results.json), including the designated
controls and retests. Counts show distinct Papers and pairs. Each median uses
the lower and upper interval bounds independently. The observed span runs from
the lowest lower bound to the highest upper bound of the paired difference.
For one pair, the span is its measurement interval. Positive differences mean
a longer Allfold wait.

| Platform, actual access and visit condition | Papers / pairs | Raw pair IDs | Median A−Z (s) | Median A/Z | Observed A−Z span (s) |
| --- | --- | --- | --- | --- | --- |
| IEEE Xplore, institutional, first after renewed preparation | 1 / 1 | F01-2 | −3.350 to −2.556 | 0.7457–0.7995 | −3.350 to −2.556 |
| IEEE Xplore, institutional, repeat with warm access | 2 / 3 | F01-3, F01-4, F02-2 | −3.457 to −2.478 | 0.8179–0.8653 | −3.764 to −0.025 |
| Cambridge Core, institutional, first after Source restarts | 1 / 2 | F06-4, F06-5 | −1.788 to −1.099 | 0.5312–0.7147 | −2.699 to −0.244 |
| Cambridge Core, institutional, repeat in the same session | 1 / 1 | F06-6 | −1.570 to −0.835 | 0.5961–0.7623 | −1.570 to −0.835 |
| Cambridge Core, publisher file after rights were verified again | 1 / 1 | F07-3 | −2.250 to −1.547 | 0.4487–0.5870 | −2.250 to −1.547 |
| Springer Link, OA, first repeat after Source restart | 1 / 1 | F03-4 | +0.489 to +1.235 | 1.2319–1.7193 | +0.489 to +1.235 |
| Springer Link, OA, repeat in the same session | 1 / 2 | F03-5, F03-6 | +0.243 to +0.922 | 0.9454–1.4647 | −0.428 to +1.609 |
| Springer Link, OA, F05 repeat after verified institution access | 1 / 1 | F05-2 | −0.494 to +0.186 | 0.9742–1.0099 | −0.494 to +0.186 |
| Springer Link, institutional, F04 control with Zotero first | 1 / 1 | F04-4 | −0.723 to +0.100 | 0.9377–1.0090 | −0.723 to +0.100 |
| Taylor & Francis, institutional | 1 / 2 | F11-2, F11-3 | −0.649 to 0.000 | 0.8750–1.0113 | −1.470 to +0.820 |
| Taylor & Francis, OA | 1 / 1 | F13-1 | +0.497 to +1.236 | 1.0972–1.2597 | +0.497 to +1.236 |
| Wiley, OA, both copies from the publisher site | 1 / 1 | F15-1 | −1.458 to −0.663 | 0.4258–0.6940 | −1.458 to −0.663 |
| Wiley and PMC, OA, same publication via different hosts | 1 / 2 | F14-2, F14-3 | −5.300 to −4.542 | 0.1439–0.2150 | −5.800 to −4.059 |
| SIAM, institutional, first prepared publisher request | 3 / 3 | F17-2, F18-4, F19-1 | +3.832 to +4.644 | 1.4852–1.5270 | +3.626 to +13.785 |
| SIAM, institutional, warm repeats of smaller publisher files | 2 / 4 | F17-3, F17-4, F18-5, F18-6 | −3.954 to −3.391 | 0–0.0713 | −7.170 to −2.551 |
| SIAM, institutional, after symmetric ePDF preview | 1 / 1 | F19-3 | −0.991 to −0.062 | 0.9615–0.9975 | −0.991 to −0.062 |
| SIAM, institutional, warm repeat of the large publisher file | 1 / 1 | F19-4 | +16.738 to +17.761 | 4.7138–5.5953 | +16.738 to +17.761 |
| EBSCO Business Source Complete, institutional, Viewer repair retest | 2 / 2 | F24-4, F23-5 | +33.955 to +34.661 | 3.3298–3.4386 | +23.198 to +45.456 |
| EBSCO Business Source Complete, institutional, F24 after Source restart | 1 / 1 | F24-5 | +20.123 to +20.821 | 2.9194–3.0556 | +20.123 to +20.821 |
| EBSCO Business Source Complete, institutional, direct details link | 2 / 2 | F24-7, F23-6 | +17.391 to +18.079 | 2.2222–2.2982 | +15.487 to +19.949 |
| ScienceDirect, OA, first saves with warm site sessions | 2 / 2 | F29-1, F31-1 | +3.973 to +4.782 | 1.2723–1.3381 | +3.513 to +5.239 |
| ScienceDirect, institutional, first save with warm site sessions | 1 / 1 | F30-1 | +0.337 to +1.283 | 1.0198–1.0781 | +0.337 to +1.283 |
| ScienceDirect, institutional, automatic Reader challenge recovery | 1 / 1 | F27-2 | +23.696 to +24.400 | 2.3128–2.3771 | +23.696 to +24.400 |
| Project Euclid, publisher OA | 1 / 1 | F22-1 | −2.261 to −1.609 | 0.3924–0.5302 | −2.261 to −1.609 |

In the separate fallback outcome F28-1, both products saved the same arXiv
preprint after opening the ScienceDirect article. Its user-wait difference was
−116.830 to −116.179 s and its ratio 0.1358–0.1386. The mechanism comparisons
F03-7 and F03-8 show the first and warm Springer Session requests separately
below. The assisted ScienceDirect pair F27-5 also retains its total wait below.
Oxford and direct INFORMS PubsOnline lack a comparable publisher pair in these strata.
The EBSCO details-link supplement R073-Fresh-2 is kept outside the original-paper
strata. Its one pair had A−Z of +17.999 to +18.684 s and A/Z of 2.2733–2.3538.

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
69 recorded slots and identifies the subscription-restricted sample omitted from
Download. The retained traces show 17 attempts with Cloudflare evidence, 49
without observed Cloudflare evidence and three with insufficient time bounds or
matching traces. Earlier
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

The retained Crossref facts for the six ScienceDirect samples contain an exact
DOI, an alternative identifier, and a LinkingHub landing with the compact PII.
These are sufficient to identify the linking record. Actual publisher routing
is established after navigation. A bounded public F29 resolver observation
returned HTTP 200 without a Location. The initial HTML carried a meta refresh
to a second page on LinkingHub. An independent header-only shortcut for the
first response would therefore leave the content destination unresolved. The
observation did not follow the refresh or request a PDF. The saved record still
requires qualified downstream platform evidence for the existing template.

The F27-2 challenge-recovery retest on `989ad81` ran in the exchanged order after
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

F27-3 repeated the original sequence in the other order on the same running
code. Both pages showed institutional Full text separately before timing. The
Allfold preparation Solver clicked and recovered its article. Chrome preparation
had separate human verification. No body was previewed. Allfold's first R024
source again reached a genuine Reader challenge. The Solver clicked and recovered
the Page, which gave no PDF entry after 19.479 s. The second R024 source reached
the CDN and concluded via the automatic recovery Page and Session stream.
Allfold saved the correct 12-page publication in 50.549–50.913 s (3,156,504 bytes).
The distinct Zotero Save verification window required the user's checkbox.
The same publication saved locally in 54.394–54.700 s (3,155,935 bytes). The
assisted total difference is −4.151 to −3.481 s and the ratio is 0.9241–0.9360.
The manual time alone is unknown. Ordinary fully automatic latency remains open.

<a id="live-sciencedirect-reader-order"></a>

The two original F27 retests both spent time in an unsuccessful
first R024 Reader before the second R024 entry succeeded. The retained exact
DOI facts had no earlier valid P2 PDF URL. Initial article extraction ran before
those two generated P2 entries. The implementation orders plain `/pdfft` followed
by `/pdfft?download=true`, so the reasoned candidate identities follow from the
two recorded R024 indices and that order. The traces do not expose full URLs.
The installed Zotero Translator uses the download query in its generated
canonical entry. A later non-scoring normal Browser visit to the plain `/pdfft`
entry on the same running Session reached the actual 12-page publisher CDN
viewer. There was no observed challenge on that visit. The earlier losses
occurred after actual Reader verification; this comparison establishes a
working plain URL in the observed warm Session.

A new Source Session on diagnostic checkout `7a4ea99` kept the original order.
After independent institutional login and article full-text confirmation, a
single Download on the restored F27 Paper reproduced the first-path loss.
The plain Reader recovered automatically from Cloudflare in 17.501 s and
landed at another origin. It reported zero PDF clues and no native GET
handoff. Discovery then recorded `no-pdf-entry`. The download-query Reader
landed at another origin in 4.250 s and supplied the actual GET even with
zero DOM clues. Its next CDN response required automatic Browser recovery,
then the existing Session stream saved and associated the 12-page publisher
PDF (3,156,648 bytes). Click-to-association was 41.987–42.334 s. This was a
single-side diagnostic, so it adds no paired score. The first Reader's final
request method and the site's internal routing decision remain unobserved.

`1e011af` reversed the two generated entries to test whether using the
installed Translator's download-query entry first eliminated the lost
handoff. Its focused fixture checks discovery's GET, original Paper target,
Referer and plain-entry fallback. The live F27-5 repeat established independent
institutional full text and exact article identity on both sides before saving.
On the revised order the download-query Reader was first. It spent 14.899 s,
automatically passed the new Cloudflare checkbox and became ready at HTTP 200.
Its other-origin landing still supplied zero qualified PDF clues and no native
GET handoff. The plain Reader ran second, spent 3.852 s and supplied the actual
GET. The owned CDN recovery and Session stream saved the 12-page publication
for the original Paper. Swapping entries moved the same failure to the first
path. The recurring loss follows the challenged Reader completion in these
observations. The last request method, the most recent GET's relationship to
the final landing and the target asset match are now recorded as bounded
classifications on the existing event.

The targeted F27-D6 Source diagnostic on `976015c` observed the cause. The
first Reader spent 10.894 s and reached the exact target PDF asset at HTTP
200 after the Solver checked the challenge. The last main-frame request was
POST. An earlier genuine GET in that same owned Reader matched the final PDF
location exactly. The handoff kept only the last request, so it dropped the
earlier GET and produced `no-pdf-entry`. The next Reader again produced the
GET and saved the verified 12-page publication. Its full 23.052–23.360 s
Source-only wait remains diagnostic evidence. The observations use bounded
classifications with no recorded asset URL or its query.

The repair retains that exact earlier main-frame GET and its Referer when
the same owned Reader settles at the verified PII asset and has no DOM clue.
The existing Session stream owns the next request and body validation. The
isolated Electron fixture observed the normal GET then POST sequence. It
failed on the former handoff and passed with the retained GET. When the
verified landing had a different query, the old GET remained ineligible. A
separate fixture navigation during the Cookie lookup confirms the previous
response cannot authorize the replacement GET.

The exact Source build at `10e5038` was launched and its rebuilt UI and
backend verified. Allfold and the fresh Chrome tab independently displayed
F27 institutional full text. Allfold recovered its preparation verification
automatically and the user completed Chrome's separate preparation checkbox.
Computer Use then timed out switching to the Allfold Workspace, binding to
the running native app and checking the desktop inventory. The Source
Workspace API showed the restored original Paper with Download available.
The user restored the existing Allfold window and the fixed-code F27-6
measurement then started from the original Candidate. The first Reader passed
the real challenge and settled on the target PDF after a main-frame POST.
The retained GET was used for the same source attempt. The CDN presented a
second challenge, which also cleared automatically. The native stream saved
the 12-page publisher PDF of 3,140,178 bytes and the original Paper acquired
its association in 63.154–63.498 s. There was no second Reader. The first
Reader consumed 29.069 s and the subsequent native stream 15.213 s. Challenge
and network timing varied across the trials, so the removal of that failed
Reader does not establish a reduction in total user wait.

The normal Zotero Save started after the Allfold association completed. Its
original Save popup was used to set the dedicated collection, where the local
parent was observed. The local API was last successfully polled at
04:59:17.086 UTC, ahead of the 05:01:07.521 UTC horizon. A later check after
relaunch found the same parent in the collection with no children. No saved
PDF or terminal attachment outcome was observed. F27-6 has no paired
performance point. Allfold and Zotero Desktop were subsequently restarted
through their normal entry points and the read-only observation resumed.

In the restarted session, the normal CARSI Login batch automatically recovered
the ScienceDirect challenge and returned an opened target. The managed page
ledger evicted that idle target while admitting other configured services. The
settled Service showed `Needs attention` with `target_closed`. A subsequent
single ScienceDirect visit from the retained CARSI resource page provided the
matching institutional article in Allfold. The original resource list remained
under CARSI and the exact article row appeared under SCIENCEDIRECT after the
same-tab navigation. Chrome independently entered the
actual resource and the user completed an article preparation checkbox. Neither
product previewed the PDF before its timed action.

R024-Fresh-1 was frozen in the supplemental mechanism cohort ahead of either
action. Allfold's original Candidate saved and associated the correct 12-page
publisher PDF of 2,849,747 bytes in 34.381–34.757 s. The sole Reader ran for
21.066 s, recovered the Cloudflare verification automatically and handed off
the observed exact GET after the main-frame POST with no DOM clue. The next
body request returned an access challenge. The owned Page reached HTTP 200
and the final Session stream completed in 4.680 s. No additional checkbox
dispatch was observed on the body Page. The normal Zotero Save selected the
dedicated collection at dispatch. Its popup disappeared without an observed
terminal result. The live Desktop API and observer found no matching local
parent or PDF by the common 600 s horizon. This establishes real operation of
the repaired handoff on another article. There is no comparable Zotero timing
point for this sample.

In the second untouched case, R024-Fresh-2, the user's preparation checkbox
cleared on the ordinary Chrome article. Zotero's subsequent Save wrote a fresh
local parent and presented a separate ScienceDirect attachment verification
window. The user passed that additional check. During the same Save, empty
Connector monitor windows repeatedly appeared, closed and put Chrome in the
foreground. The last user-observed helper window displayed the same article
with institutional full-text access. By the common 600 s observation bound,
no attachment had been observed. The later readback found the same parent
and no children. No product terminal or operator cancellation was observed.
Raw screenshots remain private.

The installed Connector 5.0.217 monitor, popup and attachment sources match
the release commit `ce29dfa` byte for byte. The separate browser window opens
on an initially blank monitor page. The monitor waits for an attachment
response, with a 60 s default, and the Connector closes the window on
settlement. A subsequent fetch of the discovered URL can enter the same
path if challenged again. The screenshots establish the article landing and
repeated focus changes. The exact response headers and cause of each reopening
require a trace of the active Save. A closely matching earlier incident was
reported to Zotero, including an article landing after verification while the
local item had no PDF. [Monitor](https://github.com/zotero/zotero-connectors/blob/ce29dfa360d1ce17a3a1f15a9d338d638a073106/src/browserExt/browserAttachmentMonitor/browserAttachmentMonitor.js#L37) · [Popup](https://github.com/zotero/zotero-connectors/blob/ce29dfa360d1ce17a3a1f15a9d338d638a073106/src/common/botBypass.js#L188-L207) · [Attachment fetch](https://github.com/zotero/zotero-connectors/blob/ce29dfa360d1ce17a3a1f15a9d338d638a073106/src/common/itemSaver_background.js#L204-L273) · [Zotero discussion](https://forums.zotero.org/discussion/114602/cant-save-pdfs-from-sciencedirect-using-connector-from-chrome)

The local Connector error list retained attachment resolver and communication
errors with neither a Paper identity nor per-entry timestamps. Its detailed
Debug logging was off during the original save. Those errors alone have no
reliable attribution to this pair. A later click in the reloaded original
tab reported `Reopening popup` and showed the prior completion with a red
cross for its PDF. No new attachment request was observed. This records the
original popup's later failure state outside its timing window.

The supplied Connector excerpt also records `Reopening popup`, local
`ping` and `getSelectedCollection` HTTP 200, and `delaySync` HTTP 204.
These events came from displaying the existing save state. Its cumulative
resolver and message errors lack Paper identifiers and timestamps. A later
read-only library check again found the exact original Fresh-2 parent with
zero attachments.

A separate capture on a new article tab used the exact ScienceDirect
Translator and an active Connector Debug buffer. The live RIS citation GET
for the exact PII at `/sdfe/arp/cite` returned HTTP 403 after 1.869 s. The RIS
import yielded zero records. The subsequent request with zero local items
returned HTTP 201 and its popup completed with no observed parent or PDF.
This capture stopped before any PDF request or attachment prompt. A separate
click on the publisher's own Cite → Export citation to RIS action reached
the same endpoint and presented a Cloudflare verification page. Chrome
ultimately reported that it could not retrieve the offered file. The
unresolved earlier attachment-stage case and this citation-stage failure
are recorded separately. Connector Debug was restored to Off. The user
then limited further work on this ScienceDirect issue to confirming
Allfold's saving path.

Allfold's subsequent normal action on the
original R024-Fresh-2 Candidate verified the current institution article
first. The timed extraction and sole Reader both recovered automatically. The
verified Reader POST handed off its prior exact GET. The body Page reached
HTTP 200 and the final stream closed in 12.718 s. The correct 14-page publisher
file of 4,364,246 bytes was saved and associated in 79.710–80.066 s. The
initial article operation took 39.052 s and the Reader took 19.581 s. This
trial provides the same functional repair evidence on a different title and
journal. Its long access and transfer wait remains in the table.

On the user's narrowed scope, the preselected F26 control measured only
Allfold. Its current institution article was verified with an automatic
preparation challenge. The old trial PDF was deleted through Trash after
confirmation. The same original Candidate was restored and its previous
file confirmed absent before clicking Download. Attempt 5 reached the
first Reader's verified asset after an automatically handled challenge.
It retained the earlier exact GET after POST and completed the source
without fallback. The native stream closed in 1.969 s. The original Paper
acquired the durable association for its correct 12-page publisher PDF of
4,834,002 bytes in 21.055–21.441 s. Earlier paired results and failures are
preserved. This control is recorded separately from paired scores.

An earlier new-order Zotero Save opened a checkbox window that later
disappeared. The original local parent had zero attachments when rechecked,
and the user requested a fresh trial. This click is retained as a non-scoring
diagnostic with unknown product terminal. The installed Connector's monitor
uses a 60 s default and closes the popup after settlement, so window closure
alone supplies no attachment outcome. The subsequent fresh Zotero Save in
F27-5 imported the 12-page publisher PDF after user verification in its own
attachment window. Allfold took 37.464–37.811 s and Zotero took 26.725–27.021 s.
The assisted total difference is +10.443 to +11.086 s and the ratio is
1.3865–1.4148. The duration of the human step alone is unknown.

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

For F23, normal PubsOnline pages for the exact DOI showed Request Access and
abstracts in both products. The separate EBSCO sessions independently reached
the matching record and PDF entry on Business Source Complete. Chrome's
normal record detail automatically rendered the publisher first page and a
29-page PDF viewer before Save. The operator used the normal article-detail
Translator action. The embedded body is a recorded preparation difference.

On `989ad81`, Allfold's PubsOnline P4 response took 1.435 s and returned
`access-authorization`. Document extraction took 5.583 s. P5 streamed the
linked arXiv 2205.09823v2 and saved it in 23.839–24.204 s. The actual 34-page
file is 9,493,072 bytes. Its earlier title and all four authors match the
Paper's explicit related arXiv record. Zotero saved and associated the 29-page
publisher PDF from EBSCO in 12.508–12.927 s (2,996,661 bytes). The exact title
and DOI were verified. Both had actual local PDFs. The versions and browser
warmth differ, so this is a source attainment result with no transfer ratio.

F24 reproduced the source difference. The independently authorized Business
Source Complete record displayed the target DOI in both products. The first
Zotero click in the same EBSCO SPA tab surfaced F23's old saved session. That
click is retained as an excluded preparation observation. A new ordinary tab
produced the real F24 save. Its normal detail embedded the 39-page publisher
Just Accepted PDF before the click. The actual file and parent arrived in
7.971–8.319 s (1,762,961 bytes), with accurate DOI, title and Just Accepted stamp.
The F24 PubsOnline P4 request took 1.480 s and reported `access-authorization`.
Allfold performed a 5.817 s Article extraction, then saved the confirmed related
arXiv 2502.16659v1 in 11.048–11.403 s (48 pages, 1,441,301 bytes). The normal
source sequence did not enter EBSCO. The different versions and browser
preparation are recorded without a paired transfer score.

F25's ordinary EBSCO DOI and exact-title searches returned no exact initial
record in Allfold. PubsOnline showed the exact Just Accepted article and a View
PDF entry in both products. There was no marked OA or verified PDF access before
the pair. Allfold recorded `access-authorization` without a file in
4.379–4.747 s. Zotero Atypon Journals saved the exact parent in the trial
collection. Its popup displayed Full Text PDF and Saving is complete, but the
parent still had zero children at the check 615.633 s after click. This is a
missing local PDF at the common 600 s horizon. The action was not manually
canceled and no precise internal attachment error time was observed.

Allfold's observed Download path did not discover the licensed EBSCO record.
The installed EBSCO Discovery Layer Translator (`660fcf3e-3414-41b8-97a5-e672fc2e491d`,
revision 2026-10-01 19:50:00) starts with a loaded EBSCO record and profile,
reads its download links, and passes the attachment to Zotero. Its exact branch
for F23 was unobserved. EBSCO's entitlement API uses separately provisioned
client credentials and a profile token. The established browser session alone
does not establish API access. The configured EBSCO Service uses the generic
EBSCOhost root through CARSI. EBSCO documents browser outbound search from
an already identified institutional profile. [EBSCO API authentication](https://developer.ebsco.com/entitlement-api/docs/use-the-client-credentials-grant) · [EBSCO profile search](https://connect.ebsco.com/s/article/Stacks-Outbound-Searches-to-the-New-EDS?language=en_US)

On 18 November, the retained EBSCO target in the real Allfold Session
(`10e5038`) opened after the user restored institutional access. A normal
profile-scoped DOI lookup yielded the exact F23 and F24 records on Business
Source Complete. The vendor's record links led to the F23 29-page publisher
PDF and the F24 Just Accepted manuscript. F23's normal viewer download reached
the system Save As dialog. The dialog closed during destination selection,
and no new file was observed at either candidate destination. This was a
Browser diagnostic before any new Paper Download or Zotero Save. The precise
attachment request, native save completion, and Paper association remain
unverified. No pairing time or EBSCO source fix is attributed to this diagnostic.

On 19 November, a separate F23 Browser diagnostic completed the normal
EBSCO viewer download and native Save As. The newly saved publication
matches the exact title, DOI and journal. It has 29 pages and 2,996,661 bytes,
the same page count and byte count as the earlier verified Zotero copy. That
file and its action timestamps are retained privately outside the Workspace.
The diagnostic establishes access and native file saving from the configured
EBSCO resource. Ordinary Paper Download still requires a verified source
handoff and the original Paper association. This run is outside the paired
results.

One later viewer reload with normal cache settings recorded a GET 200 PDF
response from `content.ebscohost.com/cds/retrieve`. The response had
2,996,661 resource bytes and was delivered over the network. DevTools showed
an application/PDF worker stack as its initiator and did not establish
which upstream response supplies the request URL. This identifies the actual
binary host and route in the authorized viewer. A Paper Download adapter
still needs evidence for the record-to-URL handoff under the saved Service.

A later diagnostic followed the viewer's **Back to details** link to the
exact F23 record and clicked its ordinary PDF entry. Network displayed a
200 GET to the record PDF endpoint on `research.ebsco.com` and two 200 PDF
responses on `content.ebscohost.com`, each reporting 2,996,661 resource
bytes. The trace associates both request families with the visible record
flow. The record response that would establish the URL handoff is still
unverified.

An additional sanitized HAR export was followed by an Allfold bridge
disconnection alert. The file was initially empty and later contained two
PDF responses, with the upstream record response absent. The diagnostics
export returned HTTP 409 while disconnected. The source application was
normally restarted on the same production code and configuration. The
Workspace remained intact. The cause of the disconnection is unknown. Both
observations were Browser diagnostics with no timed save, Paper Download,
or new Paper association.

The same resumption verified Oxford F10 on both article pages before a new
PDF action. Allfold's Oxford Service page recovered from a Cloudflare check
automatically, 21.044 s after the Solver started. Chrome's separate Oxford
institutional transition returned a supplier server error. F10 is Open Access
and loaded in a fresh normal Chrome tab through its public article entry, with
the Silverchair Translator identified. Both PDF endpoints remain to be tested
in this repeat. Springer F05's Chrome article showed Open Access and full
text after selecting Springer in CARSI. Allfold's separate portal then showed
an inactivity prompt, holding the next actions before either click.

On 19 November the actual Source application restarted on `10e5038` after
an interruption. Both products could reach the same Oxford F10 OA article
after automatic page verification. For further timed pairs, the user
requires the matching CARSI Service and actual institutional access to be
checked independently in Chrome and Allfold, including for an OA article.
Chrome's Oxford resource search displayed the CARSI inactivity prompt. The
public article preparation produced no new Download or Connector Save.

For F10-2, both products subsequently entered Oxford Journals from their
independent CARSI resource pages. The Oxford Account menu explicitly showed
the configured institutional account in each application. The Allfold Workflow
card still showed Not prepared, while the manually prepared Browser Session
held the institution access. Both article pages offered a PDF entry and the
Chrome Connector identified Silverchair. Preparation stopped at the HTML article
and its visible PDF entry in each product. Login and challenge preparation are
kept separate from the two clicks and have incomplete time bounds.

Allfold P2/API02 observed the Oxford response in 1.126 s then streamed the
publisher PDF through the observed Silverchair watermark endpoint in 4.539 s.
The latter included 1.928 s to the response and first byte. The 12-page,
1,794,823-byte local file had the exact title, DOI and journal. The verified
original Paper link and file arrived in 5.523–5.886 s. The ordinary Zotero Save
showed the dedicated collection, then its popup disappeared. No new matching
parent or local PDF was observed over 600 s. The internal terminal reason is
unknown. The original F10-1 Allfold failure is retained. Access preparation and
tested code both differed, so this observation cannot isolate a code-only gain.

F08-2 exchanged the original order and independently verified the institution
and exact article in both Oxford sessions before either click. The original
Paper previously held the related 61-page preprint. Its new, verified publisher
PDF has 19 pages and 762,331 bytes. The original Paper acquired it in
30.521–30.870 s. Both access conditions and the application version differed
from F08-1.

Two API02 response operations took 0.280 and 0.097 s. The subsequent owned
recovery operations took 13.726 and 0.425 s. The Solver clicked the verification
control automatically. The next navigation reported `ERR_BLOCKED_BY_CLIENT`,
and the Solver was canceled as the page closed. There was no human intervention
during Download. An article clue navigation then took 11.688 s. R020 recorded
two responses taking 0.470 and 0.716 s, followed by the closed PDF stream from
`watermark02.silverchair.com` in 2.850 s, with first byte at 1.320 s.

The temporary verification view limits main-frame requests to original-origin
GETs. Ordinary Session streaming handles observed cross-origin redirects
through a separate validated request. The live trace lacks the blocked
request's method and origin relation, leaving the precise cancellation cause
open. The installed Silverchair translator (2026-08-10 21:08:51) reads the
article's PDF link. The F08 Zotero Save showed the dedicated collection, then
the popup closed. No new local parent or attachment was observed at 654.823 s.
There is no paired same-version timing point.

F09-2 likewise reversed the original order after independent checks of the
configured institution and exact Oxford article. The normal Zotero Save
showed the dedicated collection before the popup closed. No new local parent
or PDF was observed at 635.785 s. Allfold then acquired the correct 26-page,
2,088,108-byte publication on the original Paper in 54.554–54.897 s. The
original F09-1 download had saved the related 24-page preprint.

An initial API02 response took 0.894 s. Its recovery view then took 43.589 s.
The Solver clicked automatically 31.345 s after it started. Two subsequent
navigations reported `ERR_BLOCKED_BY_CLIENT` before the view closed. R020
then observed four responses in 0.909, 0.799, 0.837 and 3.501 s. One of those
responses was from the publisher's institutional identity service. The PDF
came from the Silverchair watermark endpoint in 4.025 s, first byte at
1.482 s and closed writer at 4.024 s. No human intervention was required
during Download. The repeated symptom warrants distinguishing the blocked
request's method and origin relation before changing the guard or source
order.

In a separate Allfold-only F09 diagnostic, a temporary observation added the
method and origin relation to any main-frame stop without changing navigation
policy. A fresh independent CARSI entry confirmed the institution and exact
article. The existing 26-page, 2,088,108-byte publisher file was removed using
the product controls, and the same Paper was restored for a new Download.
The newly saved file matched the title, DOI and publication. The verified local
file and Paper association completed in 5.332–5.680 s. P2/API02 took 0.655 s
to respond and the final stream took 4.863 s, with first byte at 2.619 s.

The diagnostic went directly to the PDF and never opened a verification view.
It recorded no client-side block or guard stop. The two earlier blocks remain
unexplained. This repeat adds no paired timing point. The observation was
removed, and the regular source build restarted with the same Workspace.

An additional non-scoring Oxford diagnostic used the untouched Workspace Paper
`10.1093/jrsssa/qnag123`, in the same journal as F09. The explicit institutional
account and exact article with the PDF option were verified before Download.
The `c9fbf52` build with the guard observer linked the correct 19-page,
731,000-byte publisher PDF in **3.600–3.949 s**. API02 returned a response in
0.560 s and finished the Session stream in 3.048 s, with first byte at 1.911 s.
There was no verifier navigation or guard stop.

For the original F08 (`10.1093/biomet/asag050`), the user completed institutional
sign-in in Allfold's fresh Browser Session before measurement. Oxford showed the
configured institution, the exact article and its PDF option after entry through
CARSI. The previously confirmed 19-page, 762,331-byte trial file was deleted
through Trash and the same Paper was restored as a Candidate with no body.

A single Download in the observation build, with production behavior from
`c9fbf52`, saved and linked the matching 19-page, 762,338-byte Oxford publisher
PDF in **4.531–4.885 s**. The initial P2/API02 response took 0.649 s. The final
Session stream took 3.999 s, including 2.277 s to its first byte. The durable
file and original Paper association were independently verified. The action
needed no human intervention. It did not open a verification view or record a
guard stop. F08-2 and F09-2 retain their earlier blocks and recovery timings.
The method and origin of those blocked requests and Oxford's same-edition
paired timing remain unconfirmed. The F08 diagnostic adds no paired timing point.
After the evidence export, the normal source build reopened the same Workspace.

At `989ad81`, PR run 44211591848 failed in the existing Workspace lifecycle
fixture. The local field read lacked a `revision` before its response status
was checked. Twelve isolated local repetitions passed, and the runner did not
retain the failed HTTP response. The fixture now explicitly waits for the
captured Paper collection to settle before its separate local read/edit phase
and asserts the HTTP status. Production code was unchanged. That fixture no
longer covered field reads during an active collection.
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
| F11-3 / A→Z | T&F institutional publisher Accepted Manuscript, 27 pages, 1,251,963 bytes | 4.707–5.064 s | 4.244–4.534 s | +0.173 to +0.820 s | 1.0382–1.1932 |
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

For the three Springer OA control repeats of **F03**, interval median waits are
2.598–2.952s(Allfold) and1.717–2.109s(Zotero), median paired difference
+0.489 to+1.235s, median ratio1.2319–1.6079. Raw wait ranges are0.597–4.256s
and0.734–2.960s respectively. Two slower points exceed measurement precision;
the third overlaps. This is insufficient to claim parity or isolate a cause.
Cambridge has n=3 corrected repeats of one Paper: median waits1.968–2.320s
and3.513–3.887s, median paired difference−1.570 to−0.835s and ratio0.5961–0.7623;
raw wait ranges1.565–2.678s and2.148–4.667s. No slower point was observed in
that control. The two T&F institutional points favor opposite products. The
T&F OA stratum has one comparable point, so dispersion remains unknown. No
pooled daily-load average, p95, tolerance
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

For F05-2, both Springer pages confirmed institutional access and the OA
article before the clicks. Allfold took 18.619–18.978 s and Zotero took
18.792–19.113 s. Each local copy spans 29 pages and 7,842,498 bytes, with
title, DOI and the item association verified. Allfold used one R001 stream
and reached the first byte at 1.986 s from its native start. The writer
closed at 18.760 s. Zotero's parent was first observed well before its
imported PDF. The wait difference is −0.494 to +0.186 s and the ratio
0.9742–1.0099. The earlier F03 slower points remain in the record.

The 18 November resumption plan designated F04-4 as a supplemental repeat in
the reverse order before either new click. Both products reused their
independently authenticated Springer Link sessions from F05-2 and verified
institutional access on the F04 article itself. Both new files contain the same
57-page published version and each has 5,103,901 bytes. Allfold took
10.889–11.240 s and Zotero took
11.140–11.612 s. The paired difference is −0.723 to +0.100 s and the ratio
0.9377–1.0090. Allfold used one R001 stream, with first bytes at 4.358 s
and the writer closed at 10.938 s after native start. Both products' temporary
cache state remains unobserved. The two independent current inputs expand the
Springer measurements while preserving the slower F03 points and original
load-affected F04 and F05 observations.

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

F16-3 used the preplanned Zotero-first order after both sessions independently
entered Wiley from CARSI and displayed the institution, exact article, and PDF
entry. Allfold had restarted with the same production code after the diagnostic
interruption. Its product handled a Wiley verification during preparation. The
Chrome portal required the user's login before publisher access was reverified.
Neither leg preopened the PDF.

The normal Zotero action reported a Wiley Translator error and tried Embedded
Metadata. A correct new parent, including its DOI, appeared in the acceptance
collection. The popup listed a PDF, and the parent still had zero children at
the 631.093 s check. The observation horizon was 600 s, and internal terminal
time is unknown. Allfold then saved and associated the correct 15-page,
2,195,129-byte Wiley PDF in 7.079–7.434 s. One P1/R002 stream took 7.125 s, with
headers at 2.228 s, first byte at 2.229 s, and the closed writer at 7.123 s. No
comparable time difference or ratio is available for this repeat.

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
to code.

F13-2 used the preplanned Zotero-first order. Each product independently entered
Taylor & Francis from CARSI and showed the configured institution and PDF entry
on the exact article. Chrome required human verification during preparation.
No PDF was preopened. The normal Connector action first reported errors from
Taylor and Francis+NEJM and Atypon Journals, then tried Embedded Metadata. The
new local parent matched the title and article URL, lacked a DOI field, and still
had zero children at the 618.123 s check. The observation horizon was 600 s and
the internal terminal time is unknown.

After completing that observation, Allfold saved and associated the correct
34-page, 1,730,524-byte publisher Accepted Manuscript in 3.789–4.141 s. The
original Paper had been restored after deleting its earlier trial body. One
P1/R003 stream ran for 3.860 s, with headers at 1.973 s, first byte at 1.977 s
and the closed writer at 3.859 s. The two products yielded no comparable
same-version timing point on this repeat. F13-1's +0.497 to +1.236 s difference
remains in the table.

F13-3 exchanged the order again. Both products independently confirmed the
institution and exact full article after entering Taylor & Francis from CARSI.
The Allfold login and a separate Chrome publisher check required the user
during preparation. Neither PDF was previewed. The original Allfold Paper
was restored without its previous trial body and saved the verified 34-page,
1,730,524-byte publisher manuscript again in 4.388–4.739 s. One P1/R003 stream
took 4.498 s, with first byte at 2.717 s. The Zotero Save created a matching
local parent in the dedicated collection and it still had zero children at
653.400 s. The entry translator was visible in the toolbar. Its actual
execution path and terminal state are unknown. The two repeats verify
Allfold's publisher save after preparation but leave F13's original comparable
timing difference without a second comparable point.

The preselected F11-3 control used Allfold first. Chrome's retained article
initially showed Get Access. Re-entering from its own CARSI T&F resource
restored the institution. The restarted Allfold instance separately selected
T&F and completed publisher verification through its normal Solver. Both
exact articles displayed full text and their PDF entry before the two clicks.
Both saved and associated the same publisher Accepted Manuscript, 27 pages
and 1,251,963 bytes. The bounds and earlier opposite result are shown above.

F11-3 Allfold used one P1/R003 stream. It lasted 4.865 s, with the response and
first byte at 1.847 s and the closed writer at 4.864 s. The locally installed
`Taylor and Francis+NEJM` translator (2026-11-04 17:14:59) uses the same T&F
DOI PDF entry after its citation request. The test did not capture Zotero's
response and first-byte phases or either side's PDF cache flags.

F11-4 reversed the prior control order with Zotero first. Each product reused
its independently entered CARSI Taylor & Francis session and reverified the
institution and exact full article. A human completed the Chrome article
check during preparation, and neither PDF was previewed. Zotero showed
errors from Taylor and Francis+NEJM and Atypon Journals, then attempted Embedded
Metadata. The new local parent matched the title and article URL and lacked
a DOI field. It still had zero children at 625.26 s. The internal terminal
state is unknown.

After the Zotero observation, Allfold rechecked the exact article's rights
and automatically saved the 27-page, 1,251,963-byte publisher Accepted
Manuscript to the restored original Paper. The verified local file and
association took 3.798–4.149 s. One P1/R003 stream ran for 3.809 s, with first
byte at 1.825 s and the writer closed at 3.807 s. The completed control adds
no same-version timing point. The F11-2 and F11-3 timing differences remain
opposite, and publisher-level timing parity remains unconfirmed.

F12-2 reused the separately prepared T&F sessions and reverified the exact
institutional article on both. It used Allfold first, reversing F12-1's
interrupted order. The original Paper acquired the correct 35-page,
1,339,711-byte publisher Accepted Manuscript in 2.188–2.548 s through one
P1/R003 stream. The native request took 2.242 s, with the response and first
byte at 1.544 s and the closed writer at 2.241 s.

Zotero's new parent in the trial collection matched the title and the article
URL with its DOI. The DOI field was blank. Neither the save popup nor the
Translator stages were observed. The parent still had zero children at the
628.717 s check. The 600 s observation horizon is recorded separately from
the unknown internal terminal time. The repeat yields no comparable time
difference or ratio.

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

## Historical implementation checkpoints

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
added. That full PR Safety run passed in about 5 min 50 s. Its Electron step
took about 3 min 24 s. The runner also reported a macOS arm64 capacity notice.

At `e9bbacb`, the PR [Safety run 44231010339](https://github.com/dylaaan-booob/allfold/actions/runs/44231010339/job/134555758506)
passed JavaScript and Python. Electron passed 253 checks and failed the
isolated Document Date/Abstract fixture during page load, before the date
assertion. Its expected-success operation had a four-second synthetic deadline
inside the separately bounded fixture process. These operations now use the
normal task budget inside the same 85-second subprocess and 90-second test
limits. The focused native fixture passed locally. The existing extraction,
cancellation, page closure and snapshot assertions still run.
At `568534c` all three local checks passed, including 1,672 Python and 254
Electron checks. The complete associated PR
[Safety run 44233215459](https://github.com/dylaaan-booob/allfold/actions/runs/44233215459/job/134563028600)
also passed. Newer commits require their own PR check.

The diagnostic-only `976015c` passed JavaScript and Python in its associated
[Safety run 44235173287](https://github.com/dylaaan-booob/allfold/actions/runs/44235173287/job/134569445454).
Electron completed 253 tests. The isolated body-stream process reached its
existing 60 s deadline after the last logged `disk-flush` case, ahead of the
`slow-writer` terminal. The runner captured no internal error for that wait.
The fixture now surfaces an uncaught timer assertion directly to the runner.
The focused body-stream fixture passed locally with the same assertions and limits.

The Reader repair at `e4edc0a` passed the three full local checks. The
`10e5038` follow-up passed JavaScript syntax and 26 affected Electron checks,
including the native replacement-navigation regression. Its complete
[PR Safety run 44237650306](https://github.com/dylaaan-booob/allfold/actions/runs/44237650306/job/134577573323)
passed all three required steps. This is the production code launched for
the pending real retest.

The evidence-only head `7ba2285` failed in the isolated body-stream fixture.
Its held writer check capped the Node stream at three `data` events, even
though the native response can arrive in smaller fragments. An isolated
reproduction produced 17 events and 917,389 consumed bytes while the fixture
server had supplied 5,570,560 bytes. The old assertion failed. With the same
fragmented input the actual Node reader was paused with unread response data
and the fixture passed. The normal fixture also passed. A separate mutation
that resumed the held reader failed the new pause assertion. The fixture
continues to check the real writer boundary, incomplete read and durable
completion. The production Session and save code are identical to the versions
used for the F10, F05 and F04 retests. [Failed PR run](https://github.com/dylaaan-booob/allfold/actions/runs/44451059772/job/135314807811)

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

An isolated check with the same Electron 45.0.0 / Chromium 156.0.8078.48 used
the existing controlled Session fetch and a loopback HTTP server. Each size
used two ordinary GETs to the same fresh URL with `private, max-age=600`. The
in-memory Session's second GET was a cache hit at 487,337 and 3,814,861 bytes.
At the observed F19 size of 11,471,779 bytes, both GETs reached the server and
the completed events reported `fromCache: false` twice. A separate, temporary
disk-backed Session hit its cache on the three repeats. This reproduces the
cache-capacity difference independently of the publisher and agrees with the
live F19 network counters. The local fixture did not use a publisher response,
the user's browser profile or its Workspace. The smaller first-request gaps and
the first F19 transfer difference remain unexplained by this warm-cache result.
Allfold's Session storage behavior remains as tested in the live pairs.

The isolated check was repeated with `--disk-cache-size=268435456` in a fresh
temporary profile. The large in-memory entry still produced two server hits
and two `fromCache: false` events. The temporary disk-backed control made one
server request and hit its cache on the repeat. This rules out raising the disk
cache budget as a fix for the existing in-memory Session. In the initial F19
pair, Allfold spent 38.924 s after first byte and its total wait exceeded
Zotero's by 12.930–13.785 s. The first-transfer variation remains unexplained.
F19 remains a recorded large-file timing limitation.

The installed `Atypon Journals` Translator (last updated 25 October 2022)
builds an attachment from a PDF link on the loaded article. Five verified
local Zotero attachments across F17 to F19 stored the SIAM `/doi/pdf/` route,
the same route family used by Allfold P1/R039. Allfold dispatched in 7–12 ms
on the corresponding direct path. The measured F19 interval after first byte
was 38.924 s initially, 24.533 s following renewed access, and 20.108 s on the
warm repeat. The existing timings and network counters locate the slowdown in
body transfer on these observations. The reason for the first-transfer
variation remains open.

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

## EBSCO prepared-profile repair

F23-1 and F24-1 saved verified related arXiv versions after publisher access
was denied. Independent EBSCO Business Source Complete access was available
for both originals, and Zotero saved the 29-page publication and the 39-page
publisher Just Accepted manuscript, respectively. The prior Allfold discovery
sequence did not use the Paper's assigned EBSCO Service.

Production `f30bb8c` searches the prepared profile by the original DOI after
publisher sources fail and before OpenAlex. It verifies the record and uses its
actual PDF Viewer link. The task prevents automatic preview transfers while the
verified Viewer supplies the GET for the current Session stream. The isolated
public Download regression observes one licensed body GET and verifies the
published file and original SQLite association. A separate check covers the
independent preprint fallback after an unavailable EBSCO source. The associated
[full PR check](https://github.com/dylaaan-booob/allfold/actions/runs/44496676668/job/135465520919)
and all three local suites passed on the repair.

For the repair retest, both products independently used the current institution
EBSCO resource and reached the exact Business Source Complete records for F23
and F24. Both articles displayed the DOI and PDF link. The ordinary details
pages load an embedded PDF automatically. Title and DOI appeared in Allfold's
F24 embed, and the actual PDF Viewer link was observed. Treat this preparation
as potentially warm even though the operator did not click a PDF link.

The planned order is F23 Zotero → Allfold and F24 Allfold → Zotero. F23's new
normal Zotero save imported and associated the matching 29-page, 2,996,661-byte
publisher PDF in **16.778–17.091 s**. After confirmation, the old Allfold trial
body was deleted in Trash and the same original Paper was restored. The
Allfold Download still saved the related arXiv 2205.09823v2, 34 pages and
9,493,072 bytes, in **158.501–158.867 s**. Its first publisher request was
denied after 1.524 s. The generic article refresh took 33.261 s. The first
managed EBSCO search navigation timed out after 85.090 s. The P5 stream then
took 35.405 s. The publication gap persists. The body versions and the
eleven-minute gap between clicks preclude a scored timing comparison.

A separate ordinary new Allfold tab submitted the same F23 search in the same
Session. It showed the exact licensed match within the 22.632 s observation
window. The control established that the query and institution access worked
in the same Session. The exact stall of the managed navigation remains
undetermined.

F24 Allfold saved the verified arXiv 2502.16659v1, 48 pages and 1,441,301 bytes,
in **156.809–157.156 s**. The publisher body was refused after 2.552 s and the
generic article refresh took 9.312 s. The EBSCO search and record navigations
reached HTTP 200. The record remained in the entry lookup for another 85.002 s
before fallback. The Viewer was never opened. Zotero then saved and associated
the 39-page Just Accepted manuscript, 1,762,961 bytes, in **8.059–8.359 s**.
The two files have different editions and supply no transfer comparison.

F24's visible EBSCO PDF link had an accessible name containing the article
title, beyond the earlier code's accepted bare labels. The follow-up uses a
visible Viewer link whose origin, profile and record match the verified current
record. The isolated browser regression also reproduces a ready search page
held by a pending image. The search now proceeds from a committed main document
after access checks, and drains any remaining page load before navigation to
the record. Another regression verifies that an expired sign-in page still
refuses the source. After a confirmed publisher refusal, the assigned EBSCO
source now runs before the publisher article refresh. Both original Papers need
another real retest to validate these changes. The Workspace is retained.

F24-3 on `4d8c045` reached HTTP 200 in the managed search. Its next read
failed with `document_changed` before it opened the record. It saved the
verified preprint on the original Paper in **125.223–125.586 s**. The
independent Zotero save obtained the same 39-page Just Accepted manuscript in
**8.790–9.109 s**. The original publisher body path also presented a
Cloudflare page. The Solver did not find a checkbox and was canceled after a
navigation returned `ERR_BLOCKED_BY_CLIENT`. The exact blocked request remains
unverified. A generic publisher article refresh then took 60.538 s, before
the EBSCO search attempted its own access path.

The next repair retries a concurrent in-page update only while the same
qualified search Document remains current. This is a local read retry. The
original search request is sent once. A replaced main document continues to
refuse the source. After the publisher challenge handling settles, the prepared
EBSCO path can run before the extra publisher refresh. The licensed outputs on
both originals require further live evidence.

F23-3 ran on `4d9b342` after the exact Business Source Complete record and
the institutional PDF entry were confirmed in both independent sessions.
Allfold reached the managed search results and opened the record. The record
navigation waited **85.071 s** including cleanup and timed out before the
Viewer was opened. The publisher candidate had also spent **41.553 s** in
verification recovery, where the Solver started and a subsequent main-frame
navigation returned `ERR_BLOCKED_BY_CLIENT`. The exact blocked request and the
EBSCO record's load state at the deadline were not observed. The final P5
stream took **113.934 s**. Allfold saved and associated the verified 34-page,
9,493,072-byte preprint in **308.240–308.625 s**.

The next Zotero Save imported and associated the 29-page, 2,996,661-byte
publisher PDF in **20.217–20.749 s**. The file's title and DOI matched and the
new parent was in the dedicated local collection. Neither product required
user input during its measured action. The different editions preclude a
timing comparison. The `4d9b342` results of `npm --prefix electron run check`
(65 files), `uv run --locked pytest` (1,677 passed, two existing warnings), and
`npm --prefix electron test` (254 passed, zero skips) were verified locally
and the linked PR check ran all three commands successfully.
[Safety checks on 4d9b342](https://github.com/dylaaan-booob/allfold/actions/runs/44525339637/job/135564282577)

A separate Browser observation opened the same F23 details address in a new
tab within the verified EBSCO Session. It was still loading after about
127.5 s, with no title, DOI, PDF entry or access message. The tab was closed
normally and the original institutional details tab was retained. In that
tab, the site's Back to results control returned to the unique F23 result.
One follow-up click on the title did not visibly open the details. These
observations reproduce the direct-navigation stall and leave the exact
site-side cause open. Neither action started a PDF save.

After renewed access on `67e731d`, the normal Browser reached the institutional
F23 details by following the unique result's title. The first detail
snapshot after the usual ten-second observation wait showed the exact DOI
and a PDF entry. This preparation had no instrumented click timestamp.

The isolated Electron regression models a qualified search whose record link
works through the site's in-page navigation while a separate document GET
stalls. It first failed at `page_load` and passed after the browser followed
the verified search result link. The action checks the same current search
Document and same title before dispatch. The record still has to match the
original DOI and provide its own PDF Viewer entry. This fixture checks a
navigation mechanism. Live licensed saves still require evidence from both
originals.

The `67e731d` PR run passed JavaScript checking, pytest and the EBSCO Electron
case. A native presentation fixture failed at its immediate page-switch
assertion. The fixture now waits within its existing readiness window for
Main to select the expected Page after real mouse input. It also waits for
selection on the return click. The focused macOS fixture passed with both
checks. [Failed PR run](https://github.com/dylaaan-booob/allfold/actions/runs/44536159519/job/135602012670)

The test and report update at `edbfd6f` passed all three required commands
in the PR workflow. The production build used in F23-4 was `67e731d`.
[Full PR check at edbfd6f](https://github.com/dylaaan-booob/allfold/actions/runs/44542831504/job/135625444903)

F23-4 Zotero saved and associated the verified 29-page publisher PDF in
**34.353–34.702 s**. The paired Allfold Download crossed the institution
search and verified the record before it opened the Viewer. The record step
before Viewer navigation took 1.776 s. About 83.227 s after Viewer navigation
began, the source ended at `page_load` timeout. The trace contains a canceled
Viewer XHR and a font request that was still pending at cleanup. The relation
of the canceled XHR to the PDF handoff remains unknown.
Allfold associated the prior 34-page preprint again in **293.834–294.191 s**.
The direct publisher verification had also taken 35.443 s before another
client-side block. The products again saved different editions.

The next Electron regression adds a pending asset to that same Viewer. It
reproduced a `page_load` timeout after the Viewer GET. It passes when the
source uses the committed Viewer Document and waits for the attributable PDF
request within the original deadline. The normal Session stream owns the
body save.

F24-4 ran on `148adcc` after separate confirmation of the exact institutional
EBSCO record and PDF entry in both sessions. The approved old preprint was
removed and the original Paper was restored. Allfold linked the 39-page,
1,762,961-byte INFORMS Just Accepted manuscript in **57.855–58.219 s**. Zotero
then saved the same manuscript from a new detail tab in **12.763–13.143 s**.
Title, DOI, the two local associations and SHA-256 equality were verified.
Neither measured action needed intervention.

The direct Allfold publisher request took 0.940 s. Its verification recovery
took 35.081 s and ended after a navigation reported `ERR_BLOCKED_BY_CLIENT`.
The prepared EBSCO search, exact record and Viewer returned the attributable
request in 14.780 s. The R073 stream finished in 6.912 s, including 2.050 s to
first byte. The save verifies the Viewer handoff on F24. The paired wait still
favors Zotero by **44.712–45.456 s**, and the stage timings identify publisher
verification as the largest cost. The same production revision passed the
three required commands in the PR-associated run.
[Safety checks on 148adcc](https://github.com/dylaaan-booob/allfold/actions/runs/44548632128/job/135645967969)

F23-5 used the same production revision. Both sessions independently showed
the licensed EBSCO record and its PDF entry. No manual PDF preview preceded
the pair. Allfold linked the 29-page, 2,996,661-byte publisher PDF to the
restored original Paper in **41.643–42.003 s**. Zotero linked the identical
file to its new parent in **18.138–18.445 s**. Title, DOI, both local
associations and SHA-256 equality were verified. Both actions were automatic.
The paired wait favored Zotero by **23.198–23.865 s** (Allfold/Zotero
**2.2577–2.3157**).

The P4 publisher request returned an authorization response after 1.548 s,
and no publisher Reader recovery started. EBSCO search, record and Viewer
discovery took 25.171 s. The search reached the ready Document after 17.494 s.
The Session stream took 14.904 s, including 11.285 s to first byte. The
Connector's internal stage times were unavailable. This pair confirmed that
the Viewer timeout no longer forces F23 to its preprint, and also measured a
wait difference on a run without publisher recovery.

The measured publisher-recovery cost prompted a scheduling change. A
publisher challenge can defer its Reader while the existing qualified direct
entries run. If those entries yield no body, the assigned, prepared EBSCO
source gets one attempt before publisher recovery. If EBSCO is unavailable
or its transfer fails, the suspended publisher Reader resumes in its original
turn. Each attempt keeps its own Service scope, and a successful stream still
publishes to the original Paper.

The isolated discovery cases reproduced publisher recovery running before
EBSCO and now cover EBSCO success, failed transfer, an unprepared Service and
a successful earlier direct entry. Standards review found a case where the
new suspension could reorder two publisher Readers when EBSCO was unavailable.
The added regression reproduced that ordering and verifies the original turn
after the correction. Spec review confirmed the Service, Session and Paper
boundaries. At `c9fbf52`, the local JavaScript check, 1,682 Python tests and
254 Electron tests passed. The PR's full Safety checks passed on that revision.
[Safety checks on c9fbf52](https://github.com/dylaaan-booob/allfold/actions/runs/44565268319/job/135705175164)

F24-5 on `c9fbf52` exchanged the order after both EBSCO resource entries and
exact article permissions were confirmed again. Zotero first linked its new
39-page, 1,762,961-byte Just Accepted attachment in **10.129–10.484 s**.
Allfold linked the identical file to the restored original Paper in
**30.607–30.950 s**. Both actions were automatic. Title, DOI, parent and
SHA-256 equality were verified. Allfold remained **20.123–20.821 s** slower.

The first Allfold P4 request took 2.210 s and returned `access-authorization`.
There was no publisher Reader recovery to defer. The assigned EBSCO search,
record and Viewer took 22.658 s. The Viewer supplied the attributable request
within the 11.308 s from its Document becoming ready until Page release.
The R073 stream took 5.647 s,
including 2.055 s to first byte. F24's user wait decreased by 26.905–27.612 s
from F24-4 under the observed conditions. The publisher returned different
access responses in the two runs, leaving the scheduling change's live
effect unverified. Matched local licensed saving is verified on both originals,
and the EBSCO latency disadvantage remains.

The untouched mechanism supplement R073-Fresh-1 is **Fair Congested Assignment**
(DOI `10.1287/moor.2024.0581`). One restricted OpenAlex Discover produced the
original Paper and completed collection. Its title and EBSCO PDF entry were
verified in each institutional session without manually previewing the PDF.
The sample and its A→Z order were frozen before either timed action. The
original Discover inputs were restored. The running build retained the
`c9fbf52` request and saving behavior with a read-only Oxford navigation
observer. The publisher response here did not enter that observation path.

Both products saved the same **20-page, 3,007,508-byte** publisher PDF. Allfold
linked it to the collected Paper in **17.645–17.990 s**. Zotero linked it to
the new parent in **7.498–7.832 s**. Each local file matched the expected title
and DOI, and SHA-256 equality was verified. The pair had no human intervention.
The separate mechanism cohort records a difference of **+9.813 to +10.492 s**
and a ratio of **2.2529–2.3993**.

The initial publisher request returned an authorization denial in 1.379 s.
The prepared EBSCO search, exact record and Viewer took 11.751 s. R073 streamed
the verified file in 4.481 s, with first byte at 2.166 s. No publisher recovery
was needed. The path succeeded on the untouched Paper ahead of the available
repository alternative. Its delay confirms that a portion of the EBSCO
user-wait gap exists even when publisher recovery never starts.

The installed `EBSCO Discovery Layer` Translator (last updated 1 October
2026) starts from the already loaded record and can resolve its authorized PDF
through the details response and a download-link lookup. It also requests RIS
for Zotero's new parent item. The four verified Zotero attachments stored
the EBSCO content-delivery route. Connector 5.0.217 passes its resolved
attachment URL to Desktop 10.0.9, which imports the stream under that parent.
The full live resolver sequence was unavailable. The installed direct
resolution mechanism does not require mounting the Viewer Document. Allfold's
normal starting state has the collected Paper and DOI. Through `c9fbf52` it
spent 11.751–25.171 s finding the exact EBSCO record and handing off from the
Viewer in the verified samples. For example, F24-5 spent 22.658 s through the
Viewer handoff and another 5.647 s in the Session stream. The samples measure
the normal product actions from their respective starting states.

The attempt to open the record address directly stalled in the authorized
Browser Session. Following the verified result link and moving the Viewer
handoff ahead of unrelated page assets restored licensed saving. The source
ordering change also covers the earlier publisher verification wait in isolated
regressions. A direct PDF lookup after the same exact record match could reduce
the remaining discovery cost. The installed Translator's internal lookup was
not verified through Allfold's prepared Session in those measurements. That
revision used the observed, attributable Viewer request.

### EBSCO details-link follow-up

The user reached a Business Source Complete record for DOI
`10.1287/ijoc.2024.0765` by searching for the article title and saved it from
the EBSCO details page without opening the PDF Viewer. The Zotero Desktop
Local API and actual storage confirmed a 4,846,719-byte imported PDF linked to
the matching article and served by EBSCO content delivery. This independent
observation adds no timed pair. The signed attachment URL stays local.

R073 now resolves the PDF download link from EBSCO's details response after
matching the record to the original DOI. If the link is a lookup, it can be
resolved once on the same origin. The qualified delivery URL goes to the
existing Session stream. A missing or refused direct entry can use the
prepared record's Viewer. If a direct transfer fails, the original entry
can be re-established before running the qualified Viewer path. An isolated
Electron regression verifies the direct link without starting a Viewer or
issuing a discovery PDF request. The public Download regression verifies
local association after direct success and after direct refusal followed by
a successful Viewer transfer of the same delivery URL. The mechanism was
implemented from the observed link contract and installed Translator behavior.
F24-6 ran on `a921407` after both products independently reached the authorized
EBSCO record. Allfold's assigned Service retained the separate Community
selection page. The page loaded with HTTP 200, and its profile read stopped
with `page_probe_unconfirmed` at 3.753 s. The direct lookup was never reached.
Allfold linked the previously identified 48-page arXiv preprint in
18.770–19.227 s. Zotero saved the correct 39-page, 1,762,961-byte INFORMS Just
Accepted manuscript in 9.011–9.331 s. The files belong to different versions,
so this pair supplies no direct-link speed measurement.

Inspection of the retained Community page showed a visible “EBSCO一站式检索”
WebForm postback. Its JavaScript address went into the HTTP-link projection
and was rejected by the bounded Document decoder. The same type of control
had previously led from the manual CARSI resource entry to the authorized
search profile. A diagnostic click on the retained Community page did not
visibly change it. Those observations distinguish the working manual entry
from the managed source's earlier probe failure.

The Community repair separates ordinary HTTPS links from the visible WebForm
control. It binds one native main-frame POST to the verified managed Document
and the same-origin Community endpoint before the request is sent. GET redirects
in that request chain may continue to the verified search profile. The isolated
native regression checks the one POST, the qualified PDF handoff and refusal of
a changed submission destination, a child-frame submit and a repeated POST.

In the previous Login batch, EBSCO reported Opened and its retained page was
immediately closed with `access_evicted`. For preparation of `d237ee7`, the
managed page total was temporarily raised from 16 to 32 through Settings.
The Login batch ended, its retained EBSCO Community page stayed live, and the
limit was restored to 16 before any timed download. The saved configuration
hash matched the pre-adjustment hash. Each product's independent session
showed the exact EBSCO record and PDF entry. Chrome's new detail page could
load its inline full-text section. Neither side was manually previewed.

| Original Paper / order | Allfold local wait | Zotero local wait | A−Z | A/Z | Matching local PDF |
| --- | --- | --- | --- | --- | --- |
| F24-7 / A→Z | 30.355–30.768 s | 14.560–14.868 s | +15.487 to +16.208 s | 2.0416–2.1132 | 39 pages, 1,762,961 bytes, Just Accepted |
| F23-6 / Z→A | 33.048–33.399 s | 13.450–13.754 s | +19.294 to +19.949 s | 2.4028–2.4832 | 29 pages, 2,996,661 bytes, publisher PDF |

Both pairs verified title, DOI, local association and equality of the saved
files by SHA-256. Each Allfold action logged `ebsco_direct_pdf_entry` before the
R073 stream completed. F24's direct publisher entry returned a challenge after
1.954 s. EBSCO saved the license-matched file before publisher Reader recovery
was needed. This is the live trigger absent in F24-5 and R073-Fresh-1. F23's
publisher request denied authorization after 1.069 s.

Allfold spent 20.759 s on F24 discovery and 22.316 s on F23 discovery. On the
retained Community route, opening the selector and reaching the search profile
took 10.476 and 13.688 s respectively. The DOI search through record opening
took 6.214 and 5.814 s. Opening and verifying the record and resolving its
direct link took another 4.065 and 2.808 s. The record check and lookup are
measured together. No Viewer opened in these attempts. The body operations
took 7.587 and 9.433 s, with first byte after 1.955 and 1.444 s. Zotero already
had its exact article record at the start of Save. Its internal stage timings
were unavailable. These observations locate the remaining wait in preparing
the Community/profile and finding the record, with additional transfer time.

The F23 wait was 8.244–8.955 s shorter than the old measured Viewer path.
The F24 wait overlapped the F24-5 Viewer result. The live publisher and cache
conditions varied across those retests. The new measurements verify the
direct-link path and the correct save. The repeated large timing gap is
recorded under the revised acceptance criterion.

The operator's example, DOI `10.1287/ijoc.2024.0765`, supplied the new Paper
R073-Fresh-2. Discover rejected the full quoted title because it contains
hyphens. A misplaced click during result inspection also submitted the invalid
expression a second time. Neither attempt created a Paper. One corrected
OpenAlex Discover using lexical phrases completed. It created the target and
one other match. The original query, months and Provider selection were
restored, and the saved configuration hash matched. The new mechanism sample
was frozen after collection and before either measured save.

Allfold saved the licensed 20-page, 4,846,719-byte publisher PDF to the new
Paper in 32.135–32.485 s. Zotero imported the byte-identical PDF to a new item
in 13.801–14.136 s. Both were automatic. Allfold's publisher attempt returned
an authorization denial after 0.810 s. The EBSCO direct discovery took 12.628 s
and its Session stream took 18.479 s, with first byte after 4.838 s. The
transfer was the largest measured phase on this Paper. Cache use and Zotero's
internal transfer time were not observed. This pair verifies the different
journal and new-record path and leaves a +17.999 to +18.684 s wait gap.

## Historical acceptance disposition and Workspace Reset

The two original slots where Zotero saved a PDF and Allfold did not were F01-1
and F26-2. F01-1 returned `no-pdf-candidates` in approximately three seconds.
The approximately 600-second expiry belonged to pilot P04. Subsequent prepared-access F01 controls and the repaired F26 control
produced verified publisher PDFs in Allfold. The original attempts remain in
the results, along with version substitutions, preparation, and assisted saves.
F25 lacks a verified direct publisher PDF in either product.

The slow F27-2 ScienceDirect result included a 15.773 s Reader that finished
verification without a usable PDF handoff. The shipped fix reuses the qualified
GET when verification returns to the same PDF through POST. F27 and the two
untouched Papers each handed off through their first Reader and saved their
publisher PDFs. F27's repaired action still took 63.154–63.498 s with two real
challenges. The final retests lack comparable Zotero completions, so the report
records the functional improvement and leaves the paired time benefit unmeasured.

F24-5 and the earlier fresh EBSCO sample received publisher authorization
denials. F24-7 later exercised the changed source order live. Oxford F08 and
F09 and the untouched Oxford control saved directly after access was restored. The
old navigation block did not recur, so its request method and origin remain
unknown and the guard was left in place. Older results and these coverage limits
remain visible. No further live repetitions were required to elicit these paths.

At the last tested production revision `d237ee7`,
`npm --prefix electron run check` checked 65 files,
`uv run --locked pytest` passed 1,685 tests with two existing warnings, and
`npm --prefix electron test` passed all 255 tests locally. The follow-up
commits addressed the Standards and Spec review findings. The independent
native review reported no remaining actionable defect. The PR's full Safety
checks passed on this production revision.
[Production revision Safety check](https://github.com/dylaaan-booob/allfold/actions/runs/44747655318/job/136327019869)

On 21 November 2026 at 09:16 Asia/Shanghai, Settings → Reset → Workspace
displayed the configured `workspace` directory and its full-Workspace scope.
After confirmation, the product reported “Workspace permanently deleted.
A later explicit Run can recreate it.” Before Reset there were 75 Paper
records, 36 Candidates, 39 Downloaded and no Trash items. The Workspace
directory, database and Documents were absent afterwards. Candidates,
Downloaded and Trash all read zero. The final check did not start a Run.

The configuration bytes and UserState revision and content matched before
and after. The 68 Journals, 12 Services, saved credential file, covers and
existing diagnostics were retained. Raw measurements and diagnostics are in
the original local evidence directory outside Workspace. The dedicated
Zotero collection `Allfold PDF acceptance 2026-11-16` retained its 104 parent
items. Six representative local PDF attachments, including all three final
EBSCO files, were rechecked under their parents and had identical hashes
before and after Reset.
