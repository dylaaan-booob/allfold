"""Provider-independent Run result semantics shared by UI and durable history."""
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum


def _encode(value):
    if hasattr(value, 'model_dump'):
        return value.model_dump(mode='json')
    if is_dataclass(value):
        return _encode(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key:_encode(item) for key,item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


def _visible_result_facts(facts: dict, provider: str) -> tuple[list, list, dict]:
    """Keep useful Journal and date notices from current Run facts."""
    journals = []
    for journal in facts.get("journals", []):
        identifiers = []
        for item in journal["identifiers"]:
            if (item["status"] != "unknown" or item.get("records", 0) or
                    item.get("source_id") or item.get("message")):
                identifiers.append(item)
        journal["identifiers"] = identifiers
        if journal["status"] != "unknown" or journal.get("records", 0) or identifiers:
            journals.append(journal)

    details = facts.get("details", {})
    if provider == "wos":
        dates = []
        for warning in details.get("date_warnings", []):
            warning["reasons"] = [reason for reason in warning.get("reasons", [])
                                  if reason not in ("EA_fallback", "year_only")]
            if warning["reasons"]:
                dates.append(warning)
        details["date_warnings"] = dates

    issues = []
    for issue in facts.get("issues", []):
        message = issue["message"]
        if issue.get("severity") != "error":
            if (provider == "wos" and any(j["status"] == "hint" for j in journals) and
                    message.startswith("未列入当前本地 WoS 来源清单（")):
                continue
        issues.append(issue)
    return journals, issues, details


def build_run_result_summary(record: object) -> dict[str, object] | None:
    """Project current or saved facts through one Provider-independent interface."""
    if record is None:
        return None
    raw = _encode(record)
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
            details={}, issues=[dict(category="runtime", severity="error", message=error["message"])])
    facts = result.get("facts") or {}
    outcome = result.get("outcome")
    provider = result.get("provider", raw.get("provider"))
    journals, issues, details = _visible_result_facts(facts, provider)
    if provider == "integrated":
        coverage_status = details.get('discovery_status', 'unknown')
    elif provider == "wos":
        coverage_status = ("complete" if details.get("query_finished") and all(b["complete"] for b in details.get("batches", []))
                           else "partial" if result.get("returned_records") else "failed")
    else:
        coverage_status = "unknown"
    if outcome in ("Cancelled", "CANCELLED"):
        status = "cancelled"
    elif outcome in ("Failed", "FAILED"):
        status = "failed"
    elif coverage_status == "failed":
        status = "failed"
    elif coverage_status == "partial":
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
        coverage_status=coverage_status, journals=journals,
        issues=issues, statistics=statistics, details=details)


