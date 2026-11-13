# Workflow refactor tasks

Each task has one PR targeting `main`. The user accepts and merges the current PR
before a separately requested prompt starts the next task. There is no shared
long-running integration branch or advance implementation ticket batch.

| Task | Goal | Cleanup ownership | Actual status |
| --- | --- | --- | --- |
| WF01 | SQLite Paper repository, reliable identity, short transactional increments | New schema/identity/increment contracts; retain active old-path tests | Kernel implemented with real temporary SQLite checks; awaiting PR review/merge. Production adoption remains WF02 |
| WF02 | Switch all production Paper readers/writers to SQLite; local recycle bin; retire Keep/Import and active Enrich | Paper MD/Inbox.base, Keep/Import and active Enrich interfaces, tests/docs | Not started |
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

WF02 must switch existing consumers together: persistence `materialize.py`,
`markdown_state.py`, `inbox.py` and `kept_export.py`; application `workspace.py`,
`decisions.py`, `integrated_run.py`, `wos.py`, `paper_enrichment.py`,
`preprint_lookup.py`, `batch_import.py`, `export_attempts.py` and their
coordinators/Web projections. Today these still own production creation, identity
scans, listing/Reader data, review/manual edits, enrichment, preprint saves and
Import settlement through Markdown and the Workspace lock. `paper_dates.py` still
owns event facts and earliest-preprint proof. WF01 neither adapts nor retires them;
their valid regressions remain. WF02 owns replacement and corresponding removals.

Configuration UserState, Journal/Group/Label/Service records, credentials, Registry,
Run snapshots and actual user files are outside the new Paper database contract.
No Issue, PR, CI or merge outcome is implied by this list; the PR and actual checks
are the review record.
