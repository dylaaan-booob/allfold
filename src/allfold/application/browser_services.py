"""Saved Service identities for one browser invocation, never a second mapping."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

from allfold.config import AccessService, JournalConfig, load_config
from allfold.persistence.safe_write import ContentChangedError, read_text_exact
from allfold.persistence.user_state import ContentRevision, read_user_state


def browser_workspace_identity(path: Path, identity: tuple[int, int]) -> str:
    """Identify one live Workspace without exposing its local path to Electron."""
    device, inode = identity
    return hashlib.sha256(b'\0'.join((os.fsencode(path.resolve()),
        str(device).encode('ascii'), str(inode).encode('ascii')))).hexdigest()


@dataclass(frozen=True)
class BrowserServiceSnapshot:
    config_path: Path
    config_contents: str
    revision: ContentRevision
    journals: tuple[JournalConfig, ...]
    services: tuple[AccessService, ...]

    @classmethod
    def read(cls, config_path: Path):
        config_path = config_path.resolve()
        contents = read_text_exact(config_path)
        config = load_config(config_path)
        saved = read_user_state(config_path)
        if saved.revision.digest != config.user_state_revision:
            raise ContentChangedError('User state changed while reading browser Services')
        snapshot = cls(config_path, contents, saved.revision,
                       saved.state.journals, saved.state.access_services)
        snapshot.verify()
        return snapshot

    @property
    def scope(self):
        # Paths and configuration contents never cross the browser bridge.
        return dict(scope_id=hashlib.sha256(str(self.config_path).encode()).hexdigest(),
                    config_revision=hashlib.sha256(self.config_contents.encode()).hexdigest(),
                    user_state_revision=self.revision.digest)

    def verify(self):
        if (read_text_exact(self.config_path) != self.config_contents
                or read_user_state(self.config_path).revision != self.revision):
            raise ContentChangedError('Saved configuration or User State changed during browser workflow')
