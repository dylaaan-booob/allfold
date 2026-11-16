"""Attempt-owned PDF files. No content inspection, replacement or orphan scan.

Python pins directory descriptors for creation/publication/removal. Main may open
only the exclusively created inode in the recorded capability; no truncation or
write is allowed until its descriptor and directory identities match.
"""
from contextlib import ExitStack
import os
import re
import ctypes
import sys
from pathlib import Path
import stat
from uuid import UUID, uuid4

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
        self.cleanup_errors = []

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

    def _live_documents(self, documents):
        current = _open_directory_nofollow(self.workspace)
        try:
            if identity(os.fstat(current)) != identity(os.fstat(self.root)):
                raise UnsafeLibraryPath('Workspace directory changed')
        finally:
            os.close(current)
        info = os.stat('Documents', dir_fd=self.root, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or identity(info) != identity(os.fstat(documents)):
            raise UnsafeLibraryPath('Managed body directory changed')

    def _live(self, documents, staging, disposal):
        self._live_documents(documents)
        for name, parent, descriptor in [('.downloads', documents, staging), ('.cleanup', staging, disposal)]:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or identity(info) != identity(os.fstat(descriptor)):
                raise UnsafeLibraryPath('Managed directory changed')

    def _names(self):
        return f'{self.paper_id}.{self.attempt}.part', f'{self.paper_id}.pdf'

    def _validate_names(self, proof):
        temporary, target = self._names()
        if proof.native_directory is not None:
            match = re.fullmatch(r'Documents/\.downloads/(' + re.escape(f'{self.paper_id}.{self.attempt}')
                + r'(?:\.[a-f0-9]{32})?\.native/body\.part)', proof.temporary)
            if match is None:
                raise UnsafeLibraryPath('Native output does not belong to this Paper/attempt')
            temporary = match[1]
        if (proof.temporary != f'Documents/.downloads/{temporary}' or proof.target != f'Documents/{target}'):
            raise UnsafeLibraryPath('Output does not belong to this Paper/attempt')
        return temporary, target

    def _native(self, staging, proof):
        temporary, _ = self._validate_names(proof)
        name = temporary.split('/')[0]
        descriptor = self._directory(name, staging)
        info = os.fstat(descriptor)
        live = os.stat(name, dir_fd=staging, follow_symlinks=False)
        if (identity(info) != proof.native_directory or identity(live) != proof.native_directory
                or not stat.S_ISDIR(live.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise UnsafeLibraryPath('Native output directory changed')
        return descriptor

    def _location(self, staging, proof):
        temporary, _ = self._validate_names(proof)
        if proof.native_directory is None:
            return temporary, staging
        return 'body.part', self._native(staging, proof)

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

    def prepare_native(self):
        """Reserve a private, never-reused directory, leaving Chromium's leaf absent.

        Electron 45 replaces an existing save leaf, and can remove a cancelled
        leaf after done. A native attempt therefore never shares its pathname
        with a placeholder, later candidate or later attempt.
        """
        documents, staging, disposal = self._directories()
        _, target = self._names()
        try:
            os.stat(target, dir_fd=documents, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError('Managed body target already exists')
        name = f'{self.paper_id}.{self.attempt}.{uuid4().hex}.native'
        os.mkdir(name, mode=0o700, dir_fd=staging)
        descriptor = self._directory(name, staging)
        proof = OutputOwnership(temporary=f'Documents/.downloads/{name}/body.part', target=f'Documents/{target}',
            workspace=identity(os.fstat(self.root)), documents=identity(os.fstat(documents)),
            staging=identity(os.fstat(staging)), disposal=identity(os.fstat(disposal)),
            native_directory=identity(os.fstat(descriptor)))
        self._live(documents, staging, disposal)
        self._native(staging, proof)
        return proof

    def adopt_native(self, proof, observed_file):
        """Qualify Main's observed native inode, never a planned filename alone."""
        if proof.native_directory is None or proof.file is not None:
            raise UnsafeLibraryPath('A pending native capability is required')
        self._validate_names(proof)
        documents, staging, disposal = self._directories(proof)
        directory = self._native(staging, proof)
        if os.listdir(directory) != ['body.part']:
            raise UnsafeLibraryPath('Native output contains unknown objects')
        actual = proof.model_copy(update={'file': tuple(observed_file)})
        info = self._owned('body.part', directory, actual)
        if info.st_nlink != 1:
            raise UnsafeLibraryPath('Native output has an unrelated link')
        self._live(documents, staging, disposal)
        self._native(staging, proof)
        return actual

    def publish(self, proof):
        _, target = self._validate_names(proof)
        documents, staging, disposal = self._directories(proof)
        temporary, source = self._location(staging, proof)
        info = self._owned(temporary, source, proof)
        if info.st_nlink != 1:
            raise UnsafeLibraryPath('Temporary output has an external link')
        self._live(documents, staging, disposal)
        # linkat is atomic no-clobber, including a target that appeared after
        # prepare. Both fds remain pinned; no path-based rename/replace occurs.
        os.link(temporary, target, src_dir_fd=source, dst_dir_fd=documents, follow_symlinks=False)
        self._owned(target, documents, proof)
        os.fsync(documents)
        # A link into a renamed/replaced Documents descriptor is not publication
        # at the associated path. Temporary/disposal parents are auxiliary now.
        self._live_documents(documents)
        # The permanent link is durable. Auxiliary retirement cannot undo it or
        # turn it into an unassociated failed transfer.
        try:
            self._retire(temporary, source, disposal, proof)
        except (OSError, UnsafeLibraryPath) as error:
            self.cleanup_errors.append(error)
        if proof.native_directory is not None:
            try:
                self._remove_native(staging, disposal, proof)
            except (OSError, UnsafeLibraryPath) as error:
                self.cleanup_errors.append(error)
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
        _, target = self._validate_names(proof)
        documents, staging, disposal = self._directories(proof)
        try:
            temporary, source = self._location(staging, proof)
        except FileNotFoundError:
            if proof.native_directory is None:
                raise
            temporary, source = None, None
        # A completed association protects the final inode even if later
        # notification, stale guards or cancellation fail.
        for name, descriptor in ([(temporary, source)] if source is not None else []) + ([] if associated or proof.file is None else [(target, documents)]):
            self._live(documents, staging, disposal)
            if proof.file is None:
                if os.listdir(source):
                    raise UnsafeLibraryPath('Unobserved native output remains unknown')
            else:
                self._retire(name, descriptor, disposal, proof)
        if proof.native_directory is not None and source is not None:
            self._remove_native(staging, disposal, proof)

    def _remove_native(self, staging, disposal, proof):
        directory = self._native(staging, proof)
        name = proof.temporary.split('/')[-2]
        if os.listdir(directory):
            raise UnsafeLibraryPath('Native output contains unknown objects')
        slot = name + '.removed'
        _move_exclusive(name, slot, staging, disposal)
        moved = os.stat(slot, dir_fd=disposal, follow_symlinks=False)
        if not stat.S_ISDIR(moved.st_mode) or identity(moved) != proof.native_directory:
            _move_exclusive(slot, name, disposal, staging)
            raise UnsafeLibraryPath('Native directory was replaced during cleanup')
        try:
            os.rmdir(slot, dir_fd=disposal)
        except BaseException:
            _move_exclusive(slot, name, disposal, staging)
            raise
