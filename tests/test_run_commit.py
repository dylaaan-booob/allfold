"""Run retrieval never retains write exclusion or resurrects a reset Workspace."""
from threading import Event

import pytest

from allfold.application.run_commit import capture_run_workspace, commit_run_workspace
from allfold.application.workspace_reset import execute_reset, preview_reset
from allfold.config import JournalConfig, render_settings_list_text
from allfold.models import CanonicalMetadata, CanonicalPaper, ExternalIds
from allfold.persistence.materialize import materialize_papers
from allfold.persistence.safe_write import ContentChangedError, workspace_operation_lock


@pytest.fixture
def configuration(tmp_path):
    path = tmp_path / "monitor.yaml"
    path.write_text("name: Test\nvenue_whitelist: list.md\nkeyword_expression: causal\n"
                    "output_dir: workspace\nfrom_month: 2026-01\nto_month: 2026-12\n")
    scope = tmp_path / "list.md"
    scope.write_text(render_settings_list_text(
        None, (JournalConfig(name="Biometrics", issn="0006-341X"),),
        path=scope, groups=(), custom_labels=(), access_services=(),
    ))
    return path


def paper():
    return CanonicalPaper(metadata=CanonicalMetadata(title="Causal inference", journal="Biometrics"),
                          external_ids=ExternalIds(doi="10.5555/snapshot"))


def test_network_snapshot_releases_exclusion_and_reset_prevents_late_write(configuration):
    with capture_run_workspace(configuration) as snapshot:
        with workspace_operation_lock(snapshot.config.output_dir):
            pass
        assert execute_reset(configuration, preview_reset(configuration)).success
        with pytest.raises(ContentChangedError):
            with commit_run_workspace(snapshot) as lock:
                materialize_papers((paper(),), snapshot.config.output_dir, operation_lock=lock)
        assert not snapshot.config.output_dir.exists()


@pytest.mark.parametrize("replacement", ["directory", "symlink", "papers", "configuration"])
def test_retrieval_snapshot_cannot_write_to_replaced_objects(configuration, replacement):
    with capture_run_workspace(configuration) as snapshot:
        workspace = snapshot.config.output_dir
        outside = configuration.parent / "replacement"
        outside.mkdir()
        if replacement == "configuration":
            configuration.write_text(configuration.read_text().replace("causal", "inference"))
        elif replacement == "papers":
            (workspace / "Papers").rename(workspace / "old-papers")
            (workspace / "Papers").mkdir()
        else:
            workspace.rename(configuration.parent / "original")
            if replacement == "directory":
                workspace.mkdir()
            else:
                workspace.symlink_to(outside, target_is_directory=True)
        with pytest.raises(ContentChangedError):
            with commit_run_workspace(snapshot) as lock:
                materialize_papers((paper(),), workspace, operation_lock=lock)
        assert not tuple(outside.iterdir())
        if replacement == "directory":
            assert not tuple(workspace.iterdir())


def test_cancellation_prevents_any_commit(configuration):
    cancelled = Event()
    with capture_run_workspace(configuration) as snapshot:
        cancelled.set()
        with pytest.raises(ContentChangedError, match="cancelled"):
            with commit_run_workspace(snapshot, cancel_event=cancelled):
                pytest.fail("cancelled Run entered commit scope")
        assert not tuple((snapshot.config.output_dir / "Papers").iterdir())


def _commit_process(snapshot, started, release, result):
    try:
        with commit_run_workspace(snapshot) as lock:
            started.set()
            assert release.wait(5)
            saved = materialize_papers((paper(),), snapshot.config.output_dir, operation_lock=lock)
            result.put((len(saved.created_papers), len(saved.existing_papers), saved.has_errors))
    except Exception as error:
        result.put(str(error))


def test_two_processes_rescan_shared_identity_inside_commit_lock(configuration):
    import multiprocessing
    context = multiprocessing.get_context("fork")
    result = context.Queue()
    first_started, second_started, release = (context.Event() for _ in range(3))
    with capture_run_workspace(configuration) as first, capture_run_workspace(configuration) as second:
        workers = [context.Process(target=_commit_process, args=(snapshot, started, release, result))
                   for snapshot, started in ((first, first_started), (second, second_started))]
        workers[0].start()
        assert first_started.wait(5)
        workers[1].start()
        assert not second_started.wait(0.1)
        release.set()
        for worker in workers:
            worker.join(5)
            assert worker.exitcode == 0
        outcomes = [result.get(timeout=1) for _ in workers]
        assert all(isinstance(item, tuple) for item in outcomes), outcomes
        assert sorted(outcomes) == [(0, 1, False), (1, 0, False)]
        assert len(tuple((first.config.output_dir / "Papers").glob("*.md"))) == 1
