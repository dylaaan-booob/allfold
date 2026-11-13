"""Config-scoped authoritative journal state and safe legacy migration."""
from dataclasses import replace

import pytest

from safety_config_helpers import current_mapping_document
from allfold.config import JournalConfig, SettingsList
from allfold.persistence.user_state import load_user_state, compare_write_user_state


def test_migration_preserves_user_choices_and_markdown_becomes_exchange_only(tmp_path):
    config, legacy, journal, service = current_mapping_document(tmp_path)
    before = legacy.read_bytes()
    first = load_user_state(config, legacy)
    assert first.state == SettingsList((journal,), ("Statistics",), (), (service,))
    changed = replace(first.state, journals=(journal.model_copy(update={"name": "Updated journal"}),))
    saved = compare_write_user_state(config, changed, first.revision)
    assert saved.state == changed
    assert saved.revision != first.revision
    assert legacy.read_bytes() == before
    legacy.unlink()
    assert load_user_state(config, legacy).state == changed
    assert saved.database_path == tmp_path / ".allfold" / "user-data.sqlite"
    assert saved.migration_source == str(legacy.resolve())


def test_scopes_are_independent_and_stale_write_cannot_replay(tmp_path):
    config, legacy, journal, service = current_mapping_document(tmp_path)
    other = tmp_path / "machine-learning.yaml"
    other.write_bytes(config.read_bytes())
    first, second = load_user_state(config, legacy), load_user_state(other, legacy)
    assert first.revision != second.revision
    changed = replace(first.state, journals=(journal.model_copy(update={"name": "Statistics"}),))
    compare_write_user_state(config, changed, first.revision)
    assert load_user_state(other).state == second.state
    from allfold.persistence.safe_write import ContentChangedError
    with pytest.raises(ContentChangedError):
        compare_write_user_state(config, first.state, first.revision)
    with pytest.raises(ContentChangedError):
        compare_write_user_state(other, changed, first.revision)


def test_invalid_migration_and_corrupt_database_never_replace_data(tmp_path):
    from allfold.persistence.user_state import UserStateError
    config, legacy, journal, service = current_mapping_document(tmp_path)
    contents = legacy.read_text()
    legacy.write_text(contents.replace("0006-341X", "0006-3410"))
    with pytest.raises(UserStateError):
        load_user_state(config, legacy)
    assert not (tmp_path / ".allfold" / "user-data.sqlite").exists()
    legacy.write_text(contents)
    state = load_user_state(config, legacy)
    state.database_path.write_bytes(b"corrupt sqlite")
    with pytest.raises(UserStateError):
        load_user_state(config, legacy)
    assert state.database_path.read_bytes() == b"corrupt sqlite"


def test_settings_and_runtime_read_sqlite_and_settings_uses_cas(tmp_path):
    from allfold.application.settings import load_settings, save_settings, SettingsSaveOutcome
    from allfold.config import load_config
    config, legacy, journal, service = current_mapping_document(tmp_path)
    opened = load_settings(config)
    original = legacy.read_bytes()
    changed = replace(opened.draft, groups=("Statistics", "New Group"))
    saved = save_settings(config, changed)
    assert saved.outcome is SettingsSaveOutcome.SAVED
    assert load_settings(config).draft.groups == ("Statistics", "New Group")
    assert load_user_state(config).state.groups == ("Statistics", "New Group")
    assert save_settings(config, changed).outcome is SettingsSaveOutcome.REVISION_CONFLICT
    assert legacy.read_bytes() == original
    legacy.unlink()
    assert load_config(config).journals == (journal,)
    assert load_settings(config).draft.access_services == (service,)


def test_new_scope_can_be_created_with_missing_revision_without_markdown(tmp_path):
    from allfold.persistence.user_state import ContentRevision
    from allfold.persistence.safe_write import ContentChangedError
    config = tmp_path / "fresh.yaml"
    state = SettingsList((JournalConfig(name="Biometrics", issn="0006-341X"),), (), (), ())
    snapshot = compare_write_user_state(config, state, ContentRevision(False, None))
    assert load_user_state(config).state == state
    with pytest.raises(ContentChangedError):
        compare_write_user_state(config, state, ContentRevision(False, None))


