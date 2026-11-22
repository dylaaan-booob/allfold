"""Reclaim retired Browser Sessions below Main's opened directory."""
import os
import re
import shutil


_RUN_DIRECTORY = re.compile(r'run-([1-9]\d{0,9})-[a-zA-Z0-9]{6}', re.ASCII)


def _owner_exited(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        pass
    return False


def reclaim_retired_sessions(directory_fd):
    if not shutil.rmtree.avoids_symlink_attacks:
        return False
    success = True
    with os.scandir(directory_fd) as entries:
        for entry in list(entries):
            match = _RUN_DIRECTORY.fullmatch(entry.name)
            if not match:
                continue
            pid = int(match[1])
            if pid > 0x7fffffff:
                continue
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                observed = entry.stat(follow_symlinks=False)
                if not _owner_exited(pid):
                    continue
                current = os.stat(entry.name, dir_fd=directory_fd, follow_symlinks=False)
                if os.path.samestat(observed, current):
                    shutil.rmtree(entry.name, dir_fd=directory_fd)
            except FileNotFoundError:
                continue
            except OSError:
                success = False
    return success


if __name__ == '__main__':
    # Only Main supplies this open directory descriptor to the startup worker.
    raise SystemExit(0 if reclaim_retired_sessions(3) else 1)
