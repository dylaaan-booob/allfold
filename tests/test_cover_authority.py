"""Cover final-save eligibility belongs to its Journal and managed assets."""
import base64
import io
from dataclasses import replace
from PIL import Image
import pytest

from allfold.application.browser_runtime import BrowserTaskLock
from allfold.application.coordinators.journal_covers import JournalCoverSearch
from allfold.application.journal_covers import cover_details, upload_cover
from allfold.persistence.user_state import load_user_state, compare_write_user_state
from electron_test_helpers import PendingBridge
from safety_config_helpers import current_mapping_document


def image_data(color='red'):
    stream = io.BytesIO()
    Image.new('RGB', (12, 16), color).save(stream, 'PNG')
    return stream.getvalue()


@pytest.mark.parametrize('change', ['unrelated', 'journal', 'asset'])
def test_cover_result_survives_unrelated_edits_but_cannot_replace_changed_target(tmp_path, change):
    config, path, journal, _ = current_mapping_document(tmp_path)
    state = load_user_state(config, path)
    bridge, lock = PendingBridge(), BrowserTaskLock()
    search = JournalCoverSearch(bridge, lock)
    operation = search.start(path, (journal,), journal.key, config_path=config)
    assert bridge.dispatched.wait(2)
    if change == 'unrelated':
        compare_write_user_state(config, replace(state.state, groups=(*state.state.groups, 'Other Group')), state.revision)
    elif change == 'journal':
        compare_write_user_state(config, replace(state.state,
            journals=(journal.model_copy(update={'name': 'Replaced Journal'}),)), state.revision)
    else:
        upload_cover(path, journal.key, image_data('blue'), config_path=config)
    existing = cover_details(path, journal.key)
    bridge.future.set_result({'source_url': 'https://publisher.example/cover.png',
        'image_base64': base64.b64encode(image_data()).decode()})
    search.join()
    assert search.state()['phase'] == ('Completed' if change == 'unrelated' else 'Failed')
    if change != 'unrelated':
        assert cover_details(path, journal.key) == existing


def test_cancel_cover_uses_its_captured_identity_and_retains_admission_until_native_settles(tmp_path):
    config, path, journal, _ = current_mapping_document(tmp_path)
    bridge, lock = PendingBridge(), BrowserTaskLock()
    search = JournalCoverSearch(bridge, lock)
    current = search.start(path, (journal,), journal.key, config_path=config)
    assert bridge.dispatched.wait(2)
    assert not search.cancel('old')
    assert search.cancel(current['request_id'])
    assert lock.owner and search.state()['busy']
    bridge.future.set_result({})
    search.join()
    assert bridge.cancelled_tasks == [(current['request_id'], current['request_id'])]
    assert search.state()['phase'] == 'Cancelled' and lock.owner is None
