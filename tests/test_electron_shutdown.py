"""Normal exit must receive native results before shared admission can settle."""
import asyncio
from concurrent.futures import Future
import threading

import httpx
import pytest

from allfold.web.app import create_app
from allfold.web.electron_server import drain_application
from electron_test_helpers import OfflineBridge
from safety_config_helpers import current_mapping_document


@pytest.mark.parametrize('lifecycle', ['native_drain', 'lifespan'])
@pytest.mark.parametrize('operation', ['targets', 'authorize', 'credentials'])
def test_shutdown_receives_native_result_while_settings_operation_owns_admission(tmp_path, lifecycle, operation):
    class NativeBridge(OfflineBridge):
        connected = True

        def __init__(self):
            self.result = Future()
            self.dispatched = threading.Event()

        def execute(self, action, data, progress=None, *, verify_recovery=None):
            self.dispatched.set()
            return self.result

    async def scenario():
        config, _, _, _ = current_mapping_document(tmp_path)
        bridge = NativeBridge()
        application = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path / 'logs')
        watchdog_fired = threading.Event()

        def unblock_failed_shutdown():
            watchdog_fired.set()
            bridge.result.set_exception(RuntimeError('Shutdown blocked native result delivery'))

        transport = httpx.ASGITransport(app=application)
        lifespan = application.router.lifespan_context(application)
        await lifespan.__aenter__()
        async with httpx.AsyncClient(transport=transport, base_url='http://localhost') as client:
            path = '/api/ui-next/settings/credentials' if operation == 'credentials' else '/api/ui-next/zotero'
            body = {'csrf_token': application.state.csrf_token, 'operation': operation}
            if operation == 'credentials':
                body.update(operation='save', username='fixture', password='synthetic-only', expected_revision='missing')
            request = asyncio.create_task(client.post(path, json=body))
            assert await asyncio.to_thread(bridge.dispatched.wait, 2)
            native_received = asyncio.Event()

            def native_result():
                native_received.set()
                if not bridge.result.done():
                    bridge.result.set_result({'ok': True})

            # A watchdog prevents this regression itself from hanging the suite.
            watchdog = threading.Timer(1, unblock_failed_shutdown)
            watchdog.start()
            asyncio.get_running_loop().call_later(.02, native_result)
            bridge.closing = True
            try:
                if lifecycle == 'native_drain':
                    await drain_application(application)
                else:
                    await lifespan.__aexit__(None, None, None)
                response = await request
                assert not watchdog_fired.is_set(), 'Exit blocked the native result callback'
                assert native_received.is_set() and response.json() == {'ok': True}
                assert application.state.browser_task_lock.owner is None
                rejected = await client.post(path, json=body)
                assert rejected.status_code == 409
            finally:
                watchdog.cancel()
                watchdog.join()
                if lifecycle == 'native_drain':
                    await lifespan.__aexit__(None, None, None)

    asyncio.run(scenario())
