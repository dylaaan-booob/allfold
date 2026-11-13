"""FastAPI adapter for local Workspace review."""

from __future__ import annotations

import hashlib
import hmac
import base64
import json
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Request, WebSocket
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.datastructures import UploadFile
from starlette.concurrency import run_in_threadpool

from allfold.application.journal_covers import (
    MAX_IMAGE_BYTES, CoverConflict, _saved_journal, cover_details, cover_image,
)

from allfold.application.workspace_reset import ResetRefused, preview_reset, execute_reset
from allfold.application.settings import (
    SettingsDeletionApproval,
    SettingsDeletionPlan,
    SettingsIssueSource,
    _read_snapshot,
    SettingsIssue,
    SettingsLoadResult,
    SettingsSaveOutcome,
    SettingsSaveResult,
    SettingsValidationOutcome,
    SettingsValidationResult,
    load_settings,
    plan_settings_deletions,
    save_settings,
    validate_settings,
)
from allfold.application.workspace import WorkspaceSnapshot, load_workspace
from allfold.application.workspace_tasks import WorkspaceTaskHost
from allfold.application.task_clients import new_provider_pacing
from allfold.config import ConfigurationError, LoadedConfig, load_config, parse_settings_list_text
from allfold.application.full_markdown_import import (
    MAX_MARKDOWN_BYTES, preview_research_scope, confirm_research_scope, export_user_data,
)
from allfold.web.electron_bridge import ElectronBridge
from allfold.application.coordinators.journal_covers import JournalCoverSearch
from allfold.providers.openalex import OpenAlexError
from allfold.persistence.safe_write import CompareReadError
from allfold.persistence.safe_write import ContentChangedError, WorkspaceOperationLock, TextWriteCommittedError
from allfold.application.coordinators.preprint_lookup import PreprintLookup
from allfold.application.coordinators.wos_coordinator import WoSCoordinator
from allfold.application.coordinators.run_coordinator import CoordinatorStatus, RunCoordinator
from allfold.web.settings_api import install_settings_api, settings_response, settings_error
from allfold.web.settings_form import (
    SettingsFormValues,
    settings_draft_from_form,
    settings_form_from_draft,
    settings_form_from_submission,
)
from allfold.application.coordinators.login import LoginCoordinator
from allfold.web.ui_next import install_ui_next, ui_next_page

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_ALLOWED_HOSTS = ["localhost", "127.0.0.1"]


class _UIStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        # Revalidate unversioned UI code after updates, including 304 responses.
        if path.startswith("ui_next/") and Path(path).suffix in {".js", ".css"}:
            response.headers["Cache-Control"] = "no-cache"
        return response


from allfold.application.paper_fields import read_paper_fields, edit_paper_fields
from allfold.application.workspace import WorkspacePaper
from allfold.persistence.paper_repository import LibraryError
from allfold.web.ui_next import paper_payload


class _PreprintLookupAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    csrf_token: str
    workspace_id: UUID
    request_id: str | None = None


class _PaperFieldEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csrf_token: str
    workspace_id: UUID
    revision: str = Field(pattern=r'^[0-9a-f]{64}$')


class _PaperFieldReset(_PaperFieldEdit):
    fields: list[Literal['abstract', 'authors', 'publication_date']] = Field(min_length=1)


class _PaperAbstractInput(_PaperFieldEdit):
    abstract: str


class _LoginAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csrf_token: str
    service_id: str | None = None


class _LoginWorkflowAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csrf_token: str
    workflow_id: str


def _csrf_valid(submitted_csrf: str | None, csrf_token: str) -> bool:
    submitted = (submitted_csrf or "").encode("utf-8")
    return secrets.compare_digest(submitted, csrf_token.encode("ascii"))


def _workspace_state(
    config_path: Path,
) -> tuple[WorkspaceSnapshot | None, str | None]:
    try:
        config = load_config(config_path)
        return load_workspace(config.output_dir, journals=config.journals), None
    except (ConfigurationError, LibraryError, OSError) as error:
        return None, str(error)


def _workspace_health_context(config_path: Path) -> dict[str, object]:
    workspace, config_error = _workspace_state(config_path)
    return {"health_workspace": workspace, "health_config_error": config_error}


