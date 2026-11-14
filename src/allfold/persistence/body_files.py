"""Attempt-owned PDF files. No content inspection, replacement or orphan scan.

Python pins directory descriptors for creation/publication/removal. Main may open
only the exclusively created inode in the recorded capability; no truncation or
write is allowed until its descriptor and directory identities match.
"""
from contextlib import ExitStack
import os
import ctypes
import sys
from pathlib import Path
import stat
from uuid import UUID

from allfold.persistence.library_models import OutputOwnership
from allfold.persistence.library_database import UnsafeLibraryPath
from allfold.persistence.safe_write import _open_directory_nofollow


def identity(info):
    return info.st_dev, info.st_ino


def _move_exclusive(source, destination, source_directory, destination_directory):
    """Atomic no-clobber rename into the service-private disposal directory.

    POSIX rename can overwrite a concurrent destination. macOS's supported
    renameatx_np (Linux renameat2 for development) supplies the required primitive;
    no helper executable or third-party package is involved.
    """
    library = ctypes.CDLL(None, use_errno=True)
    symbol, flag = ('renameatx_np', 4) if sys.platform == 'darwin' else ('renameat2', 1)
    function = getattr(library, symbol, None)
    if function is None:
        raise OSError('No atomic no-clobber rename support')
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(source_directory, os.fsencode(source), destination_directory, os.fsencode(destination), flag) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


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
        disposal = self._directory('.cleanup', staging, create=proof is None)
        private = os.fstat(disposal)
        if private.st_uid != os.getuid() or stat.S_IMODE(private.st_mode) != 0o700:
            raise UnsafeLibraryPath('Disposal directory must remain private')
        if proof is not None and (identity(os.fstat(self.root)) != proof.workspace
                or identity(os.fstat(documents)) != proof.documents or identity(os.fstat(staging)) != proof.staging
                or identity(os.fstat(disposal)) != proof.disposal):
            raise UnsafeLibraryPath('Managed output directories changed')
        # A directory rename/replacement is a refusal, even though these fds
        # would still address the old objects. Recheck again before each action.
        self._live(documents, staging, disposal)
        return documents, staging, disposal

    def _live(self, documents, staging, disposal):
        current = _open_directory_nofollow(self.workspace)
        try:
            if identity(os.fstat(current)) != identity(os.fstat(self.root)):
                raise UnsafeLibraryPath('Workspace directory changed')
        finally:
            os.close(current)
        for name, parent, descriptor in [('Documents', self.root, documents), ('.downloads', documents, staging), ('.cleanup', staging, disposal)]:
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
        documents, staging, disposal = self._directories()
        temporary, target = self._names()
        try:
            os.stat(target, dir_fd=documents, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError('Managed body target already exists')
        self._live(documents, staging, disposal)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=staging)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise UnsafeLibraryPath('Output is not an exclusive regular file')
            proof = OutputOwnership(temporary=f'Documents/.downloads/{temporary}', target=f'Documents/{target}',
                workspace=identity(os.fstat(self.root)), documents=identity(os.fstat(documents)),
                staging=identity(os.fstat(staging)), disposal=identity(os.fstat(disposal)), file=identity(info))
            self._live(documents, staging, disposal)
            return proof
        finally:
            os.close(descriptor)

    def publish(self, proof):
        temporary, target = self._validate_names(proof)
        documents, staging, disposal = self._directories(proof)
        info = self._owned(temporary, staging, proof)
        if info.st_nlink != 1:
            raise UnsafeLibraryPath('Temporary output has an external link')
        self._live(documents, staging, disposal)
        # linkat is atomic no-clobber, including a target that appeared after
        # prepare. Both fds remain pinned; no path-based rename/replace occurs.
        os.link(temporary, target, src_dir_fd=staging, dst_dir_fd=documents, follow_symlinks=False)
        self._owned(target, documents, proof)
        self._retire(temporary, staging, disposal, proof)

        os.fsync(documents)
        self._live(documents, staging, disposal)
        return info.st_size

    def verify_published(self, proof):
        _, target = self._validate_names(proof)
        documents, staging, disposal = self._directories(proof)
        self._live(documents, staging, disposal)
        info = self._owned(target, documents, proof)
        if info.st_nlink != 1:
            raise UnsafeLibraryPath('Published body has an unrelated link')
        return info.st_size

    def _retire(self, name, directory, disposal, proof):
        # Move first, then verify the moved inode. A competing replacement of the
        # publicly addressed source can never be unlinked by this cleanup. Restore
        # an unexpected object without clobbering anything that appeared meanwhile.
        slot = f'{self.paper_id}.{self.attempt}.removed'
        pending = self._owned(slot, disposal, proof, missing=True)
        if pending is not None:
            os.unlink(slot, dir_fd=disposal)
        if self._owned(name, directory, proof, missing=True) is None:
            return
        _move_exclusive(name, slot, directory, disposal)
        try:
            self._owned(slot, disposal, proof)
        except BaseException:
            _move_exclusive(slot, name, disposal, directory)
            raise
        os.unlink(slot, dir_fd=disposal)

    def cleanup(self, proof, *, associated=False):
        temporary, target = self._validate_names(proof)
        documents, staging, disposal = self._directories(proof)
        # A completed association protects the final inode even if later
        # notification, stale guards or cancellation fail.
        for name, descriptor in [(temporary, staging)] + ([] if associated else [(target, documents)]):
            self._live(documents, staging, disposal)
            self._retire(name, descriptor, disposal, proof)
