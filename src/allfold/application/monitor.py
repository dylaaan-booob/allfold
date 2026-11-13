"""Integrated Run public result contract and application entry point."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from allfold.application.run_state import RunProvider, RunFacts, discovery_provider
from allfold.config import LoadedConfig
from allfold.date_range import ResolvedDateRange
from allfold.progress import ProgressCallback

class MonitorIssueSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class MonitorIssueComponent(str, Enum):
    DISCOVERY = "discovery"
    CANONICALIZATION = "canonicalization"
    MATERIALIZATION = "materialization"
    SNAPSHOT = "snapshot"


@dataclass(frozen=True)
class MonitorIssue:
    severity: MonitorIssueSeverity
    component: MonitorIssueComponent
    stage: str
    message: str


class RunOutcome(str, Enum):
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"


@dataclass(frozen=True)
class RunResult:
    provider: RunProvider
    resolved_date_range: ResolvedDateRange | None
    warnings: tuple[MonitorIssue, ...]
    errors: tuple[MonitorIssue, ...]
    outcome: RunOutcome
    facts: RunFacts


def run_monitor(config_path: Path, *, provider: RunProvider = RunProvider.INTEGRATED,
                loaded_config: LoadedConfig | None = None, workspace_snapshot=None,
                cancel_event=None, progress_callback: ProgressCallback | None = None, wos_stage=None, workflow_id=None,
                recovery_observer=None, pacing_state=None) -> RunResult:
    discovery_provider(provider)
    from allfold.application.integrated_run import run_integrated
    return run_integrated(config_path, loaded_config=loaded_config, workspace_snapshot=workspace_snapshot,
                          cancel_event=cancel_event, progress_callback=progress_callback, wos_stage=wos_stage,
                          workflow_id=workflow_id, recovery_observer=recovery_observer, pacing_state=pacing_state)
