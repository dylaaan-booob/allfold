"""UI Next projections of the shared Settings operations."""
from pathlib import Path
from dataclasses import replace
import os
import hmac

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from allfold.application.journal_covers import cover_details
from allfold.application.settings import load_settings, _read_journal_snapshot, SettingsIssueSource, SettingsIssue
from allfold.application.journal_lookup import journal_metadata, search_journals
from allfold.providers.openalex import OpenAlexError
from allfold.config import ConfigurationError, WORKFLOW_CONCURRENCY_FIELDS
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
    state.update(saved=saved, values=replace(context["settings_form"], openalex_api_key=None, pubmed_api_key=None), issues=tuple((*state["issues"], *context["settings_issues"])),
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
                         reset_preview):
    install_resource_api(app, config_path, csrf_token)
    install_autosave_api(app, config_path, csrf_token)
    install_credential_api(app, csrf_token)

    @app.get("/api/ui-next/settings")
    def get_settings():
        with app.state.settings_write_lock:
            state = settings_state(config_path, csrf_token)
            state['logging'] = logging_state(app)
        state["cover_search"] = app.state.journal_cover_search.state()
        return json_response(state)

    @app.get('/api/ui-next/browser-services')
    def browser_services():
        from allfold.application.browser_services import BrowserServiceSnapshot
        from allfold.persistence.safe_write import ContentChangedError
        try:
            snapshot = BrowserServiceSnapshot.read(config_path)
            return json_response({'scope': snapshot.scope, 'services': [
                {'id': service.id, 'name': service.name,
                 'access_method': service.access_method, 'access_url': service.access_url}
                for service in snapshot.services]})
        except (ConfigurationError, ContentChangedError, ValueError, OSError):
            return settings_error('Saved Browser Services are unavailable; check Settings.', 409)


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
            def commit_choice():
                from allfold.web.settings_guard import settings_task_active
                with app.state.settings_write_lock:
                    if settings_task_active(app):
                        raise ContentChangedError('Active task owns the saved Service mapping; the selection is pending')
                    choose_journal_service(config_path, key,
                        method=str(form.get('selection_method', '')), name=str(form.get('selection_name', '')),
                        url=str(form.get('selection_url', '')), expected_revision=disk.draft.journal_revision,
                        expected_monitor_revision=disk.draft.monitor_revision)
            await run_in_threadpool(commit_choice)
            return json_response(dict(settings_state(config_path, csrf_token), saved=True, message='Journal Service saved'))
        except PermissionError as error:
            return settings_error(str(error))
        except (ConfigurationError, ContentChangedError, ValueError, OSError) as error:
            return settings_error(str(error), 409)


# These are ordinary configuration values. Secrets and Workspace path changes
# deliberately remain on the explicit Preview/Confirm operation boundary.
AUTOSAVE_FIELDS = frozenset({
    'name', 'keyword_expression', 'from_month', 'to_month', 'log_level',
    'crossref_mailto', 'provider_aliases', 'provider_order', 'enabled_providers',
    *WORKFLOW_CONCURRENCY_FIELDS,
    'institution_name', 'institution_idp_entity_id', 'institution_use_shibboleth',
    'journals', 'access_services', 'groups', 'custom_labels',
})
REVISION_FIELDS = ('monitor_revision_exists', 'monitor_revision_digest',
                   'journal_revision_exists', 'journal_revision_digest')


