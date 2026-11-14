"""Attempt-owned PDF files. No content inspection, replacement or orphan scan.

Python pins directory descriptors for creation/publication/removal. Main may open
only the exclusively created inode in the recorded capability; no truncation or
write is allowed until its descriptor and directory identities match.
"""
from contextlib import ExitStack
import os
from pathlib import Path
import stat
from uuid import UUID

from allfold.persistence.library_models import OutputOwnership
from allfold.persistence.library_database import UnsafeLibraryPath
from allfold.persistence.safe_write import _open_directory_nofollow


def identity(info):
    return info.st_dev, info.st_ino


class ManagedBodyFiles:
    def __init__(self, workspace, paper_id, attempt, *, expected_workspace=None):
        self.workspace = Path(workspace).absolute()
        self.paper_id, self.attempt = UUID(str(paper_id)), int(attempt)
        if self.attempt < 1 or '..' in self.workspace.parts:
            raise ValueError('Canonical Workspace and positive attempt required')
        self.expected_workspace = expected_workspace
        self._stack = ExitStack()

    def __enter__(self):
        try:
            # Pin every component from /, never resolve through a symlink.
            descriptor = self._directory('/', None)
            for component in self.workspace.parts[1:]:
                descriptor = self._directory(component, descriptor)
            self.root = descriptor
            if self.expected_workspace is not None and identity(os.fstat(self.root)) != self.expected_workspace:
                raise UnsafeLibraryPath('Captured Workspace directory changed')
            return self
        except BaseException:
            self._stack.close()
            raise

    def __exit__(self, *_):
        self._stack.close()

    def _directory(self, name, parent, *, create=False):
        if create:
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent)
            except FileExistsError:
                pass
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        self._stack.callback(os.close, descriptor)
        return descriptor

    def _directories(self, proof=None):
        documents = self._directory('Documents', self.root, create=proof is None)
        staging = self._directory('.downloads', documents, create=proof is None)
        if proof is not None and (identity(os.fstat(self.root)) != proof.workspace
                or identity(os.fstat(documents)) != proof.documents or identity(os.fstat(staging)) != proof.staging):
            raise UnsafeLibraryPath('Managed output directories changed')
        # A directory rename/replacement is a refusal, even though these fds
        # would still address the old objects. Recheck again before each action.
        self._live(documents, staging)
        return documents, staging

    def _live(self, documents, staging):
        current = _open_directory_nofollow(self.workspace)
        try:
            if identity(os.fstat(current)) != identity(os.fstat(self.root)):
                raise UnsafeLibraryPath('Workspace directory changed')
        finally:
            os.close(current)
        for name, parent, descriptor in [('Documents', self.root, documents), ('.downloads', documents, staging)]:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or identity(info) != identity(os.fstat(descriptor)):
                raise UnsafeLibraryPath('Managed directory changed')

    def _names(self):
        return f'{self.paper_id}.{self.attempt}.part', f'{self.paper_id}.pdf'

    def _validate_names(self, proof):
        temporary, target = self._names()
        if (proof.temporary != f'Documents/.downloads/{temporary}' or proof.target != f'Documents/{target}'):
            raise UnsafeLibraryPath('Output does not belong to this Paper/attempt')
        return temporary, target

    @staticmethod
    def _owned(name, directory, proof, *, missing=False):
        try:
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            if missing:
                return None
            raise
        if not stat.S_ISREG(info.st_mode) or identity(info) != proof.file or info.st_nlink not in {1, 2}:
            raise UnsafeLibraryPath('Output is no longer the owned regular file')
        return info

    def prepare(self):
        documents, staging = self._directories()
        temporary, target = self._names()
        try:
            os.stat(target, dir_fd=documents, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError('Managed body target already exists')
        self._live(documents, staging)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=staging)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise UnsafeLibraryPath('Output is not an exclusive regular file')
            proof = OutputOwnership(temporary=f'Documents/.downloads/{temporary}', target=f'Documents/{target}',
                workspace=identity(os.fstat(self.root)), documents=identity(os.fstat(documents)),
                staging=identity(os.fstat(staging)), file=identity(info))
            self._live(documents, staging)
            return proof
        finally:
            os.close(descriptor)

    def publish(self, proof):
        temporary, target = self._validate_names(proof)
        documents, staging = self._directories(proof)
        info = self._owned(temporary, staging, proof)
        if info.st_nlink != 1:
            raise UnsafeLibraryPath('Temporary output has an external link')
        self._live(documents, staging)
        # linkat is atomic no-clobber, including a target that appeared after
        # prepare. Both fds remain pinned; no path-based rename/replace occurs.
        os.link(temporary, target, src_dir_fd=staging, dst_dir_fd=documents, follow_symlinks=False)
        self._owned(target, documents, proof)
        self._owned(temporary, staging, proof)
        os.unlink(temporary, dir_fd=staging)
        os.fsync(documents)
        self._live(documents, staging)
        return info.st_size

    def cleanup(self, proof, *, associated=False):
        temporary, target = self._validate_names(proof)
        documents, staging = self._directories(proof)
        # A completed association protects the final inode even if later
        # notification, stale guards or cancellation fail.
        for name, descriptor in [(temporary, staging)] + ([] if associated else [(target, documents)]):
            info = self._owned(name, descriptor, proof, missing=True)
            if info is not None:
                self._live(documents, staging)
                os.unlink(name, dir_fd=descriptor)
