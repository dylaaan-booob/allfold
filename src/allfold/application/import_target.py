"""Revision-bound Workspace target shared by import workflows and HTTP forms."""
from __future__ import annotations
from dataclasses import dataclass, replace
from pathlib import Path
import hashlib
import hmac
from allfold.config import LoadedConfig, load_config
from allfold.persistence.safe_write import ContentChangedError, WorkspaceOperationLock

@dataclass(frozen=True)
class _ImportTarget:
    config_path: Path
    config_digest: str
    config_identity: tuple[int, int]
    workspace: Path
    workspace_identity: tuple[int, int, int] | None
    papers_identity: tuple[int, int, int] | None
    lock_identity: tuple[int, int, int] | None
    user_state_revision: str | None

    @classmethod
    def read(cls, config_path: Path) -> tuple[_ImportTarget, LoadedConfig]:
        def identity(path: Path) -> tuple[int, int, int] | None:
            try:
                value = path.lstat()
                return value.st_dev, value.st_ino, value.st_mode
            except FileNotFoundError:
                return None

        contents = config_path.read_bytes()
        config_identity = identity(config_path)
        if config_identity is None:
            raise ContentChangedError("Configuration disappeared while reading the Workspace target")
        config = load_config(config_path)
        target = cls(config_path, hashlib.sha256(contents).hexdigest(), config_identity[:2],
                     config.output_dir, identity(config.output_dir),
                     identity(config.output_dir / 'Papers'),
                     identity(config.output_dir / '.allfold-operation.lock'), config.user_state_revision)
        if config_path.read_bytes() != contents or identity(config_path) != config_identity:
            raise ContentChangedError("Configuration changed while reading the Workspace target")
        return target, config

    def form_token(self, nonce: str) -> str:
        # 浏览器只持有签名，不能选择路径；同一 nonce 下不同目标的表单也不通用。
        return hmac.new(nonce.encode('ascii'), repr(self).encode('utf-8'), hashlib.sha256).hexdigest()

    def verify(self, lock: WorkspaceOperationLock) -> None:
        current, _ = self.read(self.config_path)
        if self.lock_identity is None:
            # 首次导入可创建空操作锁；已有锁的替换仍必须拒绝。
            current = replace(current, lock_identity=None)
        if current != self or self.workspace_identity is None or lock.identity != self.workspace_identity[:2]:
            raise ContentChangedError("Workspace changed since this import form was shown; no import started")
        lock.verify()

