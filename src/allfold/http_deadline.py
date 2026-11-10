"""Cancellable HTTPX I/O behind the synchronous Provider request interface."""

import asyncio
from contextlib import ExitStack

from anyio.from_thread import BlockingPortalProvider
import httpx


DEADLINE_REMAINING = "allfold_deadline_remaining"
_PORTALS = BlockingPortalProvider()


class HTTPDeadlineExceeded(httpx.TimeoutException):
    pass


async def _before_deadline(remaining, call, *args):
    seconds = remaining()
    if seconds <= 0:
        raise HTTPDeadlineExceeded("HTTP deadline exceeded")
    limit = asyncio.timeout(seconds)
    try:
        async with limit:
            return await call(*args)
    except TimeoutError:
        if not limit.expired():
            raise
        raise HTTPDeadlineExceeded("HTTP deadline exceeded") from None


class _ResponseStream(httpx.SyncByteStream):
    def __init__(self, stream, portal, remaining):
        self._stream = stream
        self._portal = portal
        self._remaining = remaining

    def __iter__(self):
        iterator = aiter(self._stream)
        while True:
            try:
                chunk = self._portal.call(_before_deadline, self._remaining, anext, iterator)
            except StopAsyncIteration:
                return
            yield chunk

    def close(self):
        # Close even after the deadline so an interrupted response releases its connection.
        self._portal.call(self._stream.aclose)


class DeadlineTransport(httpx.BaseTransport):
    """Run only network I/O in the shared portal; HTTPX hooks stay on the caller."""

    def __init__(self, **options):
        self._transport = httpx.AsyncHTTPTransport(**options)
        self._resources = ExitStack()
        self._portal = self._resources.enter_context(_PORTALS)
        self._resources.callback(self._portal.call, self._transport.aclose)

    def handle_request(self, request):
        # Provider GETs and buffered form POSTs use HTTPX's dual-mode ByteStream.
        remaining = request.extensions[DEADLINE_REMAINING]
        response = self._portal.call(_before_deadline, remaining, self._transport.handle_async_request, request)
        response.stream = _ResponseStream(response.stream, self._portal, remaining)
        return response

    def close(self):
        self._resources.close()
