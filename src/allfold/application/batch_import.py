"""Bounded native Import with transient projections and guarded Paper writes."""
from __future__ import annotations
from concurrent.futures import Future
from dataclasses import dataclass, replace, field
from enum import Enum
from pathlib import Path
from uuid import UUID
import threading
import secrets
from allfold.application.bounded_dispatch import bounded_dispatch
from allfold.application.history import observe, batch_history
from allfold.browser_diagnostics import normalize_browser_diagnostic, first_attachment_diagnostic, format_browser_diagnostic
from allfold.recovery_diagnostics import normalize_recovery, recovery_progress_message
from allfold.application.export_attempts import (
    PdfOutcome, _reserve_export_attempt_locked, validate_export_reservation, complete_electron_import, ExportCompletionOutcome,
)
from allfold.application.workspace import WorkspaceImportPlan, plan_workspace_import
from allfold.persistence.safe_write import workspace_operation_lock
from allfold.application.browser_runtime import BrowserTaskLock, BrowserOwner
from allfold.persistence.markdown_state import parse_paper_state
from allfold.application.browser_runtime import BrowserGateway, ElectronDisconnected
from allfold.application.browser_services import BrowserServiceSnapshot, browser_workspace_identity


class BatchPhase(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    PAUSED = "paused"
    BLOCKED = "blocked"

@dataclass(frozen=True)
class BatchPaperResult:
    paper_id: UUID
    outcome: str
    reason: str
    pdf_outcome: PdfOutcome | None = None
    parent_outcome: str = "no_effect"
    reason_code: str = "unknown"
    diagnostic: dict | None = None
    service_id: str | None = None
    service_assignment: str = 'unassigned'
    item_exists: bool | None = None
    pdf_attached: bool | None = None
    pdf_source: str | None = None
    fallback_used: bool | None = None
    query_diagnostic: dict | None = None
    uncertain_write: bool = False
    native_identity: dict | None = field(default=None, repr=False)
    recovery: list | None = None

@dataclass(frozen=True)
class BatchStatistics:
    exported_parent: int = 0
    no_effect: int = 0
    uncertain: int = 0
    skipped_blocked: int = 0
    pdf_verified_success: int = 0
    pdf_verified_failure: int = 0
    pdf_unverified: int = 0
    normal_excluded: int = 0

@dataclass(frozen=True)
class BatchSnapshot:
    phase: BatchPhase
    plan: WorkspaceImportPlan | None
    active_paper_ids: tuple[UUID, ...]
    results: tuple[BatchPaperResult, ...]
    message: str
    task_id: str | None = None
    service_id: str | None = None

    @property
    def statistics(self) -> BatchStatistics:
        return BatchStatistics(
            exported_parent=sum(r.outcome == "exported" for r in self.results),
            no_effect=sum(r.outcome == "no_effect" for r in self.results),
            uncertain=sum(r.outcome == "uncertain" or r.uncertain_write for r in self.results),
            skipped_blocked=(sum(e.kind != "normal" for e in self.plan.exclusions) if self.plan else 0)
                + sum(r.outcome in {"skipped", "blocked"} for r in self.results),
            pdf_verified_success=sum(r.pdf_outcome is PdfOutcome.VERIFIED_SUCCESS for r in self.results),
            pdf_verified_failure=sum(r.pdf_outcome is PdfOutcome.VERIFIED_FAILURE for r in self.results),
            pdf_unverified=sum(r.pdf_outcome is PdfOutcome.UNVERIFIED for r in self.results),
            normal_excluded=sum(e.kind == "normal" for e in self.plan.exclusions) if self.plan else 0,
        )

    @property
    def successful(self) -> bool:
        return (self.phase is BatchPhase.COMPLETED and self.plan is not None and bool(self.results)
                and all(e.kind == "normal" for e in self.plan.exclusions)
                and len(self.results) == len(self.plan.papers)
                and all(r.outcome == "exported" and not r.uncertain_write for r in self.results))


class BatchImportService:
    def __init__(self, bridge: BrowserGateway, browser_lock: BrowserTaskLock, *, diagnostics=None):
        self.bridge, self.browser_lock = bridge, browser_lock
        self.diagnostics = diagnostics
        self._mutex = threading.RLock()
        self._worker = None
        self._stop = threading.Event()
        self._snapshot = BatchSnapshot(BatchPhase.IDLE, None, (), (), "No batch started")

    @property
    def running(self):
        return self._worker is not None and self._worker.is_alive()

    def snapshot(self):
        with self._mutex:
            return self._snapshot

    def _publish(self, **changes):
        with self._mutex:
            self._snapshot = replace(self._snapshot, **changes)

    def start(self, workspace: Path, *, browser_owner: BrowserOwner, validate_target=None,
              services: BrowserServiceSnapshot | None = None, workflow_id=None, parent_task_id=None,
              service_id=None, initial_plan=None, zotero_target=None, skip_unprepared=frozenset(),
              paper_limit=1, service_limit=1, native_limits=None):
        self.browser_lock.require(browser_owner)
        with self._mutex:
            if self.running:
                return self._snapshot
            task_id = secrets.token_hex(16)
            self._history_context = dict(task_id=task_id, workflow_id=workflow_id or task_id, parent_task_id=parent_task_id)
            observe(self.diagnostics, "begin", "import", **self._history_context,
                details={'batch_scope':'service' if service_id else 'all', 'service_id':service_id})
            needs_native = initial_plan is None or any(paper.service_id not in skip_unprepared for paper in initial_plan.papers)
            if needs_native and not self.bridge.connected:
                self._snapshot = BatchSnapshot(BatchPhase.BLOCKED, None, (), (), "Electron runtime unavailable", task_id=task_id, service_id=service_id)
                self._finish_history(reason="browser_unavailable")
                return self._snapshot
            try:
                if service_id is not None and (services is None or service_id not in {s.id for s in services.services}):
                    raise ValueError("Selected Service is not saved in this configuration")
            except BaseException:
                self._snapshot = BatchSnapshot(BatchPhase.BLOCKED, None, (), (), "Saved configuration unavailable", task_id=task_id, service_id=service_id)
                self._finish_history(reason="configuration_changed")
                raise
            self._stop.clear()
            self._snapshot = BatchSnapshot(BatchPhase.RUNNING, initial_plan, (), (), "Scanning Kept Papers", task_id=task_id, service_id=service_id)
            self._worker = threading.Thread(target=self._execute,
                args=(workspace, browser_owner, validate_target, services, service_id, initial_plan, zotero_target,
                      frozenset(skip_unprepared), paper_limit, service_limit, dict(native_limits or {})),
                daemon=False, name="electron-import")
            try:
                self._worker.start()
            except BaseException:
                self._snapshot = replace(self._snapshot, phase=BatchPhase.BLOCKED)
                self._finish_history()
                raise
        return self.snapshot()

    def _finish_history(self, *, reason=None):
        outcome, counts, details = batch_history(self._snapshot)
        if reason:
            details["reason"] = reason
        observe(self.diagnostics, "finish", self._history_context["task_id"], outcome, statistics=counts, details=details)

    def stop(self):
        # End navigation/verification waiting, but let an escaped native save settle.
        with self._mutex:
            self._stop.set()
            if self._snapshot.phase is BatchPhase.RUNNING:
                self.bridge.cancel_current()

    def clear_terminal(self):
        with self._mutex:
            if self.running:
                raise RuntimeError("Cannot clear an active Import")
            self._snapshot = BatchSnapshot(BatchPhase.IDLE, None, (), (), "No batch started")

    def join(self):
        if self._worker is not None:
            self._worker.join()

    def _execute(self, workspace, owner, validate_target, services, service_id, initial_plan,
                 zotero_target, skip_unprepared, paper_limit, service_limit, native_limits):
        results = {}
        plan = initial_plan
        phase, message = BatchPhase.COMPLETED, "No eligible Papers to import"
        try:
            # Local commits are sequential under the same Workspace identity.
            # Native Futures overlap while this worker owns the operation lock.
            with workspace_operation_lock(workspace) as lock:
                def verify():
                    if validate_target:
                        validate_target(lock)
                    if services:
                        services.verify()

                verify()
                current_plan = plan_workspace_import(lock, services.journals if services else (), service_id=service_id)
                safe_papers = {paper.paper_id: paper for paper in current_plan.papers}
                plan = (replace(initial_plan, exclusions=current_plan.exclusions, inventory=current_plan.inventory)
                        if initial_plan is not None else current_plan)
                if plan.papers_identity != current_plan.papers_identity or plan.service_id != service_id:
                    raise RuntimeError('The fixed Paper plan no longer matches this Workspace/scope')
                workspace_identity = browser_workspace_identity(lock.path, lock.identity)
                reservations = {}

                def start(paper):
                    with self._mutex:
                        if self._stop.is_set():
                            return _settled_skip(paper, 'cancelled', 'Stopped before Native dispatch')
                        self.browser_lock.require(owner)
                        verify()
                        if safe_papers.get(paper.paper_id) != paper:
                            return _settled_skip(paper, 'workspace_changed',
                                'Paper identity, content or global eligibility changed since this batch started')
                        try:
                            reservation = _reserve_export_attempt_locked(lock, paper.paper_id,
                                expected_paper=paper, expected_papers_identity=plan.papers_identity)
                        except (RuntimeError, OSError) as error:
                            return _settled_skip(paper, 'blocked', str(error))
                        reservations[paper.paper_id] = reservation
                        self._publish(active_paper_ids=tuple(reservations), message="Translating and saving")

                        def verify_recovery():
                            if self._stop.is_set():
                                raise InterruptedError()
                            self.browser_lock.require(owner)
                            verify()
                            validate_export_reservation(reservation, operation_lock=lock)

                        return self.bridge.execute("import_paper", {
                            "doi": paper.doi, "metadata": _import_metadata(paper),
                            "zotero_target": zotero_target, "task_id": reservation.attempt.attempt_id,
                            "workflow_id": self._history_context["workflow_id"],
                            "parent_task_id": self._history_context["task_id"],
                            "paper_id": str(paper.paper_id), "workspace_identity": workspace_identity,
                            "service_id": paper.service_id, "service_scope": services.scope if services else None,
                            "limits": native_limits,
                        }, lambda progress: self._publish(message=recovery_progress_message(progress.get('recovery_action'))
                            or str(progress.get("message", "Import running"))), verify_recovery=verify_recovery)

                eligible = []
                for paper in plan.papers:
                    if paper.service_id in skip_unprepared:
                        results[paper.paper_id] = _skip(paper, 'service_unprepared',
                            'Service was not prepared in Login and was explicitly skipped')
                    else:
                        eligible.append(paper)
                self._publish(plan=plan, results=tuple(results.values()))

                for paper, future in bounded_dispatch(eligible, key=lambda paper: paper.service_id,
                        start=start, limit=paper_limit, group_limit=service_limit,
                        stopped=lambda: self._stop.is_set() or phase is not BatchPhase.COMPLETED):
                    reservation = reservations.pop(paper.paper_id, None)
                    try:
                        result = future.result()
                        if reservation is not None:
                            native = result
                            result = _settle_paper(paper, reservation, native, lock)
                            if (result.outcome in {"uncertain", "blocked"} or result.uncertain_write or native.get("stop_batch") is True):
                                phase, message = BatchPhase.PAUSED, result.reason
                    except Exception as error:
                        if reservation is None:
                            phase, message = BatchPhase.BLOCKED, f"Import stopped: {error}"
                            result = _skip(paper, "blocked", message)
                        else:
                            disconnected = isinstance(error, ElectronDisconnected)
                            reason = "Electron disconnected" if disconnected else "Native operation result unconfirmed"
                            phase, message = BatchPhase.PAUSED, reason + "; inspect Zotero before retrying"
                            result = BatchPaperResult(paper.paper_id, "uncertain", message, PdfOutcome.UNVERIFIED,
                                parent_outcome="uncertain", reason_code="connection_lost" if disconnected else "result_unconfirmed")
                    results[paper.paper_id] = replace(result, service_id=paper.service_id,
                                                      service_assignment=paper.service_assignment)
                    self._publish(results=tuple(results.values()), active_paper_ids=tuple(reservations))
                if self._stop.is_set() and phase is BatchPhase.COMPLETED:
                    phase, message = BatchPhase.STOPPED, "Stopped after active operations settled"
                lock.verify()
        except Exception as error:
            phase, message = BatchPhase.BLOCKED, f"Import stopped: {error}; inspect Zotero before retrying"
        finally:
            if phase is BatchPhase.COMPLETED:
                exported = sum(result.outcome == "exported" for result in results.values())
                message = f"Import finished: {exported} imported, {len(results) - exported} not imported"
            if plan is not None:
                for paper in plan.papers:
                    if paper.paper_id not in results:
                        results[paper.paper_id] = _skip(paper, "cancelled" if phase is BatchPhase.STOPPED else "blocked", message)
            ordered = tuple(results[paper.paper_id] for paper in plan.papers) if plan is not None else ()
            self._publish(phase=phase, results=ordered, active_paper_ids=(), message=message)
            self._finish_history()


def _skip(paper, reason_code, message):
    return BatchPaperResult(paper.paper_id, "skipped", message, reason_code=reason_code,
                            service_id=paper.service_id, service_assignment=paper.service_assignment)


def _settled_skip(paper, reason_code, message):
    future = Future()
    future.set_result(_skip(paper, reason_code, message))
    return future


def _import_metadata(paper):
    state = parse_paper_state(paper.path, paper.contents)
    metadata = {"doi": paper.doi}
    if state is not None:
        metadata.update({key: value for key, value in {
            "title": state.title, "journal": state.journal, "abstract": state.abstract,
            "publication_date": state.publication_date, "authors": list(state.authors),
            "journal_issns": list(state.journal_issns),
        }.items() if value is not None})
    return metadata


def _settle_paper(paper, reservation, result, lock):
    # A configuration change revokes new admissions. An already accepted key
    # still commits only against that invocation's exact Paper and Workspace.
    completion = complete_electron_import(reservation, result, operation_lock=lock)
    outcome = {ExportCompletionOutcome.EXPORTED: "exported", ExportCompletionOutcome.NO_EFFECT: "no_effect",
        ExportCompletionOutcome.UNCERTAIN: "uncertain"}.get(completion.outcome, "blocked")
    pdf = result.get("pdf")
    failures = pdf.get("failures") if isinstance(pdf, dict) else None
    if isinstance(pdf, dict) and pdf.get("registered") is True and isinstance(failures, list):
        failures = [failure for failure in failures if isinstance(failure, dict)
                    and failure.get("phase") not in {"initial_fetch", "oa_resolver"}]
    attachment_diagnostic = first_attachment_diagnostic(failures)
    last = result.get("last_import") if isinstance(result.get("last_import"), dict) else {}
    observations = {key: last.get(key) if type(last.get(key)) is bool else None
                    for key in ("item_exists", "pdf_attached", "fallback_used")}
    if not last and outcome == "no_effect":
        observations = dict.fromkeys(observations, False)
    source = last.get("pdf_source")
    query = last.get("query_diagnostic")
    if isinstance(query, dict):
        query = normalize_browser_diagnostic(query)
    reason = completion.message + (' ' + format_browser_diagnostic(attachment_diagnostic, include_pdf_uncertainty=False)
                                   if attachment_diagnostic else '')
    uncertain_write = result.get("uncertain_write") is True
    if uncertain_write and outcome in {"exported", "blocked"}:
        reason += " An attachment or child write is unconfirmed. Inspect Zotero before retrying."
    return BatchPaperResult(paper.paper_id, outcome, reason, PdfOutcome.UNVERIFIED,
        uncertain_write=uncertain_write,
        parent_outcome="confirmed" if outcome in {"exported", "blocked"} else outcome,
        reason_code="write_failed" if outcome == "blocked" else "result_unconfirmed" if outcome == "uncertain" or uncertain_write else "no_effect" if outcome == "no_effect" else "pdf_unverified",
        diagnostic=normalize_browser_diagnostic(result.get("diagnostic")) or attachment_diagnostic,
        **observations, pdf_source=source if source in {"translator", "openalex", "none"} else None,
        query_diagnostic=query, native_identity=result.get("zotero"),
        recovery=normalize_recovery(result.get("recovery")) or None)
