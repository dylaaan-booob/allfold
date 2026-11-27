"""Captured narrow access authority, independent of foreground Run inputs."""
from dataclasses import dataclass, field
from pathlib import Path

from allfold.application.browser_services import BrowserServiceSnapshot
from allfold.application.carsi_entry import service_entry
from allfold.config import load_config
from allfold.integrations.openalex_credentials import read_credential
from allfold.persistence.safe_write import ContentChangedError
from allfold.providers.integrated import PROVIDERS


class ServiceAccessUnavailable(ValueError):
    def __init__(self, message, diagnostic):
        super().__init__(message)
        self.diagnostic = diagnostic


@dataclass(frozen=True)
class NativeAccessBinding:
    """Captured descriptive association; verification remains with TaskAuthority."""
    scope: tuple[tuple[str, str], ...] = ()
    service_id: str | None = None
    pdf_source: str | None = None
    service_entry: dict | None = None

    def payload(self):
        if self.service_id is None:
            return {}
        return dict(service_scope=dict(self.scope), service_id=self.service_id, service_entry=self.service_entry)


@dataclass(frozen=True)
class TaskAuthority:
    config_path: Path = field(repr=False)
    service_id: str | None
    service_scope: str | None
    providers: tuple[str, ...]
    _credentials: tuple = field(repr=False)
    _saved: object = field(default=None, repr=False)
    _service: object = field(default=None, repr=False)
    _login: object = field(default=None, repr=False)

    @classmethod
    def capture(cls, config_path, login, service_id, providers):
        providers = tuple(sorted(set(providers)))
        if not set(providers) <= set(PROVIDERS):
            raise ValueError('Unknown collection Provider')
        config_path = Path(config_path).resolve()
        credentials = tuple((name, read_credential(config_path, provider=name)[1])
                            for name in providers if name in {'pubmed', 'openalex'})
        saved = service = scope = None
        if service_id is not None:
            saved = BrowserServiceSnapshot.read(config_path)
            service = next((row for row in saved.services if row.id == service_id), None)
            if service is None:
                raise ServiceAccessUnavailable('Collection Service must be a saved Service', 'service-missing')
            if service.access_method == 'manual' and (not login or login.prepared_authority(saved, service_id) is None):
                raise ServiceAccessUnavailable('Open the Manual Service with Visit', 'service-unprepared')
            entry = service_entry(config_path, service, saved.institution)
            if entry and entry.get('unavailable_reason'):
                raise ServiceAccessUnavailable(entry['unavailable_reason'], 'service-unavailable')
            scope = saved.service_scope(service_id)
        authority = cls(config_path, service_id, scope, providers, credentials, saved, service, login)
        authority.verify()
        return authority

    def verify(self):
        for provider, revision in self._credentials:
            if read_credential(self.config_path, provider=provider)[1] != revision:
                raise ContentChangedError('Collection Provider credentials changed')
        if self._saved is not None:
            self._saved.verify((self.service_id,))

    def native_access(self):
        if self.service_id is None:
            return NativeAccessBinding()
        institution = load_config(self.config_path).institution
        entry = service_entry(self.config_path, self._service, institution)
        prepared = self._login.prepared_authority(self._saved, self.service_id) if self._login else None
        kind = getattr(prepared, 'pdf_source', None)
        if self._service.access_method == 'manual' and prepared and prepared.page_id is None:
            kind = None
        if entry and set(entry.get('landing_hosts', ())) & {'search.ebscohost.com', 'research.ebsco.com', 'discovery.ebsco.com'}:
            kind = 'ebsco'
        return NativeAccessBinding(tuple(self._saved.scope.items()), self.service_id,
            kind, entry)
