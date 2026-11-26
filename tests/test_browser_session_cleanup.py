import os

import pytest

from allfold.browser_session_cleanup import reclaim_retired_sessions


@pytest.mark.parametrize('replace_root', [True, False])
def test_reclaim_prunes_only_observed_managed_sessions(tmp_path, monkeypatch, replace_root):
    owned = tmp_path / 'sessions'
    other = tmp_path / 'unrelated'
    retired = 'run-123-abc123'
    (owned / retired).mkdir(parents=True)
    (other / retired).mkdir(parents=True)
    marker = other / retired / 'unrelated-data'
    marker.write_text('preserved')
    replacement = tmp_path / 'moved'
    retired_file = owned / retired / 'old-cache'
    retired_file.write_text('retired data')

    def owner_exits_during_reclamation(pid, signal):
        if replace_root:
            owned.rename(replacement)
            owned.symlink_to(other, target_is_directory=True)
        raise ProcessLookupError

    directory = os.open(owned, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    open_directory = os.open

    def open_and_replace(name, flags, *args, **kwargs):
        fd = open_directory(name, flags, *args, **kwargs)
        if not replace_root and name == retired and kwargs.get('dir_fd') == directory:
            (owned / retired).rename(replacement)
            (other / retired).rename(owned / retired)
        return fd

    monkeypatch.setattr(os, 'kill', owner_exits_during_reclamation)
    monkeypatch.setattr(os, 'open', open_and_replace)
    try:
        assert reclaim_retired_sessions(directory)
    finally:
        os.close(directory)
    if replace_root:
        assert marker.read_text() == 'preserved'
        assert not (replacement / retired).exists()
    else:
        assert (owned / retired / marker.name).read_text() == 'preserved'
        assert list(replacement.iterdir()) == []
