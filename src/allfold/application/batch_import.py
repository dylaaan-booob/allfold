"""Serial native Import with transient projections and guarded Paper writes."""
from __future__ import annotations
from dataclasses import dataclass, replace, field
from enum import Enum
from pathlib import Path
from uuid import UUID
import threading
import secrets
from allfold.application.history import observe, batch_history
from allfold.browser_diagnostics import normalize_browser_diagnostic, first_attachment_diagnostic, format_browser_diagnostic
from allfold.application.access import AccessObservation
from allfold.application.export_attempts import (
    PdfOutcome, _reserve_export_attempt_locked, complete_electron_import, ExportCompletionOutcome,
)
from allfold.application.workspace import WorkspaceImportPlan, plan_workspace_import
from allfold.persistence.safe_write import workspace_operation_lock
from allfold.application.browser_runtime import BrowserTaskLock, BrowserOwner
from allfold.persistence.markdown_state import parse_paper_state
from allfold.application.browser_runtime import BrowserGateway, ElectronDisconnected
from allfold.application.browser_services import BrowserServiceSnapshot


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
    access: AccessObservation | None = None
    failure_stage: str | None = None
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
    native_identity: dict | None = field(default=None, repr=False)

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
    current_paper_id: UUID | None
    results: tuple[BatchPaperResult, ...]
    message: str
    current_access: AccessObservation | None = None
    task_id: str | None = None
    service_id: str | None = None

    @property
    def statistics(self) -> BatchStatistics:
        return BatchStatistics(
            exported_parent=sum(r.outcome == "exported" for r in self.results),
            no_effect=sum(r.outcome == "no_effect" for r in self.results),
            uncertain=sum(r.outcome == "uncertain" for r in self.results),
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
                and len(self.results) == len(self.plan.papers) and all(r.outcome == "exported" for r in self.results))


