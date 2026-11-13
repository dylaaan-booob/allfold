"""Saved Service identities for one browser invocation, never a second mapping."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

from allfold.config import AccessService, InstitutionConfig, JournalConfig, load_config
from allfold.persistence.safe_write import ContentChangedError, read_text_exact
from allfold.persistence.user_state import ContentRevision, read_user_state


def browser_workspace_identity(path: Path, identity: tuple[int, int]) -> str:
    """Identify one live Workspace without exposing its local path to Electron."""
    device, inode = identity
    return hashlib.sha256(b'\0'.join((os.fsencode(path.resolve()),
        str(device).encode('ascii'), str(inode).encode('ascii')))).hexdigest()


def browser_scope_id(config_path: Path) -> str:
    return hashlib.sha256(str(config_path.resolve()).encode()).hexdigest()


@dataclass(frozen=True)
class BrowserServiceSnapshot:
    config_path: Path
    config_contents: str
    revision: ContentRevision
    journals: tuple[JournalConfig, ...]
    services: tuple[AccessService, ...]
    institution: InstitutionConfig | None

    @classmethod
    def read(cls, config_path: Path):
        config_path = config_path.resolve()
        contents = read_text_exact(config_path)
        config = load_config(config_path)
        saved = read_user_state(config_path)
        if saved.revision.digest != config.user_state_revision:
            raise ContentChangedError('User state changed while reading browser Services')
        snapshot = cls(config_path, contents, saved.revision,
                       saved.state.journals, saved.state.access_services, config.institution)
        snapshot.verify_snapshot()
        return snapshot

    @property
    def scope_id(self):
        return browser_scope_id(self.config_path)

    @property
    def scope(self):
        # Paths and configuration contents never cross the browser bridge.
        return dict(scope_id=self.scope_id,
                    config_revision=hashlib.sha256(self.config_contents.encode()).hexdigest(),
                    user_state_revision=self.revision.digest)

    def authentication_key(self, credential_epoch: str) -> str:
        institution = self.institution.model_dump(mode='json') if self.institution else None
        payload = json.dumps([self.scope_id, credential_epoch, institution], sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def preparation_key(self, service: AccessService, credential_epoch: str) -> str:
        # Only the saved access record and authentication policy bind retained pages.
        payload = json.dumps([self.authentication_key(credential_epoch),
                              service.model_dump(mode='json')], sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def service_scope(self, service_id: str) -> str:
        return f'service:{self.scope_id}:{service_id}'

    def verify(self, service_ids=None):
        """Validate captured access facts, independent of ordinary input revisions."""
        config = load_config(self.config_path)
        current = read_user_state(self.config_path)
        if current.revision.digest != config.user_state_revision:
            raise ContentChangedError('User State changed while reading Browser authority')
        selected = {service.id for service in self.services} if service_ids is None else set(service_ids)
        before = {service.id: service for service in self.services if service.id in selected}
        after = {service.id: service for service in current.state.access_services if service.id in selected}
        if config.institution != self.institution or before != after or set(before) != selected:
            raise ContentChangedError('Saved Browser access authority changed')

    def verify_snapshot(self):
        if (read_text_exact(self.config_path) != self.config_contents
                or read_user_state(self.config_path).revision != self.revision):
            raise ContentChangedError('Saved configuration or User State changed during browser workflow')