def _settings_result_context(
    *,
    csrf_token: str,
    form_values: SettingsFormValues,
    issues: tuple[SettingsIssue, ...] = (),
    validation_result: SettingsValidationResult | None = None,
    save_result: SettingsSaveResult | None = None,
    disk_state: SettingsLoadResult | None = None,
    message: str | None = None,
    deletion_plan: SettingsDeletionPlan | None = None,
    deletion_proof: str = "",
    markdown_plan=None,
    markdown_contents: str = "",
    markdown_filename: str = "",
    markdown_proof: str = "",
    markdown_dirty: bool = False,
    markdown_export_guard: bool = False,
    markdown_reload_guard: bool = False,
) -> dict[str, object]:
    return {
        "csrf_token": csrf_token,
        "settings_form": form_values,
        "settings_issues": issues,
        "settings_validation": validation_result,
        "settings_save": save_result,
        "settings_disk_state": disk_state,
        "settings_message": message,
        "settings_deletion_plan": deletion_plan,
        "settings_deletion_proof": deletion_proof,
        "markdown_plan": markdown_plan,
        "markdown_payload": base64.b64encode(markdown_contents.encode("utf-8")).decode("ascii"),
        "markdown_filename": markdown_filename,
        "markdown_proof": markdown_proof,
        "markdown_dirty": markdown_dirty,
        "markdown_export_guard": markdown_export_guard,
        "markdown_reload_guard": markdown_reload_guard,
    }


