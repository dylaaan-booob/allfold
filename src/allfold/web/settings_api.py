"""UI Next projections of the shared Settings operations."""
from pathlib import Path
from dataclasses import replace
import os

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from allfold.application.journal_covers import cover_details
from allfold.application.settings import load_settings, _read_journal_snapshot, SettingsIssueSource, SettingsIssue
from allfold.application.journal_lookup import journal_metadata, search_journals
from allfold.providers.openalex import OpenAlexError
from allfold.config import ConfigurationError
from allfold.web.settings_form import settings_form_from_draft


def json_response(data, status_code=200):
    return JSONResponse(jsonable_encoder(data), status_code=status_code,
                        headers={"Cache-Control": "no-store"})


def settings_error(message: str, status_code=403):
    return json_response({"message": message}, status_code)


def settings_state(config_path: Path, csrf_token: str, *, disk=None):
    disk = disk or load_settings(config_path)
    snapshot = _read_journal_snapshot(config_path, disk.journal_path)
    issues = list(disk.issues)
    metadata = {}
    try:
        metadata = journal_metadata(disk.journal_path, disk.draft.journals)
    except ConfigurationError as error:
        issues.append(SettingsIssue(SettingsIssueSource.JOURNAL_DATA, str(error), field="journal_registry"))
    return dict(values=settings_form_from_draft(disk.draft), issues=tuple(issues),
                csrf_token=csrf_token, config_path=disk.config_path,
                journal_path=disk.journal_path, journal_metadata=metadata,
                list_text=snapshot.contents,
                saved_workspace=None if any(i.source == SettingsIssueSource.MONITOR_CONFIG for i in disk.issues)
                else (disk.config_path.parent / disk.draft.output_dir).absolute(),
                covers={j.key: cover_details(disk.journal_path, j.key)
                        for j in disk.draft.journals})


def settings_response(request: Request, context, *, status_code=200, saved=False):
    """Project the existing Settings result onto the UI Next JSON contract."""
    state = settings_state(request.app.state.config_path, context["csrf_token"],
                           disk=context.get("settings_disk_state"))
    state['logging'] = logging_state(request.app)
    state.update(saved=saved, values=replace(context["settings_form"], pubmed_api_key=None, openalex_api_key=None), issues=tuple((*state["issues"], *context["settings_issues"])),
                 message=context["settings_message"], save=context["settings_save"],
                 validation=context["settings_validation"],
                 deletion_plan=context["settings_deletion_plan"],
                 deletion_proof=context["settings_deletion_proof"],
                 import_plan=context["markdown_plan"],
                 import_payload=context["markdown_payload"],
                 import_filename=context["markdown_filename"],
                 import_proof=context["markdown_proof"], dirty=context["markdown_dirty"],
                 export_guard=context["markdown_export_guard"],
                 reload_guard=context["markdown_reload_guard"])
    return json_response(state, status_code)


def logging_state(app):
    return {'effective_level': app.state.diagnostics.level,
            'environment_override': 'ALLFOLD_LOG_LEVEL' in os.environ,
            'restart_required': True}


def install_settings_api(app, config_path, csrf_token, *, workspace_health,
                         zotero_integration, reset_preview):
    install_resource_api(app, config_path, csrf_token)

    @app.get("/api/ui-next/settings")
    def get_settings():
        state = settings_state(config_path, csrf_token)
        state['logging'] = logging_state(app)
        state["cover_search"] = app.state.journal_cover_search.state()
        return json_response(state)

    @app.get("/api/ui-next/settings/journals/search")
    def lookup_journals(q: str):
        disk = load_settings(config_path)
        try:
            return json_response({"candidates": search_journals(disk.journal_path, q)})
        except (ConfigurationError, OpenAlexError) as error:
            return json_response({"message": str(error)}, 409)

    @app.get("/api/ui-next/settings/diagnostics/{kind}")
    def diagnostics(kind: str):
        if kind == "health":
            return json_response(workspace_health(config_path))
        if kind == "zotero":
            return json_response(zotero_integration(app.state.electron_bridge))
        return json_response({"message": "Unknown diagnostic"}, 404)

    @app.get("/api/ui-next/settings/reset-preview")
    def get_reset_preview(scope: str = 'workspace'):
        return json_response(reset_preview(scope))


def install_resource_api(app, config_path, csrf_token):
    """Public resource evidence and revision-guarded, configuration-local choices."""
    import hmac
    from starlette.datastructures import FormData
    from starlette.concurrency import run_in_threadpool
    from allfold.application.carsi_catalog import get_carsi_catalog
    from allfold.application.journal_resolver import resolve_journal
    from allfold.persistence.user_state import application_data_dir, read_user_state
    from allfold.persistence.safe_write import ContentChangedError
    from allfold.application.journal_services import choose_journal_service
    from allfold.web.settings_form import settings_form_from_submission, settings_draft_from_form

    def resource_path():
        return application_data_dir(config_path) / 'resources.sqlite'

    async def validated_form(request):
        form = await request.form()
        if not hmac.compare_digest(str(form.get('csrf_token', '')), csrf_token):
            raise PermissionError('Invalid CSRF token')
        return form

    @app.post('/api/ui-next/settings/catalog')
    async def catalog(request: Request):
        try:
            form = await validated_form(request)
            return json_response(await run_in_threadpool(get_carsi_catalog, resource_path(), refresh=form.get('refresh') == 'yes'))
        except PermissionError as error:
            return settings_error(str(error))
        except (ConfigurationError, ValueError, OSError) as error:
            return settings_error(str(error), 409)

    @app.post('/api/ui-next/settings/journals/{key}/resolve')
    async def resolve(request: Request, key: str):
        try:
            form = await validated_form(request)
            state = read_user_state(config_path)
            journal = next((j for j in state.state.journals if j.key == key), None)
            if journal is None:
                return settings_error('Save the Journal before querying resources', 409)
            return json_response(await run_in_threadpool(resolve_journal, config_path, journal, refresh=form.get('refresh') == 'yes'))
        except PermissionError as error:
            return settings_error(str(error))
        except (ConfigurationError, ValueError, OSError) as error:
            return settings_error(str(error), 409)

    @app.post('/api/ui-next/settings/journals/{key}/service')
    async def choose(request: Request, key: str):
        try:
            form = await validated_form(request)
            disk = load_settings(config_path)
            settings_form = FormData([(key, value) for key, value in form.multi_items() if key not in {'selection_method', 'selection_name', 'selection_url'}])
            submitted, issues = settings_draft_from_form(settings_form_from_submission(settings_form))
            if issues or disk.issues or submitted != disk.draft:
                raise ContentChangedError('Save or Reload unsaved/stale Settings before choosing a Service')
            await run_in_threadpool(choose_journal_service, config_path, key,
                method=str(form.get('selection_method', '')), name=str(form.get('selection_name', '')),
                url=str(form.get('selection_url', '')), expected_revision=disk.draft.journal_revision,
                expected_monitor_revision=disk.draft.monitor_revision)
            return json_response(dict(settings_state(config_path, csrf_token), saved=True, message='Journal Service saved'))
        except PermissionError as error:
            return settings_error(str(error))
        except (ConfigurationError, ContentChangedError, ValueError, OSError) as error:
            return settings_error(str(error), 409)
