"""Process-local coordination for one synchronous production monitor run."""

from __future__ import annotations

import logging
import threading
import secrets
from allfold.application.history import observe, finish_run
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from allfold.application.monitor import RunResult, run_monitor
from allfold.application.run_state import RunProvider, discovery_provider
from allfold.config import ConfigurationError, load_config
from allfold.application.run_commit import capture_run_workspace
from allfold.persistence.safe_write import CompareReadError, ContentChangedError
from allfold.progress import (
    PROGRESS_STAGES,
    ActivitySnapshot,
    ProgressEvent,
    ProgressStage,
    ProgressState,
)

LOGGER = logging.getLogger(__name__)

__all__ = [
    "CoordinatorStatus",
    "StartOutcome",
    "UnexpectedRunError",
    "StartResult",
    "CoordinatorSnapshot",
    "RunCoordinator",
]


class CoordinatorStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"


class StartOutcome(str, Enum):
    STARTED = "STARTED"
    ALREADY_RUNNING = "ALREADY_RUNNING"
    START_FAILED = "START_FAILED"


@dataclass(frozen=True)
class UnexpectedRunError:
    category: str
    message: str


@dataclass(frozen=True)
class StartResult:
    outcome: StartOutcome


@dataclass(frozen=True)
class CoordinatorSnapshot:
    status: CoordinatorStatus
    progress_stage: ProgressStage | None
    started_at: datetime | None
    finished_at: datetime | None
    result: RunResult | None
    unexpected_error: UnexpectedRunError | None
    provider: RunProvider | None = None
    stage_index: int | None = None
    stage_total: int = len(PROGRESS_STAGES)
    activities: tuple[ActivitySnapshot, ...] = ()
    stage_started_at: datetime | None = None
    last_activity_at: datetime | None = None
    worker_alive: bool = False
    inactivity_warning: bool = False
    task_id: str | None = None
    browser_active: bool = False
    waiting_for_user: bool = False

    @property
    def current_activity(self) -> ActivitySnapshot | None:
        return max(self.activities, key=lambda activity: activity.updated_at, default=None)


