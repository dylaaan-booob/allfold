# Workflow refactor tasks

Each task has one PR targeting `main`. The user accepts and merges the current PR
before a separately requested prompt starts the next task. Any temporary integration branch/ticket graph is scoped to the current WF task;
it does not authorize later tasks.

| Task | Goal | Cleanup ownership | Actual status |
| --- | --- | --- | --- |
| WF01 | SQLite Paper repository, reliable identity, short transactional increments | New schema/identity/increment contracts; retain active old-path tests | Merged in PR #77 at `70bcefd69850eeb1de22ebc0fb6e00bfd653a41c`; production adoption is WF02 |
| WF02 | Switch all production Paper readers/writers to SQLite; local recycle bin; retire Keep/Import and active Enrich | Paper MD/Inbox.base, Keep/Import and active Enrich interfaces, tests/docs | Merged in PR #83 at `90cf98e50aba0b8fc333fd84f8409cb5d8a8e47c` |
| WF03 | Independent Document identity, lightweight page checks, Cloudflare main path | Translator identity coupling, full-snapshot assumptions, page-access docs | Merged in PR #85 at `541b3de7d6d3c08c8bf1441cc8fa9f6c2b37f109`; scoped live acceptance and fixture evidence below |
| WF04 | Shared Session, page limits, precise cancellation, authorization generations | Global owner, indiscriminate cancellation, duplicate listeners, broad invalidation assertions | Local integration prepared for PR #90; not merged; final integrated checks/review/PR CI pending |
| WF05 | Workspace background registry, dynamic scheduling, branch state, independent resource ownership | One-shot queues, early release, collection terminal states/retries | Not started |
| WF06 | Date/Abstract extraction and retained API/Preprint capabilities | Old date columns, abstract overwrite, author/ordinary-completion assertions/docs | Not started |
| WF07 | PDF source rules, candidates, same-page Meta/DOM hints | Source order, candidate success, URLs and request context contracts | Not started |
| WF08 | Connect new Run and Workspace background collection | Whole-batch Run gates, Completion, Preprint double locking, busy/exit contracts | Not started |
| WF09 | Session stream, managed file landing, database association service | Whole-file Buffers, extra type detection, file ownership, failure terminals | Not started |
| WF10 | Original DownloadItem, complete Download UI, local PDF actions | Cancel-and-GET replay, old download/UI states, PDF action contracts | Not started |
| WF11 | Clean install, dependencies/licenses, whole regression and residual cleanup | Uncalled Runtime/build dependencies, installation/license docs, cross-task leftovers | Not started |

## WF01 implementation boundary

- `src/allfold/persistence/paper_repository.py`: public `PaperRepository` lifecycle;
  `get`/`list_papers`/`match`/`create_or_match`; guarded `merge_metadata` and
  `edit_metadata`; `exclude`/`restore`/`clear_metadata`/`unexclude`/
  `rebuild_from_run`; `complete_body`/`clear_body`.
- `library_models.py`: independent metadata, direct identity, Preprint, body,
  immutable record and write-token values. `library_database.py`: schema version 1,
  stable Workspace identity, safe connections, upgrade entry and rollback boundary.
- [Storage contract](paper-library.md): exact API, generation, state, path and
  failure semantics. Explicit database path: `Workspace/papers.sqlite`. No
  production startup or real-Workspace shadow library is introduced.
- `tests/test_paper_repository.py` and `tests/test_paper_repository_safety.py`:
  isolated real-database component acceptance, without claiming new complete
  workflow, live-site, Zotero, actual-file or UI acceptance.

## WF02 production adoption

Run/WoS, Workspace/Reader/search, local field edits, Preprint and Trash now use
`PaperRepository` and `Workspace/papers.sqlite`. Known-v1 schema upgrades retain
existing data. Uninitialized reads create nothing; the first Run initializes
explicitly. Library errors never become an empty/rebuilt store. HTTP/worker
connections are thread-local, with Workspace UUID/path and captured generation
guards across cancellation, Reset, output-directory changes and shutdown.

The current Run filters complete/excluded/cleared identities early and adjudicates
again in final transactions. Complete matches are unchanged; a real hit can
rebuild a cleared unexcluded record with the same UUID. Ordinary Completion and
standalone Preprint query algorithms remain. Stable discovery time, primary
identity, bibliography, ordinary dates and full Preprint proof are persisted.
Collection remains `not_started`; no cross-Run work is registered.

ARRAY retains list/filter/selection/Reader, scrolling, layout, keyboard, search
and focus. Candidate, Downloaded and Trash follow library facts, including
identity-only body records. Local Reject/Restore/unexclude/clear metadata use UUID
and Workspace identity. Reject revokes write eligibility before exact-Paper
cancellation; metadata clearing waits for actual cleanup. UI revisions and
response order reject late results and retain same-record reading position.

Paper MD/Inbox authority, Keep/Import/Last Import, active Enrich, their specialized
HTTP/IPC and dedicated polling/configuration are retired. Local field edits and
Preprint no longer depend on MD/Enrich helpers. Dedicated Zotero Local API and
attachment writers, unused Translator sandbox/Runtime assembly and their exclusive
Setup/CI tests are removed. Existing vendor checkouts are not changed.

