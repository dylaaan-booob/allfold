"""Prepare the selected Services in the shared Browser Session."""

from concurrent.futures import as_completed, wait
from dataclasses import dataclass, replace
from pathlib import Path
import threading
from uuid import uuid4

from allfold.application.browser_runtime import ElectronDisconnected
from allfold.application.browser_services import BrowserServiceSnapshot
from allfold.application.carsi_catalog import get_carsi_catalog
from allfold.application.carsi_entry import service_entry
from allfold.application.history import observe
from allfold.config import load_config
from allfold.browser_diagnostics import normalize_browser_diagnostic
from allfold.persistence.user_state import application_data_dir
from allfold.recovery_diagnostics import normalize_recovery, normalize_recovery_action


@dataclass(frozen=True)
class ServicePreparation:
    status: str = 'Not prepared'
    task_id: str | None = None
    workflow_id: str | None = None
    page_id: int | None = None
    reason: str | None = None
    diagnostic: dict | None = None
    waiting_for_user: bool = False
    recovery_action: str | None = None
    recovery: list | None = None
    pdf_source: str | None = None


class LoginCoordinator:
    def __init__(self, bridge, browser_lock, *, diagnostics=None):
        self.bridge, self.browser_lock, self.diagnostics = bridge, browser_lock, diagnostics
        self._mutex = threading.RLock()
        self._worker = None
        self._stop = threading.Event()
        self._scope_id = None
        self._workflow_id = None
        self._results = {}
        self._phase = 'idle'
        self._closed_pages = set()

    @property
    def running(self):
        return self._worker is not None and self._worker.is_alive()

    def snapshot(self, saved):
        with self._mutex:
            return {
                'active': self.running, 'workflow_id': self._workflow_id,
                'phase': self._phase, 'scope': saved.scope,
                'services': [
                    {'id': service.id, 'name': service.name, 'access_method': service.access_method,
                     'access_url': service.access_url,
                     'preparation': self._result(saved, service.id) or ServicePreparation()}
                    for service in saved.services
                ],
            }

    def _result(self, saved, service_id):
        if self._scope_id == saved.scope_id:
            return self._results.get(service_id)
        return None

    def prepared_authority(self, saved, service_id):
        with self._mutex:
            result = self._result(saved, service_id)
            return result if result is not None and result.status == 'Opened' else None

    def prepared_page(self, saved, service_id):
        binding = self.prepared_authority(saved, service_id)
        return binding.page_id if binding is not None else None

    def invalidate_pages(self, page_ids):
        with self._mutex:
            closed = set(page_ids)
            if self.running:
                self._closed_pages.update(closed)
            for service_id, result in tuple(self._results.items()):
                if result.page_id in closed:
                    self._results[service_id] = replace(result, page_id=None)

    def forget_services(self, scope_id, service_ids):
        with self._mutex:
            if self._scope_id == scope_id:
                for service_id in service_ids:
                    self._results.pop(service_id, None)

    def reset(self):
        with self._mutex:
            self._results.clear()
            self._phase = 'idle'
            self._workflow_id = None

    def start(self, config_path: Path, *, manual_service_id=None, service_ids=None):
        saved = BrowserServiceSnapshot.read(config_path)
        if not self.bridge.connected:
            raise ValueError('Browser runtime unavailable')
        if manual_service_id is not None:
            services = tuple(s for s in saved.services if s.id == manual_service_id and s.access_method == 'manual')
            if not services or not services[0].access_url:
                raise ValueError('Choose a saved Manual Service with an access URL')
            entries = {}
        else:
            available = tuple(s for s in saved.services if s.access_method == 'carsi')
            chosen = set(service_ids or ())
            services = tuple(s for s in available if s.id in chosen)
            if not services or chosen != {s.id for s in services}:
                raise ValueError('Choose saved CARSI Services to prepare')
            catalog = get_carsi_catalog(application_data_dir(config_path) / 'resources.sqlite')
            entries = {s.id: service_entry(config_path, s, saved.institution, catalog=catalog) for s in services}
        saved.verify(s.id for s in services)
        with self._mutex:
            if self.running:
                raise ValueError('Login is already active')
            scopes = {saved.service_scope(service.id) for service in services}
            if entries:
                scopes.add('authentication:' + saved.scope_id)
            owner = self.browser_lock.acquire('login', scopes=scopes)
            if owner is None:
                raise ValueError('Another Browser workflow is active')
            self._stop = threading.Event()
            self._closed_pages.clear()
            self._workflow_id = uuid4().hex
            if self._scope_id != saved.scope_id:
                self._results.clear()
            self._scope_id = saved.scope_id
            self._phase = 'preparing'
            for service in services:
                reason = (entries.get(service.id) or {}).get('unavailable_reason')
                self._results[service.id] = ServicePreparation(
                    status='Unavailable' if reason else 'Not prepared', reason=reason,
                    task_id=uuid4().hex, workflow_id=self._workflow_id)
            observe(self.diagnostics, 'begin', 'login', self._workflow_id)
            self._worker = threading.Thread(target=self._run, args=(saved, services, entries, owner),
                name='allfold-login', daemon=False)
            try:
                self._worker.start()
            except BaseException:
                self._phase = 'failed'
                self.browser_lock.release(owner)
                observe(self.diagnostics, 'finish', self._workflow_id, 'failed')
                raise
            return self.snapshot(saved)

    def _progress(self, service_id, data):
        with self._mutex:
            if self._stop.is_set():
                return
            current = self._results[service_id]
            page = data.get('page_id')
            if page in self._closed_pages:
                return
            self._results[service_id] = replace(current, waiting_for_user=data.get('waiting_for_user') is True
                if 'waiting_for_user' in data else current.waiting_for_user,
                recovery_action=normalize_recovery_action(data.get('recovery_action')),
                page_id=page if type(page) is int and page > 0 else current.page_id)

    def _dispatch(self, owner, saved, service, entry, *, first):
        with self._mutex:
            def verify():
                self.browser_lock.require(owner)
                if self._stop.is_set():
                    raise InterruptedError('Preparation was canceled')
                saved.verify((service.id,))
                if entry is not None:
                    saved.verify_school()

            verify()
            if entry is not None:
                entry = service_entry(saved.config_path, service, load_config(saved.config_path).institution)
            current = self._results[service.id] = replace(self._results[service.id], status='Preparing')
            return self.bridge.execute('prepare_service' if entry is not None else 'visit_manual_service', {
                'service_id': service.id, 'service_scope': saved.scope,
                'workflow_id': self._workflow_id, 'task_id': current.task_id,
                'access_url': service.access_url, 'service_entry': entry, 'first_entry': first,
            }, lambda progress: self._progress(service.id, progress), verify_recovery=verify)

    def _settle(self, saved, service, future):
        try:
            data = future.result()
            saved.verify((service.id,))
            if service.access_method == 'carsi':
                saved.verify_school()
        except ElectronDisconnected:
            data = {'reason': 'connection_lost'}
        except (OSError, RuntimeError, ValueError):
            data = {'reason': 'failed'}
        with self._mutex:
            diagnostic = normalize_browser_diagnostic(data.get('diagnostic'))
            target = data.get('target_page_id')
            opened = data.get('outcome') == 'Opened' and type(target) is int and target > 0
            stopped = self._stop.is_set()
            status = ('Canceled' if stopped else 'Opened' if opened else
                      'Needs attention' if data.get('outcome') in {'Opened', 'Needs attention'} else 'Failed')
            self._results[service.id] = replace(self._results[service.id], status=status,
                waiting_for_user=False, diagnostic=diagnostic, recovery_action=None,
                recovery=normalize_recovery(data.get('recovery')) or None,
                page_id=target if opened and not stopped and target not in self._closed_pages else None,
                pdf_source='ebsco' if opened and data.get('pdf_source') == 'ebsco' else None,
                reason=(diagnostic or {}).get('code') or data.get('reason'))
            return opened and not stopped

    def _run(self, saved, services, entries, owner):
        phase = 'completed'
        try:
            eligible = iter(s for s in services if not (entries.get(s.id) or {}).get('unavailable_reason'))
            first = next(eligible, None)
            if first is not None and not self._settle(saved, first,
                    self._dispatch(owner, saved, first, entries.get(first.id), first=True)):
                phase = 'completed' if self._results[first.id].status == 'Needs attention' else 'failed'
                return
            pending = {}
            try:
                for service in eligible:
                    future = self._dispatch(owner, saved, service, entries[service.id], first=False)
                    pending[future] = service
            finally:
                # Registration and cancellation both use the coordinator mutex.
                # Each submitted operation keeps its owner through native settlement.
                try:
                    for future in as_completed(pending):
                        self._settle(saved, pending[future], future)
                finally:
                    wait(pending)
        except ElectronDisconnected:
            phase = 'interrupted'
        except (OSError, RuntimeError, ValueError):
            phase = 'failed'
        finally:
            try:
                with self._mutex:
                    stopped = self._stop.is_set()
                    self._phase = 'canceled' if stopped else phase
                    for service in services:
                        current = self._results[service.id]
                        if current.status in {'Not prepared', 'Preparing'}:
                            self._results[service.id] = replace(current, status='Canceled' if stopped else 'Needs attention',
                                reason='cancelled' if stopped else 'first_service_incomplete', waiting_for_user=False)
                    counts = {status: sum(self._results[s.id].status == label for s in services)
                              for status, label in [('opened','Opened'), ('needs_attention','Needs attention'),
                                                    ('failed','Failed'), ('unavailable','Unavailable')]}
                    outcome = ('cancelled' if stopped else phase if phase != 'completed' else
                        'partial' if counts['opened'] and (counts['failed'] or counts['needs_attention']) else
                        'failed' if counts['failed'] else 'needs_attention' if counts['needs_attention'] else
                        'opened' if counts['opened'] else 'no_effect')
                    observe(self.diagnostics, 'finish', self._workflow_id, outcome, statistics={'services': len(services), **counts},
                        details={'results': [{'service_id': s.id,
                            'outcome': self._results[s.id].status.lower().replace(' ', '_').replace('canceled', 'cancelled'),
                            'reason': self._results[s.id].reason, 'diagnostic': self._results[s.id].diagnostic,
                            'recovery': self._results[s.id].recovery} for s in services]})
            finally:
                self.browser_lock.release(owner)

    def cancel(self, workflow_id):
        with self._mutex:
            if not self.running or self._workflow_id != workflow_id:
                return False
            self._stop.set()
            self.bridge.cancel_workflow(workflow_id)
            return True

    def shutdown(self):
        self.cancel(self._workflow_id)

    def join(self):
        if self._worker is not None:
            self._worker.join()
