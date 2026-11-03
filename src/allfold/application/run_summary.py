"""Provider-independent Run result semantics shared by UI and durable history."""
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
import re
from allfold.application.crossref_retrieval import is_optional_metadata_warning


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


