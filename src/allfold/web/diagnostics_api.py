"""HTTP projection for bounded local evidence and guarded Logs Reset."""
from concurrent.futures import TimeoutError
import hmac
import os
import secrets
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from allfold.application.coordinators.run_coordinator import CoordinatorStatus
from allfold.diagnostics import DiagnosticRefused
from allfold.browser_diagnostics import format_browser_diagnostic
from allfold.persistence.safe_write import _open_directory_nofollow


class _ExportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    csrf_token: str | None = None
    task_id: str | None = None


def _json(data, status=200):
    return JSONResponse(data, status_code=status, headers={'Cache-Control': 'no-store'})


def install_diagnostics_api(app, *, run_slot):
    store = app.state.diagnostics
    bridge = app.state.electron_bridge

    def valid_csrf(value):
        return (isinstance(value, str) and value.isascii()
                and hmac.compare_digest(value, app.state.csrf_token))

    def native_call(operation, expected=None):
        data = {'operation': operation, 'scope_id': store.scope_id}
        if expected is not None:
            data['expected'] = expected
        result = bridge.execute('diagnostics_reset', data).result(timeout=10)
        if not isinstance(result, dict) or result.get('scope_id') != store.scope_id:
            raise DiagnosticRefused('Native log identity could not be confirmed')
        store.native_status(result.get('status'))
        return result

    def offline_native_absent():
        # A disconnected transport is not proof that Electron exited. Never
        # delete its files from Python, even when its current sink looks idle.
        path = store.root / 'scopes' / store.scope_id / 'electron'
        try:
            directory = _open_directory_nofollow(path)
        except FileNotFoundError:
            return True
        else:
            os.close(directory)
            return False

    def logs_preview():
        app.state.reset_confirmation = None
        try:
            if bridge.connected:
                native = native_call('preview')
                if native.get('available') is not True or not isinstance(native.get('token'), str):
                    raise DiagnosticRefused('Native diagnostic writer is unavailable')
            elif not offline_native_absent():
                raise DiagnosticRefused('Electron disconnected; existing native logs cannot be safely reset')
            else:
                native = None
            plan = store.preview_reset()
            token = secrets.token_urlsafe(32)
            app.state.reset_confirmation = (token, plan, 'logs', native)
            return {'reset_plan': {'scope': 'logs', 'scope_id': store.scope_id,
                'history_records': len(store.history()['records']),
                'includes_native': native is not None, 'includes_app_level': False,
                'description': 'Clear history and diagnostic files for this configuration only. '
                    'Workspace, settings, browser sessions and downloaded diagnostic bundles are preserved.'},
                'reset_token': token, 'reset_error': None}
        except (OSError, ValueError, RuntimeError, TimeoutError):
            return {'reset_plan': None, 'reset_token': None,
                    'reset_error': 'Logs preview unavailable. Reconnect Electron and reopen Settings; no files were deleted.'}

    @app.get('/api/history')
    def history():
        data = store.history()
        for record in data['records']:
            if record.get('diagnostic'):
                record['diagnostic_message'] = format_browser_diagnostic(record['diagnostic'])
            for result in record.get('details', {}).get('results', []):
                if result.get('diagnostic'):
                    result['diagnostic_message'] = format_browser_diagnostic(result['diagnostic'])
        return _json(data)

    @app.post('/api/diagnostics/export')
    def export(body: _ExportRequest):
        if not valid_csrf(body.csrf_token):
            return _json({'message': 'Invalid or missing CSRF token.'}, 403)
        try:
            payload = store.export(body.task_id)
        except (OSError, ValueError, DiagnosticRefused):
            return _json({'message': 'Diagnostics unavailable or task is outside the retained history.'}, 409)
        return Response(payload, media_type='application/zip', headers={
            'Content-Disposition': 'attachment; filename="allfold-diagnostics.zip"',
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    def reset_logs(form):
        result = None
        status = 409
        with app.state.import_submission_lock, app.state.reset_lock, store.reset_guard():
            saved = app.state.reset_confirmation
            app.state.reset_confirmation = None  # Every submitted attempt consumes the authorization.
            token = form.get('reset_token')
            if (saved is None or len(saved) < 3 or saved[2] != 'logs'
                    or not isinstance(token, str) or not token.isascii()
                    or not secrets.compare_digest(token, saved[0])):
                message = 'Logs confirmation is stale or already used. Reopen Reset.'
            elif (app.state.run_coordinator.snapshot().status is CoordinatorStatus.RUNNING
                    or app.state.wos_coordinator.running or app.state.batch_import.running
                    or app.state.kept_workflow.snapshot().active
                    or app.state.browser_task_lock.owner is not None):
                message = 'A workflow is active; Logs Reset refused.'
            elif not run_slot.acquire(blocking=False):
                message = 'A Run is active; Logs Reset refused.'
            else:
                owner = app.state.browser_task_lock.acquire('logs-reset')
                try:
                    if owner is None:
                        raise DiagnosticRefused('A browser workflow is active')
                    # Validate before any producer deletes data. Revalidation
                    # inside reset protects the later Python deletion as well.
                    store.validate_reset(saved[1])
                    native = saved[3]
                    if native is not None:
                        if not bridge.connected:
                            raise DiagnosticRefused('Native connection changed')
                        native_result = native_call('reset', native)
                        result = {'native': native_result, 'python': None}
                        if native_result.get('success') is not True:
                            raise DiagnosticRefused('Native logs were not fully cleared')
                    elif bridge.connected or not offline_native_absent():
                        raise DiagnosticRefused('Native writer changed since preview')
                    python_result = store.reset(saved[1])
                    result = {**(result or {}), 'python': python_result}
                    status = 200 if python_result['success'] else 409
                    message = ('Logs cleared for this configuration.' if status == 200 else
                               'Logs Reset incomplete; some diagnostic files remain. Reopen Reset to inspect the current target.')
                except (OSError, ValueError, RuntimeError, TimeoutError):
                    message = ('Logs Reset could not complete. Some files may have been deleted; '
                               'the result is unconfirmed. No automatic retry was performed.' if result else
                               'Logs Reset refused or native result unconfirmed. Reconnect Electron and reopen Reset; no automatic retry was performed.')
                finally:
                    if owner is not None:
                        app.state.browser_task_lock.release(owner)
                    run_slot.release()
        return _json({'reset_plan': None, 'reset_token': None, 'reset_error': message,
                      'reset_success': status == 200, 'reset_result': result}, status)

    @app.post('/settings/logs-reset')
    async def logs_reset(request: Request):
        form = await request.form()
        if not valid_csrf(form.get('csrf_token')):
            return _json({'message': 'Invalid or missing CSRF token.'}, 403)
        return await run_in_threadpool(reset_logs, form)

    return logs_preview
