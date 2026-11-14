"""Native output capabilities preserve the shared no-clobber completion seam."""
from uuid import uuid4
import os
import pytest
from allfold.models import ExternalIds
from allfold.persistence.paper_repository import PaperRepository, PaperMetadata
from allfold.persistence.body_files import ManagedBodyFiles, identity
from allfold.persistence.library_database import UnsafeLibraryPath


def test_native_absent_leaf_is_adopted_then_published_without_replacing(tmp_path):
    with PaperRepository.create(tmp_path) as repo:
        paper = repo.create_or_match(repo.workspace_id, direct_ids=ExternalIds(doi='10.5555/native'),
            metadata=PaperMetadata(title='Original response')).paper
        token = repo.begin_download(paper.token, lifecycle_id=uuid4())
        with ManagedBodyFiles(tmp_path, paper.id, token.attempt) as files:
            pending = files.prepare_native()
            repo.record_download_output(token, pending)
            leaf = tmp_path / pending.temporary
            assert not leaf.exists() and pending.file is None
            assert leaf.parent.stat().st_mode & 0o777 == 0o700
            leaf.write_bytes(b'Original POST bytes')
            actual = files.adopt_native(pending, identity(leaf.stat()))
            repo.adopt_native_output(token, pending, actual)
            assert repo.get(paper.id).download.output == actual
            assert files.publish(actual) == 19
            saved = repo.complete_download(token, size_bytes=19)
            files.cleanup(actual, associated=True)
            assert (tmp_path / saved.body.relative_path).read_bytes() == b'Original POST bytes'
            assert not leaf.parent.exists()


@pytest.mark.parametrize('replacement', ['leaf', 'directory', 'link'])
def test_native_replacements_are_never_published_or_deleted(tmp_path, replacement):
    paper_id = uuid4()
    with ManagedBodyFiles(tmp_path, paper_id, 1) as files:
        pending = files.prepare_native()
        leaf = tmp_path / pending.temporary
        leaf.write_bytes(b'owned')
        actual = files.adopt_native(pending, identity(leaf.stat()))
        if replacement == 'directory':
            leaf.parent.rename(leaf.parent.with_name(leaf.parent.name + '.old'))
            leaf.parent.mkdir()
            leaf.write_bytes(b'unknown')
        else:
            leaf.rename(leaf.with_name('owned.old'))
            if replacement == 'link':
                outside = tmp_path / 'outside'; outside.write_bytes(b'unknown'); leaf.symlink_to(outside)
            else:
                leaf.write_bytes(b'unknown')
        with pytest.raises((OSError, UnsafeLibraryPath)): files.publish(actual)
        with pytest.raises((OSError, UnsafeLibraryPath)): files.cleanup(actual)
        assert leaf.read_bytes() == b'unknown'


def test_unobserved_native_output_is_not_claimed_by_name_on_retry(tmp_path):
    with ManagedBodyFiles(tmp_path, uuid4(), 1) as files:
        pending = files.prepare_native()
        leaf = tmp_path / pending.temporary
        leaf.write_bytes(b'unknown after restart')
        with pytest.raises((OSError, UnsafeLibraryPath)): files.cleanup(pending)
        assert leaf.read_bytes() == b'unknown after restart'
