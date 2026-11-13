"""Captured narrow access authority, independent of foreground Run inputs."""
from dataclasses import dataclass, field
from pathlib import Path

from allfold.application.browser_services import BrowserServiceSnapshot
from allfold.integrations.openalex_credentials import read_credential
from allfold.persistence.safe_write import ContentChangedError
from allfold.providers.integrated import PROVIDERS


@dataclass(frozen=True)
class TaskAuthority:
    config_path: Path = field(repr=False)
    service_id: str | None
    service_scope: str | None
    providers: tuple[str, ...]
    _credentials: tuple = field(repr=False)
    _saved: object = field(default=None, repr=False)
    _prepared: object = field(default=None, repr=False)
    _login: object = field(default=None, repr=False)

    @classmethod
    def capture(cls, config_path, login, service_id, providers):
        providers = tuple(sorted(set(providers)))
        if not set(providers) <= set(PROVIDERS):
            raise ValueError('Unknown collection Provider')
        config_path = Path(config_path).resolve()
        credentials = tuple((name, read_credential(config_path, provider=name)[1])
                            for name in providers if name in {'pubmed', 'openalex'})
        saved = prepared = scope = None
        if service_id is not None:
            saved = BrowserServiceSnapshot.read(config_path)
            if not any(service.id == service_id for service in saved.services):
                raise ValueError('Collection Service must be a saved Service')
            prepared = login.prepared_authority(saved, service_id) if login else None
            if prepared is None:
                raise ValueError('Collection Service must have a valid prepared context')
            scope = saved.service_scope(service_id)
        authority = cls(config_path, service_id, scope, providers, credentials, saved, prepared, login)
        authority.verify()
        return authority

    def verify(self):
        for provider, revision in self._credentials:
            if read_credential(self.config_path, provider=provider)[1] != revision:
                raise ContentChangedError('Collection Provider credentials changed')
        if self._saved is not None:
            self._saved.verify((self.service_id,))
            if self._login.prepared_authority(self._saved, self.service_id) != self._prepared:
                raise ContentChangedError('Collection prepared access context changed')
