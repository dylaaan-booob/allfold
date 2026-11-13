"""One explicit Journal cover search; local assets remain independently guarded."""
import base64
import binascii
from pathlib import Path
import secrets
import threading

from allfold.browser_diagnostics import format_browser_diagnostic, normalize_browser_diagnostic
from allfold.recovery_diagnostics import normalize_recovery, recovery_progress_message
from allfold.application.history import observe
from allfold.application.browser_runtime import ElectronDisconnected
from allfold.application.journal_covers import (
    MAX_IMAGE_BYTES, CoverConflict, _save_cover, capture_cover_authority, cover_details, save_crop, upload_cover,
)
from allfold.url_safety import normalize_public_http_url

MAX_IMAGE_BASE64 = 4 * ((MAX_IMAGE_BYTES + 2) // 3)
FAILED_MESSAGE = "未获取到图片"


class JournalCoverSearch:
    def __init__(self, bridge=None, browser_lock=None, *, diagnostics=None, settings_lock=None):
        self.bridge, self.browser_lock = bridge, browser_lock
        self.diagnostics = diagnostics
        self._lock = threading.RLock()
        self._asset_lock = threading.Lock()
        self._settings_lock = settings_lock or threading.RLock()
        self._uploading = False
        self._task = None
        self._worker = None

    @property
    def running(self):
        return self._worker is not None and self._worker.is_alive()

    def state(self):
        with self._lock:
            state = dict(phase='Idle', request_id=None, journal_key=None, result=None, message='',
                         waiting_for_user=False, supported=bool(self.bridge and self.bridge.connected),
                         busy=bool(self._task and not self._task['settled']) or self._uploading)
            if self._task:
                state.update({key: self._task[key] for key in (
                    'phase', 'request_id', 'journal_key', 'result', 'message', 'waiting_for_user')})
            return state

    def start(self, list_path: Path, journals, journal_key, *, config_path: Path):
        if not isinstance(journal_key, str) or not journal_key.strip():
            raise ValueError('journal_key is required')
        journal = next((j for j in journals if j.key == journal_key), None)
        if journal is None:
            raise ValueError('Save this Journal before searching')
        with self._lock:
            if self.state()['busy']:
                raise ValueError('Cover assets are busy')
            if not self.bridge or not self.bridge.connected:
                raise ValueError('Electron runtime is unavailable')
            owner = self.browser_lock.acquire('covers')
            if owner is None:
                raise ValueError('Another browser workflow is active')
            try:
                task = dict(request_id=secrets.token_hex(16), journal_key=journal.key, result=None,
                    phase='Running', message='Searching this Journal', waiting_for_user=False, settled=False,
                    stop=threading.Event(), owner=owner, list_path=list_path,
                    config_path=config_path, authority=capture_cover_authority(list_path, journal, config_path=config_path))
                observe(self.diagnostics, "begin", "covers", task["request_id"])
                self._task = task
                self._worker = threading.Thread(target=self._run, args=(task, journal),
                    name='electron-cover-search', daemon=False)
                self._worker.start()
            except BaseException:
                if self._task is not None:
                    observe(self.diagnostics, "finish", self._task["request_id"], "failed", details={"reason":"failed"})
                self.browser_lock.release(owner)
                self._task = None
                raise
            return self.state()

    def _run(self, task, journal):
        try:
            with self._lock:
                if task['stop'].is_set():
                    raise InterruptedError()
                pending = self.bridge.execute('search_journal_cover',
                    {'journal_key': journal.key, 'name': journal.name, 'task_id':task['request_id'], 'workflow_id':task['request_id']}, lambda data: self._progress(task, data))
            result = pending.result()
            with self._lock:
                task['recovery'] = normalize_recovery(result.get('recovery'))
                if task['stop'].is_set():
                    raise InterruptedError()
                diagnostic = normalize_browser_diagnostic(result.get('diagnostic'))
                task['diagnostic'] = diagnostic
                if diagnostic:
                    task.update(phase='Failed', message=format_browser_diagnostic(diagnostic))
                    return
            with self._asset_lock:
                with self._lock:
                    if task['stop'].is_set():
                        raise InterruptedError()
                source = normalize_public_http_url(result.get('source_url')) if result.get('source_url') else None
                image = result.get('image_base64')
                if not source or not isinstance(image, str) or len(image) > MAX_IMAGE_BASE64:
                    raise ValueError(FAILED_MESSAGE)
                data = base64.b64decode(image, validate=True)
                if len(data) > MAX_IMAGE_BYTES:
                    raise ValueError('Image too large')
                with self._settings_lock, self._lock:
                    if task['stop'].is_set():
                        raise InterruptedError()
                    _save_cover(task['list_path'], journal.key, data, source_type='downloaded', source_url=source,
                        config_path=task['config_path'], authority=task['authority'])
                    task.update(phase='Completed', message='Saved', result=cover_details(task['list_path'], journal.key))
        except InterruptedError:
            task.update(phase='Cancelled', message='Cancelled')
        except (ValueError, OSError, binascii.Error):
            task.update(phase='Failed', message=FAILED_MESSAGE)
        except Exception as error:
            if isinstance(error, ElectronDisconnected):
                task["history_interrupted"] = True
            task.update(phase='Failed', message='Electron cover search failed')
        finally:
            with self._lock:
                task['waiting_for_user'] = False
                self.browser_lock.release(task['owner'])
                task['settled'] = True
                observe(self.diagnostics, 'finish', task['request_id'], 'interrupted' if task.get('history_interrupted') else task['phase'].lower(),
                    statistics={'downloaded':int(task['phase'] == 'Completed')}, diagnostic=task.get('diagnostic'),
                    details={'recovery':task.get('recovery'), 'reason':'connection_lost' if task.get('history_interrupted') else
                        'cancelled' if task['phase'] == 'Cancelled' else 'failed' if task['phase'] == 'Failed' else None})

    def _progress(self, task, data):
        with self._lock:
            if not task['stop'].is_set():
                task.update(waiting_for_user=data.get('waiting_for_user') is True,
                    message='Complete verification in BROWSER' if data.get('waiting_for_user') else
                        recovery_progress_message(data.get('recovery_action')) or 'Searching this Journal')

    def cancel(self, request_id):
        with self._lock:
            task = self._task
            if not self.running or not task or task['phase'] != 'Running' or task['request_id'] != request_id:
                return False
            task['stop'].set()
            self.bridge.cancel_task(task['request_id'], task['request_id'])
            task['message'] = 'Stopping; waiting for the browser request to settle'
            return True

    def shutdown(self):
        if self._task:
            self.cancel(self._task['request_id'])

    def join(self):
        if self._worker:
            self._worker.join()

    def upload(self, list_path, journal_key, data, *, config_path: Path):
        if not self._asset_lock.acquire(blocking=False):
            raise ValueError('Cover assets are busy')
        try:
            with self._lock:
                if self.state()['busy']:
                    raise ValueError('Cover search is running')
                self._uploading = True
            try:
                return upload_cover(list_path, journal_key, data, config_path=config_path)
            finally:
                with self._lock:
                    self._uploading = False
        finally:
            self._asset_lock.release()

    def crop(self, list_path, journal_key, sha256, crop, *, config_path: Path):
        if not self._asset_lock.acquire(blocking=False):
            raise CoverConflict('Cover assets are busy')
        try:
            with self._lock:
                if self.state()['busy']:
                    raise CoverConflict('Cover search or upload is running')
                return save_crop(list_path, journal_key, sha256, crop, config_path=config_path)
        finally:
            self._asset_lock.release()
