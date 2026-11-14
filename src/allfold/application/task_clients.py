"""Independent, execution-owned Provider clients over application-owned pacing.

The runtime supplies captured authority, cancellation and one absolute deadline.
Neither factory nor attempt borrows a Run snapshot, connection or request cache.
"""
from contextlib import ExitStack, contextmanager
from pathlib import Path
from threading import Condition, Lock

from allfold.application.provider_lookup import provider_client
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
                 mailto, progress_callback, recovery_observer, providers):
        self.cancel_event, self.deadline = cancel_event, deadline
        self.request_cache = {}
        self._factory, self._guard = factory, request_guard
        self._mailto, self._progress, self._observer = mailto, progress_callback, recovery_observer
        self._stack, self._clients = ExitStack(), {}
        self._closed = False
        self._providers = frozenset(PROVIDERS if providers is None else providers)
        if not self._providers <= set(PROVIDERS):
            raise ValueError('Unknown declared Provider')
        request_guard()
        self._credentials = {name: read_credential(factory.config_path, provider=name)[0]
                             for name in self._providers if name in DISCOVERY_PROVIDERS}
        request_guard()

    def provider(self, name):
        if self._closed:
            raise RuntimeError('Attempt clients are closed')
        if name not in self._providers:
            raise ValueError('Provider was not declared for this attempt')
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

    def __init__(self, config_path, *, pacing_state=None, client_factory=provider_client):
        self.config_path = Path(config_path)
        self.pacing_state = pacing_state if pacing_state is not None else new_provider_pacing()
        self.client_factory = client_factory
        self._condition = Condition()
        self._active = 0
        self._closed = False

    @contextmanager
    def open(self, *, cancel_event, request_guard, deadline, mailto='',
             progress_callback=None, recovery_observer=None, providers=None):
        with self._condition:
            if self._closed:
                raise RuntimeError('Independent client factory is closed')
            self._active += 1
        try:
            clients = AttemptClients(self, cancel_event=cancel_event, request_guard=request_guard,
                deadline=deadline, mailto=mailto, progress_callback=progress_callback,
                recovery_observer=recovery_observer, providers=providers)
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

    @contextmanager
    def open_pdf_discovery(self, *, cancel_event, request_guard, deadline, http_options=None):
        """Owned PDF/API readers; optional publisher credentials have no saved source yet.

        The OpenAlex credential revision belongs to the captured task authority.
        Check it before and after reading its value, and at every later request.
        Creating clients here never starts a Provider request.
        """
        from allfold.pdf_http import PdfHttpClient
        from allfold.providers.openalex import OpenAlexClient
        with self._condition:
            if self._closed:
                raise RuntimeError('Independent client factory is closed')
            self._active += 1
        try:
            request_guard()
            key = read_credential(self.config_path, provider='openalex')[0]
            request_guard()
            options = dict(http_options or {})
            # These capabilities belong to the PDF reader, not ProviderReadClient.
            pdf_options = {name: options.pop(name) for name in ('resolver', 'credentials', 'max_redirects')
                           if name in options}
            with ExitStack() as resources:
                http = resources.enter_context(PdfHttpClient(guard=request_guard, cancel_event=cancel_event,
                    deadline=deadline, pacing_state=self.pacing_state, **pdf_options, **options))
                openalex = resources.enter_context(OpenAlexClient(api_key=key, guard=request_guard,
                    cancel_event=cancel_event, deadline=deadline, pacing_state=self.pacing_state,
                    request_url_guard=http.openalex_request_guard, **options))
                yield http, openalex
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()