def test_default_migration_uses_configuration_specific_legacy_path(tmp_path):
    config, legacy, journal, service = current_mapping_document(tmp_path)
    destination = tmp_path / "statistics.md"
    legacy.rename(destination)
    config.write_text(config.read_text().replace("list.md", "statistics.md"))
    assert load_user_state(config).state.journals == (journal,)


def test_identity_conflicts_and_unsafe_paths_preserve_authoritative_state(tmp_path):
    from allfold.persistence.user_state import UserStateError
    from allfold.config import ConfigurationError
    config, legacy, journal, service = current_mapping_document(tmp_path)
    snapshot = load_user_state(config)
    conflicting = JournalConfig(name="Other journal", eissn=journal.issn)
    with pytest.raises(ConfigurationError, match="duplicate or conflicting"):
        compare_write_user_state(config, replace(snapshot.state, journals=(journal, conflicting)), snapshot.revision)
    assert load_user_state(config).revision == snapshot.revision
    held = snapshot.database_path.with_suffix(".backup")
    snapshot.database_path.rename(held)
    snapshot.database_path.symlink_to(held)
    with pytest.raises(UserStateError, match="symlink"):
        load_user_state(config)
    with pytest.raises(UserStateError, match="symlink"):
        compare_write_user_state(config, snapshot.state, snapshot.revision)
    assert held.read_bytes().startswith(b"SQLite format 3")


def test_reset_preserves_database_and_refuses_data_directory(tmp_path):
    import httpx
    from allfold.application.carsi_catalog import get_carsi_catalog
    from allfold.application.workspace_reset import execute_reset, preview_reset, ResetRefused
    config, legacy, journal, service = current_mapping_document(tmp_path)
    snapshot = load_user_state(config)
    cache = snapshot.database_path.parent / "resources.sqlite"
    catalog = get_carsi_catalog(cache, transport=httpx.MockTransport(lambda request: httpx.Response(
        200, headers={"content-type": "text/html"},
        text='<script>var SPList=[{"production":"EBSCO","searchStr":"EBSCO",'
             '"url":"https://search.ebscohost.com/","sptype":"1"}];</script>')))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "paper.md").write_text("isolated paper")
    assert execute_reset(config, preview_reset(config)).success
    assert load_user_state(config).state == snapshot.state
    assert get_carsi_catalog(cache).resources == catalog.resources
    config.write_text(config.read_text().replace("output_dir: workspace", "output_dir: .allfold"))
    with pytest.raises(ResetRefused):
        preview_reset(config)


def test_statistics_and_machine_learning_keep_distinct_complete_scopes(tmp_path):
    from allfold.application.settings import load_settings, save_settings, SettingsSaveOutcome
    from allfold.config import AccessService, load_config

    original, legacy, journal, service = current_mapping_document(tmp_path)
    statistics, machine_learning = tmp_path / "statistics.yaml", tmp_path / "machine-learning.yaml"
    statistics.write_bytes(original.read_bytes())
    machine_learning.write_bytes(original.read_bytes())
    statistics_opened = load_settings(statistics).draft
    machine_opened = load_settings(machine_learning).draft
    euclid = AccessService.create("Project Euclid", "https://projecteuclid.org/", access_method="manual")
    machine_journal = JournalConfig(name="Fixture Journal", issn="0090-5364", group="Learning", labels=("Priority",),
                                    access_service_id=euclid.id)
    # Persistence already validates identity collisions; use the saved identity
    # at this boundary so the test exercises scope ownership without a provider.
    machine_state = SettingsList((machine_journal,), ("Learning", "Unused"), ("Priority", "Later"), (euclid,))
    compare_write_user_state(machine_learning, machine_state, machine_opened.journal_revision)
    statistics_changed = replace(statistics_opened, groups=("Statistics", "Inference"), custom_labels=("Read",),
                                 journals=(journal.model_copy(update={"labels": ("Read",)}),))
    assert save_settings(statistics, statistics_changed).outcome is SettingsSaveOutcome.SAVED
    assert load_user_state(machine_learning).state == machine_state
    assert load_config(machine_learning).journals == (machine_journal,)
    assert load_settings(statistics).draft.access_services == (service,)
    assert load_settings(statistics).draft.groups == ("Statistics", "Inference")
    assert load_settings(statistics).draft.custom_labels == ("Read",)


