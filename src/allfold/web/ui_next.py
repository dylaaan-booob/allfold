"""JSON and page adapters for the four-page frontend."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import secrets
from typing import Literal
from uuid import UUID

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from allfold.application.decisions import DecisionOutcome, keep_paper, reject_paper
from allfold.application.journal_covers import cover_details
from allfold.application.run_state import RunProvider, read_last_run_snapshot
from allfold.application.workspace import journal_for_paper, load_workspace
from allfold.application.journal_lookup import journal_metadata
from allfold.persistence.user_state import load_user_state, read_user_state
from allfold.config import ConfigurationError, load_config
from allfold.models import WorkflowStatus
from allfold.keywords import parse_keyword_expression
from allfold.persistence.safe_write import ContentChangedError
from allfold.application.coordinators.run_coordinator import StartOutcome
from allfold.providers.wos import compile_wos_query
from allfold.providers.integrated import PROVIDERS, compile_query
from allfold.application.integrated_run import validate_selection
from allfold.integrations.openalex_credentials import read_credential, OpenAlexCredentialError
from allfold.web.run_presentation import build_run_presentation, build_run_result_summary


def ui_next_page() -> FileResponse:
    page = Path(__file__).parent / "static/ui_next/index.html"
    if not page.is_file():
        raise RuntimeError("UI resources are missing; run npm --prefix electron run setup")
    return FileResponse(page,
                        headers={"Cache-Control": "no-store"})


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csrf_token: str | None = None


class _Decision(_Action):
    expected_status: WorkflowStatus


class _RunStart(_Action):
    provider: Literal[RunProvider.INTEGRATED] = RunProvider.INTEGRATED
    enabled_providers: tuple[str, ...] | None = None


class _RunExpression(_Action):
    keyword_expression: str = Field(default="", max_length=20000)


def provider_expressions(text: str):
    values = {}
    try:
        ast = parse_keyword_expression(text)
    except ValueError as error:
        return {provider: {"expression": None, "error": str(error)} for provider in (*PROVIDERS,"integrated","wos")}
    for provider in (*PROVIDERS,"integrated","wos"):
        try:
            compiled = compile_wos_query(ast) if provider == "wos" else compile_query(ast,provider) if provider in {"openalex","europe_pmc","zbmath"} else text
            values[provider] = {"expression": compiled, "error": ""}
        except ValueError as error:
            values[provider] = {"expression": None, "error": str(error)}
    return values


class _WoSCancel(_Action):
    task_id: str


def install_ui_next(app: FastAPI, config_path: Path, csrf_token: str, *, read_target) -> None:
    def valid(body: _Action) -> bool:
        return secrets.compare_digest((body.csrf_token or "").encode(), csrf_token.encode())

    def response(data, status=200):
        return JSONResponse(jsonable_encoder(data), status_code=status,
                            headers={"Cache-Control": "no-store"})

    @app.get("/ui-next", include_in_schema=False)
    @app.get("/ui-next/", include_in_schema=False)
    def page():
        return ui_next_page()

    @app.get("/api/ui-next/workspace")
    def workspace_data():
        try:
            target, config = read_target(config_path)
            state_snapshot = load_user_state(config_path, config.venue_whitelist)
            settings_list = state_snapshot.state
            journals, services = settings_list.journals, settings_list.access_services
            workspace = load_workspace(target.workspace, journals=journals)
            current, _ = read_target(config_path)
            if current != target or read_user_state(config_path).revision != state_snapshot.revision:
                raise ContentChangedError("Workspace/configuration changed; refresh before continuing")
            with app.state.import_submission_lock:
                import_token = target.form_token(app.state.import_token)
            registry_issues = []
            try:
                metadata = journal_metadata(config.venue_whitelist, journals)
            except ConfigurationError as error:
                metadata = {}
                registry_issues.append(str(error))
            service_by_id = {s.id: s for s in services}
            conferences = {item.id: item for item in getattr(settings_list, "conferences", ())}
            records = {}
            subjects = defaultdict(list)
            for name in settings_list.groups:
                subjects[(name, False)] = []
            for journal in journals:
                info = metadata.get(journal.key, {})
                service = service_by_id.get(journal.access_service_id)
                record = dict(key=journal.key, source_type="journal", issn=journal.issn, eissn=journal.eissn, name=journal.name,
                              group=journal.group, labels=list(journal.labels),
                              publisher=info.get("publisher"), sources=info.get("sources", []),
                              service=service.name if service else None,
                              service_id=service.id if service else None,
                              cover=f"/settings/covers/{journal.key}/image",
                              cover_detail=cover_details(config.venue_whitelist, journal.key), papers=[])
                records[journal.key] = record
                subjects[(journal.group, False)].append(record)
            kept = []
            for paper in (*workspace.inbox, *workspace.kept):
                journal = journal_for_paper(paper, journals)
                conference = conferences.get(paper.conference_id)
                source_name = paper.conference or paper.journal or "Unknown source"
                key = (paper.conference_id or f"conference:{paper.conference}") if paper.conference else (
                    journal.key if journal else f"unmapped:{source_name}")
                if key not in records:
                    records[key] = dict(key=key, issn=None, eissn=None, name=source_name,
                                        source_type="conference" if paper.conference else "journal",
                                        group=conference.group if conference else None,
                                        labels=list(conference.labels) if conference else [], publisher=None, service=None,
                                        service_id=None, cover=None, papers=[])
                    subjects[(conference.group, False) if conference else (None, True)].append(records[key])
                record = records[key]
                enrichment = app.state.paper_enrichment.state(paper.paper_id)
                item = dict(id=str(paper.paper_id), title=paper.title,
                            publication_date=paper.publication_date, abstract=paper.abstract,
                            conference=paper.conference, conference_id=paper.conference_id,
                            journal=paper.journal, publication_type=paper.publication_type,
                            first_public_at=paper.first_public_at, accepted_at=paper.accepted_at,
                            accepted_approximate=paper.accepted_approximate, date_note=paper.date_note,
                            date_evidence=[item.model_dump(mode="json", exclude_none=True) for item in paper.date_evidence],
                            indexed_terms=[item.model_dump(mode="json", exclude_none=True) for item in paper.indexed_terms],
                            external_ids=paper.external_ids.model_dump(exclude_none=True),
                            related_dois=list(paper.related_dois),
                            sources=[source.model_dump(mode="json", exclude_none=True) for source in paper.sources],
                            authors=list(paper.authors), doi=paper.external_ids.doi,
                            discovered_at=paper.discovered_at.isoformat(), status=paper.status.value,
                            enriched=enrichment["completed_in_session"],
                            enrichPhase=enrichment["phase"], enrichMessage=enrichment["message"],
                            enrichment_request_id=enrichment["request_id"],
                            syncWarning="sync failed" in enrichment["message"])
                if paper.status is WorkflowStatus.CANDIDATE:
                    record["papers"].append(item)
                else:
                    kept.append(dict(paper=item, journal={k: record[k] for k in ("key", "issn", "eissn", "name", "source_type")}))
            groups = []
            for (group_name, unmapped), entries in subjects.items():
                name = "Unmapped sources" if unmapped else group_name if group_name is not None else "Ungrouped / virtual"
                active = [entry for entry in entries if entry["papers"]]
                for entry in active:
                    entry["papers"].sort(key=lambda p: p["id"])
                    entry["papers"].sort(key=lambda p: p["discovered_at"], reverse=True)
                    entry["papers"].sort(key=lambda p: p["first_public_at"] or p["publication_date"] or "", reverse=True)
                if active:
                    groups.append(dict(name=name, journals=active))
            return response(dict(
                subjects=groups, csrf_token=csrf_token, import_token=import_token,
                counts=dict(candidates=len(workspace.inbox), active_journals=sum(len(g["journals"]) for g in groups)),
                kept=dict(papers=kept, journals=[{k: r[k] for k in ("key", "issn", "eissn", "name", "source_type", "service_id")} for r in records.values()],
                          services=[s.model_dump() for s in services], settings=config.kept_workflow,
                          titles={str(p.paper_id): p.title for p in workspace.papers}),
                issues=[*registry_issues, *(issue.message for issue in workspace.issues)],
            ))
        except (ConfigurationError, ContentChangedError, OSError) as error:
            return response({"message": str(error)}, 409)

    @app.post("/api/ui-next/papers/{paper_id}/{action}")
    def decision(paper_id: UUID, action: Literal["keep", "reject"], body: _Decision):
        if not valid(body):
            return response({"message": "Invalid or missing CSRF token; refresh the page."}, 403)
        try:
            config = load_config(config_path)
            result = {"keep": keep_paper, "reject": reject_paper}[action](
                config.output_dir, paper_id, body.expected_status)
            return response(result, 200 if result.outcome is DecisionOutcome.UPDATED else 409)
        except (ConfigurationError, OSError) as error:
            return response({"message": str(error)}, 409)

    def run_data(start=None):
        snapshot = app.state.run_coordinator.snapshot()
        providers = {}
        try:
            config = load_config(config_path)
            expressions = provider_expressions(config.keyword_expression)
            message = expressions['integrated']['error']
            try:
                validate_selection(config)
            except (ValueError, OSError) as error:
                message = str(error)
            providers['integrated'] = dict(**expressions['integrated'],enabled=not message,message=message,
                enabled_providers=config.enabled_providers,latest=read_last_run_snapshot(config.output_dir,RunProvider.INTEGRATED))
        except (ConfigurationError, OSError) as error:
            providers = {'integrated':dict(enabled=False,message=str(error),expression=None,latest=None)}
        wos = app.state.wos_coordinator.state()
        providers["wos"] = dict(enabled=wos["enabled"], message=wos["message"], latest=wos["latest"],
                                snapshot=wos["snapshot"])
        for provider, entry in providers.items():
            current = wos['snapshot'] if provider == 'wos' else snapshot if snapshot.provider and snapshot.provider.value == provider else None
            current_json = jsonable_encoder(current) if current else None
            entry['result_summary'] = build_run_result_summary(
                current if current_json and current_json.get('status') == 'FINISHED' else entry.get('latest'))
        return dict(snapshot=jsonable_encoder(snapshot),
                    progress=build_run_presentation(snapshot, now=datetime.now(timezone.utc)),
                    result_summary=build_run_result_summary(snapshot) if snapshot.status.value == 'FINISHED' else None,
                    providers=providers, start_outcome=start.outcome.value if start else None)

    @app.get("/api/ui-next/run")
    def run_state():
        return response(run_data())

    @app.post("/api/ui-next/run")
    def run_start(body: _RunStart):
        if not valid(body):
            return response({"message": "Invalid or missing CSRF token; refresh the page."}, 403)
        with app.state.settings_write_lock:
            if app.state.browser_task_lock.owner and app.state.browser_task_lock.owner.kind == "credentials":
                return response({"message": "Credential update is in progress"}, 409)
            availability = run_data()["providers"][body.provider.value]
            if not availability["enabled"]:
                return response({"message": availability["message"]}, 409)
            config = load_config(config_path)
            if body.enabled_providers is not None and body.enabled_providers != config.enabled_providers:
                return response({"message":"Provider selection changed; save and refresh before running"},409)
            start = app.state.run_coordinator.start(body.provider)
            if start.outcome is StartOutcome.ALREADY_RUNNING and app.state.wos_coordinator.running:
                return response({"message": "Run WoS is already active"}, 409)
            return response(run_data(start), 200 if start.outcome is StartOutcome.STARTED else 409)

    @app.post("/api/ui-next/run/cancel")
    def run_cancel(body: _Action):
        if not valid(body):
            return response({"message":"Invalid CSRF token"},403)
        app.state.run_coordinator.cancel()
        return response(run_data())

    @app.post("/api/ui-next/run-expression")
    def run_expression(body: _RunExpression):
        if not valid(body):
            return response({"message": "Invalid CSRF token"}, 403)
        return response({"providers": provider_expressions(body.keyword_expression)})

    @app.get("/api/ui-next/run-wos")
    def wos_state():
        return response(wos_data(app.state.wos_coordinator.state()))

    def wos_data(data):
        record = data['snapshot'] if data['snapshot']['status'] == 'FINISHED' else data.get('latest')
        data['result_summary'] = build_run_result_summary(record)
        return data

    @app.post("/api/ui-next/run-wos")
    def wos_start(body: _Action):
        if not valid(body):
            return response({"message": "Invalid CSRF token"}, 403)
        try:
            with app.state.settings_write_lock:
                return response(wos_data(app.state.wos_coordinator.start()))
        except (ValueError, OSError, ContentChangedError) as error:
            return response({"message": str(error)}, 409)

    @app.post("/api/ui-next/run-wos/cancel")
    def wos_cancel(body: _WoSCancel):
        if not valid(body):
            return response({"message": "Invalid CSRF token"}, 403)
        accepted = app.state.wos_coordinator.cancel(body.task_id)
        return response({"accepted": accepted}, 200 if accepted else 409)