def install_autosave_api(app, config_path, csrf_token):
    import hmac
    from starlette.concurrency import run_in_threadpool
    from allfold.application.settings import save_settings, SettingsSaveOutcome
    from allfold.web.settings_form import settings_draft_from_form, SettingsJournalRow, SettingsAccessServiceRow
    from allfold.web.settings_guard import settings_task_active

    def apply_patch(body):
        with app.state.settings_write_lock:
            disk = load_settings(config_path)
            state = settings_state(config_path, csrf_token, disk=disk)
            state['logging'] = logging_state(app)
            def refusal(outcome, message, issues=()):
                return json_response(dict(state, saved=False, outcome=outcome, message=message, issues=issues))
            if settings_task_active(app):
                return refusal('TASK_ACTIVE', 'Pending: configuration will be revalidated after the active task releases ownership.')
            changes, base = body.get('changes'), body.get('base')
            if (not isinstance(changes, dict) or not set(changes) <= AUTOSAVE_FIELDS
                    or not isinstance(base, dict) or set(base) != set(REVISION_FIELDS)):
                return refusal('INVALID_DRAFT', 'Only ordinary configuration fields can be autosaved.')
            values = settings_form_from_draft(disk.draft)
            if any(base[key] != getattr(values, key) for key in REVISION_FIELDS):
                return refusal('REVISION_CONFLICT', 'Saved configuration changed. Review the saved state before reapplying the retained draft.')
            try:
                updates = dict(changes)
                for key, row_type in (('journals', SettingsJournalRow), ('access_services', SettingsAccessServiceRow)):
                    if key in updates:
                        updates[key] = tuple(row_type(**row) for row in updates[key])
                for key in ('provider_order', 'enabled_providers', 'groups', 'custom_labels'):
                    if key in updates:
                        updates[key] = tuple(updates[key])
                values = replace(values, **updates)
                draft, issues = settings_draft_from_form(values)
            except (TypeError, ValueError, AttributeError):
                return refusal('INVALID_DRAFT', 'Configuration patch has invalid field values.')
            if draft is None or issues:
                return refusal('INVALID_DRAFT', 'Configuration validation failed; the draft is retained.', issues)
            result = save_settings(config_path, draft)
            state = settings_state(config_path, csrf_token, disk=result.state)
            state['logging'] = logging_state(app)
            return json_response(dict(state, saved=result.outcome is SettingsSaveOutcome.SAVED,
                outcome=result.outcome.value, save=result, validation=result.validation,
                message='Saved' if result.outcome is SettingsSaveOutcome.SAVED else 'Configuration was not fully saved; the draft is retained.',
                issues=tuple((*state['issues'], *result.issues))))

    @app.post('/api/ui-next/settings/autosave')
    async def autosave(request: Request):
        try:
            body = await request.json()
        except ValueError:
            return settings_error('Invalid configuration patch', 400)
        if not isinstance(body, dict) or not hmac.compare_digest(str(body.get('csrf_token', '')), csrf_token):
            return settings_error('Invalid CSRF token')
        return await run_in_threadpool(apply_patch, body)


def install_credential_api(app, csrf_token):
    """Explicit native credential mutation owns admission through settlement."""
    import hmac
    from starlette.concurrency import run_in_threadpool
    from allfold.application.browser_runtime import ElectronDisconnected
    from allfold.web.settings_guard import settings_task_active

    def commit(body):
        with app.state.settings_write_lock:
            if settings_task_active(app):
                return json_response({'ok': False, 'error': 'cas_task_active',
                    'message': 'Active task owns the saved configuration; credential draft retained.'}, 409)
            owner = app.state.browser_task_lock.acquire('credentials')
            if owner is None:
                return json_response({'ok': False, 'error': 'cas_task_active'}, 409)
            try:
                if not app.state.electron_bridge.connected:
                    raise ElectronDisconnected()
                result = app.state.electron_bridge.execute('cas_credentials', {
                    key: body[key] for key in ('operation', 'username', 'password', 'expected_revision')
                }).result()
                if result.get('ok') is True:
                    app.state.login.invalidate_credentials()
                # Native returns a bounded status only, never password/plaintext.
                return json_response({key: result[key] for key in
                    ('ok', 'error', 'configured', 'username', 'revision') if key in result})
            except (ElectronDisconnected, RuntimeError, OSError):
                return json_response({'ok': False, 'error': 'cas_store_unavailable',
                    'message': 'Credential result could not be confirmed. Re-read status before retrying.'}, 409)
            finally:
                app.state.browser_task_lock.release(owner)

    @app.post('/api/ui-next/settings/credentials')
    async def credentials(request: Request):
        try:
            body = await request.json()
        except ValueError:
            return settings_error('Invalid credential operation', 400)
        if not isinstance(body, dict) or not hmac.compare_digest(str(body.get('csrf_token', '')), csrf_token):
            return settings_error('Invalid CSRF token')
        if (body.get('operation') not in ('save', 'clear') or any(
                not isinstance(body.get(key), str) for key in ('username', 'password', 'expected_revision'))
                or len(body['username']) > 1024 or len(body['password']) > 16384
                or len(body['expected_revision']) > 128):
            return settings_error('Invalid credential operation', 400)
        return await run_in_threadpool(commit, body)