def test_saved_service_order_labels_and_manual_mapping_survive_reload(tmp_path):
    from allfold.config import AccessService
    config, legacy, journal, service = current_mapping_document(tmp_path)
    snapshot = load_user_state(config)
    manual = AccessService.create("Project Euclid", "https://projecteuclid.org", access_method="manual")
    wos = AccessService.create("Web of Science")
    other = JournalConfig(name="Annals", issn="0090-5364", group="Statistics", labels=("Read",), access_service_id=manual.id)
    changed = SettingsList((other, journal), ("Statistics", "Empty group"), ("Read", "Unused"), (wos, manual, service))
    compare_write_user_state(config, changed, snapshot.revision)
    assert load_user_state(config).state == changed


def test_runtime_snapshot_changes_when_only_saved_service_changes(tmp_path):
    from allfold.config import load_config
    config, legacy, journal, service = current_mapping_document(tmp_path)
    original = load_config(config)
    snapshot = load_user_state(config)
    changed = replace(snapshot.state, access_services=(service.model_copy(update={"name": "EBSCO"}),))
    compare_write_user_state(config, changed, snapshot.revision)
    assert load_config(config) != original


def test_settings_deletion_requires_current_approval_and_corruption_blocks_save(tmp_path):
    from allfold.application.settings import (
        load_settings, save_settings, SettingsSaveOutcome, SettingsDeletionApproval,
    )
    config, legacy, journal, service = current_mapping_document(tmp_path)
    opened = load_settings(config)
    removed = replace(opened.draft, access_services=(), journals=(journal.model_copy(update={"access_service_id": None}),))
    assert save_settings(config, removed).outcome is SettingsSaveOutcome.INVALID_DRAFT
    approval = SettingsDeletionApproval(removed.monitor_revision, removed.journal_revision, (service.id,))
    saved = save_settings(config, removed, deletion_approval=approval)
    assert saved.outcome is SettingsSaveOutcome.SAVED
    assert load_user_state(config).state.access_services == ()
    assert save_settings(config, removed, deletion_approval=approval).outcome is SettingsSaveOutcome.REVISION_CONFLICT
    database = load_user_state(config).database_path
    database.write_bytes(b"damaged database")
    result = save_settings(config, saved.state.draft)
    assert result.outcome is not SettingsSaveOutcome.SAVED
    assert database.read_bytes() == b"damaged database"


def test_covers_use_saved_db_journal_identifiers_without_markdown(tmp_path):
    import io
    from PIL import Image
    from allfold.application.journal_covers import upload_cover, cover_details, CoverError
    config, legacy, journal, _ = current_mapping_document(tmp_path)
    load_user_state(config)
    legacy.unlink()
    output = io.BytesIO()
    Image.new("RGB", (20, 30), "red").save(output, "PNG")
    upload_cover(legacy, journal.key, output.getvalue(), config_path=config)
    assert cover_details(legacy, journal.key)["state"] == "Uploaded"
    snapshot = load_user_state(config)
    replacement = JournalConfig(name="Other", issn="0090-5364")
    compare_write_user_state(config, replace(snapshot.state, journals=(replacement,)), snapshot.revision)
    with pytest.raises(CoverError, match="does not exist"):
        upload_cover(legacy, journal.key, output.getvalue(), config_path=config)


