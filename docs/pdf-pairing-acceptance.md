# Local Allfold / Zotero PDF pairing acceptance

Issue: [#140](https://github.com/dylaaan-booob/allfold/issues/140). Baseline:
`a2e511aa86ab5aa292f224301d6609a59c287fa2`.

**Status: incomplete; saved checkpoint 17 November 2026, 02:46 UTC. Fourteen
of the 31 frozen Papers have observations (25 pair slots including repeats);
17 Papers are unstarted. Six same-version low-load pairs now have reliable local
file/association endpoints. Springer has two slower Allfold points and one
interval overlap; T&F has one slower point requiring swapped repeats. No platform
is confirmed at parity. Workspace is retained for required measurements/retests.**

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
At this checkpoint Allfold has 21 automatic local-PDF successes, one assisted
success, two failures and one unattempted end. Zotero has 19 local-PDF successes
and six operator interruptions with unknown product terminal state. These are
attempt counts, not independent-paper success rates. Saving a related preprint
is a task result but is not a publisher-version success.

| Actual platform | Papers started / planned | Local PDF observations, including repeats | Conclusion |
| --- | --- | --- | --- |
| IEEE Xplore | 2 / 2 | Allfold 0 success,1 failure,1 end unattempted; Zotero 2 publisher files | Original extra failure retained. Same-access target retests outstanding. Not confirmed. |
| Springer Link | 3 / 3 | Allfold 10 successes; Zotero 9 successes,1 interruption | Three corrected low-load controls: two slower points and one overlap. Cause unresolved; not confirmed. |
| Cambridge Core | 2 / 2 | Both 5 successes; one Zotero body is a preprint | One corrected timed control favors Allfold; two further controls outstanding. Not confirmed. |
| Oxford Academic | 3 / 3 | Allfold 2 related preprints,1 access-challenge failure; Zotero 3 interrupted saves without parent/PDF | New native CF Prepare recovery observed; publisher PDF retests outstanding. Not confirmed. |
| Taylor & Francis | 3 / 3 | Allfold 4 successes: original preprint plus3 publisher Accepted Manuscripts; Zotero 2 publisher Accepted Manuscripts,2 interrupted parent-only saves | Same-version F11 retry faster; first F13 slower. Controls/repeats and F12 retry outstanding. Not confirmed. |
| Project Euclid | 1 / 3 | Both saved related arXiv v4; Allfold required in-download hCaptcha assistance | First-access recovery reported separately; normal prepared-access controls and2 papers outstanding. Not confirmed. |
| Wiley | 0 / 3 | Not started | Not confirmed. |
| SIAM | 0 / 3 | Not started | Not confirmed. |
| INFORMS PubsOnline | 0 / 3 | Not started; configured EBSCO capability is not a platform result | Not confirmed. |
| ScienceDirect | 0 / 6 | Formal cohort not started; repaired-path pilots remain separate | Not confirmed. |

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
current T&F pairs used nativee67e136 and frontenda9663f7; native/Python sources
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

For Springer OA, n=3 paired repeats of **one** Paper: interval median waits are
2.598–2.952s(Allfold) and1.717–2.109s(Zotero), median paired difference
+0.489 to+1.235s, median ratio1.2319–1.6079. Raw wait ranges are0.597–4.256s
and0.734–2.960s respectively. Two slower points exceed measurement precision;
the third overlaps. This is insufficient to claim parity or isolate a cause.
The other access strata each have n=1; the raw point is their only median and
no dispersion estimate is claimed. No pooled daily-load average, p95, tolerance
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
JavaScript63files, Python1622tests(2existing deprecation warnings), Electron243tests
with no skips. These marks have not yet been observed on the real running process
at this saved checkpoint; they are not retroactive phase measurements.

F03 publisher files are22pages/2636871bytes; F04 are57pages/5103901bytes; F05
are29pages/7842498bytes. F04's first Zotero save created only a parent; its trial
tab was closed19:11:53 UTC after no observed activity/temporary file. Two later
fresh saves obtained publisher PDFs. Temporary Connector Debug produced zero
lines and was restored off; no causal recovery claim is made.

F06 publisher FirstView has personalized watermarks/small byte differences.
F07 differs in version: Allfold publisher FirstView42pages/572214bytes, Zotero
arXiv2603.07780v1,109pages/1146058bytes. Exact title, all three authors and the
Paper's explicit preprint relation were verified; no transfer comparison is made.

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
to code. Two swapped F13 repeats, the preselected F11 controls and F12 recovery
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
interruptions; no AgentDock UI was used. The obsolete tool-choice question does
not block the restored channel.

At the checkpoint Workspace has72Papers,56Candidates,16Downloaded,0Trash, no
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

Latest head `fdad2a3`'s full PR-linked [run 43976157092](https://github.com/dylaaan-booob/allfold/actions/runs/43976157092)
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
succeeded for actual PR head a9663f778c920c588414f2e8816b8a962faffcc0. Later commits
require their own latest-PR check; this earlier success is not a completion claim.

Raw diagnostics, runtime proofs, click records and local file/association observations
are outside Workspace in a private evidence directory. Public tables contain no
PDFs, cookies, credentials, signed URLs, sensitive institutional pages or raw auth
requests. Workspace Reset has **not** run: mandatory acceptance/retests remain.
The dedicated Zotero collection retains all trial materials and the original
library is preserved.
