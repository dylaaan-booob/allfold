# Local Allfold / Zotero PDF pairing acceptance

Issue: [#140](https://github.com/dylaaan-booob/allfold/issues/140). Baseline:
`a2e511aa86ab5aa292f224301d6609a59c287fa2`.

**Status: incomplete. These are calibration pilots, not a frozen representative
cohort or evidence that any platform has reached parity. Workspace is retained
because diagnosis and real retests remain necessary.**

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
provider selections were restored. Collection settled before Download. No direct
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
| P04 / 10.1109/tnnls.2026.3706351 | IEEE Xplore, institutional | Z→A; later diagnostic A retries | Initial parent deadline expired, about 600 s; later 20.481–20.887 s and 17.571–17.946 s | 17.829–18.220 s; new paired save awaiting authentication | Access/Session changed before successful retries; no code-benefit or parity claim. |
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
their live-site effect is unverified, and this commit is not loaded in the current
9383359 process. Full Python checks now pass 1622 tests. Fixed-baseline review of
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
PDF permission and normal institutional login required the user's QR-code MFA.
The new Zotero save has not started, so that paired repeat remains incomplete.

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
No frozen formal manifest exists yet. Representative platform samples, mechanism
coverage, matched repeats/controls, completed latest CI, and final
Workspace Reset remain outstanding. No platform is confirmed at parity.

The full PR-linked run for 098288a failed in the isolated native Cancel fixture's
five-second public-progress wait, after the earlier 603f02f full run had passed.
The original failed run is retained at
[run 43912807839](https://github.com/dylaaan-booob/allfold/actions/runs/43912807839).
No production timeout or assertion was changed. An isolated local reproduction
on the same source passed all 41 public native cases in about 12.7 s; full native
checks also passed all 241 tests on the same 098288a source, with no skips, in
120.7 s; JavaScript checks passed 63 files. The next latest PR run remains to be
verified. The failure's cause is not established, so it is not described as repaired.

Raw diagnostics, runtime proofs, click records and local association/file
observations are retained outside Workspace in the task's private evidence
directory. They are not public inputs: no PDF, credentials, cookie, signed URL,
institutional page or raw authentication request is included in this report.
Workspace Reset has **not** run. Zotero acceptance material remains in its dedicated
collection, and the user's existing library is preserved.
