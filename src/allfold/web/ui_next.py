"""JSON and page adapters for the four-page frontend."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from contextlib import nullcontext
import secrets
from typing import Literal
from uuid import UUID

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from allfold.application.decisions import apply_paper_action
from allfold.application.journal_covers import cover_details
from allfold.application.preprint_lookup import formal_lookup_doi
from allfold.application.run_state import RunProvider, read_last_run_snapshot
from allfold.application.workspace import PaperStatus, WorkspacePaper, journal_for_paper, load_workspace
from allfold.application.journal_lookup import journal_metadata
from allfold.persistence.user_state import load_user_state, read_user_state
from allfold.config import ConfigurationError, load_config
from allfold.paper_dates import date_value
from allfold.models import EvidenceDate
from allfold.persistence.paper_repository import LibraryError
from allfold.url_safety import normalize_public_http_url
from allfold.keywords import parse_keyword_expression
from allfold.persistence.safe_write import ContentChangedError
from allfold.application.coordinators.run_coordinator import StartOutcome
from allfold.providers.wos import compile_wos_query
from allfold.providers.integrated import PROVIDERS, compile_query
from allfold.application.integrated_run import validate_selection
from allfold.integrations.openalex_credentials import read_credential, OpenAlexCredentialError
from allfold.web.run_presentation import build_run_presentation, build_run_result_summary


def _date_evidence_payload(event: EvidenceDate) -> dict:
    fact = event.model_dump(mode="json", exclude_none=True, exclude={"url"})
    try:
        url = normalize_public_http_url(event.url)
    except ValueError:
        return fact
    if url:
        fact["url"] = url
    return fact


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
    workspace_id: UUID
    expected_status: PaperStatus | None = None


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
            if provider not in {"pubmed", "openalex", "integrated", "wos"}:
                values[provider] = {"expression": None, "error": ""}
                continue
            compiled = compile_wos_query(ast) if provider == "wos" else compile_query(ast,provider) if provider in {"pubmed","openalex"} else text
            values[provider] = {"expression": compiled, "error": ""}
        except ValueError as error:
            values[provider] = {"expression": None, "error": str(error)}
    return values


class _RunCancel(_Action):
    task_id: str = Field(min_length=1, max_length=128)


def paper_payload(paper: WorkspacePaper, *, preprint_lookup=None, workspace_tasks=None, cleanup_pending=None) -> dict:
    if cleanup_pending is None:
        cleanup_pending = (workspace_tasks.cleanup_pending(paper.paper_id, paper.record.workspace_id)
            if workspace_tasks else bool(preprint_lookup and preprint_lookup.cleaning_up(paper.paper_id, paper.record.workspace_id)))
    metadata = paper.record.metadata
    doi = paper.external_ids.doi
    proof_keys = {(item.provider, item.version, date_value(item)) for item in paper.preprint_evidence}
    preprints = [item.model_dump(mode='json', exclude_none=True) for item in paper.preprints
                 if (item.provider, item.version, item.date) not in proof_keys]
    preprints.extend(dict(_date_evidence_payload(item), date=date_value(item)) for item in paper.preprint_evidence)
    return dict(id=str(paper.paper_id), workspace_id=str(paper.record.workspace_id),
        revision=paper.record.revision, metadata_present=paper.metadata_present,
        excluded=paper.record.excluded, status=paper.status.value if paper.status else None,
        title=paper.title, identity_label=paper.identity_label,
        identities=[dict(namespace=identity.namespace, value=identity.value) for identity in paper.record.identities],
        primary_identity=(dict(namespace=paper.record.primary_identity.namespace,
                               value=paper.record.primary_identity.value) if paper.record.primary_identity else None),
        publication_date=paper.publication_date, abstract=paper.abstract, journal=paper.journal,
        conference=paper.conference, publication_type=paper.publication_type,
        first_public_at=paper.first_public_at, ordinary_dates=list(paper.ordinary_dates), preprints=preprints,
        preprint_relations=[ref.model_dump(mode='json', exclude_none=True) for ref in paper.preprint_relations],
        indexed_terms=[term.model_dump(mode='json', exclude_none=True) for term in paper.indexed_terms],
        author_keywords=list(paper.author_keywords), authors=list(paper.authors),
        external_ids=paper.external_ids.model_dump(exclude_none=True), doi=doi,
        sources=[source.model_dump(mode='json', exclude_none=True) for source in paper.sources],
        journal_issns=list(paper.journal_issns),
        discovered_at=paper.discovered_at.isoformat() if paper.discovered_at else None,
        notes=metadata.notes if metadata else None, collection_status=paper.record.collection_status,
        body_present=paper.record.body is not None,
        preprint_lookup_available=bool(metadata is not None and not paper.record.excluded and formal_lookup_doi(
            doi, paper.publication_type, paper.journal, paper.conference)),
        cleanup_pending=bool(cleanup_pending))


def install_ui_next(app: FastAPI, config_path: Path, csrf_token: str) -> None:
    def valid(body: _Action) -> bool:
        return secrets.compare_digest((body.csrf_token or "").encode(), csrf_token.encode())

    def response(data, status=200):
        return JSONResponse(jsonable_encoder(data), status_code=status,
                            headers={"Cache-Control": "no-store"})

    @app.get("/ui-next", include_in_schema=False)
    @app.get("/ui-next/", include_in_schema=False)
    def page():
        return ui_next_page()

    @app.get('/api/ui-next/workspace')
    def workspace_data():
        try:
            configuration = config_path.read_bytes()
            config = load_config(config_path)
            state_snapshot = load_user_state(config_path, config.venue_whitelist)
            settings_list = state_snapshot.state
            journals, services = settings_list.journals, settings_list.access_services
            registry = app.state.workspace_tasks.peek()
            with registry.paper_gate() if registry else nullcontext():
                workspace = load_workspace(config.output_dir, journals=journals)
                cleanup = {paper.paper_id: app.state.workspace_tasks.cleanup_pending(paper.paper_id, paper.record.workspace_id)
                           for paper in workspace.papers}
            if config_path.read_bytes() != configuration or read_user_state(config_path).revision != state_snapshot.revision:
                raise ContentChangedError('Workspace/configuration changed; refresh before continuing')
            registry_issues = []
            try:
                metadata = journal_metadata(config.venue_whitelist, journals)
            except ConfigurationError as error:
                metadata = {}
                registry_issues.append(str(error))
            service_by_id = {service.id: service for service in services}
            records, subjects = {}, defaultdict(list)
            for name in settings_list.groups:
                subjects[(name, False)] = []
            for journal in journals:
                info = metadata.get(journal.key, {})
                service = service_by_id.get(journal.access_service_id)
                entry = dict(key=journal.key, source_type='journal', issn=journal.issn, eissn=journal.eissn,
                    name=journal.name, group=journal.group, labels=list(journal.labels), publisher=info.get('publisher'),
                    sources=info.get('sources', []), service=service.name if service else None,
                    service_id=service.id if service else None, cover=f'/settings/covers/{journal.key}/image',
                    cover_detail=cover_details(config.venue_whitelist, journal.key), papers=[])
                records[journal.key] = entry
                subjects[(journal.group, False)].append(entry)
            downloaded, trash = [], []
            for paper in workspace.papers:
                if paper.status is None:
                    continue
                journal = journal_for_paper(paper, journals)
                source_name = paper.conference or paper.journal or 'Unassigned'
                key = journal.key if journal else f'unmapped:{source_name}'
                if key not in records:
                    records[key] = dict(key=key, issn=None, eissn=None, name=source_name, source_type='unmapped',
                        group=None, labels=[], publisher=None, service=None, service_id=None, cover=None, papers=[])
                    subjects[(None, True)].append(records[key])
                entry = records[key]
                item = paper_payload(paper, cleanup_pending=cleanup[paper.paper_id])
                if paper.status is PaperStatus.CANDIDATE:
                    entry['papers'].append(item)
                else:
                    target = trash if paper.status is PaperStatus.TRASH else downloaded
                    target.append(dict(paper=item, journal={name: value for name, value in entry.items() if name != 'papers'}))
            groups = [dict(name='Unmapped sources' if unmapped else name if name is not None else 'Ungrouped / virtual',
                           journals=[entry for entry in entries if entry['papers']])
                      for (name, unmapped), entries in subjects.items() if any(entry['papers'] for entry in entries)]
            catalog = [{name: value for name, value in entry.items() if name != 'papers'}
                       for entry in records.values()]
            return response(dict(workspace_id=workspace.workspace_id, revision=workspace.revision,
                initialized=workspace.initialized, subjects=groups, csrf_token=csrf_token,
                counts=dict(candidates=len(workspace.inbox), downloaded=len(downloaded), trash=len(trash),
                            active_journals=sum(len(group['journals']) for group in groups)),
                downloaded=dict(papers=downloaded, journals=catalog, services=[service.model_dump() for service in services],
                                titles={str(paper.paper_id): paper.title or paper.identity_label for paper in workspace.papers}),
                trash=dict(papers=trash), issues=registry_issues))
        except (ConfigurationError, ContentChangedError, LibraryError, OSError) as error:
            return response({'message': str(error)}, 409)

    @app.post('/api/ui-next/papers/{paper_id}/{action}')
    def decision(paper_id: UUID, action: Literal['reject', 'restore', 'clear-metadata', 'unexclude'], body: _Decision):
        if not valid(body):
            return response({'message': 'Invalid or missing CSRF token; refresh the page.'}, 403)
        try:
            with app.state.settings_write_lock, app.state.reset_lock:
                config = load_config(config_path)
                registry = app.state.workspace_tasks.current()
                result = apply_paper_action(config.output_dir, body.workspace_id, paper_id, action,
                    expected_status=body.expected_status, preprint_lookup=app.state.preprint_lookup,
                    workspace_registry=registry, cancel=False)
            result.signal_cancellation()
            with registry.paper_gate():
                from allfold.persistence.paper_repository import PaperRepository
                with PaperRepository.open(config.output_dir, expected_workspace_id=body.workspace_id) as repository:
                    paper, revision = repository.get(paper_id), repository.revision
                payload = paper_payload(WorkspacePaper(paper), workspace_tasks=app.state.workspace_tasks)
            return response(dict(workspace_id=paper.workspace_id, revision=revision, paper=payload))
        except (ConfigurationError, ContentChangedError, LibraryError, ValueError, OSError) as error:
            return response({'message': str(error)}, 409)

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
        entry = providers['integrated']
        entry['result_summary'] = build_run_result_summary(snapshot if snapshot.status.value == 'FINISHED' else entry.get('latest'))
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
            if app.state.workspace_tasks.changing:
                return response({'message': 'Workspace/configuration maintenance is in progress'}, 409)
            if any(owner.exclusive for owner in app.state.browser_task_lock.owners):
                return response({"message": "Browser control operation is in progress"}, 409)
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
    def run_cancel(body: _RunCancel):
        if not valid(body):
            return response({"message":"Invalid CSRF token"},403)
        accepted = app.state.run_coordinator.cancel(body.task_id)
        return response({**run_data(), 'accepted': accepted}, 200 if accepted else 409)

    @app.post("/api/ui-next/run-expression")
    def run_expression(body: _RunExpression):
        if not valid(body):
            return response({"message": "Invalid CSRF token"}, 403)
        return response({"providers": provider_expressions(body.keyword_expression)})

    @app.get("/api/ui-next/run-wos")
    def wos_state():
        # Legacy URL projects the same task and durable result.
        return response(run_data())

    @app.post("/api/ui-next/run-wos")
    def wos_start(body: _Action):
        return run_start(_RunStart(csrf_token=body.csrf_token))

    @app.post("/api/ui-next/run-wos/cancel")
    def wos_cancel(body: _RunCancel):
        if not valid(body):
            return response({"message": "Invalid CSRF token"}, 403)
        accepted = app.state.run_coordinator.cancel(body.task_id)
        return response({"accepted": accepted}, 200 if accepted else 409)
