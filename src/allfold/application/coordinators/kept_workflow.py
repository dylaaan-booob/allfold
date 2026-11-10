"""Process-local ownership and result projection for one fixed Kept Import."""
from __future__ import annotations

from dataclasses import dataclass, replace
import secrets
import threading

from allfold.application.batch_import import BatchImportService, BatchPhase
from allfold.application.history import observe, batch_history
from allfold.persistence.safe_write import ContentChangedError


@dataclass(frozen=True)
class WorkflowSnapshot:
    workflow_id: str | None = None
    generation: int = 0
    phase: str = "idle"
    message: str = "Ready to import Kept Papers."
    navigation: str | None = None
    service_id: str | None = None
    planned_total: int = 0

    @property
    def active(self) -> bool:
        return self.phase in {"importing", "stopping"}

    @property
    def can_cancel(self) -> bool:
        return self.phase == "importing"


class KeptWorkflow:
    def __init__(self, batch: BatchImportService, login, lock, *, browser_lock, diagnostics=None):
        self.batch = batch
        self.login = login
        self.browser_lock = browser_lock
        self.diagnostics = diagnostics
        self._lock = lock
        self._snapshot = WorkflowSnapshot()
        self._worker = None

    def snapshot(self) -> WorkflowSnapshot:
        with self._lock:
            return self._snapshot

    def clear_terminal(self) -> None:
        with self._lock:
            if self._snapshot.active or self.batch.running:
                raise RuntimeError("Cannot clear an active Kept workflow")
            self._snapshot = WorkflowSnapshot(generation=self._snapshot.generation + 1)

    def unprepared_services(self, saved, papers, service_id=None):
        required = {paper.service_id for paper in papers if service_id is None or paper.service_id == service_id}
        return [dict(id=service.id, name=service.name) for service in saved.services
                if service.id in required and self.login.prepared_page(saved, service.id) is None]

    def start(self, target, settings, saved, *, skip_unprepared) -> WorkflowSnapshot:
        with self._lock:
            if self._snapshot.active or self.batch.running:
                raise ContentChangedError("A fixed Kept batch is already active; selection cannot retarget it.")
            owner = self.browser_lock.acquire("kept")
            if owner is None:
                raise ContentChangedError("Browser runtime is busy; no batch started.")
            batch_started = False
            try:
                self._start_batch(owner, target, settings, saved, skip_unprepared)
                batch_started = True
                self._worker = threading.Thread(target=self._settle, args=(owner,),
                    daemon=False, name="kept-workflow")
                try:
                    self._worker.start()
                except BaseException:
                    # Preserve ownership and aggregate actual outcomes even if a
                    # separate projection thread cannot be started.
                    self._settle(owner)
                    raise
            finally:
                if not batch_started:
                    self.browser_lock.release(owner)
            return self._snapshot

    def _start_batch(self, owner, target, settings, saved, skip_unprepared):
        plan = target.paper_plan
        if plan is None or not plan.papers:
            raise ContentChangedError("No Kept Papers to import.")
        if target.zotero_target is None:
            raise ContentChangedError("Choose and authorize a Zotero Library/Collection in Queue before starting.")
        saved.verify()
        unprepared = self.unprepared_services(saved, plan.papers)
        missing = {item["id"] for item in unprepared}
        if missing != set(skip_unprepared) or len(missing) != len(skip_unprepared):
            raise ContentChangedError("Review Login results or explicitly confirm the unprepared Services to skip.")
        zotero_target = target.zotero_target.model_dump()
        if any(paper.service_id not in missing for paper in plan.papers):
            checked = self.batch.bridge.execute("zotero_local", {
                "operation": "validate", "target": zotero_target,
            }).result()
            if not checked.get("ok"):
                raise ContentChangedError("Zotero target is unavailable: " + str(checked.get("error", "api_failure")))
        workflow_id = secrets.token_urlsafe(24)
        self._snapshot = WorkflowSnapshot(workflow_id=workflow_id,
            generation=self._snapshot.generation + 1, phase="importing", service_id=target.service_id,
            planned_total=len(plan.papers), message="Importing the fixed eligible Kept scope.")
        observe(self.diagnostics, "begin", "kept", workflow_id,
            details={"batch_scope": "service" if target.service_id else "all", "service_id": target.service_id,
                "config_revision": target.config_digest, "user_state_revision": target.user_state_revision})
        try:
            self.batch.start(target.workspace, browser_owner=owner, validate_target=target.verify,
                services=saved, workflow_id=workflow_id, parent_task_id=workflow_id,
                service_id=target.service_id, initial_plan=plan, zotero_target=zotero_target,
                skip_unprepared=missing, paper_limit=settings.paper_global_concurrency,
                service_limit=settings.paper_service_concurrency,
                native_limits={"translator": settings.translator_concurrency, "pdf": settings.pdf_concurrency,
                    "writer": settings.zotero_writer_concurrency})
        except BaseException:
            observe(self.diagnostics, "finish", workflow_id, "interrupted", details={"reason": "failed"})
            self._snapshot = replace(self._snapshot, phase="interrupted", message="Unable to start Import.")
            raise

    def _settle(self, owner) -> None:
        self.batch.join()
        with self._lock:
            result = self.batch.snapshot()
            outcome, counts, details = batch_history(result)
            if self._snapshot.phase == "stopping" and outcome != "uncertain":
                outcome = "cancelled"
                details["reason"] = "cancelled"
            observe(self.diagnostics, "finish", self._snapshot.workflow_id,
                "completed" if outcome == "confirmed" else outcome, statistics=counts, details=details)
            self._snapshot = replace(self._snapshot,
                phase="completed" if result.phase is BatchPhase.COMPLETED else "interrupted",
                message=result.message, navigation="kept")
            self.browser_lock.release(owner)

    def _matches(self, workflow_id: str, generation: int) -> bool:
        return (workflow_id, generation) == (self._snapshot.workflow_id, self._snapshot.generation)

    def cancel(self, workflow_id: str, generation: int) -> bool:
        with self._lock:
            if not self._matches(workflow_id, generation) or not self._snapshot.can_cancel:
                return False
            if self.batch.snapshot().phase is not BatchPhase.RUNNING:
                return False
            self.batch.stop()
            self._snapshot = replace(self._snapshot, phase="stopping",
                message="Stopping; waiting for active operations to settle")
            return True

    def acknowledge_navigation(self, workflow_id: str, generation: int) -> bool:
        with self._lock:
            if not self._matches(workflow_id, generation):
                return False
            self._snapshot = replace(self._snapshot, navigation=None)
            return True

    def shutdown(self) -> None:
        with self._lock:
            self.cancel(self._snapshot.workflow_id, self._snapshot.generation)

    def join(self) -> None:
        if self._worker is not None:
            self._worker.join()
