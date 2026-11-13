"""Framed stdio fixture transport around the real Bridge; isolated Electron CDP only."""
import asyncio
import json
import sys

from fastapi import WebSocketDisconnect
from allfold.web.electron_bridge import ElectronBridge


class Socket:
    headers = {'host': 'fixture'}

    def __init__(self):
        self.ready = asyncio.Event()

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
        if message.get('type') == 'ready':
            self.ready.set()


async def main():
    socket = Socket()
    bridge = ElectronBridge('fixture-only', 'fixture', cdp_url=sys.argv[1])
    receiver = asyncio.create_task(bridge.connect(socket))
    await socket.ready.wait()
    result = await bridge._execute('prepare_service', {'workflow_id': 'fixture'}, None, None)
    assert result == {'outcome': 'Opened'}
    print(json.dumps({'type': 'fixture_complete'}), flush=True)
    await receiver


asyncio.run(main())