def create_app(config_path: Path, *, electron_bridge: ElectronBridge, diagnostics_root: Path | None = None) -> FastAPI:
    """Create the local Web adapter without requiring valid configuration."""

    if electron_bridge is None:
        raise ValueError('ElectronBridge is required')
    resolved_config_path = config_path.resolve()
    csrf_token = secrets.token_urlsafe(32)
    deletion_key = secrets.token_bytes(32)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            yield
        finally:
            from allfold.web.electron_server import drain_application
            electron_bridge.finish_disconnected()
            await drain_application(application)

    app = FastAPI(
        lifespan=lifespan,
        title="Allfold",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.stopping = False
    app.state.config_path = resolved_config_path
    app.state.csrf_token = csrf_token
    from allfold.diagnostics import DiagnosticStore
    try:
        diagnostic_level = load_config(resolved_config_path).log_level.value
    except (ConfigurationError, ValueError, OSError):
        diagnostic_level = 'info'
    app.state.diagnostics = DiagnosticStore(resolved_config_path, root=diagnostics_root, level=diagnostic_level)
    from allfold.application.browser_runtime import BrowserTaskLock
    app.state.settings_write_lock = threading.RLock()
    app.state.browser_task_lock = BrowserTaskLock(admission_lock=app.state.settings_write_lock)
    app.state.electron_bridge = electron_bridge
    electron_bridge.diagnostics = app.state.diagnostics

    @app.websocket("/api/electron/ws")
    async def electron_socket(socket: WebSocket):
        await electron_bridge.connect(socket)

    @app.get("/api/electron/health")
    def electron_health():
        return {"runtime": "electron", "connected": electron_bridge.connected}

    @app.middleware("http")
    async def electron_shutdown_guard(request: Request, call_next):
        if (electron_bridge.closing or app.state.stopping) and request.method != "GET":
            return JSONResponse({"message": "Application is shutting down"}, status_code=409)
        return await call_next(request)

    run_slot = threading.Lock()
    app.state.run_slot = run_slot
    pacing = new_provider_pacing()
    app.state.run_coordinator = RunCoordinator(resolved_config_path, run_slot=run_slot, diagnostics=app.state.diagnostics, pacing_state=pacing)
    app.state.journal_cover_search = JournalCoverSearch(electron_bridge, app.state.browser_task_lock,
        diagnostics=app.state.diagnostics, settings_lock=app.state.settings_write_lock)
    app.state.login = LoginCoordinator(electron_bridge, app.state.browser_task_lock, diagnostics=app.state.diagnostics)
    app.state.workspace_tasks = WorkspaceTaskHost(resolved_config_path,
        browser_lock=app.state.browser_task_lock, bridge=electron_bridge,
        diagnostics=app.state.diagnostics, login=app.state.login, pacing_state=pacing,
        settings_lock=app.state.settings_write_lock)
    app.state.workspace_tasks.initialize()
    app.state.preprint_lookup = PreprintLookup(resolved_config_path, app.state.browser_task_lock,
        run_slot=run_slot, pacing_state=pacing, workspace_tasks=app.state.workspace_tasks)
    electron_bridge.access_pages_closed = app.state.login.invalidate_pages
    def page_limits():
        from allfold.config import WorkflowConfig
        try:
            workflow = load_config(resolved_config_path).workflow
        except (ConfigurationError, ValueError, OSError):
            workflow = WorkflowConfig()
        return {'global_limit': workflow.managed_page_global_limit,
                'service_limit': workflow.managed_page_service_limit}
    electron_bridge.page_limits = page_limits
    app.state.wos_coordinator = WoSCoordinator(resolved_config_path, app.state.login, run_slot,
        bridge=electron_bridge, browser_lock=app.state.browser_task_lock, diagnostics=app.state.diagnostics)
    app.state.run_coordinator.wos_stage = app.state.wos_coordinator
    app.state.reset_confirmation = None
    app.state.reset_lock = threading.Lock()
    admission_lock = app.state.settings_write_lock

    def login_state():
        from allfold.application.browser_services import BrowserServiceSnapshot
        saved = BrowserServiceSnapshot.read(resolved_config_path)
        return JSONResponse(jsonable_encoder(app.state.login.snapshot(saved)))

    @app.get("/api/login/state")
    def read_login():
        try:
            return login_state()
        except (ValueError, OSError, RuntimeError) as error:
            return JSONResponse({"message": str(error)}, status_code=409)

    @app.post("/api/login/start")
    def start_login(body: _LoginAction):
        if not _csrf_valid(body.csrf_token, csrf_token):
            return JSONResponse({"message": "Invalid or missing CSRF token."}, status_code=403)
        try:
            with app.state.settings_write_lock:
                result = app.state.login.start(resolved_config_path, manual_service_id=body.service_id)
            return JSONResponse(jsonable_encoder(result))
        except (ValueError, OSError, RuntimeError) as error:
            return JSONResponse({"message": str(error)}, status_code=409)

    @app.post("/api/login/cancel")
    def cancel_login(body: _LoginWorkflowAction):
        if not _csrf_valid(body.csrf_token, csrf_token):
            return JSONResponse({"message": "Invalid or missing CSRF token."}, status_code=403)
        if not app.state.login.cancel(body.workflow_id):
            return JSONResponse({"message": "Login task is no longer active."}, status_code=409)
        return read_login()

    @app.post("/api/login/confirm")
    def confirm_login(body: _LoginWorkflowAction):
        if not _csrf_valid(body.csrf_token, csrf_token):
            return JSONResponse({"message": "Invalid or missing CSRF token."}, status_code=403)
        try:
            with app.state.settings_write_lock:
                saved = BrowserServiceSnapshot.read(resolved_config_path)
                result = app.state.login.confirm_all(saved, body.workflow_id)
            return JSONResponse(jsonable_encoder(result))
        except (ValueError, OSError, RuntimeError) as error:
            return JSONResponse({"message": str(error)}, status_code=409)

    from allfold.application.browser_services import BrowserServiceSnapshot
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=_ALLOWED_HOSTS,
    )
    app.mount("/static", _UIStaticFiles(directory=_STATIC_DIR), name="static")


    @app.get('/api/papers/{paper_id}/preprint-lookup/state')
    def preprint_lookup_state(paper_id: UUID, request_id: str | None = None):
        return JSONResponse(app.state.preprint_lookup.state(paper_id, request_id),
                            headers={'Cache-Control': 'no-store'})

    @app.post('/api/papers/{paper_id}/preprint-lookup/start')
    def preprint_lookup_start(paper_id: UUID, body: _PreprintLookupAction):
        if not _csrf_valid(body.csrf_token, csrf_token):
            return JSONResponse({'error': 'Invalid CSRF token'}, status_code=403)
        try:
            with app.state.settings_write_lock, app.state.reset_lock:
                return JSONResponse(app.state.preprint_lookup.start(paper_id, body.workspace_id))
        except (ConfigurationError, LibraryError, ValueError, OSError, ContentChangedError, CompareReadError) as error:
            return JSONResponse({'error': str(error)}, status_code=409)

    @app.post('/api/papers/{paper_id}/preprint-lookup/cancel')
    def preprint_lookup_cancel(paper_id: UUID, body: _PreprintLookupAction):
        if not _csrf_valid(body.csrf_token, csrf_token):
            return JSONResponse({'error': 'Invalid CSRF token'}, status_code=403)
        accepted = app.state.preprint_lookup.cancel(paper_id, body.request_id, body.workspace_id)
        return JSONResponse({'accepted': True} if accepted else {'error': 'Preprint lookup is no longer active'},
                            status_code=200 if accepted else 409)

    @app.get('/api/papers/{paper_id}/fields')
    def paper_field_snapshot(paper_id: UUID, workspace_id: UUID | None = None):
        try:
            workspace = load_config(resolved_config_path).output_dir
            return JSONResponse(read_paper_fields(workspace, paper_id, workspace_id=workspace_id),
                                headers={'Cache-Control': 'no-store'})
        except (ConfigurationError, LibraryError, ValueError, OSError, ContentChangedError) as error:
            return JSONResponse({'error': str(error)}, status_code=409)

    def write_paper_fields(paper_id, body, **changes):
        if not _csrf_valid(body.csrf_token, csrf_token):
            return JSONResponse({'error': 'Invalid CSRF token'}, status_code=403)
        try:
            with app.state.settings_write_lock, app.state.reset_lock:
                if app.state.workspace_tasks.changing:
                    raise ValueError('Workspace/configuration maintenance is in progress')
                workspace = load_config(resolved_config_path).output_dir
                registry = app.state.workspace_tasks.current()
                with registry.paper_gate():
                    paper, revision, fields = edit_paper_fields(workspace, body.workspace_id, paper_id, body.revision, **changes)
                    payload = paper_payload(WorkspacePaper(paper), workspace_tasks=app.state.workspace_tasks)
            return JSONResponse(jsonable_encoder(dict(saved=True, workspace_id=paper.workspace_id,
                revision=revision, paper=payload, fields=fields)))
        except (ConfigurationError, LibraryError, ValueError, OSError, ContentChangedError) as error:
            return JSONResponse({'error': str(error)}, status_code=409)

    @app.post('/api/papers/{paper_id}/fields/reset')
    def reset_paper_fields(paper_id: UUID, body: _PaperFieldReset):
        return write_paper_fields(paper_id, body, reset_fields=body.fields)

    @app.post('/api/papers/{paper_id}/abstract/input')
    def input_paper_abstract(paper_id: UUID, body: _PaperAbstractInput):
        return write_paper_fields(paper_id, body, abstract=body.abstract)


    @app.get("/", include_in_schema=False)
    def workspace_page():
        return ui_next_page()

    from allfold.web.diagnostics_api import install_diagnostics_api
    logs_reset_preview = install_diagnostics_api(app, run_slot=run_slot)

    def reset_preview_context(scope: str = 'workspace') -> dict[str, object]:
        if scope == 'logs':
            return logs_reset_preview()
        with app.state.reset_lock:
            if scope != 'workspace':
                app.state.reset_confirmation = None
                return {'reset_plan': None, 'reset_token': None, 'reset_error': 'Unknown Reset scope.'}
            # Each display supersedes its predecessor; POST cannot choose a path.
            app.state.reset_confirmation = None
            try:
                plan = preview_reset(resolved_config_path)
                token = secrets.token_urlsafe(32)
                app.state.reset_confirmation = (token, plan, 'workspace', None)
                return {"reset_plan": plan, "reset_token": token, "reset_error": None}
            except (ResetRefused, OSError, ValueError) as error:
                return {"reset_plan": None, "reset_token": None, "reset_error": str(error)}

    @app.post("/settings/workspace-reset", response_class=JSONResponse)
    async def reset_workspace_route(request: Request) -> JSONResponse:
        form = await request.form()
        csrf = form.get("csrf_token")
        if not _csrf_valid(str(csrf) if csrf is not None else None, csrf_token):
            return settings_error("Invalid or missing CSRF token.")
        return await run_in_threadpool(reset_workspace, form)

    def reset_workspace(form):
        change = control = owner = None
        slot = False
        result = None
        message, status = 'Workspace Reset refused.', 409
        try:
            with admission_lock, app.state.reset_lock:
                saved = app.state.reset_confirmation
                app.state.reset_confirmation = None
                token = form.get('reset_token')
                if (saved is None or len(saved) < 3 or saved[2] != 'workspace'
                        or not isinstance(token, str) or not token.isascii()
                        or not secrets.compare_digest(token, saved[0])):
                    raise ResetRefused('Reset confirmation is stale or already used. Reload Settings.')
                if app.state.workspace_tasks.changing:
                    raise ResetRefused('Workspace maintenance is already in progress.')
                if app.state.run_coordinator.snapshot().status is CoordinatorStatus.RUNNING or app.state.wos_coordinator.running:
                    raise ResetRefused('A Run is active; Reset refused.')
                owned = app.state.workspace_tasks.browser_owner_ids
                if any(current.id not in owned for current in app.state.browser_task_lock.owners):
                    raise ResetRefused('A browser workflow is active; Reset refused.')
                # Verify the exact preview before revoking any background work.
                if preview_reset(resolved_config_path) != saved[1]:
                    raise ResetRefused('Workspace or configuration changed; reload Settings to confirm.')
                control = app.state.browser_task_lock.reserve_control('workspace-reset')
                if control is None:
                    raise ResetRefused('Another Browser control is active; Reset refused.')
                slot = run_slot.acquire(blocking=False)
                if not slot:
                    raise ResetRefused('A foreground Run is active; Reset refused.')
                change = app.state.workspace_tasks.begin_change(whole=True)
            # API-only/queued/write/cleanup work closes its captured resources and
            # SQLite connections before the existing filesystem safety operation.
            app.state.workspace_tasks.drain_change(change)
            with admission_lock, app.state.reset_lock:
                if preview_reset(resolved_config_path) != saved[1]:
                    raise ResetRefused('Workspace or configuration changed while work settled.')
                owner = app.state.browser_task_lock.acquire('workspace-reset', control=control)
                if owner is None:
                    raise ResetRefused('Browser cleanup did not settle; Reset refused.')
                result = execute_reset(resolved_config_path, saved[1])
                message, status = result.message, 200 if result.success else 409
                if result.success or result.workspace_invalidated:
                    app.state.diagnostics.workspace_reset()
        except (ResetRefused, LibraryError, ValueError, RuntimeError, OSError) as error:
            message = str(error)
        finally:
            if owner is not None:
                app.state.browser_task_lock.release(owner)
            if control is not None:
                app.state.browser_task_lock.release_control(control)
            try:
                if change is not None:
                    with admission_lock:
                        app.state.workspace_tasks.finish_change(change)
            finally:
                if slot:
                    run_slot.release()
        return JSONResponse(jsonable_encoder({
            'reset_plan': None, 'reset_token': None, 'reset_error': message,
            'reset_success': status == 200, 'reset_result': result,
        }), status_code=status, headers={'Cache-Control': 'no-store'})

    def markdown_reply(request: Request, values: SettingsFormValues, *, message: str,
                       plan=None, contents: str = "", filename: str = "",
                       proof: str = "", dirty: bool = False, issues=(),
                       export_guard: bool = False,
                       reload_guard: bool = False,
                       saved: bool = False) -> JSONResponse:
        return settings_response(request,
            _settings_result_context(csrf_token=csrf_token, form_values=values,
                issues=issues, message=message, markdown_plan=plan,
                markdown_contents=contents, markdown_filename=filename,
                markdown_proof=proof, markdown_dirty=dirty,
                markdown_export_guard=export_guard,
                markdown_reload_guard=reload_guard,
                ), saved=saved)

    def submitted_settings(form):
        values = settings_form_from_submission(form)
        draft, issues = settings_draft_from_form(values)
        disk = load_settings(resolved_config_path)
        dirty = draft is None or draft != disk.draft
        return values, draft, issues, disk, dirty

    def require_settings_csrf(form) -> bool:
        supplied = form.get("csrf_token")
        return _csrf_valid(str(supplied) if supplied is not None else None, csrf_token)

    @app.get("/settings/covers/{journal_key}/image")
    def local_journal_cover(journal_key: str) -> Response:
        disk = load_settings(resolved_config_path)
        try:
            _saved_journal(disk.journal_path, journal_key, config_path=resolved_config_path)
            found = cover_image(disk.journal_path, journal_key)
        except (OSError, ValueError, ConfigurationError):
            found = None
        headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}
        if found is None:
            return Response(status_code=404, headers=headers)
        data, content_type = found
        return Response(content=data, media_type=content_type, headers=headers)

    @app.get("/settings/covers/search")
    def cover_search_state():
        return JSONResponse(app.state.journal_cover_search.state())

    @app.post("/settings/covers/search")
    async def start_cover_search(request: Request):
        form = await request.form()
        if not require_settings_csrf(form):
            return JSONResponse({'message': 'Invalid CSRF token'}, status_code=403)
        journal_key = str(form.get('journal_key', '')).strip()
        if not journal_key:
            return JSONResponse({'message': 'journal_key is required'}, status_code=400)
        def begin_cover():
            with app.state.settings_write_lock:
                disk = load_settings(resolved_config_path)
                return app.state.journal_cover_search.start(disk.journal_path, disk.draft.journals,
                                                            journal_key, config_path=resolved_config_path)
        try:
            return JSONResponse(await run_in_threadpool(begin_cover))
        except (ValueError, OSError) as error:
            return JSONResponse({'message': str(error)}, status_code=409)

    @app.post("/settings/covers/search/cancel")
    async def cancel_cover_search(request: Request):
        form = await request.form()
        if not require_settings_csrf(form):
            return JSONResponse({'message': 'Invalid CSRF token'}, status_code=403)
        accepted = app.state.journal_cover_search.cancel(str(form.get('request_id', '')))
        return JSONResponse({'accepted': accepted}, status_code=200 if accepted else 409)

    @app.post("/settings/covers/{journal_key}/crop")
    async def crop_journal_cover(request: Request, journal_key: str) -> JSONResponse:
        form = await request.form()
        if not require_settings_csrf(form):
            return JSONResponse({"ok": False, "message": "Invalid CSRF token"}, status_code=403)
        try:
            crop = {key: float(form.get(key, "")) for key in ("x", "y", "size")}
            disk = load_settings(resolved_config_path)
            detail = await run_in_threadpool(app.state.journal_cover_search.crop,
                disk.journal_path, journal_key, str(form.get("sha256", "")), crop, config_path=resolved_config_path)
            return JSONResponse({"ok": True, "cover": detail})
        except CoverConflict as error:
            return JSONResponse({"ok": False, "message": str(error)}, status_code=409)
        except (OSError, ValueError, TypeError, ConfigurationError) as error:
            return JSONResponse({"ok": False, "message": str(error)}, status_code=400)

    @app.post("/settings/covers/{journal_key}/upload")
    async def upload_journal_cover(request: Request, journal_key: str) -> JSONResponse:
        if app.state.journal_cover_search.state()["busy"]:
            return JSONResponse({"ok": False, "message": "Cover search is running"}, status_code=409)
        async with request.form() as form:
            if not require_settings_csrf(form):
                return JSONResponse({"ok": False, "message": "Invalid CSRF token"}, status_code=403)
            upload = form.get("file")
            if not isinstance(upload, UploadFile):
                return JSONResponse({"ok": False, "message": "Choose an image file"}, status_code=400)
            data = await upload.read(MAX_IMAGE_BYTES + 1)
        disk = load_settings(resolved_config_path)
        try:
            outcome = await run_in_threadpool(app.state.journal_cover_search.upload, disk.journal_path, journal_key, data, config_path=resolved_config_path)
            state = await run_in_threadpool(cover_details, disk.journal_path, journal_key)
            return JSONResponse({"ok": True, "result": outcome, "state": state["state"]})
        except (OSError, ValueError, ConfigurationError) as error:
            return JSONResponse({"ok": False, "message": str(error)}, status_code=400)

    scope_previews = {}

    @app.post("/settings/import/preview", response_class=JSONResponse)
    async def preview_markdown_import(request: Request) -> JSONResponse:
        form = await request.form()
        if not require_settings_csrf(form):
            return settings_error("Invalid or missing CSRF token.")
        values, draft, issues, disk, dirty = submitted_settings(form)
        upload = form.get("markdown_file")
        try:
            if draft is None or issues or disk.issues:
                raise ConfigurationError("Resolve Settings errors before Import")
            if not isinstance(upload, UploadFile) or not upload.filename:
                raise ConfigurationError("Choose a UTF-8 .md file")
            blob = await upload.read(MAX_MARKDOWN_BYTES + 1)
            if len(blob) > MAX_MARKDOWN_BYTES:
                raise ConfigurationError("Markdown Import file exceeds 1 MiB")
            contents = blob.decode("utf-8", errors="strict")
            choices = json.loads(str(form.get("import_choices", "{}")))
            if not isinstance(choices, dict):
                raise ValueError("Import choices must be an object")
            plan = await run_in_threadpool(preview_research_scope, resolved_config_path,
                disk.journal_path, contents, filename=upload.filename, choices=choices,
                query_gokb=form.get("query_gokb") == "yes")
            proof = secrets.token_urlsafe(32)
            # A server-held preview binds the exact verified selections and remote
            # evidence; Confirm never re-resolves them against a changed network.
            if len(scope_previews) >= 32:
                scope_previews.pop(next(iter(scope_previews)))
            scope_previews[proof] = (plan, draft, contents, upload.filename, choices)
            return markdown_reply(request, values, message="Research Scope Preview; no user data changed.",
                plan=plan, contents=contents, filename=upload.filename, proof=proof, dirty=dirty)
        except (ConfigurationError, ContentChangedError, OSError, UnicodeError, ValueError) as error:
            return markdown_reply(request, values, message=f"Import Preview blocked: {error}", issues=issues)

    @app.post("/settings/import/confirm", response_class=JSONResponse)
    async def confirm_markdown_import(request: Request) -> JSONResponse:
        form = await request.form()
        if not require_settings_csrf(form):
            return settings_error("Invalid or missing CSRF token.")
        values, draft, issues, disk, dirty = submitted_settings(form)
        try:
            if draft is None or issues or disk.issues:
                raise ConfigurationError("Resolve Settings errors before Import")
            if form.get("confirm_full_import") != "yes":
                raise ConfigurationError("Explicit Confirm Import required")
            if dirty and form.get("import_discard") != "yes":
                raise ConfigurationError("Unsaved Settings Draft: Save or explicitly Discard before Import")
            proof = str(form.get("markdown_import_proof", ""))
            stored = scope_previews.get(proof)
            if stored is None:
                raise ContentChangedError("Import Preview is no longer valid; Preview again")
            plan, preview_draft, contents, filename, choices = stored
            expected_payload = base64.b64encode(contents.encode()).decode()
            if (draft != preview_draft or form.get("markdown_import_payload") != expected_payload
                    or form.get("markdown_import_filename") != filename
                    or (form.get("import_choices") is not None and json.loads(str(form.get("import_choices"))) != choices)):
                raise ContentChangedError("Import source, draft or choices changed; Preview again")
            if draft.journal_revision != disk.draft.journal_revision or draft.monitor_revision != disk.draft.monitor_revision:
                raise ContentChangedError("Settings revisions changed; Reload and Preview again")
            def verify_monitor_before_write():
                current = _read_snapshot(resolved_config_path, source=SettingsIssueSource.MONITOR_CONFIG)
                if current.issue or current.revision != draft.monitor_revision:
                    raise ContentChangedError("Monitor configuration changed; Preview again")
            def commit_scope():
                from allfold.web.settings_guard import settings_input_active
                with app.state.settings_write_lock:
                    if settings_input_active(app):
                        raise ContentChangedError('Active task owns the saved configuration; Import is pending')
                    confirm_research_scope(plan, before_write=verify_monitor_before_write)
            await run_in_threadpool(commit_scope)
            scope_previews.pop(proof, None)
            saved = load_settings(resolved_config_path)
            return markdown_reply(request, settings_form_from_draft(saved.draft),
                message="Research Scope added to saved User Data.", saved=True)
        except (ConfigurationError, ContentChangedError, CompareReadError, OSError, UnicodeError, ValueError) as error:
            return markdown_reply(request, values, message=f"Import not written: {error}", issues=issues)

    @app.post("/settings/export", response_class=JSONResponse)
    async def export_markdown(request: Request):
        form = await request.form()
        if not require_settings_csrf(form):
            return settings_error("Invalid or missing CSRF token.")
        values, draft, issues, disk, dirty = submitted_settings(form)
        if dirty and form.get("export_discard") != "yes":
            return markdown_reply(request, values, message="Unsaved Settings Draft: Save or explicitly Discard before Export.",
                issues=issues, export_guard=True)
        try:
            if disk.issues:
                raise ConfigurationError("Resolve Settings errors before Export")
            return Response(content=export_user_data(resolved_config_path).encode("utf-8"),
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="allfold-user-data.md"',
                         "Cache-Control": "no-store"})
        except (ConfigurationError, OSError) as error:
            return markdown_reply(request, values, message=f"Export blocked: {error}", issues=issues)

    @app.post("/settings/reload", response_class=JSONResponse)
    async def reload_markdown(request: Request) -> JSONResponse:
        form = await request.form()
        if not require_settings_csrf(form):
            return settings_error("Invalid or missing CSRF token.")
        values, draft, issues, disk, dirty = submitted_settings(form)
        if form.get("reload_step") != "confirm" or form.get("reload_word") != "RELOAD":
            return markdown_reply(request, values,
                message="Reload discards unsaved Journals, Groups, Mapping, Monitor, Institution and workflow edits. Confirm explicitly.",
                reload_guard=True)
        saved = load_settings(resolved_config_path)
        response = markdown_reply(request, settings_form_from_draft(saved.draft),
            message="Reloaded saved User Data and monitor configuration. Prior unsaved edits discarded.", issues=saved.issues, saved=True)
        return response

    @app.post("/settings/save", response_class=JSONResponse)
    async def save_settings_route(request: Request) -> JSONResponse:
        form = await request.form()
        submitted_csrf = form.get("csrf_token")
        if not _csrf_valid(
            str(submitted_csrf) if submitted_csrf is not None else None,
            csrf_token,
        ):
            return settings_error("Invalid or missing CSRF token.")

        return await run_in_threadpool(save_submitted_settings, request, form)

    def save_submitted_settings(request, form):
        from allfold.web.settings_guard import settle_settings_effects
        effects = {}
        try:
            return save_submitted_settings_locked(request, form, effects)
        except (ValueError, RuntimeError, OSError) as error:
            return settings_error(str(error), 409)
        finally:
            settle_settings_effects(app, effects)

    def save_submitted_settings_locked(request, form, effects):
        from allfold.web.settings_guard import settings_write_context
        with app.state.settings_write_lock:
            values = settings_form_from_submission(form)
            draft, form_issues = settings_draft_from_form(values)
            if draft is None:
                return settings_response(request,
                    _settings_result_context(
                        csrf_token=csrf_token,
                        form_values=values,
                        issues=form_issues,
                        message="Settings were not saved.",
                    ),
                )

            disk = load_settings(config_path)
            blocked, invalidation = settings_write_context(app, disk.draft, draft)
            if blocked:
                return JSONResponse({"saved": False, "outcome": "TASK_ACTIVE", "message": "Pending: affected work is still active or cleaning up; the draft is retained."})
            plan = plan_settings_deletions(disk.draft, draft)
            proof = hmac.new(deletion_key, repr((draft, plan)).encode("utf-8"), hashlib.sha256).hexdigest()
            approved = (
                plan.required
                and str(form.get("confirm_settings_deletions", "")) == "yes"
                and hmac.compare_digest(str(form.get("settings_deletion_proof", "")), proof)
            )
            # 确认仅由本进程签发，精确绑定全部草稿字段、真实删除目标及原始版本。
            # 不保存草稿副本；变更草稿、服务成员或文件版本都需重新预览。
            if plan.required and not approved and not disk.issues and (
                draft.monitor_revision == disk.draft.monitor_revision
                and draft.journal_revision == disk.draft.journal_revision
            ) and validate_settings(config_path, draft).outcome is SettingsValidationOutcome.VALID:
                return settings_response(request,
                    _settings_result_context(
                        csrf_token=csrf_token, form_values=values,
                        deletion_plan=plan, deletion_proof=proof,
                        message="Review the affected Services and Journals, then confirm this Save.",
                    ),
                )
            approval = SettingsDeletionApproval(
                draft.monitor_revision, draft.journal_revision,
                tuple(service.id for service in plan.services),
            ) if approved else None
            from allfold.web.settings_guard import prepare_settings_effects, drain_settings_effects, settings_revisions_current
            if (not disk.issues and settings_revisions_current(disk.draft, draft)
                    and validate_settings(config_path, draft).outcome is SettingsValidationOutcome.VALID):
                prepare_settings_effects(app, effects, invalidation, disk.draft, draft)
        drain_settings_effects(app, effects)
        with app.state.settings_write_lock:
            # A non-maintenance save may have yielded to a foreground start;
            # its captured configuration must remain protected until settlement.
            if effects.get('change') is None and settings_write_context(app, disk.draft, draft)[0]:
                return JSONResponse({"saved": False, "outcome": "TASK_ACTIVE", "message": "Pending: affected work is still active or cleaning up; the draft is retained."})
            result = (
                save_settings(config_path, draft, deletion_approval=approval)
                if approval is not None else save_settings(config_path, draft)
            )
            from allfold.web.settings_guard import record_settings_effects
            record_settings_effects(app, effects, invalidation, disk.draft, result.state.draft)
            if result.outcome is SettingsSaveOutcome.SAVED:
                response = settings_response(request,
                    _settings_result_context(
                        csrf_token=csrf_token,
                        form_values=settings_form_from_draft(result.state.draft),
                        issues=result.issues,
                        validation_result=result.validation,
                        save_result=result,
                        disk_state=result.state,
                        message="Settings saved.",
                    ), saved=True,
                )
                return response

            if result.outcome is SettingsSaveOutcome.PARTIAL_SAVE:
                # 保留提交时的字段与原始 revision；只读磁盘状态单独报告实际写入。
                form_values = values
                message = (
                    "Settings were partially saved: "
                    f"journal data written: {'yes' if result.journal_written else 'no'}, "
                    f"monitor configuration written: {'yes' if result.monitor_written else 'no'}, "
                    f"PubMed API Key written: {'yes' if result.pubmed_key_written else 'no'}, "
                    f"OpenAlex API Key written: {'yes' if result.openalex_key_written else 'no'}. "
                    "Reload and reconcile before another Save."
                )
            elif result.outcome is SettingsSaveOutcome.REVISION_CONFLICT:
                form_values = values
                message = (
                    "Settings were not saved because files changed since this "
                    "editor was opened. Reload and reconcile before retrying."
                )
            elif result.outcome is SettingsSaveOutcome.WRITE_FAILED:
                form_values = values
                message = "Settings could not be written."
            else:
                form_values = values
                message = "Settings draft is invalid and was not saved."

            return settings_response(request,
                _settings_result_context(
                    csrf_token=csrf_token,
                    form_values=form_values,
                    issues=result.issues,
                    validation_result=result.validation,
                    save_result=result,
                    disk_state=result.state,
                    message=message,
                ),
            )

    install_settings_api(app, resolved_config_path, csrf_token,
                         workspace_health=_workspace_health_context,
                         reset_preview=reset_preview_context)
    install_ui_next(app, resolved_config_path, csrf_token)
    return app
