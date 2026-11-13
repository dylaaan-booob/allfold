"""Independent, execution-owned Provider clients over application-owned pacing.

The runtime supplies captured authority, cancellation and one absolute deadline.
Neither factory nor attempt borrows a Run snapshot, connection or request cache.
"""
from contextlib import ExitStack, contextmanager
from pathlib import Path
from threading import Condition, Lock

from allfold.application.metadata_completion import completion_client
from allfold.integrations.openalex_credentials import read_credential
from allfold.providers.integrated import DISCOVERY_PROVIDERS, PROVIDERS


def new_provider_pacing():
    """Create one host pacing state; pass it to Run, Preprint and this factory."""
    return {'lock': Lock()}


class AttemptClients:
    """Use and close in the worker context that owns this attempt.

    Clients may be reused within that context, including their existing adapter
    caches, but are never inherited by another attempt. Repository ownership stays
    with the worker, outside this HTTP-only boundary.
    """

    def __init__(self, factory, *, cancel_event, request_guard, deadline,
                 mailto, progress_callback, recovery_observer):
        self.cancel_event, self.deadline = cancel_event, deadline
        self.request_cache = {}
        self._factory, self._guard = factory, request_guard
        self._mailto, self._progress, self._observer = mailto, progress_callback, recovery_observer
        self._stack, self._clients = ExitStack(), {}
        self._closed = False
        request_guard()
        self._credentials = {name: read_credential(factory.config_path, provider=name)[0]
                             for name in DISCOVERY_PROVIDERS}
        request_guard()

    def provider(self, name):
        if self._closed:
            raise RuntimeError('Attempt clients are closed')
        if name not in PROVIDERS:
            raise ValueError('Unknown Provider')
        self._guard()
        if name not in self._clients:
            client = self._factory.client_factory(name,
                api_key=self._credentials.get(name), mailto=self._mailto,
                cancel_event=self.cancel_event, pacing_state=self._factory.pacing_state,
                deadline=self.deadline, progress_callback=self._progress)
            client.request_guard = self._guard
            if self._observer is not None:
                client.recovery_observer = self._observer
            self._clients[name] = self._stack.enter_context(client)
        return self._clients[name]

    def close(self):
        if not self._closed:
            self._closed = True
            self._stack.close()


class IndependentClientFactory:
    """Application-owned admission; contexts own their clients through real close."""

    def __init__(self, config_path, *, pacing_state=None, client_factory=completion_client):
        self.config_path = Path(config_path)
        self.pacing_state = pacing_state if pacing_state is not None else new_provider_pacing()
        self.client_factory = client_factory
        self._condition = Condition()
        self._active = 0
        self._closed = False

    @contextmanager
    def open(self, *, cancel_event, request_guard, deadline, mailto='',
             progress_callback=None, recovery_observer=None):
        with self._condition:
            if self._closed:
                raise RuntimeError('Independent client factory is closed')
            self._active += 1
        try:
            clients = AttemptClients(self, cancel_event=cancel_event, request_guard=request_guard,
                deadline=deadline, mailto=mailto, progress_callback=progress_callback,
                recovery_observer=recovery_observer)
            try:
                yield clients
            finally:
                clients.close()
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def close(self):
        """Stop admission and wait after the runtime has cancelled/drained work."""
        with self._condition:
            self._closed = True
            self._condition.wait_for(lambda: self._active == 0)
