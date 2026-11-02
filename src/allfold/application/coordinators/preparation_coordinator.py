"""Saved-Service preparation over the single Electron connection."""
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from urllib.parse import urlencode
import secrets
import threading
from pydantic import ValidationError
from allfold.config import (
    AccessService, ConfigurationError, InstitutionConfig, load_config,
    resolve_config_path, validate_access_mapping,
)
from allfold.browser_diagnostics import format_browser_diagnostic, normalize_browser_diagnostic
from allfold.persistence.safe_write import ContentChangedError
from allfold.persistence.user_state import load_user_state, read_user_state
from allfold.application.settings import load_settings
from allfold.application.workspace import journals_for_paper, load_workspace

CARSI_LOGIN_URL = "https://ds.carsi.edu.cn/Shibboleth.sso/Login"
CARSI_PORTAL_URL = "https://ds.carsi.edu.cn/wxds"

class PreparationPhase(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    BLOCKED = "blocked"

class PreparationOutcome(str, Enum):
    OPENED = "Opened"
    NEEDS_ATTENTION = "Needs attention"
    FAILED = "Failed"

@dataclass(frozen=True)
class PreparationResult:
    service_id: str
    outcome: PreparationOutcome
    reason: str
    diagnostic: dict[str, object] | None = None

@dataclass(frozen=True)
class PreparationSnapshot:
    phase: PreparationPhase
    task_id: str | None
    generation: int
    services: tuple[AccessService, ...]
    current_service_id: str | None
    results: tuple[PreparationResult, ...]
    message: str
    authorization_pending: bool = False
    waiting_for_user: bool = False
    manual_services: tuple[AccessService, ...] = ()

def institution_login_url(entity_id: str | None) -> str | None:
    """Construct the official CARSI entry only from a schema-valid IdP entity ID."""
    try:
        validated = InstitutionConfig(idp_entity_id=entity_id).idp_entity_id
    except (ValidationError, ValueError) as error:
        raise ConfigurationError("Institution.idp_entity_id is invalid") from error
    if validated is None:
        return None
    return f"{CARSI_LOGIN_URL}?{urlencode({'entityID': validated, 'target': CARSI_PORTAL_URL})}"

def read_saved_preparation_services(config_path: Path) -> tuple[AccessService, ...]:
    """Snapshot Services needed by current Kept Papers, using saved configuration only."""
    state = load_settings(config_path)
    try:
        if state.issues:
            raise ConfigurationError("Saved configuration has unresolved issues")
        snapshot = load_user_state(config_path, state.journal_path)
        journals, services = snapshot.state.journals, snapshot.state.access_services
        validate_access_mapping(journals, services)
        workspace = load_workspace(resolve_config_path(config_path, state.draft.output_dir, "workspace"), journals)
        if workspace.issues:
            raise ConfigurationError("Workspace Paper data cannot safely be read")
        needed = {journal.access_service_id for paper in workspace.kept
                  for journal in journals_for_paper(paper, journals) if journal.access_service_id}
        if read_user_state(config_path).revision != snapshot.revision:
            raise ContentChangedError("User state changed while preparing snapshot")
        if load_settings(config_path).draft.monitor_revision != state.draft.monitor_revision:
            raise ContentChangedError("Configuration changed while preparing snapshot")
    except (OSError, ConfigurationError, ContentChangedError) as error:
        raise ConfigurationError("Saved user state cannot safely start Preparation") from error
    return tuple(service for service in services if service.id in needed)


class PreparationCoordinator:
    def __init__(self, bridge, browser_lock):
        self.bridge, self.browser_lock = bridge, browser_lock
        self._lock = threading.RLock()
        self._worker = None
        self._stop = threading.Event()
        self._target_page = None
        self._snapshot = PreparationSnapshot(PreparationPhase.IDLE, None, 0, (), None, (), 'Not started')

    def ready(self):
        return self.bridge.connected

    @property
    def running(self):
        return self._worker is not None and self._worker.is_alive()

    def snapshot(self):
        with self._lock:
            return self._snapshot

    def _publish(self, **changes):
        self._snapshot = replace(self._snapshot, **changes)

    def start(self, config_path, *, service=None, browser_owner=None):
        state_revision = load_user_state(config_path).revision
        relevant = (service,) if service else read_saved_preparation_services(config_path)
        services = tuple(s for s in relevant if s.access_method == 'carsi')
        manual = tuple(s for s in relevant if s.access_method == 'manual')
        config = load_config(config_path)
        if config.user_state_revision != state_revision.digest:
            raise ContentChangedError("User state changed before Preparation start")
        login = institution_login_url(config.institution.idp_entity_id if config.institution else None)
        institution = config.institution
        if services and not (institution and (institution.name or (institution.use_shibboleth and login))):
            raise ValueError('Select an Institution first; CARSI institution search requires Institution Name, '
                             'or enable Shibboleth with a Public IdP Entity ID')
        authentication = {'login_url': login, 'institution_name': institution.name if institution else None,
                          'use_shibboleth': institution.use_shibboleth if institution else False}
        with self._lock:
            if self.running:
                raise ValueError('Preparation is still running')
            owner = browser_owner
            if owner is not None:
                self.browser_lock.require(owner)
            elif services:
                owner = self.browser_lock.acquire('preparation')
                if owner is None:
                    raise ValueError('Another browser workflow is active')
            self._stop = threading.Event()
            self._target_page = None
            self._snapshot = PreparationSnapshot(
                PreparationPhase.RUNNING if services else PreparationPhase.COMPLETED,
                secrets.token_hex(16), self._snapshot.generation + 1, services, None, (),
                'Preparing saved Services' if services else 'No related CARSI Services; review Manual Service URLs',
                authorization_pending=bool(services), manual_services=manual)
            if services:
                self._worker = threading.Thread(target=self._run,
                    args=(owner, browser_owner is None, authentication), name='electron-preparation', daemon=False)
                try:
                    self._worker.start()
                except BaseException:
                    self._publish(phase=PreparationPhase.BLOCKED, authorization_pending=False)
                    if browser_owner is None:
                        self.browser_lock.release(owner)
                    raise
            return self._snapshot

    def _run(self, owner, release_owner, authentication):
        try:
            if not self.bridge.connected:
                raise ValueError('Electron runtime is unavailable')
            for service in self._snapshot.services:
                with self._lock:
                    if self._stop.is_set():
                        break
                    self.browser_lock.require(owner)
                    self._publish(current_service_id=service.id, waiting_for_user=False,
                                  message=f'Preparing {service.name}')
                    pending = self.bridge.execute('prepare_service', {
                        'task_id': self._snapshot.task_id, 'service_id': service.id,
                        'name': service.name, **authentication}, self._progress)
                result = pending.result()
                with self._lock:
                    if self._stop.is_set():
                        break
                    diagnostic = normalize_browser_diagnostic(result.get('diagnostic'))
                    if (isinstance(diagnostic, dict) and diagnostic.get('stage') == 'authentication'
                            and diagnostic.get('code') in {'institution_credentials_rejected', 'carsi_session_expired'}):
                        self._target_page = None
                        self._publish(phase=PreparationPhase.BLOCKED, waiting_for_user=False,
                            results=(*self._snapshot.results, PreparationResult(service.id,
                                PreparationOutcome.FAILED, diagnostic['code'], diagnostic)),
                            message=format_browser_diagnostic(result.get('diagnostic')))
                        return
                    if (isinstance(diagnostic, dict)
                            and diagnostic.get('stage') in {'navigation', 'preparation'}
                            and diagnostic.get('code') in {'timeout', 'refresh_unconfirmed'}):
                        steps = {'request', 'page_load', 'resource_ready', 'resource_filter',
                                 'resource_search', 'visit_target', 'verification'}
                        step = diagnostic.get('step')
                        step = step if step in steps else 'request'
                        self._target_page = None
                        self._publish(phase=PreparationPhase.BLOCKED, waiting_for_user=False,
                            results=(*self._snapshot.results, PreparationResult(service.id,
                                PreparationOutcome.FAILED, 'timeout', diagnostic)),
                            message=f'Preparation timed out [{step}]; remaining queue stopped.')
                        return
                    evidence = result.get('evidence', {})
                    opened = (result.get('outcome') == 'Opened'
                        and evidence.get('visit_action_observed') is True
                        and evidence.get('navigation_observed') is True
                        and type(evidence.get('target_page_id')) is int)
                    reason = 'target_opened' if opened else result.get('reason', 'unknown')
                    if not opened and diagnostic and reason == 'unknown':
                        reason = 'navigation_failed'
                    if reason not in {'target_opened', 'timeout', 'manual_action_required', 'ambiguous_resource',
                                      'unverified_official_page', 'resource_not_found', 'navigation_failed'}:
                        reason = 'unknown'
                    self._target_page = evidence.get('target_page_id') if opened else None
                    self._publish(results=(*self._snapshot.results, PreparationResult(service.id,
                        PreparationOutcome.OPENED if opened else PreparationOutcome.NEEDS_ATTENTION, reason, diagnostic)),
                        waiting_for_user=False)
            with self._lock:
                self._publish(phase=PreparationPhase.STOPPED if self._stop.is_set() else PreparationPhase.COMPLETED,
                              message='Preparation canceled' if self._stop.is_set() else 'Preparation queue finished')
        except Exception:
            with self._lock:
                self._publish(phase=PreparationPhase.BLOCKED, message='Electron Preparation failed; no automatic retry')
        finally:
            with self._lock:
                self._publish(authorization_pending=False, waiting_for_user=False, current_service_id=None)
                if release_owner:
                    self.browser_lock.release(owner)

    def _progress(self, data):
        with self._lock:
            if not self._stop.is_set():
                waiting = data.get('waiting_for_user') is True
                issue = {'institution_name_required': 'Institution Name is missing; complete login in BROWSER or cancel and select an Institution',
                         'institution_search_failed': 'Institution search did not complete; continue manually in BROWSER or cancel'}.get(data.get('login_issue'))
                self._publish(waiting_for_user=waiting,
                    message=(issue or 'Complete login or verification in BROWSER') if waiting else 'Preparing Service')

    def cancel(self, task_id, generation):
        with self._lock:
            if (task_id, generation) != (self._snapshot.task_id, self._snapshot.generation) or not self.running:
                return False
            self._stop.set()
            self.bridge.cancel_current()
            self._publish(message='Stopping; waiting for the browser request to settle')
            return True

    def join(self):
        if self._worker:
            self._worker.join()

    def wos_handoff(self, task_id, generation):
        with self._lock:
            if ((task_id, generation) == (self._snapshot.task_id, self._snapshot.generation)
                    and self._snapshot.phase is PreparationPhase.BLOCKED
                    and any(result.reason == 'timeout' for result in self._snapshot.results)):
                raise ValueError(self._snapshot.message)
            if ((task_id, generation) == (self._snapshot.task_id, self._snapshot.generation)
                    and self._snapshot.phase is PreparationPhase.COMPLETED):
                return self._target_page
            return None
