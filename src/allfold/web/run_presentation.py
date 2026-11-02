"""Pure presentation helpers for the Local Web run panel."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from fastapi.encoders import jsonable_encoder

from allfold.application.crossref_retrieval import is_optional_metadata_warning
from allfold.progress import ActivityKind, ActivitySnapshot, ProgressStage
from allfold.application.coordinators.run_coordinator import (
    CoordinatorSnapshot,
    CoordinatorStatus,
)

_STAGE_LABELS = {
    ProgressStage.CHECKING_MONITOR: "Checking monitor",
    ProgressStage.DISCOVERING_PAPERS: "Discovering papers",
    ProgressStage.PREPARING_PAPERS: "Preparing papers",
    ProgressStage.MATCHING_LITERATURE: "Matching literature",
    ProgressStage.UPDATING_WORKSPACE: "Capturing papers",
}

_SOURCE_LABELS = {
    "application": "Application",
    "crossref": "Crossref",
    "openalex": "OpenAlex",
    "pubmed": "PubMed",
    "workspace": "Workspace",
}

_UNIT_LABELS = {
    "doi": ("DOI", "DOI"),
    "issn": ("ISSN", "ISSNs"),
    "file": ("file", "files"),
    "journal": ("journal", "journals"),
    "paper": ("paper", "papers"),
    "work": ("work", "works"),
}


def _visible_result_facts(facts: dict, provider: str) -> tuple[list, list, dict]:
    """Filter known noise from encoded facts, including already saved schema-v4 runs."""
    journals = []
    for journal in facts.get("journals", []):
        identifiers = []
        for item in journal["identifiers"]:
            if provider == "crossref" and item.get("message"):
                item["message"] = "; ".join(message for message in item["message"].split("; ")
                                             if not is_optional_metadata_warning(message)) or None
            if (item["status"] != "unknown" or item.get("records", 0) or
                    item.get("source_id") or item.get("message")):
                identifiers.append(item)
        journal["identifiers"] = identifiers
        if journal["status"] != "unknown" or journal.get("records", 0) or identifiers:
            journals.append(journal)

    details = facts.get("details", {})
    if provider == "openalex" and "source_resolution" in details:
        details["source_resolution"] = {key: value for key, value in details["source_resolution"].items()
                                         if key != "resolved" and value}
    if provider == "crossref" and not any(details.get("manifest", {}).get(key) for key in ("partial", "failed")):
        details.pop("manifest", None)
    if provider == "pubmed" and "skipped" in details:
        details["skipped"].pop("doi_conflict", None)
    if provider == "wos":
        dates = []
        for warning in details.get("date_warnings", []):
            warning["reasons"] = [reason for reason in warning.get("reasons", [])
                                  if reason not in ("EA_fallback", "year_only")]
            if warning["reasons"]:
                dates.append(warning)
        details["date_warnings"] = dates

    issues = []
    missing_identifiers = {item["issn"]: item for journal in journals
                           for item in journal["identifiers"] if item["status"] == "not_found"}
    for issue in facts.get("issues", []):
        message = issue["message"]
        if provider == "crossref" and issue["category"] in ("notice", "retrieval") and is_optional_metadata_warning(message):
            continue
        if issue.get("severity") != "error":
            if provider == "openalex" and message == "work has neither a valid DOI nor a usable title":
                continue
            if provider == "pubmed":
                if (message == "Unknown PubModel; selected reliable publication date with PubDate priority" or
                        (issue["category"] == "exclusion" and re.fullmatch(r"PubMed skipped \d+ records: doi_conflict", message))):
                    continue
                if message.startswith("PubMed ESearch PhraseNotFound: ") and issue.get("issn") in missing_identifiers:
                    item = missing_identifiers[issue["issn"]]
                    item["message"] = item.get("message") or message
                    continue
            if (provider == "wos" and any(j["status"] == "hint" for j in journals) and
                    message.startswith("未列入当前本地 WoS 来源清单（")):
                continue
        issues.append(issue)
    return journals, issues, details


def build_run_result_summary(record: object) -> dict[str, object] | None:
    """Project current or saved facts through one Provider-independent interface."""
    if record is None:
        return None
    raw = jsonable_encoder(record)
    if raw.get("status") in ("not_found", "invalid", "unsupported"):
        return {"availability": raw["status"], "error": raw.get("error")}
    if "snapshot" in raw:
        return build_run_result_summary(raw["snapshot"])
    result = raw.get("result") if "result" in raw else raw
    if result is None:
        error = raw.get("unexpected_error")
        if not error:
            return None
        return dict(availability="available", provider=raw.get("provider"), status="failed",
            outcome="FAILED", coverage_status="unknown", created_papers=None, existing_papers=None,
            finished_at=raw.get("finished_at"), resolved_date_range=None, journals=[], statistics={},
            details={}, coverage=[], issues=[dict(category="runtime", severity="error", message=error["message"])])
    facts = result.get("facts") or {}
    coverage = result.get("coverage", raw.get("coverage", []))
    outcome = result.get("outcome")
    provider = result.get("provider", raw.get("provider"))
    journals, issues, details = _visible_result_facts(facts, provider)
    statuses = {unit["status"] for unit in coverage}
    if provider == "wos":
        coverage_status = ("complete" if details.get("query_finished") and all(b["complete"] for b in details.get("batches", []))
                           else "partial" if result.get("returned_records") else "failed")
    else:
        coverage_status = ("complete" if statuses == {"COMPLETE"} else
                           "partial" if "COMPLETE" in statuses or "PARTIAL" in statuses else
                           "failed" if "FAILED" in statuses else "unavailable" if statuses else "unknown")
    if outcome in ("Cancelled", "CANCELLED"):
        status = "cancelled"
    elif outcome in ("INVALID_CONFIGURATION", "Failed", "FAILED"):
        status = "failed"
    elif coverage_status in ("partial", "failed", "unavailable"):
        status = "incomplete"
    elif outcome == "Partial" or any(i.get("severity") == "error" for i in issues):
        status = "capture_issues"
    elif (provider == "wos" and (result.get("unmatched_journal_records", 0) > 0 or details.get("date_warnings"))) or any(i["category"] != "exclusion" for i in issues) or any(
        j["status"] not in ("complete", "empty", "observed", "unknown") or
        any(i["status"] not in ("resolved", "complete", "empty", "unknown") for i in j["identifiers"])
        for j in journals
    ):
        status = "completed_with_notices"
    else:
        status = "completed"
    statistics = facts.get("statistics", {})
    statistics = {key: value for key, value in statistics.items()
                  if key not in ("evidence_clusters", "retained_clusters") and
                  (provider == "wos" or key.startswith(provider + "_"))}
    if provider == "wos":
        # Batch details remain the single display location; status still uses all failures.
        batch_messages = {f"{batch['first']}-{batch['last']}: {message}"
                          for batch in details.get("batches", []) for message in batch.get("issues", [])}
        issues = [issue for issue in issues
                  if not (issue["category"] == "retrieval" and issue["message"] in batch_messages)]
    return dict(availability="available", provider=provider, status=status, outcome=outcome,
        finished_at=facts.get("finished_at") or raw.get("finished_at"),
        resolved_date_range=result.get("resolved_date_range", raw.get("resolved_date_range")) or
            (dict(from_date=raw["from_date"], to_date=raw["to_date"]) if raw.get("from_date") else None),
        created_papers=facts.get("created_papers"), existing_papers=facts.get("existing_papers"),
        coverage_status=coverage_status, coverage=coverage, journals=journals,
        issues=issues, statistics=statistics, details=details)


def _duration_text(seconds: float) -> str:
    whole_seconds = max(0, int(seconds))
    minutes, seconds = divmod(whole_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _source_label(source: str | None) -> str | None:
    if source is None:
        return None
    return _SOURCE_LABELS.get(source, source.replace("_", " ").title())


def _unit_label(unit: str | None, value: int) -> str | None:
    if unit is None:
        return None
    singular, plural = _UNIT_LABELS.get(
        unit,
        (unit.replace("_", " "), f"{unit.replace('_', ' ')}s"),
    )
    return singular if value == 1 else plural


def _activity_counter(activity: ActivitySnapshot) -> tuple[str | None, bool]:
    current = activity.current
    total = activity.total
    if current is None or current < 0:
        return None, False
    if total is not None and total >= 0 and current <= total:
        unit = _unit_label(activity.unit, total)
        text = f"{current} / {total}" + (f" {unit}" if unit else "")
        return text, total > 0
    unit = _unit_label(activity.unit, current)
    text = f"{current}" + (f" {unit}" if unit else "") + " processed"
    return text, False


def _semantic_key(*parts: str) -> str:
    identity = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(identity).hexdigest()[:16]


def _announcement(
    snapshot: CoordinatorSnapshot,
    *,
    stage_label: str | None,
    activities: tuple[ActivitySnapshot, ...],
) -> tuple[str, str]:
    label = snapshot.provider.label if snapshot.provider is not None else "Run"
    provider = snapshot.provider.value if snapshot.provider is not None else ""
    if snapshot.status is CoordinatorStatus.IDLE:
        return _semantic_key("idle"), "Monitor ready."

    if snapshot.status is CoordinatorStatus.RUNNING and not snapshot.worker_alive:
        return (
            _semantic_key("running", provider, "worker-stopped"),
            f"{label} stopped. The monitor worker is no longer active.",
        )

    if snapshot.status is CoordinatorStatus.FINISHED:
        if snapshot.result is not None:
            outcome = snapshot.result.outcome.value
            return (
                _semantic_key("finished", provider, "result", outcome),
                f"{label} finished: {outcome}.",
            )
        if snapshot.unexpected_error is not None:
            category = snapshot.unexpected_error.category
            return (
                _semantic_key("finished", provider, "error", category),
                f"{label} stopped because of an unexpected internal error.",
            )
        return _semantic_key("finished", provider), f"{label} finished."

    parts = ["running", provider]
    message_parts = [f"{label} in progress."]
    if snapshot.progress_stage is not None:
        parts.append(snapshot.progress_stage.value)
        if stage_label is not None and snapshot.stage_index is not None:
            message_parts.append(
                f"Stage {snapshot.stage_index} of {snapshot.stage_total}: "
                f"{stage_label}."
            )
    else:
        parts.append("starting")
        message_parts.append("Starting.")

    for activity in activities:
        parts.extend(
            (
                activity.kind.value,
                activity.source or "",
                activity.operation,
                activity.label,
            )
        )
        source = _source_label(activity.source)
        if source is not None:
            message_parts.append(f"{source}.")
        if activity.kind is ActivityKind.RETRYING:
            message_parts.append("Retrying.")
        elif activity.kind is ActivityKind.WAITING:
            message_parts.append("Waiting.")
        message_parts.append(f"{activity.label}.")

    parts.append(
        "inactive" if snapshot.inactivity_warning else "active"
    )
    if snapshot.inactivity_warning:
        message_parts.append("No recent activity.")

    return _semantic_key(*parts), " ".join(message_parts)


def _activity_presentation(
    activity: ActivitySnapshot, *, now: datetime, inactivity_warning: bool,
) -> dict[str, object]:
    activity_counter, activity_determinate = _activity_counter(activity)
    activity_source = _source_label(activity.source)
    activity_state = (
        activity.kind.value.title()
        if activity.kind is not ActivityKind.WORKING
        else None
    )

    eta_text: str | None = None
    estimating = False
    if (
        activity.kind is ActivityKind.WORKING
        and not inactivity_warning
    ):
        if activity.eta_seconds is not None:
            eta_text = _duration_text(activity.eta_seconds)
        elif (
            activity.current is not None
            and activity.total is not None
            and activity.current >= 0
            and activity.total >= 0
            and activity.current <= activity.total
            and activity.total > activity.current
        ):
            estimating = True

    return {
        "activity": activity,
        "activity_source": activity_source,
        "activity_state": activity_state,
        "activity_counter": activity_counter,
        "activity_determinate": activity_determinate,
        "eta_text": eta_text,
        "estimating": estimating,
        "age_text": _duration_text((now - activity.updated_at).total_seconds()),
    }


def build_run_presentation(
    snapshot: CoordinatorSnapshot,
    *,
    now: datetime,
) -> dict[str, object]:
    """Derive display-only fields without mutating coordinator state."""

    stage_label = (
        _STAGE_LABELS[snapshot.progress_stage]
        if snapshot.progress_stage is not None
        else None
    )
    elapsed_end = now if snapshot.status is CoordinatorStatus.RUNNING else snapshot.finished_at
    elapsed_text = (
        _duration_text((elapsed_end - snapshot.started_at).total_seconds())
        if snapshot.started_at is not None
        and elapsed_end is not None
        else None
    )
    last_activity_text = (
        _duration_text((now - snapshot.last_activity_at).total_seconds())
        if snapshot.last_activity_at is not None
        else None
    )

    announcement_key, announcement_message = _announcement(
        snapshot,
        stage_label=stage_label,
        activities=snapshot.activities,
    )

    return {
        "stage_label": stage_label,
        "elapsed_text": elapsed_text,
        "last_activity_text": last_activity_text,
        "activities": tuple(
            _activity_presentation(activity, now=now, inactivity_warning=snapshot.inactivity_warning)
            for activity in snapshot.activities
        ),
        "announcement_key": announcement_key,
        "announcement_message": announcement_message,
    }
