# Data and execution safety

These invariants apply across modules. Field-level definitions remain in code; tests below are the verification entry points.

| Invariant | Implementation | Safety checks |
| --- | --- | --- |
| Each canonical configuration owns an independent Journal/Group/Label/Service scope. Validated migration preserves its legacy source, SQLite writes compare revisions, and corrupt state is not replaced by recovered defaults. External cache refresh never overwrites user Service choices. | [User state](../src/allfold/persistence/user_state.py), [Settings](../src/allfold/application/settings.py), [Resolver](../src/allfold/application/journal_resolver.py) | Isolated Settings, migration, Resolver and research-scope exchange tests |
| Runs are create-only; existing Paper bytes and human fields are preserved. UUID, normalized primary DOI and direct reliable namespaced identity checks guard creation; exact-content revisions guard manual mutations. | [Paper persistence](../src/allfold/persistence/markdown_state.py), [safe writes](../src/allfold/persistence/safe_write.py) | [identity](../tests/test_paper_identity.py), [materialize](../tests/test_materialize.py), [decisions](../tests/test_application_decisions.py), [safe writes](../tests/test_safe_write.py) |
| Reset and file operations validate roots, ownership and directory identity; symlinks cannot redirect destructive operations. | [Workspace Reset](../src/allfold/application/workspace_reset.py), [safe writes](../src/allfold/persistence/safe_write.py) | [Reset](../tests/test_workspace_reset.py), [native exports](../electron/tests/wos-operations.test.cjs) |
| Browser operations remain bound to their task and document. User tab selection does not retarget an active operation; stale results and cancellation cannot grant new authority. | [browser runtime](../electron/src/browser/browser-runtime.cjs), [bridge](../src/allfold/web/electron_bridge.py) | [browser](../electron/tests/browser-runtime.test.cjs), [Import control](../electron/tests/import-control.test.cjs) |
| Institution credentials are limited to saved-Institution CARSI Login and its attributable authentication pages. Service preparation reuses the authenticated Session. Ordinary Browser, Import, Enrich and Covers gain no credential authority. | [institution auth](../electron/src/auth/institution-auth.cjs), [browser runtime](../electron/src/browser/browser-runtime.cjs) | [browser authority](../electron/tests/browser-runtime.test.cjs) |
| Explicit CARSI credential mutations compare the displayed encrypted-store revision, serialize writes and settle through authenticated bridge ownership. Only status is available through direct renderer IPC; passwords remain outside YAML, local draft storage and diagnostics. | [credential store](../electron/src/auth/cas-credentials.cjs), [Main](../electron/src/main.cjs) | [credential revisions](../electron/tests/cas-credentials.test.cjs), [native settlement](../electron/tests/import-control.test.cjs) |
| Remote pages stay sandboxed without Node or host IPC. Trusted UI IPC, document identity and the current CDP endpoint retain their validation. | [Main](../electron/src/main.cjs), [Preloads](../electron/src/preload/), [documents](../electron/src/browser/document-runtime.cjs) | [identity](../electron/tests/browser-identity.test.cjs), [browser](../electron/tests/browser-runtime.test.cjs) |
| Import pins its Zotero instance/Library/Collection and admits bounded parallel exact-key saves while retaining Workspace/task ownership through settlement. An uncertain write stops new dispatch. Local API is the only write channel. Partial or uncertain writes retain known keys without replay or deletion; a confirmed parent does not prove PDF persistence. Local task details retain exact known Zotero keys, and diagnostic exports omit them. | [batch Import](../src/allfold/application/batch_import.py), [Local API Import](../electron/src/zotero/local-importer.cjs), [completion](../src/allfold/application/export_attempts.py) | [Python Import](../tests/test_electron_import.py), [native Import](../electron/tests/local-importer.test.cjs), [Import control](../electron/tests/import-control.test.cjs) |
| Zotero authorization stays in protected native storage, bound to Server ID. API and upload requests use controlled loopback endpoints; publisher/OpenAlex requests never receive the key. Authorization recovery cannot replay a write. | [Local API](../electron/src/zotero/local-api.cjs), [authorization](../electron/src/zotero/local-auth.cjs) | [Local API protocol](../electron/tests/local-api.test.cjs) |
| Webpage Enrich fills eligible fields and can independently append Received or Accepted. History candidates require a DOI-matching Web Translator journal article and its verified source document. The Adapter keeps candidates separate from the Zotero Item and refreshes only that document for up to 30 seconds. Cancellation and Workspace/Paper revision checks guard the Markdown write. | [enrichment](../src/allfold/application/paper_enrichment.py), [Translator host](../electron/src/zotero/translator.cjs) | [enrichment](../tests/test_paper_enrichment.py), [native Runtime](../electron/tests/translator-runtime.test.cjs), [Import control](../electron/tests/import-control.test.cjs) |
| Cancellation and exit stop new dispatch while waiting for escaped native saves. Fixed step, deadline and Solver rules remain request and document scoped. Page changes do not replay actions. | [Main](../electron/src/main.cjs), [bridge](../src/allfold/web/electron_bridge.py), [Solver](../src/allfold/integrations/cloudflare_solver.py) | [Import control](../electron/tests/import-control.test.cjs), [native exports](../electron/tests/wos-operations.test.cjs) |
| Credentials, Cookie/Authorization values, page bodies and signed URLs stay out of application diagnostics and fixtures. | [logging](../electron/src/shared/logging.cjs), [HTTP](../electron/src/zotero/session-http.cjs) | [logging](../electron/tests/logging.test.cjs), [HTTP](../electron/tests/session-http.test.cjs) |
| History and diagnostics are bounded, configuration scoped and independent of Workspace authority. Producers and local exports apply explicit schema allowlists; logging failure cannot change a business result or replay a save. | [local diagnostics](../src/allfold/diagnostics.py), [native writer](../electron/src/shared/diagnostic-writer.cjs), [contract](logging.md) | [persistence/export/Reset](../tests/test_diagnostics.py), [cross-runtime export](../tests/test_diagnostics_contract.py), [native logging](../electron/tests/logging.test.cjs) |
| Setup preserves existing configuration and keys. Fixed upstream sources and Runtime ownership are validated before assembly; unknown contents are not overwritten. | [setup](../electron/scripts/setup.cjs), [assembler](../electron/scripts/prepare-runtime.cjs) | [setup](../electron/tests/setup.test.cjs), [Runtime](../electron/tests/runtime-build.test.cjs), [UI build](../electron/tests/ui-build.test.cjs) |

