"""Minimal current-body file authority, independent of historical download output."""
from contextlib import ExitStack
import os
from pathlib import Path
import stat
from uuid import uuid4

from allfold.persistence.body_files import identity, _move_exclusive
from allfold.persistence.library_database import UnsafeLibraryPath
from allfold.persistence.library_models import BodyReference
from allfold.persistence.safe_write import _open_directory_nofollow


class CurrentBodyFile:
    def __init__(self, workspace, body, *, expected_workspace):
        self.workspace = Path(workspace).absolute()
        if '..' in self.workspace.parts:
            raise UnsafeLibraryPath('Canonical Workspace required')
        self.relative_path = BodyReference.model_validate(body).relative_path
        self.parts = self.relative_path.split('/')
        self.expected_workspace = expected_workspace
        self._stack = ExitStack()
        self.directories = []
        self.missing_name = None
        self.file = None

    def __enter__(self):
        try:
            self.root = _open_directory_nofollow(self.workspace)
            self._stack.callback(os.close, self.root)
            if identity(os.fstat(self.root)) != self.expected_workspace:
                raise UnsafeLibraryPath('Workspace directory changed')
            parent = self.root
            for name in self.parts[:-1]:
                try:
                    descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                except FileNotFoundError:
                    self.missing_name = name
                    break
                self._stack.callback(os.close, descriptor)
                self.directories.append((name, parent, descriptor))
                parent = descriptor
            self.parent = parent
            if self.missing_name is None:
                try:
                    descriptor = os.open(self.parts[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
                except FileNotFoundError:
                    self.missing_name = self.parts[-1]
                else:
                    self._stack.callback(os.close, descriptor)
                    info = os.fstat(descriptor)
                    self._regular(info)
                    self.file = identity(info)
            self.verify()
            return self
        except BaseException:
            self._stack.close()
            raise

    def __exit__(self, *_):
        self._stack.close()

    @staticmethod
    def _regular(info):
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise UnsafeLibraryPath('Body must remain a regular single-link file')

    def _live(self):
        current = _open_directory_nofollow(self.workspace)
        try:
            if identity(os.fstat(current)) != self.expected_workspace:
                raise UnsafeLibraryPath('Workspace directory changed')
        finally:
            os.close(current)
        for name, parent, descriptor in self.directories:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or identity(info) != identity(os.fstat(descriptor)):
                raise UnsafeLibraryPath('Body directory changed')

    def verify(self):
        """Return False only for confirmed absence in the original live parents."""
        self._live()
        if self.missing_name is not None:
            try:
                os.stat(self.missing_name, dir_fd=self.parent, follow_symlinks=False)
            except FileNotFoundError:
                self._live()
                return False
            raise UnsafeLibraryPath('Missing body location changed')
        try:
            info = os.stat(self.parts[-1], dir_fd=self.parent, follow_symlinks=False)
        except FileNotFoundError:
            self._live()
            return False
        self._regular(info)
        if identity(info) != self.file:
            raise UnsafeLibraryPath('Body file changed')
        self._live()
        return True

    def payload(self):
        if not self.verify():
            raise FileNotFoundError('Body is absent')
        return dict(relative_path=self.relative_path, workspace=self.expected_workspace,
            directories=[identity(os.fstat(descriptor)) for _, _, descriptor in self.directories], file=self.file)

    def delete(self, guard):
        """Move without clobbering, verify the captured inode, then unlink privately.

        A swapped source is restored without overwriting. A failed unlink also
        attempts restoration; an unreturnable file remains private and untouched.
        There is no orphan scan or persistent deletion/recovery queue.
        """
        if not self.verify():
            return
        documents = self.directories[0][2]
        parent = documents
        for name in ('.downloads', '.cleanup'):
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent)
            except FileExistsError:
                pass
            descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            self._stack.callback(os.close, descriptor)
            self.directories.append((name, parent, descriptor))
            parent = descriptor
        private = os.fstat(parent)
        if private.st_uid != os.getuid() or stat.S_IMODE(private.st_mode) != 0o700:
            raise UnsafeLibraryPath('Body disposal directory must remain private')
        slot = f'body-{uuid4().hex}.removed'
        guard()
        if not self.verify():
            return
        _move_exclusive(self.parts[-1], slot, self.parent, parent)
        try:
            info = os.stat(slot, dir_fd=parent, follow_symlinks=False)
            self._regular(info)
            if identity(info) != self.file:
                raise UnsafeLibraryPath('Body was replaced before deletion')
            self._live()
            guard()
            os.unlink(slot, dir_fd=parent)
        except BaseException:
            _move_exclusive(slot, self.parts[-1], parent, self.parent)
            raise
        os.fsync(parent)
        os.fsync(self.parent)