class BatchImportService:
    def __init__(self, bridge: BrowserGateway, browser_lock: BrowserTaskLock, *, diagnostics=None):
        self.bridge, self.browser_lock = bridge, browser_lock
        self.diagnostics = diagnostics
        self._mutex = threading.Lock()
        self._worker = None
        self._stop = threading.Event()
        self._snapshot = BatchSnapshot(BatchPhase.IDLE, None, None, (), "No batch started")

    @property
    def running(self):
        return self._worker is not None and self._worker.is_alive()

    def snapshot(self):
        with self._mutex:
            return self._snapshot

    def _publish(self, **changes):
        with self._mutex:
            self._snapshot = replace(self._snapshot, **changes)

    def start(self, workspace: Path, *, browser_owner: BrowserOwner, validate_target=None, config_path=None, workflow_id=None, parent_task_id=None, service_id=None, initial_plan=None, zotero_target=None):
        self.browser_lock.require(browser_owner)
        with self._mutex:
            if self.running:
                return self._snapshot
            task_id = secrets.token_hex(16)
            self._history_context = dict(task_id=task_id, workflow_id=workflow_id or task_id, parent_task_id=parent_task_id)
            observe(self.diagnostics, "begin", "import", **self._history_context,
                details={'batch_scope':'service' if service_id else 'all', 'service_id':service_id})
            if not self.bridge.connected:
                self._snapshot = BatchSnapshot(BatchPhase.BLOCKED, None, None, (), "Electron runtime unavailable", task_id=task_id, service_id=service_id)
                self._finish_history(reason="browser_unavailable")
                return self._snapshot
            try:
                services = BrowserServiceSnapshot.read(config_path) if config_path is not None else None
                if service_id is not None and (services is None or service_id not in {s.id for s in services.services}):
                    raise ValueError("Selected Service is not saved in this configuration")
            except BaseException:
                self._snapshot = BatchSnapshot(BatchPhase.BLOCKED, None, None, (), "Saved configuration unavailable", task_id=task_id, service_id=service_id)
                self._finish_history(reason="configuration_changed")
                raise
            self._stop.clear()
            self._snapshot = BatchSnapshot(BatchPhase.RUNNING, None, None, (), "Scanning Kept Papers", task_id=task_id, service_id=service_id)
            self._worker = threading.Thread(target=self._execute,
                args=(workspace, browser_owner, validate_target, services, service_id, initial_plan, zotero_target), daemon=False, name="electron-import")
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
        # End navigation/verification waiting, but let an escaped ItemSaver settle.
        with self._mutex:
            self._stop.set()
            self.bridge.cancel_current()

    def clear_terminal(self):
        with self._mutex:
            if self.running:
                raise RuntimeError("Cannot clear an active Import")
            self._snapshot = BatchSnapshot(BatchPhase.IDLE, None, None, (), "No batch started")

    def join(self):
        if self._worker is not None:
            self._worker.join()

    def _execute(self, workspace, owner, validate_target, services, service_id, initial_plan, zotero_target):
        results = []
        plan = None
        phase, message = BatchPhase.COMPLETED, "No eligible Papers to import"
        try:
            # Held across translation, the complete ItemSaver call and Paper commit.
            with workspace_operation_lock(workspace) as lock:
                if validate_target:
                    validate_target(lock)
                if services:
                    services.verify()
                current_plan = plan_workspace_import(lock, services.journals if services else (), service_id=service_id)
                safe_papers = {paper.paper_id: paper for paper in current_plan.papers}
                plan = (replace(initial_plan, exclusions=current_plan.exclusions, inventory=current_plan.inventory)
                        if initial_plan is not None else current_plan)
                if plan.papers_identity != current_plan.papers_identity or plan.service_id != service_id:
                    raise RuntimeError('The fixed Paper plan no longer matches this Workspace/scope')
                self._publish(plan=plan)
                for paper in plan.papers:
                    if self._stop.is_set():
                        phase, message = BatchPhase.STOPPED, "Stopped; remaining Papers stay kept"
                        break
                    self.browser_lock.require(owner)
                    if safe_papers.get(paper.paper_id) != paper:
                        results.append(BatchPaperResult(paper.paper_id, 'skipped',
                            'Paper identity, content or global eligibility changed since this batch started',
                            reason_code='workspace_changed', service_id=paper.service_id,
                            service_assignment=paper.service_assignment))
                        self._publish(results=tuple(results))
                        continue
                    try:
                        reservation = _reserve_export_attempt_locked(lock, paper.paper_id,
                            expected_paper=paper, expected_papers_identity=plan.papers_identity)
                    except (RuntimeError, OSError) as error:
                        results.append(BatchPaperResult(paper.paper_id, "skipped", str(error), reason_code="blocked"))
                        continue
                    self._publish(current_paper_id=paper.paper_id, message="Translating and saving once")
                    in_flight = False
                    try:
                        # Serialize stop with dispatch registration; the actual result waits outside the mutex.
                        with self._mutex:
                            if self._stop.is_set():
                                phase, message = BatchPhase.STOPPED, "Stopped before next Paper"
                                break
                            if validate_target:
                                validate_target(lock)
                            if services:
                                services.verify()
                            state = parse_paper_state(paper.path, paper.contents)
                            metadata = {"doi": paper.doi}
                            if state is not None:
                                metadata.update({key: value for key, value in {
                                    "title": state.title, "journal": state.journal,
                                    "abstract": state.abstract, "publication_date": state.publication_date,
                                    "authors": list(state.authors), "journal_issns": list(state.journal_issns),
                                }.items() if value is not None})
                            pending = self.bridge.execute("import_paper", {
                                "doi": paper.doi, "metadata": metadata, "zotero_target": zotero_target, "task_id": reservation.attempt.attempt_id,
                                "workflow_id": self._history_context["workflow_id"],
                                "parent_task_id": self._history_context["task_id"],
                                "paper_id": str(paper.paper_id), "service_id": paper.service_id,
                                "service_scope": services.scope if services else None},
                                lambda progress: self._publish(message=str(progress.get("message", "Import running"))))
                            in_flight = True
                        result = pending.result()
                        completion = complete_electron_import(reservation, result, operation_lock=lock)
                        in_flight = False
                        outcome = {ExportCompletionOutcome.EXPORTED:"exported", ExportCompletionOutcome.NO_EFFECT:"no_effect",
                            ExportCompletionOutcome.UNCERTAIN:"uncertain"}.get(completion.outcome,"blocked")
                        pdf = result.get("pdf")
                        failures = pdf.get("failures") if isinstance(pdf, dict) else None
                        if isinstance(pdf, dict) and pdf.get("registered") is True and isinstance(failures, list):
                            failures = [failure for failure in failures if isinstance(failure, dict)
                                        and failure.get("phase") not in {"initial_fetch", "oa_resolver"}]
                        attachment_diagnostic = first_attachment_diagnostic(failures)
                        last = result.get("last_import") if isinstance(result.get("last_import"), dict) else {}
                        observations = {key: last.get(key) if type(last.get(key)) is bool else None
                                        for key in ("item_exists", "pdf_attached", "fallback_used")}
                        if not last and result.get("parent", {}).get("outcome") == "no_effect":
                            observations = dict.fromkeys(observations, False)
                        source = last.get("pdf_source")
                        query = last.get("query_diagnostic")
                        if isinstance(query, dict):
                            query = normalize_browser_diagnostic(query)
                        reason = completion.message + (' ' + format_browser_diagnostic(attachment_diagnostic, include_pdf_uncertainty=False)
                                                       if attachment_diagnostic else '')
                        results.append(BatchPaperResult(paper.paper_id,outcome,reason,PdfOutcome.UNVERIFIED,
                            parent_outcome="confirmed" if outcome in {"exported", "blocked"} else outcome,
                            reason_code="write_failed" if outcome == "blocked" else "result_unconfirmed" if outcome == "uncertain" else "no_effect" if outcome == "no_effect" else "pdf_unverified",
                            diagnostic=normalize_browser_diagnostic(result.get("diagnostic")) or attachment_diagnostic,
                            **observations, pdf_source=source if source in {"translator", "openalex", "none"} else None,
                            query_diagnostic=query, native_identity=result.get("zotero")))
                        if outcome in {"uncertain", "blocked"} or result.get("stop_batch") is True:
                            phase, message = BatchPhase.PAUSED, completion.message
                            break
                    except ElectronDisconnected:
                        results.append(BatchPaperResult(paper.paper_id,"uncertain",
                            "Electron disconnected; inspect Zotero before retrying",PdfOutcome.UNVERIFIED, parent_outcome="uncertain", reason_code="connection_lost"))
                        phase, message = BatchPhase.PAUSED, "Connection lost; no save replayed"
                        break
                    except Exception:
                        if in_flight:
                            results.append(BatchPaperResult(paper.paper_id, "uncertain",
                                "Native operation result unconfirmed; inspect Zotero before retrying", PdfOutcome.UNVERIFIED,
                                parent_outcome="uncertain", reason_code="result_unconfirmed"))
                        raise
                    assignments = {item.paper_id: item for item in plan.papers}
                    self._publish(results=tuple(replace(result, service_id=assignments[result.paper_id].service_id,
                        service_assignment=assignments[result.paper_id].service_assignment) for result in results))
                if self._stop.is_set() and phase is BatchPhase.COMPLETED:
                    phase, message = BatchPhase.STOPPED, "Stopped after current save settled"
                lock.verify()
        except Exception as error:
            phase, message = BatchPhase.BLOCKED, f"Import stopped: {error}; inspect Zotero before retrying"
        finally:
            if plan is not None:
                assignment = {paper.paper_id: paper for paper in plan.papers}
                results = [replace(result, service_id=assignment[result.paper_id].service_id,
                    service_assignment=assignment[result.paper_id].service_assignment) for result in results]
            if phase is BatchPhase.COMPLETED:
                exported = sum(result.outcome == "exported" for result in results)
                message = f"Import finished: {exported} imported, {len(results) - exported} not imported"
            if plan is not None and phase is not BatchPhase.COMPLETED:
                finished = {result.paper_id for result in results}
                results.extend(BatchPaperResult(paper.paper_id, "skipped", message,
                    reason_code="cancelled" if phase is BatchPhase.STOPPED else "blocked", service_id=paper.service_id,
                    service_assignment=paper.service_assignment)
                    for paper in plan.papers if paper.paper_id not in finished)
            # KeptWorkflow releases browser ownership after observing this terminal state.
            self._publish(phase=phase,results=tuple(results),current_paper_id=None,message=message)
            self._finish_history()
