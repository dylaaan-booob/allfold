"""Serial native Import with transient projections and guarded Paper writes."""
from __future__ import annotations
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from uuid import UUID
import threading
from allfold.application.access import AccessObservation
from allfold.application.export_attempts import (
    PdfOutcome, _reserve_export_attempt_locked, complete_electron_import, ExportCompletionOutcome,
)
from allfold.application.workspace import WorkspaceImportPlan, plan_workspace_import
from allfold.persistence.safe_write import workspace_operation_lock
from allfold.application.browser_runtime import BrowserTaskLock, BrowserOwner
from allfold.persistence.markdown_state import parse_paper_state
from allfold.application.browser_runtime import BrowserGateway, ElectronDisconnected


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
    def __init__(self, bridge: BrowserGateway, browser_lock: BrowserTaskLock):
        self.bridge, self.browser_lock = bridge, browser_lock
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

    def start(self, workspace: Path, *, browser_owner: BrowserOwner, validate_target=None):
        self.browser_lock.require(browser_owner)
        with self._mutex:
            if self.running:
                return self._snapshot
            if not self.bridge.connected:
                self._snapshot = BatchSnapshot(BatchPhase.BLOCKED, None, None, (), "Electron runtime unavailable")
                return self._snapshot
            self._stop.clear()
            self._snapshot = BatchSnapshot(BatchPhase.RUNNING, None, None, (), "Scanning Kept Papers")
            self._worker = threading.Thread(target=self._execute,
                args=(workspace, browser_owner, validate_target), daemon=False, name="electron-import")
            self._worker.start()
        return self.snapshot()

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

    def _execute(self, workspace, owner, validate_target):
        results = []
        plan = None
        phase, message = BatchPhase.COMPLETED, "No eligible Papers to import"
        try:
            # Held across translation, the complete ItemSaver call and Paper commit.
            with workspace_operation_lock(workspace) as lock:
                if validate_target:
                    validate_target(lock)
                plan = plan_workspace_import(lock)
                self._publish(plan=plan)
                for paper in plan.papers:
                    if self._stop.is_set():
                        phase, message = BatchPhase.STOPPED, "Stopped; remaining Papers stay kept"
                        break
                    self.browser_lock.require(owner)
                    try:
                        reservation = _reserve_export_attempt_locked(lock, paper.paper_id,
                            expected_paper=paper, expected_papers_identity=plan.papers_identity)
                    except (RuntimeError, OSError) as error:
                        results.append(BatchPaperResult(paper.paper_id, "skipped", str(error)))
                        continue
                    self._publish(current_paper_id=paper.paper_id, message="Translating and saving once")
                    try:
                        # Serialize stop with dispatch registration; the actual result waits outside the mutex.
                        with self._mutex:
                            if self._stop.is_set():
                                phase, message = BatchPhase.STOPPED, "Stopped before next Paper"
                                break
                            state = parse_paper_state(paper.path, paper.contents)
                            metadata = {"doi": paper.doi}
                            if state is not None:
                                metadata.update({key: value for key, value in {
                                    "title": state.title, "journal": state.journal,
                                    "abstract": state.abstract, "publication_date": state.publication_date,
                                    "authors": list(state.authors), "journal_issns": list(state.journal_issns),
                                }.items() if value is not None})
                            pending = self.bridge.execute("import_paper", {"doi": paper.doi, "metadata": metadata},
                                lambda progress: self._publish(message=str(progress.get("message", "Import running"))))
                        result = pending.result()
                        completion = complete_electron_import(reservation, result, operation_lock=lock)
                        outcome = {ExportCompletionOutcome.EXPORTED:"exported", ExportCompletionOutcome.NO_EFFECT:"no_effect",
                            ExportCompletionOutcome.UNCERTAIN:"uncertain"}.get(completion.outcome,"blocked")
                        results.append(BatchPaperResult(paper.paper_id,outcome,completion.message,PdfOutcome.UNVERIFIED))
                        if outcome in {"uncertain", "blocked"}:
                            phase, message = BatchPhase.PAUSED, completion.message
                            break
                    except ElectronDisconnected:
                        results.append(BatchPaperResult(paper.paper_id,"uncertain",
                            "Electron disconnected; inspect Zotero before retrying",PdfOutcome.UNVERIFIED))
                        phase, message = BatchPhase.PAUSED, "Connection lost; no save replayed"
                        break
                    self._publish(results=tuple(results))
                if self._stop.is_set() and phase is BatchPhase.COMPLETED:
                    phase, message = BatchPhase.STOPPED, "Stopped after current save settled"
                lock.verify()
        except Exception as error:
            phase, message = BatchPhase.BLOCKED, f"Import stopped: {error}; inspect Zotero before retrying"
        finally:
            if phase is BatchPhase.COMPLETED:
                exported = sum(result.outcome == "exported" for result in results)
                message = f"Import finished: {exported} imported, {len(results) - exported} not imported; PDF unverified"
            if plan is not None and phase is not BatchPhase.COMPLETED:
                finished = {result.paper_id for result in results}
                results.extend(BatchPaperResult(paper.paper_id, "skipped", message)
                    for paper in plan.papers if paper.paper_id not in finished)
            # KeptWorkflow releases browser ownership after observing this terminal state.
            self._publish(phase=phase,results=tuple(results),current_paper_id=None,message=message)
