"""Process-local CARSI login and independent saved-Service preparation."""
from dataclasses import dataclass, replace
from contextlib import closing
from pathlib import Path
from urllib.parse import urlencode
import threading
from uuid import uuid4

from pydantic import ValidationError

from allfold.application.bounded_dispatch import bounded_dispatch
from allfold.application.browser_runtime import ElectronDisconnected
from allfold.application.browser_services import BrowserServiceSnapshot
from allfold.application.history import observe
from allfold.browser_diagnostics import normalize_browser_diagnostic
from allfold.recovery_diagnostics import normalize_recovery, normalize_recovery_action
from allfold.config import ConfigurationError, InstitutionConfig, load_config


CARSI_LOGIN_URL = "https://ds.carsi.edu.cn/Shibboleth.sso/Login"
CARSI_PORTAL_URL = "https://ds.carsi.edu.cn/wxds"

def institution_login_url(entity_id: str | None) -> str | None:
    """Construct the official CARSI entry only from a schema-valid IdP entity ID."""
    try:
        validated = InstitutionConfig(idp_entity_id=entity_id).idp_entity_id
    except (ValidationError, ValueError) as error:
        raise ConfigurationError("Institution.idp_entity_id is invalid") from error
    if validated is None:
        return None
    return f"{CARSI_LOGIN_URL}?{urlencode({'entityID': validated, 'target': CARSI_PORTAL_URL})}"


@dataclass(frozen=True)
class ServicePreparation:
    status: str = 'Not prepared'
    task_id: str | None = None
    workflow_id: str | None = None
    page_id: int | None = None
    reason: str | None = None
    diagnostic: dict | None = None
    waiting_for_user: bool = False
    manually_confirmed: bool = False
    recovery_action: str | None = None
    recovery: list | None = None


@dataclass(frozen=True)
class PreparedService:
    page_id: int | None
    key: str
    manually_confirmed: bool = False


