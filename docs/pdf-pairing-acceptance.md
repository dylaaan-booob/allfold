# Local Allfold / Zotero PDF pairing acceptance

Issue: [#140](https://github.com/dylaaan-booob/allfold/issues/140). Baseline:
`a2e511aa86ab5aa292f224301d6609a59c287fa2`.

**Status: incomplete. The 31-paper representative manifest is now frozen and
formal pairing has started. Seven Papers have observations; the remaining 24
are unstarted. Reliable paired timing and the IEEE access retest are blocked on
manual inputs described below. No platform is confirmed at parity. Workspace is
retained for required measurements/retests.**

## Environment and endpoint

The source checkout, rebuilt UI, live process and local API were checked, rather
than inferring the running version from Git. macOS 27.2.1 (26B131); Electron
45.0.0 / Chromium 156.0.8078.48; Chrome 157.0.8103.51, existing Default profile;
Zotero Desktop 10.0.9 / Connector 5.0.217. Connector could reach Desktop and local
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

## Formal checkpoint, measurement defect and blockers

The immutable [31-paper manifest](pdf-pairing-manifest.json) was committed before
the first formal click; all original samples remain. The
[formal result table](pdf-pairing-formal-results.json) contains 13 observation
slots across seven distinct Papers, including pending/interrupted endpoints.
Allfold has 11 verified local-PDF successes, one failure, and one unattempted end;
Zotero has 12 verified local-PDF successes (one submitted preprint), and one
operator interruption with unknown product terminal state. These are attempt
counts, not independent-paper success estimates.

| Actual platform | Formal Papers started / planned | Local PDF observations, including repeats | Conclusion |
| --- | --- | --- | --- |
| IEEE Xplore | 2 / 2 | Allfold 0 success, 1 failure, 1 end pending; Zotero 2 successes | Same-access retry blocked on Electron institution login; no parity confirmation. |
| Springer Link | 3 / 3 | Allfold 7 successes; Zotero 6 successes, 1 operator interruption | Files verified; timing evidence affected by measurement load, normal-load controls pending. |
| Cambridge Core | 2 / 2 | Both 4 successes; Zotero includes one arXiv submitted version | One version-divergent pair and two missing Zotero click times; no parity confirmation. |
| Oxford Academic | 0 / 3 | Not started | Not confirmed. |
| Taylor & Francis | 0 / 3 | Not started | Not confirmed. |
| Wiley | 0 / 3 | Not started | Not confirmed. |
| SIAM | 0 / 3 | Not started | Not confirmed. |
| Project Euclid | 0 / 3 | Not started | Not confirmed. |
| INFORMS PubsOnline | 0 / 3 | Not started; configured EBSCO capability is not a platform result | Not confirmed. |
| ScienceDirect | 0 / 6 | Formal cohort not started; repaired-path pilots retained separately | Not confirmed. |

**Measurement-load defect:** the original task-local observer repeatedly requested
full JSON for the newest 20 Zotero items at nominal 250 ms. A no-download A/B check
measured Zotero CPU at 20.9–26.6% with this observer and 0% when paused. It was
replaced at 19:40:20 UTC with a keys query and individual metadata reads only for
new/pending items; two steady observations were 1.3% and 1.5%. No product setting,
timeout, source code or outcome criterion changed. File/association observations
remain valid, but all older timings, including pilots, are retained as
measurement-affected evidence and **do not establish normal-load parity**. No
numerical correction is subtracted. Repeated warm controls under the lighter
observer remain necessary; their cache state must stay explicit.

Nine successful pairs have comparable publisher versions. Seven have raw paired
timings from the older observer; two Cambridge repeats lack a reliable Zotero T0.
There is currently **zero** complete same-version, two-sided timed pair eligible
for a normal-load parity decision after the observer correction. Normal-load
medians and dispersion are therefore not estimable (N=0). Raw intervals,
differences and ratios remain in the table, with eligibility false. No p95,
pooled daily-load average, tolerance percentage or non-significance argument is used.

F03's publisher PDF is 22 pages / 2,636,871 bytes; F04's is 57 pages / 5,103,901
bytes; F05's is 29 pages / 7,842,498 bytes. Titles/DOIs/pages and parent/Paper
relations were inspected. F03's rendered publisher first page and normalized
first-page text in Zotero match. F04's original Zotero save produced only a parent;
after evidence and no visible activity/temporary storage, only its trial tab was
closed at 19:11:53 UTC. This is an operator interruption, with no invented failure
or timeout endpoint. Two fresh saves later obtained the publisher PDF. Connector
Debug was temporarily enabled for those diagnostic retries, logged zero lines,
and restored off without clearing or submitting output; Desktop debug stayed off.
Neither the new session nor the logging toggle is claimed as the cause of recovery.

F06's publisher FirstView is 33 pages; personalized download-time watermarks and
small byte differences were retained. F07 differs materially: Allfold obtained
the Cambridge publisher FirstView, 42 pages / 572,214 bytes, with the correct DOI;
Zotero obtained arXiv 2603.07780v1, 109 pages / 1,146,058 bytes. The submitted
version has no publisher DOI in its body, but its exact title, all three authors
and the original Paper's explicit preprint relationship match. Both are valid
local full-text outcomes. Their observed access states and versions differ;
no same-version timing or transfer-efficiency comparison is made.

Actual diagnostics show a single P1/R001 native request/stream for successful
Springer trials (first-pair combined durations 2.117, 4.921 and 2.602 s). These
figures combine request/transfer handling, not a separately measured transfer
segment. Cambridge used cached P3 discovery clues. The source-event/operation
fields retain actual rules and durations; missing first-byte, exact association
and UI-render times are explicit. Existing collection/Document/API clues and
article/Translator preparation are part of each starting context, not silently
claimed to be identical network preprocessing. The representative and warm
control/anomaly observations remain separately tagged. ScienceDirect's targeted
Reader/CDN pilots do not enter representative statistics. IEEE Reader, Optica,
R059, LWW/OCE and other unobserved mechanisms are not treated as covered.

Two manual inputs block continued meaningful pairing:

- F01's normal Electron CARSI renewal reached the official institution account
  page with empty fields and no visible saved autofill. Local user login is
  pending; Chrome's successful login is not copied to Electron. The original
  no-candidate/HTTP202 failure remains unresolved until a same-access retry.
- Chrome/CUA repeatedly returned `noWindowsAvailable`/`timeoutReached` around
  normal Connector clicks. F06's two later PDFs prove saving occurred, but no
  accurate click time survived. Tool waits are not product waits. Chrome's high
  CPU was observed and recovered without restarting it; its cause is not proved.
  The connected AgentDock `desktop` fallback was found/read but not used for UI:
  current Computer Use documentation permits other technologies only when
  specifically requested by the user. A concrete tool-choice request is pending.

At 20:00:59 UTC the product reported 72 Papers, 10 current bodies, zero active
Downloads, zero Download cleanup and zero active collection. Original Run inputs
and providers were restored exactly; temporary Connector debugging is off. This
idle checkpoint is **not** permission to Reset while required retests remain.
Workspace Reset has not been attempted, trial data and authentication page remain,
and temporary trial windows are retained for continuation. Annual Reviews had no
eligible Paper in the existing/normal-Run pool; unmapped/other absent platforms
and unavailable mechanisms receive no inferred parity result.

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

All 68 configured journals were inventoried by their saved Service. Actual scope
includes Oxford, Annual Reviews, Taylor & Francis, Wiley, ScienceDirect, Springer,
SIAM, Cambridge, IEEE, EBSCO-mapped journals, Project Euclid, and unmapped journals.
EBSCO mapping is an access capability, not proof of the actual full-text platform.
The [formal manifest](pdf-pairing-manifest.json) froze 31 untreated distinct Papers
on 2026-11-16 at 18:40:53.823107 UTC, before the first formal click. It records
specific DOI/URLs, saved discovery state, configured Service versus actual platform,
OA/access knowledge, caches, declared orders and preselected repeat controls.
The [formal results](pdf-pairing-formal-results.json) preserve every observation,
including F01’s first Allfold no-candidate failure and Zotero’s verified 16-page
local PDF (13.193–13.568 s). Electron’s subsequent ordinary article visit showed
no PDF rights; the old institutional homepage was insufficient proof. Normal
CARSI renewal reached the official account page with empty fields/no autofill;
user login is pending before a comparable Allfold retest. This original failure
is retained rather than silently excluded. Formal main pairs, controls,
mechanism coverage and final Workspace Reset remain incomplete. No platform is
confirmed at parity. At manifest freeze, IEEE and Cambridge each had two eligible untreated Papers;
ScienceDirect has six; the other seven platforms have three each. Unavailable
Optica/R059/LWW/OCE paths are not claimed as covered.

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

Raw diagnostics, runtime proofs, click records and local association/file
observations are retained outside Workspace in the task's private evidence
directory. They are not public inputs: no PDF, credentials, cookie, signed URL,
institutional page or raw authentication request is included in this report.
Workspace Reset has **not** run. Zotero acceptance material remains in its dedicated
collection, and the user's existing library is preserved.