Use isolated configuration, Workspace and transport fixtures. Offline checks do not prove live authentication, challenge completion, native saving or PDF storage. Inspect actual Zotero state before retrying an uncertain save. Apply the existing manual boundary to CAPTCHA, MFA and ambiguous pages; run supported Cloudflare solving automatically within the originating request and document deadline. hCaptcha waits for manual verification.

A managed refresh is eligible only within the current owned main-frame load and
before business actions. The Browser binds each main-frame network request ID to
its navigation generation and checks the exact promise of an explicit load.
Native failure events retain URL and frame evidence. The Session request observer
also identifies non-GET navigation.
A stateful authentication action or manual verification blocks replay of that
attempt. CARSI reentry after Visit requires an acknowledged click and one
attributable target. Before any Visit, the resource search must have reached a
verified detail document through the existing read-only controls.

Before reentry or initial Paper replacement, the native operation rechecks its
authority on the original authenticated bridge request. Python verifies the saved
configuration, User State and Service preparation key or the exact Paper and
Workspace. The boolean response is bound to that invocation, with a five-second
timeout within its original deadline. Native code independently verifies the
attempt owner and live Page or Document. Internal retirement revokes only the
failed attempt, including its observers and private pages. The parent task,
shared CARSI Portal and Session remain in use. Reentry keeps the existing
authentication record and never grants new credential authority.

Last Import is an in-memory observation of the latest execution. Parent/children
queries use only the fixed instance, Library and known keys; PDF Yes also requires
confirmed upload registration. Failed reads and unresolved writes remain unable
to verify. These checks never request file paths, read the saved PDF or add keys
and PDF source to Paper frontmatter or persistent verification tables. Zotero's
ordinary object serialization can include storage fields; Allfold ignores them.
See the [protocol notes](zotero-local-api.md) for this server-side distinction and
the separately authorized real-Zotero acceptance boundary.

If credential ciphertext can be read but not decrypted, status reports an error
and its ciphertext revision without exposing a username or treating it as usable.
An explicitly confirmed complete replacement still compares that revision. If the
file itself cannot be read, no overwrite revision is available; the UI retains the
draft and requires a successful status read before submitting. Status responses
preserve newer credential input, which stays outside ordinary draft recovery.

Integrated Run overlaps selected Discovery with shared Work lookup without
holding the Workspace operation lock. Verified WoS batches submit DOI facts
through an in-memory callback after count/path/identity checks. Late native
identity conflicts remain quarantined even if a DOI was already located. Run
classifies roots against the complete saved index, including Rejected, before
DOI-to-PMID resolution and metadata completion. The captured authority covers
normal and final retry dispatch. Related versions can supply dates and provenance
while formal direct evidence supplies the persisted identities.

Every helper dispatch shares the parent's configuration/Workspace/cancellation
checks; invalidation latches cancellation across sources. A selected active WoS
disconnect revokes new HTTP dispatch while its native Future and Browser owner
remain held until native settlement. Application shutdown revokes the parent,
settles pending native authority through controlled teardown, and joins the parent
worker before its snapshot/slot can be released. Ordinary native source failures
remain local and do not discard other sources' verified facts.

Integrated Run captures configuration and Workspace ownership before the
network phase, then rechecks that ownership, cancellation and the complete
identity index under one short commit lock before atomic creates. Reset or
replacement cannot cause a late result to recreate or write a different
Workspace. Cancellation stops subsequent creates and retains the actual count
of files already committed. [Paper identity](paper-identity.md) defines the
persisted identity, source, date and DOI-action boundaries.

The Info preprint lookup shares configuration/Reset/workflow admission and the
Run slot without acquiring browser authority. It requires one existing
non-Rejected Paper with a valid formal DOI. Requests run outside the Workspace
lock. Commit checks configuration and source scope, Workspace/Papers identity,
exact Paper revision, UUID, primary identity and cancellation. A Reject or
intervening edit prevents the stale write. The operation appends deduplicated
preprint date and source facts and fills only an empty First public.
[Preprint lookup regressions](../tests/test_preprint_lookup.py) cover these
boundaries.
