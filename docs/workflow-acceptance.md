# WF01–WF11 acceptance index

WF11 was the final task, from main `229b6fb157bf2cb8d993c2cbb3b458240a507417`.
It merged in [PR #122](https://github.com/dylaaan-booob/allfold/pull/122) at
`c0599aa7aa590863b27a3923a3e782c0a35a5fa8` on 2026-11-15; the merged main's
[Safety checks / safety](https://github.com/dylaaan-booob/allfold/actions/runs/43697788889) passed.
This index records current callers and observable assertions, not 72 new tests.
The execution ledger separates completed source/fixture checks from historical
samples and remaining human conditions. No real account, personal profile/library
or user file is used. No installer, signing, release or additional workflow phase
is introduced.

## Execution ledger

On 2026-11-15, macOS 27.2.1 arm64 used Node 24.21.0, Python 3.12.14,
uv 0.12.19 and Electron 45.0.0. The code candidate is
`af37fe7d71591711359b767b3ba252f64d50f50e`; subsequent ledger edits are documentation.
Final PR Head and PR-associated CI belong in the PR, avoiding a self-SHA loop.

| Command / observation | Actual result and version |
| --- | --- |
| `npm --prefix electron run check` | 63 project files passed, including after the final inactive-reveal removal. |
| `node tools/build-ui-next.mjs` | Passed; generated UI stays ignored. |
| `uv run --locked pytest` | 1,466 passed, two existing dependency deprecation warnings, at `48dec324d02abe7b0c61ce8d6fe34169fdfea81f`; Python/schema/fixtures are unchanged in the code candidate. The earlier full run identified one stale `hidden_iframe` diagnostic example; it was rewritten as current navigation, retaining exact association/error/privacy assertions, before this passing full run. |
| `npm --prefix electron test` | 238 passed, zero failed/skipped at `48dec324d02abe7b0c61ce8d6fe34169fdfea81f`; public native composition printed all 28 cases. Rendered Download/Trash screenshots were inspected. |
| `node --test --test-concurrency=1 electron/tests/workspace-layout-dom.test.cjs electron/tests/browser-workspaces-dom.test.cjs electron/tests/browser-presentation-dom.test.cjs` | Three passed after final review corrections. Text/selection/scroll, collection/edit races, Download/Trash, native Browser input/focus/Session and workspace assertions remain. The inactive Enrich reveal object/CSS/callbacks and vacuous retired assertions are removed; the used abstract-line metric helper, Candidate scrolling rule and source notices remain. |
| `npm --prefix electron run setup` | Passed on a fresh tracked-source export of the code candidate, initially without `.venv`, either dependency tree, generated UI, vendor/Runtime, Workspace, config or UserState. Normal package caches were allowed; no old dependency tree was copied. Locked uv/npm installs, official Electron binary/version check and UI build all completed. |
| Repeated actual setup + `setup.test.cjs` | Earlier clean candidate `48dec324` preserved a modified existing config byte-for-byte on repeat. Normal suite tests also preserve a synthetic credential file and symlink target. Setup/config logic is unchanged in the code candidate. |
| `electron/node_modules/.bin/electron electron/tests/source-startup.fixture.cjs "$PWD/.startup-smoke/profile" --config "$PWD/config.example.yaml"` | Passed on the freshly installed code candidate: Main → project Python health → authenticated bridge → built UI → native Browser page navigation/actual destruction → normal quit. Captured UI inspected; zero renderer errors. Python reported application shutdown complete/process exit; port 18767 was free afterward, and read-only startup created no Paper database. |
| Same startup command with fixture-only `--fail-after-ready` / `--timeout-after-ready` | Each returned expected failure status 1 after normal Main drain; Python process was gone and 18767 free. Before the fix, an intentional failure reproduced the orphaned test Python; only that proved test-owned process was signalled for cleanup. Main/production shutdown itself is unchanged. |

The Main smoke is deliberately a normal empty-library startup. New-library Run,
collection, Retry and both durable body paths are proved by the separate P/N
production compositions below, not inferred from the startup screenshot. Setup's
normal npm policy reported a blocked esbuild postinstall; the existing platform
package/build path still completed without changing trust settings or locks.

- **P**: `uv run --locked pytest`, including every named Python test below.
- **N**: `npm --prefix electron test`, serial as defined by `package.json`.
  It includes the real Electron/local HTTP fixtures, the 28 public native cases,
  the rendered layout fixture and its `document_metadata_pipeline.py` races.
- **C**: fresh source `npm --prefix electron run setup`, then the opt-in
  `source-startup.fixture.cjs` requiring the unchanged normal `src/main.cjs`.
  Main starts project Python, checks health, authenticates the bridge, loads the
  built UI and BrowserRuntime, closes a real local native page, then quits normally.
- **S**: static producer/caller review at the same source candidate. Entry paths:
  setup/package/check/CI → Main → `electron_server.create_app` → Run/collection/
  body/local services → repository/managed files. Neither runtime dispatches
  Translator/Desktop/Local API/attachment import. Dedicated retired diagnostic
  fields/events are rejected by both validators and export, without rewriting logs.
- **R**: fixed historical live samples in [PR #121](https://github.com/dylaaan-booob/allfold/pull/121):
  `6bfdab0` retained stream/local paths, `ead4909` ScienceDirect,
  `175df8c` Microbiology R059 original POST→303→PDF. Earlier Microbiology P5
  fallback is distinct. Final Head `48f43a43edc338be82724df7e15bf52623d0d44d`
  passed [PR CI](https://github.com/dylaaan-booob/allfold/actions/runs/43679649066).
  Reader switch, precise cancel/explicit retry, OS open/locate/Trash were scoped
  disposable-data observations. WF11 does not repeat or broaden those claims.
- **H**: human/environment boundary, explicitly retained per row. It does not
  block the authorized source/fixture/PR work.
- **L**: accepted native cancellation limit: Chromium may asynchronously unlink
  an externally substituted private staging pathname after `done(cancelled)`.
  Item terminal is not proof of all Chromium file-worker cleanup. No replacement
  survival claim, sleep, `/dev/fd`, POST replay or new receiver is added. Stream
  writer closure, application-owned cleanup and final no-clobber remain required.

Test paths below are relative to `tests/` for P and `electron/tests/` for N.
`layout` means `workspace-layout-dom.fixture.cjs` through `workspace-layout-dom.test.cjs`;
`stream` means `body-stream.test.cjs` / `body-stream.fixture.cjs` /
`tests/electron_body_stream_fixture.py`; `native` means `body-native.test.cjs` /
`body-native.fixture.cjs` / `tests/electron_body_native_fixture.py`.
These are controlled native/composition results, not institution compatibility.

## A01–A72

Each row names the current production entry and the assertion that observes its
result. P/N/C refer to this task's execution ledger, R to fixed historical evidence.
“None” closes that row's remaining conditions at the indicated evidence layer;
it does not imply universal live-site acceptance.

| ID | Production entry and observable regression | Evidence / remaining conditions |
| --- | --- | --- |
| A01 | `integrated_run` → `ProductionCollectionService` → registry base admission; `test_collection_planner.py::test_http_run_hands_off_real_branches_and_next_run_cancel_preserves_them` reads the base while branches are blocked and checks stable UUID. | P; none. |
| A02 | `run_commit`/repository identity transaction; `test_collection_repository.py::test_concurrent_admission_commits_one_paper_and_one_queued_attempt`, `test_paper_repository.py::test_multi_identity_conflict_has_no_partial_rows_or_new_index`. | P; none. |
| A03 | Workspace projection → `kept.js`/Reader refresh; layout rejects rebuilding selected Reader, scroll, text selection and Info expansion during incremental collection. | N; H: arbitrary physical pointer/window interactions beyond fixture sizes. |
| A04 | Run coordinator hands ownership to Workspace; `test_http_run_hands_off_real_branches_and_next_run_cancel_preserves_them` parameterizes later API and controlled WoS Run, cancelling B while A remains active. | P; H: actual institution/WoS permission. |
| A05 | Run slot, durable admission and Paper gate; `test_collection_runtime.py::test_admitted_before_registration_is_atomic_against_download_and_legacy`, `test_body_downloads.py::test_mutually_exclusive_reservations_and_submission_failure_settle_attempt`; foreground coordinator tests retain its single slot. | P; none. |
| A06 | `document_metadata`/registry/repository terminal state; `test_legal_empty_and_json_ld_warning_are_completed_not_failed`, `test_incremental_results_and_empty_completion_persist_without_automatic_replay` in their owning test files. | P; none. |
| A07 | Registry branch/cleanup → Retry; `test_collection_runtime.py::test_failure_retains_incremental_results_and_occupancy_until_cleanup_then_retries_only_failed`. | P; none. |
| A08 | Original tokens, scoped cancellation and actual drain; `test_document_metadata.py::test_reject_restore_refuses_old_native_result_and_recovery_without_reopening_page`, `test_pdf_discovery_tasks.py::test_whole_workspace_maintenance_waits_native_cleanup_before_rebinding`, native cancel/drain. | P/N/L; none beyond accepted L. |
| A09 | Body reservation → PDF-only refresh; `test_pdf_discovery_tasks.py::test_completed_collection_uses_real_discovery_without_changing_collection_or_content`; native public cases assert no collection is created. | P/N; none. |
| A10 | Repository normalized ordinary dates; `test_paper_repository.py::test_dates_merge_by_precision_without_preprint_or_publication_inference`; actual Document extraction covers complete block/date grammar. | P/N; none. |
| A11 | Incremental repository union; `test_date_arrival_order_and_duplicates_have_the_same_result`; `document_metadata_pipeline.py::component_race` runs API-first, DOM-first and simultaneous real SQLite writes. | P/N; none. |
| A12 | Separate Preprint proof and ordinary dates; `test_dates_merge_by_precision_without_preprint_or_publication_inference`, component race and layout's separate First public/ordinary nodes. | P/N; none. |
| A13 | `paper_dates`/repository/Run preservation; `test_run_library.py::test_run_preserves_formal_fields_future_dates_and_full_preprint_family_proof`; extraction's legal future dates never infer publication. | P/N; none. |
| A14 | First-empty-only abstract increments; `test_paper_repository.py::test_existing_abstract_and_user_fields_survive_all_automatic_candidates`; component race `base` mutation. | P/N; none. |
| A15 | API/DOM field increments; pipeline `component_race` API-first/DOM-first, reopen and HTTP projection assertions preserve the first valid abstract. | N; none. |
| A16 | Atomic conditional abstract write; `test_concurrent_automatic_abstracts_fill_once_without_lost_dates`, `test_empty_abstract_does_not_claim_first_candidate_and_unrelated_edits_preserve_authority`; pipeline simultaneous/empty API. | P/N; none. |
| A17 | Field generations and incremental writes; `test_manual_abstract_edit_revokes_only_older_abstract_candidates`, pipeline `manual`/`clear` keeps human notes and dates; layout keeps unsaved/in-flight edits. | P/N; none. |
| A18 | Dynamic scheduler + Session-wide `PageBudget`; `test_dynamic_dispatch.py::test_global_and_service_limits_hold_until_workers_really_return`; `page-resources.test.cjs` checks real bounded WebContents and final counts. | P/N; none at fixture layer. |
| A19 | Prepare retained Portal/target ownership and popup quotas; `page-resources` fixture, `browser-runtime.test.cjs` retained-target/popup/destruction cases. | N; H: real Portal variations, historical WF04 sample remains in task history. |
| A20 | Exact Document/CDP target and frame; `cloudflare-solver.test.cjs` “clicks only the selected same-URL tab and its owned challenge frame”; Document probe mutation cases. | N; none at fixture layer. |
| A21 | Bridge solver queue + serial slot; `test_electron_bridge_solver.py::test_solver_slot_waits_for_actual_cleanup_and_skips_expired_or_canceled_queue` and `test_disconnect_and_shutdown_stop_queue_and_join_workers`; native `cloudflare-solver` exact-target recheck. | P/N; H: real challenge success is not inferred. |
| A22 | Browser background creation, viewport and bounded readiness; `browser-runtime.test.cjs` “a first background page never selects, presents or focuses the Browser”, real `document-probes`/`page-resources`. | N; H: arbitrary dynamic publisher behavior. |
| A23 | Bounded access/solver/manual waits; `browser-runtime` Imperva/hCaptcha/manual/absolute-deadline cases and `document-probes` error markers. | P/N; H: real MFA/Imperva/solver-unavailable site interaction. |
| A24 | Main → Browser/Document fixed probes and Pydoll/CDP; real `document-probes`, `cloudflare-solver` fixtures; S confirms no full serializer/Translator caller. | N/S; none at controlled mechanism layer. |
| A25 | Necessary-purpose planner and independent Preprint; `test_necessary_metadata.py::test_ordinary_gaps_do_not_schedule_requests_after_necessary_capabilities_settle`, precreation identity/native-family tests and `test_preprint_lookup.py`. | P/S; none. |
| A26 | Combined native extraction before one final binding check; `test_document_metadata.py::test_composite_document_saves_bounded_pdf_facts_once_under_original_attempt`, `test_independent_document_failure_preserves_other_success`, real `pdf-clues` fixture. | P/N; none. |
| A27 | Lazy P1–P5 coordinator; `test_pdf_discovery.py::test_t01_p1_confirmation_stops_before_any_later_io`, public HTTP lazy-first-request tests. | P/N stream; none. |
| A28 | Current-response actual final URL → relative reader resolution; `test_pdf_http.py::test_actual_http_redirect_final_url_is_relative_base_and_no_probe`, real stream known-reader cases. | P/N; none. |
| A29 | Session request target/secret scope; `test_every_redirect_boundary_checks_dns_and_scopes_secrets_but_keeps_referer`, stream exact signed query/Referer/Cookie/redirect assertions. | P/N; R retained Oxford/IEEE samples; H: other authenticated CDN policies. |
| A30 | `executeBodyStream` pipeline; stream unknown-length and gzip cases compare transferred payload without enforcing encoded Content-Length equality. | N; none. |
| A31 | Response/native type qualification; public bounded HTML access barrier tests, stream `html.pdf`/challenge, native public `action-html`/challenge cases. | P/N; none. |
| A32 | Stream backpressure, actual writer close and task settlement; stream `slow-writer`, disk/close faults and cancel cases; host actual-terminal tests. | P/N/L; no blanket native file-worker closure claim. |
| A33 | Per-Paper request/item/path ownership; Session same-URL fixture and public native cases retain exact task output; bridge multiplexing and exact cancellation regressions. | P/N; none. |
| A34 | `SharedSessionEvents` finite native observation/late-item custody; `session-downloads` expiry/late/ambiguous cases and native `no-item`. | N; none. |
| A35 | Native interrupted terminal → new explicit attempt; native `interrupted`, `test_native_body_downloads.py` terminal/cleanup cases, interrupted download restart tests. | P/N/L; no resume or native external-replacement survival claim. |
| A36 | Document/action → original request/frame/item; native POST/inline/iframe/popup/current-form/named-target cases compare payload and request counts, R059 actual redirect fixture. | N/R; H: other publisher action variants. |
| A37 | Coordinator cancellation/access/budget stop semantics; `test_t22_terminal_parent_state_stops_all_followup`, body access barriers, native cancelled current forms and no POST replay. | P/N; none. |
| A38 | Public HTTP → stream/native → managed publication → SQLite → Workspace; stream and all 28 public native cases assert completed/body presence together; layout moves same Reader into Downloaded. | N/R; none at controlled composition layer. |
| A39 | Locked setup → real Main/Python/bridge/UI/Browser; C; P/N exercise new temporary library/collection/body/Prepare/solver without Zotero. | C/P/N/S; H: packaged/installed app is outside source delivery. |
| A40 | Production Prepare/Session, stream and original-response service. | R is scoped ScienceDirect/R059/IEEE/Oxford; H: unexercised real institution login/expired authorization/CDNs remain unverified. |
| A41 | Repository match/admission + terminal reuse; `test_concurrent_admission_commits_one_paper_and_one_queued_attempt`, `test_existing_terminal_paper_reuses_without_capturing_irrelevant_new_authority`, `test_run_library.py`. | P; none. |
| A42 | Run early classification + final exclusion transaction; `test_run_library.py::test_excluded_and_released_placeholder_have_distinct_early_run_classification`, `test_paper_repository.py::test_exclusion_clear_and_rebuild_keep_identity_and_invalidate_old_writes`. | P; none. |
| A43 | Direct-identity creation and DOI-free native confirmation; `test_supported_direct_identity_can_create_without_doi`, `test_missing_or_retired_reliable_identity_cannot_create`, `test_title_and_unknown_ids_never_merge_papers`, DOI-free planner tests. | P; none. |
| A44 | Formal identity versus related Preprint; `test_necessary_metadata.py::test_actual_branch_saves_formal_increment_and_keeps_related_preprint_separate`, `test_reported_wos_pmid_cannot_own_a_formal_paper_or_discard_its_metadata`. | P; none. |
| A45 | `paper_payload` → Reader/download state; public HTTP active/failed/cancelled projection tests and layout's ongoing/completed classification assertions. | P/N; none. |
| A46 | Body admission current-task/body-first path; `test_public_download_reuses_exact_attempt_and_projects_durable_completion`, `test_existing_identity_only_trash_body_precedes_all_download_eligibility`, stream local reopen requests issue no new body fetch. | P/N; none. |
| A47 | Explicit new body attempt after settlement; public stream retry/delete/new attempt, `test_process_interruption_keeps_only_proven_outputs_without_replay`, completed-metadata PDF-only discovery. | P/N; none. |
| A48 | UUID-based `ManagedBodyFiles` permanent path; `test_body_downloads.py::test_download_completion_keeps_manual_edits_and_never_replaces`; repository stable UUID/primary and native file tests. | P/N; none. |
| A49 | No-clobber permanent publication; `test_target_conflict_never_overwrites_or_claims`, `test_final_inode_replacement_cannot_be_completed_or_removed`. | P; none; L does not apply to permanent bodies. |
| A50 | Stream/file/SQLite failure is terminal; stream disk-write/fsync/close faults; `test_final_database_failure_cleans_output_without_fallback_or_success`, public native `action-html`. | P/N/L; current native-output proof remains required. |
| A51 | Finite restart normalization + proved fragment disposal; `test_process_interruption_keeps_only_proven_outputs_without_replay` parameterizes transfer/publication/DB boundaries. | P; injected persisted boundaries, not a physical power-loss experiment; L applies only to native private cancellation. |
| A52 | Host/bridge actual drain and finite interruption; `test_actual_application_drain_waits_client_and_native_terminal_before_factory_close`, `test_first_lifecycle_bind_interrupts_old_tasks_once_without_network_or_replay`, C normal quit, native public `drain`. | P/N/C/L; H: OS power loss beyond persisted-boundary simulation. |
| A53 | Reject transaction → exact signals outside locks; `test_local_body.py::test_reject_is_immediate_but_delete_waits_for_actual_collection_exit`, Preprint reject/cleanup, collection late-write tests; layout Trash projection. | P/N; none. |
| A54 | Body completion/Reject transaction winner; `test_body_downloads.py::test_reject_final_transaction_order_and_restore_never_revives_old_token`. | P; none. |
| A55 | Restore preserves UUID without renewing authority; `test_collection_runtime.py::test_reject_restore_blocks_old_writes_and_occupancy_until_actual_worker_exit`, `test_delayed_http_reject_cannot_cancel_restored_paper_retry`, body stale-click tests. | P; none. |
| A56 | Trash `LocalBodyService` remove only current PDF; `test_trash_pdf_deletion_removes_only_file_and_association`, `test_failed_unlink_restores_owned_body_without_clearing_association`, stream delete→explicit new attempt. | P/N/R; none at fixture layer. |
| A57 | Repository clear metadata retaining body/strong IDs/exclusion; `test_body_slot_survives_metadata_clear_and_can_be_obtained_again`, `test_exclusion_clear_and_rebuild_keep_identity_and_invalidate_old_writes`. | P; none. |
| A58 | Minimal excluded identity across reopen; repository clear/exclusion tests and `test_workspace_reads_only_sqlite_and_keeps_identity_only_body`; Run exclusion fixture. | P; no expiration path, S; none. |
| A59 | `apply_paper_action` Restore/local projection; `test_workspace_library.py::test_http_run_initializes_single_library_then_reopens_local_read_and_trash`, layout Restore with/without PDF, completed collection reuse. | P/N; none. |
| A60 | Unexclude stays local; Run alone rebuilds original UUID; `test_only_released_placeholders_accept_new_run_results`, `test_excluded_and_released_placeholder_have_distinct_early_run_classification`; existing-body-first HTTP tests. | P; none. |
| A61 | Metadata generations + Run admission; `test_old_run_cannot_rebuild_a_paper_cleared_after_its_initial_snapshot`, repository clear/rebuild and original-token admission tests. | P; none. |
| A62 | Public Retry qualification + preserved successful branches; `test_public_retry_service_checks_exact_attempt_and_only_pending_api_access`, `test_retry_never_forces_not_started_excluded_or_identity_only_metadata`, cleanup/empty tests. | P/N layout; none. |
| A63 | `WorkspaceTaskHost` narrow config/Provider epochs; `test_settings_ordinary_inputs_preserve_work_and_service_change_drains_only_affected`, `test_provider_key_change_drains_only_declared_provider_attempts`. | P; none. |
| A64 | Exact Run B cancel, transferred A ownership, independent Preprint; controlled WoS next-Run planner test, `test_preprint_lookup.py::test_public_preprint_identity_and_active_request_allow_actual_run`, `test_run_cancel_identity.py`. | P/N task handoff; H: actual WoS service cancellation variants. |
| A65 | Workspace branch-owned clients/caches/snapshots; `test_independent_client_survives_source_run_close_and_unrelated_paper_cancel`, `test_verified_work_from_a_closed_discovery_client_is_reused_without_borrowing_it`, actual production planner handoff. | P; none. |
| A66 | Current-file capture → Main local adapter → conditional association clear; `test_confirmed_missing_conditionally_clears_only_body_and_keeps_identity_placeholder`, `test_unsafe_or_inaccessible_body_preserves_association`, stale-generation/missing tests, stream shell-error case. | P/N/R; H: other default-app/file-manager behavior. |
| A67 | Workspace/library/Paper revision and current terminal UI guards; layout holds old Workspace responses across Reject/collection/download and checks retained current classification; HTTP old-missing-result test. | P/N; none. |
| A68 | Actual close then scoped cleanup; `test_closed_unlink_fault_releases_budget_and_blocks_retry_network_until_clean`, `test_cleanup_quarantines_and_restores_replacement_between_check_and_removal`, native/local replacement and drain tests. | P/N/L; L does not relax stream/permanent/local/Trash checks. |
| A69 | Actual Reset admission/drain → safe deletion; `test_workspace_reset_accepts_api_cleanup_but_waits_outside_locks_before_deletion`, `test_workspace_reset.py` dangerous/custom/replaced/partial-delete cases. | P; H: destructive confirmation with real data intentionally unperformed. |
| A70 | Config/UserState scope preservation and exchange; `test_user_state.py::test_reset_preserves_database_and_refuses_data_directory`, `test_research_scope.py::test_portable_export_import_restores_independent_services_order_and_local_ids`, setup repeated-copy/symlink tests. | P/N/C; none. |
| A71 | Current setup/Main/Run/collection/body/local dispatch/DTOs; S plus `test_web_routes_use_workspace_identity_and_retire_business_endpoints`, new diagnostic write/export tests and workbench exact workflow/task/parent/page handoff. | P/N/S; first-configuration journal seed and Research Scope Import/export remain intentional. |
| A72 | Read-only missing library and strict v5 open/valid v4/v3 upgrade; `test_valid_prior_format_preserves_content_and_schema_failure_rolls_back`, repository corrupt/unknown/refusal tests, `test_workspace_get_does_not_initialize_or_interrupt_a_late_appearing_library`. | P/C; none; no new schema or migration is introduced. |

## Retained rules, source and limits

The complete Date/Abstract appendix E is retained in
[WF06 #97](https://github.com/dylaaan-booob/allfold/issues/97) and
[Document extraction](browser-documents.md#internal-combined-document-operation). Its former
production-stage gates are historical; WF08 connected the services. Appendix F,
T01–T24, R001–R072, API01–API17 and S001–S142 remain in the
[adopted discovery specification](pdf-source-discovery.md) with original source,
license, applicability and evidence limits. This index changes no algorithm,
platform condition, numbering or attribution.

Setup/check/CI no longer fetch or assemble Translator Runtime. `upstream.lock`
retains historical pins, while `electron/src`, COPYING, the tracked pristine
UserAgent-Switcher files and full UAParser corresponding source/notices remain.
See [third-party sources](third-party.md) and [Electron NOTICE](../electron/NOTICE.md).
Dependency versions/locks, native page/solver ownership, schema v5, no-clobber and
all data-protection boundaries are retained. No automated report, environment,
generated UI or private state is part of the source candidate.

## Recovery issue closure and remaining external evidence

[Issue #72](https://github.com/dylaaan-booob/allfold/issues/72) is complete in its
implementation scope: [PR #76](https://github.com/dylaaan-booob/allfold/pull/76)
merged bounded Provider/browser/PDF recovery and diagnostics, closing tickets
#73–75. The retained navigation/reentry and Provider deadline/cooldown contracts
are documented in [Document access](browser-documents.md) and [HTTP](http.md).
Later WF tasks explicitly retired Translator, ordinary Completion and Zotero
saving; their old acceptance entries are not pending current-product work.

This closure does not establish universal external-service reliability. PR #76's
historical 12-service batch reached 10 Opened, one WoS connection failure and one
manual Needs attention; the intermittent disconnect cause remains undetermined,
and that whole batch has not been revalidated on the merged WF11 main.
[PR #107](https://github.com/dylaaan-booob/allfold/pull/107) recorded Optica clues
but Radware HTML for its PDF candidates, without successful PDF-transfer evidence.
These limit the corresponding remote access/download claims, not local library
or Reader operation; they are not proof that the same failures persist on main.
The accepted native cancellation risk (L), per-row human boundaries (H) and
[source-only delivery](release.md#current-delivery) remain unchanged. No further
refactoring phase or additional acceptance gate is introduced.