Still active: BrowserRuntime, isolated Document preload/identity/page checks,
Prepare, Login, WoS, Covers and request-bound Cloudflare. They do not depend on
the retired generated Translator Runtime. WF03/WF04 own their later architecture
changes. WF05/WF08 own background registry/cross-Run collection; WF06 owns new
webpage Date/Abstract extraction; WF07/WF09/WF10 own PDF source/transfer/file/UI
services. No executable Download, physical PDF action or retry entrance is added.

Real SQLite/application fixtures and temporary Electron/DOM fixtures are the
cutover evidence. Removed assertions belonged to retired product paths; generic
Provider, identity, safety, Browser, layout and keyboard tests remain. The latest
PR checks and final review report establish the actual validation result. No
real Workspace, PDF, account, institution or site was operated for this task.
This document does not imply successful CI or a merge before those events occur.

## WF03 Document access

Spec [#84](https://github.com/dylaaan-booob/allfold/issues/84) scopes this feature
branch to independent article identity and bounded Document/access probes.
Prepare/Login/Manual Service/Covers/WoS use the new access/binding path without
article DOI requirements. The internal Paper entry independently confirms article
identity; it has no production caller or new public entry. Collection remains
`not_started`. [Controlled Documents](browser-documents.md) records the interfaces,
limits, solver chain and finite outcomes.

Real temporary-profile Electron fixtures cover preload/probes, formal article
entry, conflicts, missing evidence, current-Document mutation, challenge recheck
and Pydoll/CDP exact targets. Public Bridge tests cover multiplexing, queue expiry,
precise cancellation, actual cleanup/slot release and shutdown/disconnect. Covers
and WoS Export share request deadlines, preserving native DownloadItem terminal
ownership and the eight-field export contract. PR #85 merged at
`541b3de7d6d3c08c8bf1441cc8fa9f6c2b37f109`; the evidence below describes WF03,
not acceptance of subsequent changes.

Scoped live acceptance on 2026-11-13 used a separate application copy, test
configuration, isolated Workspace/cover directory and a fresh browser profile.
The same initial CARSI Login completed after the user's QR authentication;
Oxford and WoS preparation both opened. One WoS batch returned/exported/accepted
28 of 28 records and the Run completed with 28 new test Papers. Cover Search
saved one cover. Cancellation during a real WoS wait ended the task and a later
Run started successfully. Manual Service was not configured and was skipped.
No Cloudflare/hCaptcha/Imperva challenge or separate MFA step was observed in those accepted paths;
real challenge completion remains unverified. Production Workspace, Zotero and
existing configuration/scopes were preserved.

Acceptance exposed an auth observation superseded by a redirect and a WoS export
overlay mistaken for Document replacement. The fixes discard stale auth facts and
refresh only the known WoS overlay binding within the same native Document and
result identity. Negative/cancellation/terminal regressions remain. A native
review also found stale-binding observer cleanup after a pre-dispatch export
failure; focused regression now covers cleanup and a subsequent retry.

Full serialization/translation-only enumeration and unused Import-only attachment
capture/bypass/response-cancel helpers were removed in WF03. WF04 owns shared
Session listener consolidation, original DownloadItem capability fixtures, page
quotas/scheduling and full closure policy. No download replacement or later WF
implementation is part of WF03. Retained host adaptations keep AGPL attribution.

## WF04 implementation boundary

WF04 local slices consolidate native Session events/download routing, scoped
authorization and exact cancellation, physical page admission/lifetime and live
limit configuration. The retained fixed fixtures prove the tested native resource
and original-response seams; [page resources](browser-pages.md) records the
BrowserRuntime main-frame form-POST refusal without replay. Real CARSI/WoS and
CAPTCHA compatibility remain separately authorized manual acceptance. PR #90 is
unmerged; final integrated checks, review and latest PR-associated CI must be
reported from their actual outputs. WF05 registry, WF08 background/cross-Run and
WF09/WF10 PDF transport/permanent files/Download UI have not been implemented.

Scoped live acceptance on 2026-11-13 used a separate application copy, temporary
configuration/Workspace/covers and a fresh profile. Institution QR Login,
Oxford/WoS preparation and parallel Cover Search completed. A Manual Project
Euclid Visit and a WoS challenge resumed after the user completed hCaptcha.
One small WoS Run queried/exported/accepted 28 records and created 28 test Papers;
canceling the next Browser-stage Run allowed another successful export with
28 already saved. Ordinary keyword saving preserved preparation, while changing
Oxford access invalidated only Oxford. The user-owned page survived task cleanup.

At global 4/Service 3, the live batch ended without blocked admission; native
creation/destruction events showed a peak of three managed pages. Target eviction
invalidated the matching Service. Acceptance exposed a late native `Opened`
result overwriting the closed-target reason with `unverified_official_page`;
the scoped fix preserves `target_closed`, verified through both public coordinator
regressions and another live low-capacity batch. Normal exit during an actual
authentication wait canceled the native operation, destroyed its page and exited;
restart remained idle, retained the isolated Papers/cover and restored limits 16/4.

The first WoS preparation returned `ERR_INVALID_REDIRECT`; a new controlled
Prepare after completed authentication succeeded. Its cause was not established,
and no redirect/replay permission was expanded. Saved-credential mutation and a
live Cloudflare Solver challenge were not exercised by this QR/hCaptcha sample.
This is scoped compatibility evidence, not a claim about every Service or entry.
