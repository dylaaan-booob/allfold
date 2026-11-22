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

    def owner_exits_during_reclamation(pid, signal):
        if replace_root:
            owned.rename(replacement)
            owned.symlink_to(other, target_is_directory=True)
        else:
            (owned / retired).rename(replacement)
            (other / retired).rename(owned / retired)
        raise ProcessLookupError

    monkeypatch.setattr(os, 'kill', owner_exits_during_reclamation)
    directory = os.open(owned, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        assert reclaim_retired_sessions(directory)
    finally:
        os.close(directory)
    if replace_root:
        assert marker.read_text() == 'preserved'
        assert not (replacement / retired).exists()
    else:
        assert (owned / retired / marker.name).read_text() == 'preserved'
        assert replacement.is_dir()
