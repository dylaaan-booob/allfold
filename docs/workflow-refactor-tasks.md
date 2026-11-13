# Workflow refactor tasks

Each task has one PR targeting `main`. The user accepts and merges the current PR
before a separately requested prompt starts the next task. Any temporary integration branch/ticket graph is scoped to the current WF task;
it does not authorize later tasks.

| Task | Goal | Cleanup ownership | Actual status |
| --- | --- | --- | --- |
| WF01 | SQLite Paper repository, reliable identity, short transactional increments | New schema/identity/increment contracts; retain active old-path tests | Merged in PR #77 at `70bcefd69850eeb1de22ebc0fb6e00bfd653a41c`; production adoption is WF02 |
| WF02 | Switch all production Paper readers/writers to SQLite; local recycle bin; retire Keep/Import and active Enrich | Paper MD/Inbox.base, Keep/Import and active Enrich interfaces, tests/docs | Production integration implemented in the WF02 branch; PR #83 and its actual checks are the review record; not merged |
| WF03 | Independent Document identity, lightweight page checks, Cloudflare main path | Translator identity coupling, full-snapshot assumptions, page-access docs | Not started |
| WF04 | Shared Session, page limits, precise cancellation, authorization generations | Global owner, indiscriminate cancellation, duplicate listeners, broad invalidation assertions | Not started |
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