class LoginCoordinator:
    def __init__(self, bridge, browser_lock, *, diagnostics=None):
        self.bridge, self.browser_lock, self.diagnostics = bridge, browser_lock, diagnostics
        self._mutex = threading.RLock()
        self._worker = None
        self._stop = threading.Event()
        self._auth_key = None
        self._scope_id = None
        self._credential_epoch = uuid4().hex
        self._workflow_id = None
        self._confirmation_batch: tuple[str, dict[str, str]] | None = None
        self._results = {}
        self._keys = {}
        self._phase = 'idle'
        self._carsi = ServicePreparation()
        self._closed_pages = set()

    @property
    def running(self):
        return self._worker is not None and self._worker.is_alive()

    def snapshot(self, saved):
        with self._mutex:
            carsi = self._carsi if self._auth_key == saved.authentication_key(self._credential_epoch) else ServicePreparation()
            return {
                'active': self.running, 'workflow_id': self._workflow_id,
                'phase': self._phase, 'scope': saved.scope, 'carsi': carsi,
                'confirmation_workflow_id': self._confirmation_id(saved),
                'services': [
                    {'id': service.id, 'name': service.name, 'access_method': service.access_method,
                     'access_url': service.access_url, 'preparation': self._service_result(saved, service) or ServicePreparation()}
                    for service in saved.services
                ],
            }

    def _service_result(self, saved, service):
        if self._keys.get(service.id) == saved.preparation_key(service, self._credential_epoch):
            return self._results.get(service.id)
        return None

    def prepared_authority(self, saved, service_id):
        with self._mutex:
            service = next((service for service in saved.services if service.id == service_id), None)
            result = self._service_result(saved, service) if service is not None else None
            if result is not None and result.status == 'Opened':
                return PreparedService(result.page_id, self._keys[service_id], result.manually_confirmed)
            return None

    def prepared_page(self, saved, service_id):
        binding = self.prepared_authority(saved, service_id)
        return binding.page_id if binding is not None else None

    def _confirmation_id(self, saved):
        if self._confirmation_batch is None or self.running:
            return None
        workflow_id, keys = self._confirmation_batch
        current_keys = {service.id: saved.preparation_key(service, self._credential_epoch)
                        for service in saved.services}
        if (keys == current_keys and all(self._keys.get(service_id) == key for service_id, key in keys.items())
                and any(self._results[service_id].status != 'Opened' for service_id in keys)):
            return workflow_id
        return None

    def confirm_all(self, saved, workflow_id):
        with self._mutex:
            expected = self._confirmation_id(saved)
            if expected is None or workflow_id != expected:
                raise ValueError('The Login results changed or are unavailable. Refresh Login.')
            if not self.bridge.connected:
                raise ValueError('Browser runtime unavailable')
            owner = self.browser_lock.acquire('login', scopes={saved.service_scope(service.id) for service in saved.services})
            if owner is None:
                raise ValueError('Another Browser workflow is active')
            try:
                saved.verify()
                for service in saved.services:
                    result = self._results[service.id]
                    if result.status != 'Opened':
                        result = replace(result, status='Opened', page_id=None,
                            reason='manual_login_confirmed', diagnostic=None)
                    self._results[service.id] = replace(result, manually_confirmed=True)
                self._confirmation_batch = None
                self._workflow_id = workflow_id
                self._phase = 'confirmed'
                return self.snapshot(saved)
            finally:
                self.browser_lock.release(owner)

    def access_invalidation(self, scope_id, service_ids, authentication_changed=False):
        with self._mutex:
            if self._scope_id != scope_id:
                return None
            keys = {service_id: key for service_id, key in self._keys.items() if service_id in service_ids}
            authentication = self._auth_key if authentication_changed else None
            return {'scope_id': scope_id, 'preparation_keys': keys, 'authentication_key': authentication} if keys or authentication else None

    def invalidate_pages(self, page_ids):
        with self._mutex:
            closed = set(page_ids)
            if self.running:
                self._closed_pages.update(closed)
            if self._carsi.page_id in closed:
                self._carsi = ServicePreparation()
            for service_id, result in tuple(self._results.items()):
                if result.page_id in closed:
                    self._results[service_id] = replace(result, status='Needs attention', page_id=None,
                        reason='target_closed', waiting_for_user=False, recovery_action=None,
                        manually_confirmed=False)
            self._confirmation_batch = None

    def invalidate_credentials(self):
        """Called under Browser admission after a confirmed native credential change."""
        with self._mutex:
            self._credential_epoch = uuid4().hex
            self._results.clear()
            self._keys.clear()
            self._confirmation_batch = None
            self._carsi = ServicePreparation()
            self._auth_key = None

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
        institution = saved.institution
        authentication = dict(institution_name=institution.name if institution else None,
            use_shibboleth=institution.use_shibboleth if institution else False,
            login_url=institution_login_url(institution.idp_entity_id if institution else None))
        if needs_carsi and not (authentication['institution_name'] or
                authentication['use_shibboleth'] and authentication['login_url']):
            raise ValueError('Save an Institution before starting CARSI Login')
        with self._mutex:
            if self.running:
                raise ValueError('Login is already active')
            owner = self.browser_lock.acquire('login', scopes={saved.service_scope(service.id) for service in services})
            if owner is None:
                raise ValueError('Another Browser workflow is active')
            self._stop = threading.Event()
            self._closed_pages.clear()
            self._workflow_id = uuid4().hex
            auth_key = saved.authentication_key(self._credential_epoch)
            if manual_service_id is None or self._auth_key != auth_key:
                self._results.clear()
                self._keys.clear()
                self._confirmation_batch = None
                self._carsi = ServicePreparation()
            self._auth_key = auth_key
            self._scope_id = saved.scope_id
            self._phase = 'carsi' if needs_carsi else 'preparing'
            for service in services:
                self._keys[service.id] = saved.preparation_key(service, self._credential_epoch)
                self._results[service.id] = ServicePreparation(task_id=uuid4().hex, workflow_id=self._workflow_id)
            observe(self.diagnostics, 'begin', 'login', self._workflow_id)
            self._worker = threading.Thread(target=self._run,
                args=(saved, services, authentication if needs_carsi else None, owner, manual_service_id, config.workflow.prepare_service_concurrency),
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
            if self._stop.is_set():
                return
            page = data.get('page_id')
            if type(page) is int and page in self._closed_pages:
                return
            updated = replace(current, waiting_for_user=data.get('waiting_for_user') is True,
                recovery_action=normalize_recovery_action(data.get('recovery_action')),
                page_id=page if type(page) is int and page > 0 else current.page_id)
            if service_id is None:
                self._carsi = updated
            else:
                self._results[service_id] = updated

    def _dispatch(self, owner, saved, action, data, service_id=None):
        self.browser_lock.require(owner)
        saved.verify((service_id,) if service_id is not None else ())
        if data.get('portal_page_id') in self._closed_pages:
            raise InterruptedError('Preparation Portal closed')
        recovery = {}
        if action == 'prepare_service':
            workflow = self._workflow_id
            epoch = self._credential_epoch
            key = data['preparation_key']

            def verify_recovery():
                self.browser_lock.require(owner)
                saved.verify((service_id,))
                with self._mutex:
                    if (self._stop.is_set() or self._workflow_id != workflow or self._credential_epoch != epoch
                            or self._keys.get(service_id) != key):
                        raise InterruptedError('Preparation authority changed')

            recovery['verify_recovery'] = verify_recovery
        return self.bridge.execute(action, {
            **data, 'workflow_id': self._workflow_id, 'service_scope': saved.scope,
            'authentication_key': self._auth_key,
            'service_id': service_id,
        }, lambda progress: self._progress(service_id, progress), **recovery)

    def _settle_service(self, current, data):
        evidence = data.get('evidence') or {}
        diagnostic = normalize_browser_diagnostic(data.get('diagnostic'))
        target = evidence.get('target_page_id')
        opened = (data.get('outcome') == 'Opened' and evidence.get('visit_action_observed') is True
                  and evidence.get('navigation_observed') is True and type(target) is int and target > 0
                  and target not in self._closed_pages)
        status = ('Opened' if opened else 'Canceled' if self._stop.is_set() else
                  'Needs attention' if data.get('outcome') in {'Opened', 'Needs attention'} else 'Failed')
        return replace(current, status=status, waiting_for_user=False, diagnostic=diagnostic,
            recovery_action=None, recovery=normalize_recovery(data.get('recovery')) or None,
            page_id=target if opened else None,
            reason=('target_opened' if opened else diagnostic.get('code') if diagnostic else
                    'unverified_official_page' if data.get('outcome') == 'Opened' else data.get('reason', 'failed')))

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
                saved.verify(())
                portal_page = result.get('portal_page_id')
                with self._mutex:
                    success = (type(portal_page) is int and portal_page > 0 and result.get('outcome') == 'Opened'
                               and portal_page not in self._closed_pages)
                    self._carsi = replace(self._carsi, status='Opened' if success else
                        'Canceled' if self._stop.is_set() else 'Failed', waiting_for_user=False,
                        page_id=portal_page if success else None,
                        diagnostic=normalize_browser_diagnostic(result.get('diagnostic')), recovery_action=None,
                        recovery=normalize_recovery(result.get('recovery')) or None)
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
                        'preparation_key': self._keys[service.id],
                    }, service.id)

            eligible = (service for service in services if service.access_method == 'carsi' or manual_service_id is not None)
            with closing(bounded_dispatch(eligible, key=lambda service: service.id, start=start,
                    limit=concurrency, group_limit=1, stopped=lambda: self._stop.is_set())) as results:
                for service, future in results:
                    try:
                        data = future.result()
                    except ElectronDisconnected:
                        data = {'reason': 'connection_lost'}
                    except (OSError, RuntimeError, ValueError):
                        data = {'reason': 'failed'}
                    try:
                        saved.verify((service.id,))
                    except (OSError, RuntimeError, ValueError):
                        phase = 'failed'
                        data = {'reason': 'configuration_changed', 'recovery': data.get('recovery')}
                    with self._mutex:
                        self._results[service.id] = self._settle_service(self._results[service.id], data)
        except ElectronDisconnected:
            phase = 'interrupted'
        except (OSError, RuntimeError, ValueError):
            phase = 'failed'
        finally:
            try:
                with self._mutex:
                    stopped = self._stop.is_set()
                    self._phase = 'canceled' if stopped else phase
                    if manual_service_id is None and self._phase in {'completed', 'failed'}:
                        self._confirmation_batch = self._workflow_id, self._keys.copy()
                    if self._carsi.status == 'Preparing':
                        self._carsi = replace(self._carsi, status='Canceled' if stopped else 'Failed', waiting_for_user=False)
                    for service in services:
                        current = self._results[service.id]
                        if current.status in {'Not prepared', 'Preparing'}:
                            self._results[service.id] = replace(current, status='Canceled' if stopped else 'Needs attention',
                                reason='cancelled' if stopped else 'carsi_login_required', waiting_for_user=False, recovery_action=None)
                    counts = {status: sum(self._results[s.id].status == label for s in services)
                              for status, label in [('opened','Opened'), ('needs_attention','Needs attention'), ('failed','Failed')]}
                    outcome = ('cancelled' if stopped else phase if phase != 'completed' else
                        'partial' if counts['opened'] and (counts['failed'] or counts['needs_attention']) else
                        'failed' if counts['failed'] else 'needs_attention' if counts['needs_attention'] else
                        'opened' if counts['opened'] else 'no_effect')
                    observe(self.diagnostics, 'finish', self._workflow_id, outcome,
                        statistics={'services': len(services), **counts},
                        details={'recovery': self._carsi.recovery, 'results': [{'service_id': s.id,
                            'outcome': self._results[s.id].status.lower().replace(' ', '_').replace('canceled', 'cancelled'),
                            'reason': self._results[s.id].reason, 'diagnostic': self._results[s.id].diagnostic,
                            'recovery': self._results[s.id].recovery}
                            for s in services]})
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
