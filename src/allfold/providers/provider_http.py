"""HTTP policy for Provider reads, including PubMed's read-only form POST."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from random import random
import socket
import ssl
from threading import Event, Lock, local
import time

import httpx

from allfold.http_client import create_http_client
from allfold.http_deadline import DEADLINE_REMAINING, HTTPDeadlineExceeded
from allfold.progress import ActivityKind

REGULAR_ATTEMPTS = 3
RECOVERY_SECONDS = 90
TRANSIENT_HTTP = {429, 500, 502, 503, 504}
WAIT_FOR_AUTHORITY_INTERVAL = 0.25
TRANSIENT_TIMEOUTS = (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout)
TRANSIENT_CONNECTIONS = (httpx.ConnectError, httpx.ReadError, httpx.WriteError)


class DiscoveryError(ValueError):
    pass


class Cancelled(DiscoveryError):
    pass


class ProviderFailure(DiscoveryError):
    def __init__(self, message, *, kind, code, transient=False, transport_error=None, outcome='unknown'):
        super().__init__(message)
        self.kind, self.code = kind, code
        self.transient = transient
        self.transport_error = transport_error
        self.outcome = outcome


class ProviderHTTPError(ProviderFailure):
    def __init__(self, provider, status):
        kind = 'access' if status in {401, 402, 403, 407} else 'remote_service'
        reason = httpx.codes.get_reason_phrase(status)
        super().__init__(f'{provider}: HTTP {status}' + (f' {reason}' if reason else ''), kind=kind,
            code='rate_limited' if status == 429 else 'http_error',
            transient=status in TRANSIENT_HTTP, outcome='responded')
        self.status = status


class ProviderBudgetExceeded(DiscoveryError):
    pass


class _DeadlineStream(httpx.SyncByteStream):
    def __init__(self, stream, check):
        self._stream, self._check = stream, check

    def __iter__(self):
        for chunk in self._stream:
            self._check()
            yield chunk

    def close(self):
        self._stream.close()


def _transport_failure(provider, error):
    causes = []
    cause = error
    while cause is not None and all(cause is not item for item in causes):
        causes.append(cause)
        cause = cause.__cause__ or (None if cause.__suppress_context__ else cause.__context__)
    tls = any(isinstance(cause, ssl.SSLError) for cause in causes)
    permanent_dns = any(isinstance(cause, socket.gaierror) and cause.errno != socket.EAI_AGAIN for cause in causes)
    timeout = isinstance(error, TRANSIENT_TIMEOUTS)
    # httpcore uses this exact error for EOF before response headers. Other
    # RemoteProtocolError cases include malformed messages and incomplete bodies.
    disconnected = (isinstance(error, httpx.RemoteProtocolError)
                    and str(error) == 'Server disconnected without sending a response.')
    temporary = not (tls or permanent_dns) and (timeout or disconnected or isinstance(error, TRANSIENT_CONNECTIONS))
    subtype = next((cls.__name__ for cls in (*TRANSIENT_TIMEOUTS, *TRANSIENT_CONNECTIONS)
                    if isinstance(error, cls)), None)
    if disconnected:
        subtype = 'RemoteProtocolError'
    kind = ('access' if tls or isinstance(error, httpx.ProxyError)
            else 'runtime' if isinstance(error, httpx.PoolTimeout)
            else 'protocol' if not disconnected and isinstance(error, (
                httpx.ProtocolError, httpx.DecodingError, httpx.InvalidURL, httpx.TooManyRedirects, httpx.UnsupportedProtocol))
            else 'transport')
    return ProviderFailure(f'{provider}: network request failed ({type(error).__name__})',
        kind=kind, code='timeout' if isinstance(error, httpx.TimeoutException) else 'network_error',
        transient=temporary, transport_error=subtype,
        outcome='not_sent' if isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
        else 'unknown')


def _retry_after(value, wall_time):
    if value is None:
        return None
    value = value.strip()
    if value.isascii() and value.isdecimal():
        return float(value)
    try:
        date = parsedate_to_datetime(value)
        return max(0.0, (date - wall_time()).total_seconds()) if date.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


class ProviderCooldowns:
    """Admission state owned by the Python host, with no network I/O under its lock."""

    def __init__(self):
        self._lock = Lock()
        self._until = {}

    def extend(self, key, now, status, delay):
        with self._lock:
            for expired in [scope for scope, (_, until) in self._until.items() if until <= now]:
                del self._until[expired]
            if delay > 0 and now + delay > self._until.get(key, (0, now))[1]:
                self._until[key] = (status, now + delay)

    def remaining(self, key, now):
        with self._lock:
            status, until = self._until.get(key, (0, now))
            if until <= now:
                self._until.pop(key, None)
            return status, max(0, until - now)


# The desktop host runs one Python process. Replacing a short-lived client does
# not erase server instructions, and injected transports are isolated by default.
_APPLICATION_COOLDOWNS = ProviderCooldowns()


@dataclass
class ReadOperation:
    deadline: float
    activity: Callable[[ActivityKind, str | None, str], None] | None = None
    attempt: int = 1
    attempt_limit: int = REGULAR_ATTEMPTS
    request: httpx.Request | None = None
    failure: ProviderFailure | None = None
    exhausted: bool = False

    @property
    def can_recheck(self):
        return (not self.exhausted and self.request is not None
                and self.failure is not None and self.failure.transient)


class ProviderReadClient:
    """Dispatch safe Provider reads through HTTPX with a single retry owner."""

    def __init__(self, provider, *, api_key=None, transport=None, timeout=30, interval=0,
                 pacing_state=None, cancel_event=None, guard=None, recovery_observer=None,
                 sleep=time.sleep, monotonic=time.monotonic, wall_time=lambda: datetime.now(timezone.utc),
                 jitter=random, cooldowns=None, deadline=None):
        self.provider = provider
        self._pubmed_auth = sha256(api_key.encode()).digest() if provider == 'pubmed' and api_key else None
        self._timeout, self._interval = timeout, interval
        self._pacing = pacing_state if pacing_state is not None else {}
        self._pacing_lock = self._pacing.setdefault('lock', Lock())
        self._cancel = cancel_event if cancel_event is not None else Event()
        self._guard = guard
        self.recovery_observer = recovery_observer
        self._sleep, self._now, self._wall_time, self._jitter = sleep, monotonic, wall_time, jitter
        self._deadline = deadline
        self._cooldowns = cooldowns if cooldowns is not None else (
            _APPLICATION_COOLDOWNS if transport is None else ProviderCooldowns())
        self._trace = local()
        self._access_failure = None
        self.request_count = 0
        self.http = create_http_client(transport=transport, timeout=timeout, deadline_reads=True, event_hooks={
            'request': [self._before_request], 'response': [self._observe_response],
        })

    def check_authority(self):
        if self._cancel.is_set():
            raise Cancelled('Run cancelled')
        if self._guard is not None:
            self._guard()

    def operation(self, activity=None):
        deadline = self._now() + RECOVERY_SECONDS
        if self._deadline is not None:
            deadline = min(deadline, self._deadline)
        return ReadOperation(deadline, activity)

    def _scope(self, request):
        auth = request.headers.get('authorization')
        context = sha256(auth.encode()).digest() if auth else (
            self._pubmed_auth if self.provider == 'pubmed' and request.method == 'POST' else None)
        url = request.url
        port = url.port or {'https': 443, 'http': 80}.get(url.scheme)
        return url.scheme, url.host.removesuffix('.'), port, context

    def _event(self, event, operation, action, *, failure=None, status=None, delay=None, stop=None):
        if self.recovery_observer is None:
            return
        details = dict(provider=self.provider, stage='provider', recovery_action=action,
                       attempt=operation.attempt, attempt_limit=operation.attempt_limit,
                       remaining_ms=max(0, round((operation.deadline - self._now()) * 1000)))
        if failure is not None:
            dispatch = ('not_dispatched' if action == 'cooldown_wait' else
                        {'responded': 'confirmed', 'not_sent': 'not_dispatched'}.get(failure.outcome, 'unknown'))
            details.update(code=failure.code, failure_kind=failure.kind, dispatch_outcome=dispatch)
            if failure.transport_error is not None:
                details['transport_error'] = failure.transport_error
            status = getattr(failure, 'status', status)
        if status:
            details['status'] = status
        if delay is not None:
            details['wait_ms'] = round(delay * 1000)
        if stop is not None:
            details['recovery_stop'] = stop
        try:
            self.recovery_observer(event, details)
        except Exception:
            # Observability must not affect a Provider request or its settlement.
            pass

    def _activity(self, operation, kind, detail, *, label=None):
        if operation.activity is not None:
            operation.activity(kind, label, detail)

    def _remaining(self, operation):
        return operation.deadline - self._now()

    def _check_response_deadline(self, operation, status):
        if self._remaining(operation) <= 0:
            self._response_budget_exhausted(operation, status)

    def _response_budget_exhausted(self, operation, status):
        if status is not None and status >= 400:
            operation.failure = ProviderHTTPError(self.provider, status)
        raise ProviderBudgetExceeded(f'{self.provider}: Provider request recovery budget exhausted')

    def _wait(self, operation, seconds):
        self.check_authority()
        if seconds >= self._remaining(operation):
            raise ProviderBudgetExceeded(f'{self.provider}: Provider request recovery budget exhausted')
        if self._sleep is time.sleep:
            until = self._now() + seconds
            while (remaining := until - self._now()) > 0:
                self._cancel.wait(min(remaining, WAIT_FOR_AUTHORITY_INTERVAL))
                self.check_authority()
        else:
            self._sleep(seconds)
            self.check_authority()

    def _before_request(self, request):
        self._trace.status = None
        operation = self._trace.operation
        scope = self._scope(request)
        waiting_status = None
        reported = False
        while True:
            self.check_authority()
            if self._access_failure is not None:
                raise self._access_failure
            now = self._now()
            remaining = operation.deadline - now
            status, delay = self._cooldowns.remaining(scope, now)
            if remaining <= 0 or delay >= remaining:
                if delay > 0:
                    self._event('recovery_exhausted', operation, 'cooldown_wait',
                        failure=ProviderHTTPError(self.provider, status), stop='budget')
                raise ProviderBudgetExceeded(f'{self.provider}: Provider request recovery budget exhausted'
                    + (f' during HTTP {status} cooldown' if delay > 0 else ''))
            if delay > 0:
                if waiting_status is None:
                    self._event('service_cooldown_started', operation, 'cooldown_wait',
                        failure=ProviderHTTPError(self.provider, status), delay=delay)
                waiting_status = status
                self._activity(operation, ActivityKind.WAITING,
                    f'HTTP {status} · {delay:.2f} seconds', label='Waiting for provider cooldown')
                try:
                    self._wait(operation, delay)
                except Cancelled:
                    self._event('recovery_exhausted', operation, 'cooldown_wait',
                        failure=ProviderHTTPError(self.provider, status), stop='canceled')
                    raise
                continue
            if waiting_status is not None:
                self._event('service_cooldown_ended', operation, 'cooldown_wait',
                    failure=ProviderHTTPError(self.provider, waiting_status))
                waiting_status = None
                continue
            with self._pacing_lock:
                now = self._now()
                delay = self._pacing.get(scope[:3], now) - now
                ready = delay <= 0 and self._cooldowns.remaining(scope, now)[1] <= 0
                if ready and reported and now < operation.deadline:
                    self._pacing[scope[:3]] = now + self._interval
                    self.request_count += 1
                    operation.request = request
                    break
            if ready and not reported:
                self._activity(operation, ActivityKind.WORKING, 'Request dispatched')
                reported = True
            elif delay > 0:
                self._wait(operation, delay)
        request.extensions['timeout'] = httpx.Timeout(min(self._timeout, operation.deadline - now)).as_dict()
        deadline, monotonic = operation.deadline, self._now
        request.extensions[DEADLINE_REMAINING] = lambda: deadline - monotonic()

    def _observe_response(self, response):
        status = self._trace.status = response.status_code
        if status in TRANSIENT_HTTP:
            delay = _retry_after(response.headers.get('retry-after'), self._wall_time)
            if delay is not None or status == 429:
                # An exhausted sender and a canceled sender still publish the response.
                self._cooldowns.extend(self._scope(response.request), self._now(), status,
                                       1 if delay is None else delay)
            self._trace.retry_after = delay is not None
        operation = self._trace.operation

        def check():
            self._check_response_deadline(operation, status)

        check()
        if not response.is_stream_consumed:
            response.stream = _DeadlineStream(response.stream, check)

    def read(self, prepare, operation, *, decode, follow_redirects, final=False):
        if final:
            operation.attempt = operation.attempt_limit = REGULAR_ATTEMPTS + 1
            action = 'completion_recheck'
            self._event('recovery_scheduled', operation, action, failure=operation.failure)
            self._activity(operation, ActivityKind.RETRYING, 'Final check · one request',
                           label='Checking failed provider request')
        else:
            action = 'provider_retry'
        self._trace.operation = operation
        self._trace.retry_after = False
        self._trace.status = None
        try:
            return self._read(prepare, operation, decode, follow_redirects, action, final)
        finally:
            del self._trace.operation
            del self._trace.retry_after
            del self._trace.status

    def _read(self, prepare, operation, decode, follow_redirects, action, final):
        attempts = range(1, REGULAR_ATTEMPTS + 1) if not final else (operation.attempt,)
        for attempt in attempts:
            operation.attempt = attempt
            self._trace.retry_after = False
            self._trace.status = None
            try:
                self.check_authority()
                if self._access_failure is not None:
                    raise self._access_failure
                try:
                    request = operation.request if final else prepare()
                    response = self.http.send(request, follow_redirects=follow_redirects)
                except HTTPDeadlineExceeded:
                    self.check_authority()
                    self._response_budget_exhausted(operation, self._trace.status)
                except (httpx.HTTPError, httpx.InvalidURL) as error:
                    self.check_authority()
                    self._check_response_deadline(operation, self._trace.status)
                    raise _transport_failure(self.provider, error) from None
                self.check_authority()
                self._check_response_deadline(operation, response.status_code)
                result = self._decode(response, decode)
            except ProviderBudgetExceeded:
                operation.exhausted = True
                if attempt > 1:
                    self._event('recovery_exhausted', operation, action, failure=operation.failure, stop='budget')
                if operation.failure is not None:
                    raise operation.failure from None
                raise
            except Cancelled:
                if attempt > 1:
                    self._event('recovery_exhausted', operation, action, failure=operation.failure, stop='canceled')
                raise
            except ProviderFailure as failure:
                operation.failure = failure
                self.check_authority()
                if not failure.transient or attempt == operation.attempt_limit:
                    if attempt > 1:
                        self._event('recovery_exhausted', operation, action, failure=failure,
                                    stop='limit' if failure.transient else 'failed')
                    raise
                delay = 0 if self._trace.retry_after else (1 if getattr(failure, 'status', 0) == 429 else 5) * (
                    2 ** (attempt - 1)) * (1 + 0.25 * self._jitter())
                operation.attempt = attempt + 1
                self._event('recovery_scheduled', operation, action, failure=failure, delay=delay)
                self._activity(operation, ActivityKind.RETRYING,
                    f'Retry {attempt + 1}/{REGULAR_ATTEMPTS} · {delay:.2f} seconds' if delay else
                    f'Retry {attempt + 1}/{REGULAR_ATTEMPTS} · checking cooldown',
                    label=f'{failure} · Retry {attempt + 1}/{REGULAR_ATTEMPTS}')
                try:
                    if delay:
                        self._wait(operation, delay)
                except ProviderBudgetExceeded:
                    operation.exhausted = True
                    self._event('recovery_exhausted', operation, action, failure=failure, stop='budget')
                    raise failure from None
                except Cancelled:
                    self._event('recovery_exhausted', operation, action, failure=failure, stop='canceled')
                    raise
            else:
                if attempt > 1:
                    self._event('recovery_succeeded', operation, action, failure=operation.failure)
                self._activity(operation, ActivityKind.WORKING, 'Response received')
                return result

    def _decode(self, response, decode):
        status = response.status_code
        text = response.text.lstrip().lower()
        html = 'text/html' in response.headers.get('content-type', '').lower() or text.startswith(('<!doctype html', '<html'))
        challenge = html and (status == 202 or any(marker in text for marker in (
            'anubis', 'captcha', 'cf-chl-', 'challenge-platform',
            'verify you are human', 'checking your browser')))
        if challenge:
            kind = 'Anubis verification' if 'anubis' in text else 'an HTML verification page'
            self._access_failure = ProviderFailure(
                f'{self.provider}: access limited by {kind} (HTTP {status}); further automatic requests stopped for this client',
                kind='access', code='http_error', outcome='responded')
            raise self._access_failure
        if status != 200:
            raise ProviderHTTPError(self.provider, status)
        if html:
            raise ProviderFailure(f'{self.provider}: unexpected HTML response instead of API metadata',
                kind='protocol', code='http_error', outcome='responded')
        return decode(response)


def object_json(provider, response):
    try:
        data = response.json()
        if isinstance(data, dict):
            return data
    except (ValueError, UnicodeDecodeError):
        pass
    raise ProviderFailure(f'{provider}: invalid JSON response', kind='protocol', code='http_error',
                          outcome='responded') from None
