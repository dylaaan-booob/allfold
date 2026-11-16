"""Framed stdio transport around the authenticated Bridge; no business operation."""
import asyncio
import json
import sys

from fastapi import WebSocketDisconnect
from allfold.logging_setup import configure_logging
from allfold.web.electron_bridge import ElectronBridge


class Socket:
    headers = {'host': 'fixture'}

    async def accept(self):
        pass

    async def close(self, **_kwargs):
        pass

    async def receive_json(self):
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            raise WebSocketDisconnect()
        return json.loads(line)

    async def send_json(self, message):
        print(json.dumps(message), flush=True)


async def main():
    configure_logging()
    bridge = ElectronBridge('fixture-only', 'fixture', cdp_url=sys.argv[1])
    await bridge.connect(Socket())
    assert not bridge._pending
    print(json.dumps({'type': 'fixture_complete'}), flush=True)


asyncio.run(main())