class RunCoordinator:
    """Coordinate one transient production run without persisting run state."""

    def __init__(self, config_path: Path, *, run_slot=None, diagnostics=None) -> None:
        self.diagnostics = diagnostics
        self.wos_stage = None
        self._task_id = None
        self._config_path = config_path
        self._run_slot = run_slot or threading.Lock()
        self._slot_owned = False
        self._lock = threading.Lock()
        self._status = CoordinatorStatus.IDLE
        self._provider: RunProvider | None = None
        self._progress_state = ProgressState()
        self._started_at: datetime | None = None
        self._finished_at: datetime | None = None
        self._result: RunResult | None = None
        self._unexpected_error: UnexpectedRunError | None = None
        self._worker: threading.Thread | None = None
        self._config_snapshot = None
        self._workspace_snapshot = None
        self._cancel_event = threading.Event()

    def start(self, provider: RunProvider = RunProvider.INTEGRATED) -> StartResult:
        """Start a production run on a dedicated worker if none is active."""

        provider = discovery_provider(provider)
        with self._lock:
            if self._status is CoordinatorStatus.RUNNING:
                return StartResult(StartOutcome.ALREADY_RUNNING)

            if not self._run_slot.acquire(blocking=False):
                return StartResult(StartOutcome.ALREADY_RUNNING)
            self._slot_owned = True
            self._task_id = secrets.token_hex(16)
            observe(self.diagnostics, "begin", "run", self._task_id, provider=provider.value)
            self._provider = provider
            self._status = CoordinatorStatus.RUNNING
            self._progress_state = ProgressState()
            self._started_at = datetime.now(timezone.utc)
            self._finished_at = None
            self._result = None
            self._unexpected_error = None
            self._cancel_event = threading.Event()
            try:
                config = load_config(self._config_path)
                from allfold.application.integrated_run import validate_selection
                validate_selection(config)
                self._config_snapshot = config
                self._workspace_snapshot = capture_run_workspace(self._config_path,config)
            except (ValueError, CompareReadError, ContentChangedError, OSError) as error:
                self._status = CoordinatorStatus.FINISHED
                self._finished_at = datetime.now(timezone.utc)
                self._unexpected_error = UnexpectedRunError(category=type(error).__name__,message=str(error))
                self._release_slot()
                observe(self.diagnostics, "finish", self._task_id, "failed", details={"reason":"workspace_changed"})
                return StartResult(StartOutcome.START_FAILED)
            worker = threading.Thread(
                target=self._run_worker,
                name=f"allfold-{provider.value}-run",
            )
            self._worker = worker
            try:
                # 在线程启动成功前保持锁，避免暴露 RUNNING + 尚未启动 worker 的瞬时状态。
                worker.start()
            except Exception as error:
                if self._workspace_snapshot is not None:
                    self._workspace_snapshot.close()
                self._status = CoordinatorStatus.FINISHED
                self._finished_at = datetime.now(timezone.utc)
                self._result = None
                self._unexpected_error = UnexpectedRunError(
                    category=type(error).__name__,
                    message="The monitor worker could not be started.",
                )
                self._release_slot()
                observe(self.diagnostics, "finish", self._task_id, "failed", details={"reason":"failed"})
                start_error = error
            else:
                start_error = None

        if start_error is not None:
            LOGGER.error(
                "Failed to start monitor worker",
                exc_info=(
                    type(start_error),
                    start_error,
                    start_error.__traceback__,
                ),
            )
            return StartResult(StartOutcome.START_FAILED)

        return StartResult(StartOutcome.STARTED)

    def cancel(self) -> bool:
        with self._lock:
            if self._status is not CoordinatorStatus.RUNNING:
                return False
            self._cancel_event.set()
        if self.wos_stage is not None and self.wos_stage.running:
            self.wos_stage.cancel(self._task_id)
        return True

    def _release_slot(self):
        if self._slot_owned:
            self._slot_owned = False
            self._run_slot.release()

    def snapshot(self) -> CoordinatorSnapshot:
        """Copy current transient state under the coordinator lock."""

        now = datetime.now(timezone.utc)
        with self._lock:
            worker_alive = (
                self._status is CoordinatorStatus.RUNNING
                and self._worker is not None
                and self._worker.is_alive()
            )
            progress = self._progress_state.snapshot(
                at=now,
                active=self._status is CoordinatorStatus.RUNNING and worker_alive,
            )
            return CoordinatorSnapshot(
                task_id=self._task_id,
                browser_active=bool(self.wos_stage and self.wos_stage.task and self.wos_stage.task["status"] == "RUNNING"),
                waiting_for_user=bool(self.wos_stage and self.wos_stage.task and self.wos_stage.task.get("waiting_for_user")),
                provider=self._provider,
                status=self._status,
                progress_stage=progress.progress_stage,
                started_at=self._started_at,
                finished_at=self._finished_at,
                result=self._result,
                unexpected_error=self._unexpected_error,
                stage_index=progress.stage_index,
                stage_total=progress.stage_total,
                activities=progress.activities,
                stage_started_at=progress.stage_started_at,
                last_activity_at=progress.last_activity_at,
                worker_alive=worker_alive,
                inactivity_warning=progress.inactivity_warning,
            )

    def _update_progress(self, event: ProgressEvent) -> None:
        with self._lock:
            if self._status is CoordinatorStatus.RUNNING:
                self._progress_state.apply(
                    event,
                    at=datetime.now(timezone.utc),
                )

    def _run_worker(self) -> None:
        result: RunResult | None = None
        unexpected_error: UnexpectedRunError | None = None
        try:
            result = run_monitor(self._config_path, provider=self._provider,
                progress_callback=self._update_progress, loaded_config=self._config_snapshot,
                workspace_snapshot=self._workspace_snapshot, cancel_event=self._cancel_event,
                wos_stage=self.wos_stage.execute_stage if self.wos_stage else None, workflow_id=self._task_id)
        except BaseException as error:
            LOGGER.exception("Unexpected exception during monitor run")
            unexpected_error = UnexpectedRunError(
                category=type(error).__name__,
                message="The monitor run stopped because of an unexpected internal error.",
            )
        finally:
            if self._workspace_snapshot is not None:
                self._workspace_snapshot.close()
                self._workspace_snapshot = None
            with self._lock:
                self._result = result if unexpected_error is None else None
                self._unexpected_error = unexpected_error
                self._finished_at = datetime.now(timezone.utc)
                self._status = CoordinatorStatus.FINISHED
                self._release_slot()
                native = self.wos_stage.task if self.wos_stage is not None else None
                diagnostic = native.get('diagnostic') if native and native['id'] == self._task_id else None
                finish_run(self.diagnostics, self._task_id, self._result, provider=self._provider.value, diagnostic=diagnostic)