@pytest.mark.parametrize("change_state", [None, "groups", "journals", "access_services"])
def test_wos_uses_independent_sqlite_service_and_detects_changes(tmp_path, change_state):
    import threading
    from allfold.config import AccessService
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.application.coordinators.login import PreparedService
    from allfold.application.coordinators.wos_coordinator import WoSCoordinator
    from allfold.persistence.paper_repository import PaperRepository
    from electron_test_helpers import PendingBridge

    class Login:
        def prepared_page(self, saved, service_id):
            assert any(service.id == service_id and service.name == "Web of Science" for service in saved.services)
            return 71
        def prepared_authority(self, saved, service_id):
            return PreparedService(self.prepared_page(saved, service_id), 'e' * 64)


    config, legacy, journal, service = current_mapping_document(tmp_path)
    config.write_text(config.read_text() + "\ninstitution:\n  name: Fixture University\n")
    original = load_user_state(config)
    wos = AccessService.create("Web of Science")
    saved = compare_write_user_state(config, replace(original.state, access_services=(service, wos)), original.revision)
    legacy.unlink()
    bridge = PendingBridge()
    slot, browser_lock = threading.Lock(), BrowserTaskLock()
    coordinator = WoSCoordinator(config, Login(), slot, bridge=bridge, browser_lock=browser_lock)
    coordinator.start()
    assert bridge.dispatched.wait(2)
    if change_state:
        changes = {
            "groups": ("Statistics", "Added"),
            "journals": (journal.model_copy(update={"name": "Updated journal"}),),
            "access_services": (service, wos.model_copy(update={"access_url": "https://www.webofscience.com/"})),
        }
        compare_write_user_state(config, replace(saved.state, **{change_state: changes[change_state]}), saved.revision)
    bridge.future.set_result({"page_id": 71, "total": 0, "batch_limit": 100})
    coordinator.join()
    result = coordinator.state()["snapshot"]["result"]
    if change_state:
        assert any("configuration changed" in text for text in result["issues"]), result["issues"]
        assert result["outcome"] == "Failed"
    else:
        assert result["outcome"] == "Completed"
    assert [action for action, _ in bridge.calls] == ["wos_query"]
    assert not slot.locked() and browser_lock.owner is None
    with PaperRepository.open(tmp_path / "workspace") as repository:
        assert repository.list_papers() == ()


def test_load_config_rejects_symlink_legacy_source_before_migration(tmp_path):
    from allfold.config import ConfigurationError, load_config
    config, legacy, _, _ = current_mapping_document(tmp_path)
    held = tmp_path / "held.md"
    legacy.rename(held)
    legacy.symlink_to(held)
    before = held.read_bytes()
    with pytest.raises(ConfigurationError, match="symlink"):
        load_config(config)
    assert held.read_bytes() == before
    assert not (tmp_path / ".allfold").exists()


def test_sqlite_state_rejects_hardlinks_before_in_place_write(tmp_path):
    from allfold.persistence.user_state import UserStateError

    config, legacy, _, _ = current_mapping_document(tmp_path)
    snapshot = load_user_state(config)
    other = tmp_path / "retained-user-data.sqlite"
    other.hardlink_to(snapshot.database_path)
    original = other.read_bytes()
    with pytest.raises(UserStateError, match="single-link"):
        compare_write_user_state(config, replace(snapshot.state, groups=("Statistics", "Added")), snapshot.revision)
    assert other.read_bytes() == original


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
@pytest.mark.parametrize("kind", ["hardlink", "symlink", "directory"])
@pytest.mark.parametrize("operation", ["read", "write"])
def test_user_state_rejects_unsafe_sidecars_before_opening(tmp_path, suffix, kind, operation):
    from allfold.persistence.user_state import UserStateError, read_user_state

    config, _, _, _ = current_mapping_document(tmp_path)
    snapshot = load_user_state(config)
    target = tmp_path / "unrelated.txt"
    original = b"\x00" + b"preserve user bytes\n" * 100
    target.write_bytes(original)
    sidecar = snapshot.database_path.with_name(snapshot.database_path.name + suffix)
    if kind == "hardlink":
        sidecar.hardlink_to(target)
    elif kind == "symlink":
        sidecar.symlink_to(target)
    else:
        sidecar.mkdir()
    with pytest.raises(UserStateError, match="sidecar"):
        if operation == "read":
            read_user_state(config)
        else:
            compare_write_user_state(config, replace(snapshot.state, groups=("Statistics", "Added")), snapshot.revision)
    assert target.read_bytes() == original
