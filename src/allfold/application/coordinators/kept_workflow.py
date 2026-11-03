"""Process-local sequencing of existing Kept executors."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import secrets
import threading
import time
from typing import TYPE_CHECKING

from allfold.application.batch_import import BatchImportService, BatchPhase, BatchSnapshot
from allfold.application.history import observe, batch_history
from allfold.config import ConfigurationError, KeptWorkflowConfig, LoadedConfig
from allfold.persistence.safe_write import ContentChangedError
from allfold.application.coordinators.preparation_coordinator import (
    PreparationCoordinator, PreparationOutcome, PreparationPhase,
)

if TYPE_CHECKING:
    from allfold.application.import_target import _ImportTarget


@dataclass(frozen=True)
class WorkflowSnapshot:
    workflow_id: str | None = None
    generation: int = 0
    mode: str = "full"
    phase: str = "idle"
    settings: KeptWorkflowConfig = KeptWorkflowConfig()
    institution_name: str | None = None
    preparation_task_id: str | None = None
    preparation_generation: int = 0
    waiting_for_login: bool = False
    import_started: bool = False
    transition_deadline: float | None = None
    message: str = "Ready to prepare access and import Kept Papers."
    navigation: str | None = None

    @property
    def active(self) -> bool:
        return self.phase in {"preparing", "waiting_for_user", "transition", "importing", "stopping"}

    @property
    def can_continue(self) -> bool:
        return self.phase == "waiting_for_user" and not self.waiting_for_login

    @property
    def can_cancel(self) -> bool:
        return self.active and self.phase != "stopping"


class KeptWorkflow:
    def __init__(self, preparation: PreparationCoordinator, batch: BatchImportService,
                 lock: threading.RLock, *,
                 begin_import: Callable[[_ImportTarget, str], BatchSnapshot],
                 has_kept: Callable[[_ImportTarget], bool],
                 clock: Callable[[], float] = time.monotonic, browser_lock, diagnostics=None):
        self.diagnostics = diagnostics
        self._cancel_requested = False
        self.preparation = preparation
        self.batch = batch
        self._lock = lock
        self._begin_import = begin_import
        self._has_kept = has_kept
        self._clock = clock
        self.browser_lock = browser_lock
        self.browser_owner = None
        self._snapshot = WorkflowSnapshot()
        self._target: _ImportTarget | None = None
        self._authorization: str | None = None
        self._due: float | None = None
        self._stop = threading.Event()

    def snapshot(self) -> WorkflowSnapshot:
        with self._lock:
            return self._snapshot

    def _publish(self, **changes) -> None:
        self._snapshot = replace(self._snapshot, **changes)

    def clear_terminal(self) -> None:
        with self._lock:
            if self._snapshot.active or self.batch.running:
                raise RuntimeError("Cannot clear an active Kept workflow")
            self._stop.set()
            self._release_browser()
            self._target = self._authorization = self._due = None
            self._snapshot = WorkflowSnapshot(generation=self._snapshot.generation + 1)

    def start(self, target: _ImportTarget, config: LoadedConfig, authorization: str,
              *, mode: str = "full") -> WorkflowSnapshot:
        with self._lock:
            if self._snapshot.active:
                return self._snapshot
            self.browser_owner = self.browser_lock.acquire("kept")
            if self.browser_owner is None:
                self._publish(phase="interrupted", message="Browser runtime is busy")
                return self._snapshot
            self._stop.set()
            self._stop = threading.Event()
            self._target, self._authorization, self._due = target, authorization, None
            self._snapshot = WorkflowSnapshot(
                workflow_id=secrets.token_urlsafe(24), generation=self._snapshot.generation + 1,
                mode=mode, phase="preparing", settings=config.kept_workflow,
                institution_name=config.institution.name if config.institution else None,
            )
            self._cancel_requested = False
            observe(self.diagnostics, "begin", "kept", self._snapshot.workflow_id)
            try:
                if not self._has_kept(target):
                    self._interrupt("No Kept Papers to import.", reason="no_kept_papers")
                elif mode == "import_only":
                    self._start_import()
                else:
                    preparation = self.preparation.start(target.config_path, browser_owner=self.browser_owner,
                        workflow_id=self._snapshot.workflow_id, parent_task_id=self._snapshot.workflow_id)
                    self._publish(preparation_task_id=preparation.task_id,
                                  preparation_generation=preparation.generation)
                    if preparation.phase in {PreparationPhase.BLOCKED, PreparationPhase.STOPPED}:
                        self._interrupt(preparation.message)
                    else:
                        self.advance()
            except (ConfigurationError, ContentChangedError, OSError, RuntimeError, ValueError) as error:
                self._interrupt(str(error))
            if self._snapshot.active:
                try:
                    threading.Thread(target=self._run,
                                     args=(self._snapshot.workflow_id, self._snapshot.generation, self._stop),
                                     daemon=True, name="kept-workflow").start()
                except BaseException:
                    # This observation cannot release native/Workspace ownership or settle a save.
                    observe(self.diagnostics, "finish", self._snapshot.workflow_id,
                        "uncertain" if self._snapshot.import_started else "interrupted",
                        details={"reason":"result_unconfirmed", "result_known":False,
                            "mode":self._snapshot.mode})
                    raise
            return self._snapshot

    def _release_browser(self) -> None:
        if self.browser_owner is not None:
            self.browser_lock.release(self.browser_owner)
            self.browser_owner = None

    def _interrupt(self, message: str, *, reason="failed") -> None:
        self._release_browser()
        observe(self.diagnostics, "finish", self._snapshot.workflow_id,
            "cancelled" if self._cancel_requested else "interrupted",
            details={"reason":"cancelled" if self._cancel_requested else reason, "mode":self._snapshot.mode})
        self._authorization = None
        self._publish(phase="interrupted", message=message, transition_deadline=None,
                      waiting_for_login=False, navigation="kept")

    def _start_import(self) -> None:
        # All callers share the existing submission lock; only this path consumes the grant.
        if self._snapshot.import_started or self._authorization is None:
            return
        self._publish(import_started=True, phase="importing", transition_deadline=None, waiting_for_login=False,
                      message="Importing all eligible Workspace Kept Papers.")
        authorization, self._authorization = self._authorization, None
        try:
            result = self._begin_import(self._target, authorization,
                workflow_id=self._snapshot.workflow_id, parent_task_id=self._snapshot.workflow_id)
            self._finish_import(result)
        except (ConfigurationError, ContentChangedError, OSError) as error:
            self._interrupt(str(error))
            return

    def _finish_import(self, result: BatchSnapshot) -> None:
        if result.phase is BatchPhase.RUNNING:
            if self._snapshot.phase == "importing":
                self._publish(message=result.message)
            return
        outcome, counts, details = batch_history(result)
        if self._cancel_requested and outcome != "uncertain":
            outcome = "cancelled"
            details["reason"] = "cancelled"
        details["mode"] = self._snapshot.mode
        observe(self.diagnostics, "finish", self._snapshot.workflow_id,
            "completed" if outcome == "confirmed" else outcome, statistics=counts, details=details)
        if result.phase is not BatchPhase.COMPLETED:
            self._interrupt(result.message)
            return
        self._release_browser()
        self._publish(phase="completed", message=result.message, navigation="kept")

    def advance(self) -> None:
        """Worker tick; GET/presentation never calls this method."""
        with self._lock:
            state = self._snapshot
            try:
                if state.phase == "stopping" and not state.import_started:
                    if not self.preparation.snapshot().authorization_pending:
                        self._interrupt("Workflow canceled; no automatic Import will start.")
                elif state.phase in {"importing", "stopping"}:
                    self._finish_import(self.batch.snapshot())
                elif state.phase == "transition":
                    if self._clock() >= self._due:
                        self._start_import()
                elif state.phase in {"preparing", "waiting_for_user"}:
                    preparation = self.preparation.snapshot()
                    if (preparation.task_id, preparation.generation) != (
                            state.preparation_task_id, state.preparation_generation):
                        self._interrupt("Preparation task changed; start a new explicit workflow.")
                    elif preparation.phase in {PreparationPhase.BLOCKED, PreparationPhase.STOPPED}:
                        self._interrupt(preparation.message)
                    elif preparation.phase is PreparationPhase.RUNNING:
                        self._publish(
                            phase="waiting_for_user" if preparation.waiting_for_user else "preparing",
                            waiting_for_login=preparation.waiting_for_user,
                            message="Waiting for institution login in BROWSER." if preparation.waiting_for_user
                            else preparation.message,
                        )
                    elif preparation.phase is PreparationPhase.COMPLETED and (state.phase == "preparing" or state.waiting_for_login):
                        safe = (not preparation.manual_services and all(
                            item.outcome is PreparationOutcome.OPENED for item in preparation.results))
                        if state.settings.auto_import_after_preparation and safe:
                            delay = state.settings.transition_delay_seconds
                            self._due = self._clock() + delay
                            self._publish(phase="transition", waiting_for_login=False, transition_deadline=time.time() + delay,
                                          message="Preparation finished. Import will start after the transition delay.")
                        else:
                            self._publish(phase="waiting_for_user", waiting_for_login=False,
                                          message="Review Service access and results, then continue to Import.")
            except (ConfigurationError, ContentChangedError, OSError) as error:
                self._interrupt(str(error))

    def _matches(self, workflow_id: str, generation: int) -> bool:
        return (workflow_id, generation) == (self._snapshot.workflow_id, self._snapshot.generation)

    def continue_import(self, workflow_id: str, generation: int) -> bool:
        with self._lock:
            if not self._matches(workflow_id, generation) or not self._snapshot.can_continue:
                return False
            self._start_import()
            return True

    def cancel(self, workflow_id: str, generation: int) -> bool:
        with self._lock:
            if not self._matches(workflow_id, generation) or not self._snapshot.can_cancel:
                return False
            self._cancel_requested = True
            if self._snapshot.import_started:
                self.batch.stop()
                self._publish(phase="stopping", message="Stopping; waiting for the current operation to settle",
                              transition_deadline=None, navigation="kept")
                return True
            if self._snapshot.preparation_task_id:
                self.preparation.cancel(self._snapshot.preparation_task_id, self._snapshot.preparation_generation)
                if self.preparation.snapshot().authorization_pending:
                    self._publish(phase="stopping", waiting_for_login=False,
                                  message="Stopping; waiting for Preparation to settle", transition_deadline=None)
                    return True
            self._interrupt("Workflow canceled; no automatic Import will start.")
            self._stop.set()
            return True

    def acknowledge_navigation(self, workflow_id: str, generation: int) -> bool:
        with self._lock:
            if not self._matches(workflow_id, generation):
                return False
            self._publish(navigation=None)
            return True

    def _run(self, workflow_id: str, generation: int, stop: threading.Event) -> None:
        while not stop.wait(0.1):
            with self._lock:
                if not self._matches(workflow_id, generation) or not self._snapshot.active:
                    return
                self.advance()

    def shutdown(self) -> None:
        with self._lock:
            self.cancel(self._snapshot.workflow_id, self._snapshot.generation)
            self._stop.set()
