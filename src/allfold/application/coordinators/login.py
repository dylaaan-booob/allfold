"""Process-local CARSI login and independent saved-Service preparation."""
from dataclasses import dataclass, replace
from pathlib import Path
import threading
from uuid import uuid4

from allfold.application.bounded_dispatch import bounded_dispatch
from allfold.application.browser_runtime import ElectronDisconnected
from allfold.application.browser_services import BrowserServiceSnapshot
from allfold.application.coordinators.preparation_coordinator import institution_login_url
from allfold.application.history import observe
from allfold.browser_diagnostics import normalize_browser_diagnostic
from allfold.config import load_config


@dataclass(frozen=True)
class ServicePreparation:
    status: str = 'Not prepared'
    task_id: str | None = None
    workflow_id: str | None = None
    page_id: int | None = None
    reason: str | None = None
    diagnostic: dict | None = None
    waiting_for_user: bool = False


class LoginCoordinator:
    def __init__(self, bridge, browser_lock, *, diagnostics=None):
        self.bridge, self.browser_lock, self.diagnostics = bridge, browser_lock, diagnostics
        self._mutex = threading.RLock()
        self._worker = None
        self._stop = threading.Event()
        self._scope = None
        self._workflow_id = None
        self._results = {}
        self._phase = 'idle'
        self._carsi = ServicePreparation()

    @property
    def running(self):
        return self._worker is not None and self._worker.is_alive()

    def snapshot(self, saved):
        with self._mutex:
            results = self._results if self._scope == saved.scope else {}
            return {
                'active': self.running, 'workflow_id': self._workflow_id,
                'phase': self._phase, 'scope': saved.scope, 'carsi': self._carsi,
                'services': [
                    {'id': service.id, 'name': service.name, 'access_method': service.access_method,
                     'access_url': service.access_url, 'preparation': results.get(service.id, ServicePreparation())}
                    for service in saved.services
                ],
            }

    def prepared_page(self, saved, service_id):
        with self._mutex:
            result = self._results.get(service_id) if self._scope == saved.scope else None
            return result.page_id if result is not None and result.status == 'Opened' else None

    def start(self, config_path: Path, *, manual_service_id=None):
        saved = BrowserServiceSnapshot.read(config_path)
        config = load_config(config_path)
        saved.verify()
        if not self.bridge.connected:
            raise ValueError('Browser runtime unavailable')
        services = saved.services
        if manual_service_id is not None:
            services = tuple(s for s in services if s.id == manual_service_id and s.access_method == 'manual')
            if not services or not services[0].access_url:
                raise ValueError('Choose a saved Manual Service with an access URL')
        needs_carsi = any(service.access_method == 'carsi' for service in services)
        institution = config.institution
        authentication = dict(institution_name=institution.name if institution else None,
            use_shibboleth=institution.use_shibboleth if institution else False,
            login_url=institution_login_url(institution.idp_entity_id if institution else None))
        if needs_carsi and not (authentication['institution_name'] or
                authentication['use_shibboleth'] and authentication['login_url']):
            raise ValueError('Save an Institution before starting CARSI Login')
        with self._mutex:
            if self.running:
                raise ValueError('Login is already active')
            owner = self.browser_lock.acquire('login')
            if owner is None:
                raise ValueError('Another Browser workflow is active')
            self._stop = threading.Event()
            self._workflow_id = uuid4().hex
            scope = saved.scope
            if manual_service_id is None or self._scope != scope:
                self._results = {}
                self._carsi = ServicePreparation()
            self._scope = scope
            self._phase = 'carsi' if needs_carsi else 'preparing'
            for service in services:
                self._results[service.id] = ServicePreparation(task_id=uuid4().hex, workflow_id=self._workflow_id)
            observe(self.diagnostics, 'begin', 'login', self._workflow_id)
            self._worker = threading.Thread(target=self._run,
                args=(saved, services, authentication if needs_carsi else None, owner, manual_service_id, config.kept_workflow.prepare_service_concurrency),
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
            current = self._carsi if service_id is None else self._results[service_id]
            page = data.get('page_id')
            updated = replace(current, waiting_for_user=data.get('waiting_for_user') is True,
                page_id=page if type(page) is int and page > 0 else current.page_id)
            if service_id is None:
                self._carsi = updated
            else:
                self._results[service_id] = updated

    def _dispatch(self, owner, saved, action, data, service_id=None):
        self.browser_lock.require(owner)
        saved.verify()
        return self.bridge.execute(action, {
            **data, 'workflow_id': self._workflow_id, 'service_scope': saved.scope,
            'service_id': service_id,
        }, lambda progress: self._progress(service_id, progress))

    def _settle_service(self, current, data):
        evidence = data.get('evidence') or {}
        diagnostic = normalize_browser_diagnostic(data.get('diagnostic'))
        target = evidence.get('target_page_id')
        opened = (data.get('outcome') == 'Opened' and evidence.get('visit_action_observed') is True
                  and evidence.get('navigation_observed') is True and type(target) is int and target > 0)
        status = ('Opened' if opened else 'Canceled' if self._stop.is_set() else
                  'Needs attention' if data.get('outcome') == 'Needs attention' else 'Failed')
        return replace(current, status=status, waiting_for_user=False, diagnostic=diagnostic,
            page_id=target if opened else current.page_id,
            reason='target_opened' if opened else diagnostic.get('code') if diagnostic else data.get('reason', 'failed'))

    def _run(self, saved, services, authentication, owner, manual_service_id, concurrency):
        phase, portal_page = 'completed', None
        try:
            if authentication is not None:
                with self._mutex:
                    self._carsi = ServicePreparation(status='Preparing', task_id=uuid4().hex, workflow_id=self._workflow_id)
                    if self._stop.is_set():
                        return
                    pending = self._dispatch(owner, saved, 'login_carsi', {
                        **authentication, 'task_id': self._carsi.task_id,
                    })
                result = pending.result()
                saved.verify()
                portal_page = result.get('portal_page_id')
                success = type(portal_page) is int and portal_page > 0 and result.get('outcome') == 'Opened'
                with self._mutex:
                    self._carsi = replace(self._carsi, status='Opened' if success else
                        'Canceled' if self._stop.is_set() else 'Failed', waiting_for_user=False,
                        page_id=portal_page if success else self._carsi.page_id,
                        diagnostic=normalize_browser_diagnostic(result.get('diagnostic')))
                if not success:
                    phase = 'failed'
                    return
            with self._mutex:
                self._phase = 'preparing'
                for service in services:
                    if service.access_method == 'manual' and manual_service_id is None:
                        self._results[service.id] = replace(self._results[service.id],
                            status='Needs attention', reason='manual_action_required')

            def start(service):
                with self._mutex:
                    if self._stop.is_set():
                        raise InterruptedError()
                    current = self._results[service.id]
                    self._results[service.id] = replace(current, status='Preparing')
                    return self._dispatch(owner, saved, 'prepare_service' if service.access_method == 'carsi' else 'visit_manual_service', {
                        'task_id': current.task_id, 'name': service.name,
                        'portal_page_id': portal_page, 'access_url': service.access_url,
                    }, service.id)

            eligible = (service for service in services if service.access_method == 'carsi' or manual_service_id is not None)
            for service, future in bounded_dispatch(eligible, key=lambda service: service.id, start=start,
                    limit=concurrency, group_limit=1, stopped=self._stop.is_set):
                try:
                    data = future.result()
                except ElectronDisconnected:
                    data = {'reason': 'connection_lost'}
                except (OSError, RuntimeError, ValueError):
                    data = {'reason': 'failed'}
                with self._mutex:
                    self._results[service.id] = self._settle_service(self._results[service.id], data)
        except ElectronDisconnected:
            phase = 'interrupted'
        except (OSError, RuntimeError, ValueError):
            phase = 'failed'
        finally:
            with self._mutex:
                stopped = self._stop.is_set()
                self._phase = 'canceled' if stopped else phase
                if self._carsi.status == 'Preparing':
                    self._carsi = replace(self._carsi, status='Canceled' if stopped else 'Failed', waiting_for_user=False)
                for service in services:
                    current = self._results[service.id]
                    if current.status in {'Not prepared', 'Preparing'}:
                        self._results[service.id] = replace(current, status='Canceled' if stopped else 'Needs attention',
                            reason='cancelled' if stopped else 'carsi_login_required', waiting_for_user=False)
                counts = {status: sum(self._results[s.id].status == label for s in services)
                          for status, label in [('opened','Opened'), ('needs_attention','Needs attention'), ('failed','Failed')]}
                outcome = ('cancelled' if stopped else phase if phase != 'completed' else
                    'partial' if counts['opened'] and (counts['failed'] or counts['needs_attention']) else
                    'failed' if counts['failed'] else 'needs_attention' if counts['needs_attention'] else
                    'opened' if counts['opened'] else 'no_effect')
                observe(self.diagnostics, 'finish', self._workflow_id, outcome,
                    statistics={'services': len(services), **counts},
                    details={'results': [{'service_id': s.id,
                        'outcome': self._results[s.id].status.lower().replace(' ', '_').replace('canceled', 'cancelled'),
                        'reason': self._results[s.id].reason, 'diagnostic': self._results[s.id].diagnostic}
                        for s in services]})
                self.browser_lock.release(owner)

    def cancel(self, workflow_id):
        with self._mutex:
            if not self.running or self._workflow_id != workflow_id:
                return False
            self._stop.set()
            self.bridge.cancel_current()
            return True

    def shutdown(self):
        self.cancel(self._workflow_id)

    def join(self):
        if self._worker is not None:
            self._worker.join()
