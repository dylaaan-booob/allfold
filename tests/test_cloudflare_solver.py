"""Solver cancellation joins actual CDP transport cleanup, with isolated transport."""
import asyncio
from threading import Event

from allfold.integrations.cloudflare_solver import solve_cloudflare


def test_cancel_during_transport_cleanup_waits_until_connection_is_closed(monkeypatch):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        closed = []

        class Connection:
            def __init__(self, **_kwargs):
                pass

            async def execute_command(self, _command):
                # A rejected target still owns its already-open CDP connection.
                return {'result': {'targetInfo': {'type': 'iframe'}}}

            async def close(self):
                entered.set()
                await release.wait()
                closed.append(True)

        monkeypatch.setattr('pydoll.connection.connection_handler.ConnectionHandler', Connection)
        stop = Event()
        async def progress(_data):
            pass
        task = asyncio.create_task(solve_cloudflare('ws://127.0.0.1:1/devtools/browser/fixture',
            stop, target_id='a' * 32, progress=progress))
        await entered.wait()
        stop.set()
        try:
            await asyncio.sleep(.12)
            assert not task.done(), 'cancel cannot return while actual connection cleanup is unfinished'
        finally:
            release.set()
            await task
        assert closed == [True]
    asyncio.run(scenario())
