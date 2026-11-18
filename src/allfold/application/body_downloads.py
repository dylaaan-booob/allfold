"""One Paper owner coordinates lazy discovery, Session transport and completion."""
from concurrent.futures import Future
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace, field
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

from allfold.application.browser_services import browser_workspace_identity
from allfold.pdf_discovery import CandidateResult, CurrentResponse, PdfDiscovery, PdfSourceReadError, SUPPORTED_PDF_TARGET_TYPES
from allfold.pdf_rules import PdfCandidate, PdfTarget, PdfRuleInputs
from allfold.pdf_responses import access_limited, parse_current_response, reader_context
from allfold.persistence.body_files import ManagedBodyFiles
from allfold.persistence.paper_repository import PaperRecord, StaleWriteError, InvalidPaperState, LibraryError
from allfold.providers.provider_http import Cancelled, ProviderBudgetExceeded


@dataclass(frozen=True)
class _BodyRequest:
    primary: object
    candidates: tuple | None
    progress: object = None
    target: object = None
    facts: tuple = ()
    http_options: object = field(default=None, repr=False)
    direct: tuple = ()
    provider_authority: object = field(default=None, repr=False)
    prior_attempt: int = 0
    service_id: str | None = None
    service_reason: str | None = None
    service_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class BodyResult:
    status: str
    paper: PaperRecord | None = None
    candidate_result: CandidateResult | None = None


def complete_attempt(reservation, repository, files, output, *, source_url=None, pdf_source=None, fallback_used=None):
    """Publish the closed transport and associate its exact original attempt.

    The caller must already have awaited the actual transport/writer terminal.
    No SQLite write transaction surrounds filesystem publication.
    """
    registry = reservation.registry
    size_bytes = files.publish(output)
    for error in files.cleanup_errors:
        registry._fault(reservation, 'body-file-cleanup', error)
    with registry.paper_gate():
        # Filesystem/SQLite are separate operations. Check the original library
        # identity here; the transaction owns Paper/attempt eligibility.
        if registry._identity != registry._path_identity():
            raise StaleWriteError('Workspace path or database was replaced')
        return repository.complete_download(reservation.download_token, size_bytes=size_bytes, source_url=source_url,
            pdf_source=pdf_source, fallback_used=fallback_used, direct_identities=reservation.body_request.direct)


def _source_projection(url):
    # Signed/session request spelling stays operation-local, never in provenance.
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, '/', '', ''))[:2048]


def _record_source(reservation, stage, rule, reason, attempt, *, origin=None, fallback=None, service_id=None):
    from allfold.application.history import observe
    from allfold.recovery_diagnostics import SCHEMA
    if reason not in SCHEMA['fields']['pdf_reason']['enum']:
        reason = 'source-failed'
    value = dict(pdf_stage=stage, pdf_rule=rule, pdf_reason=reason, pdf_attempt=attempt)
    if service_id is not None:
        value['service_id'] = service_id
    if fallback is not None:
        value['fallback_used'] = fallback
    if origin:
        value['source_origin'] = _source_projection(origin)
    registry = reservation.registry
    record = dict(value, paper_id=str(reservation.paper_id), attempt=reservation.download_token.attempt)
    with registry.paper_gate():
        registry.body_observations.append(record)
        del registry.body_observations[:-64]
    observe(registry.diagnostics, 'record_pdf_source', dict(record,
        workflow_id=reservation.workflow_id, task_id=reservation.task_id,
        workspace_id=str(reservation.workspace_id)))


@contextmanager
def _access_operation(reservation, repository, authority=None):
    """Release one access binding only after its original native resources end."""
    from allfold.application.collection_runtime import BodyAccessOperation, _CleanupUnconfirmed
    registry = reservation.registry
    registry._guard(reservation, repository)
    operation = BodyAccessOperation(reservation, authority or reservation.authority)
    with registry.paper_gate():
        registry._require_live(reservation)
        if reservation.access_operation is not None:
            raise InvalidPaperState('Another access operation owns this Download')
        reservation.access_operation = operation
    try:
        registry._guard(operation, repository)
        yield operation
    finally:
        native = operation.native_future
        if native is not None and (not native.done() or native.cancelled()):
            error = _CleanupUnconfirmed('Download access resource settlement is unconfirmed')
            registry.fail_reservation(reservation, phase='body-native-cleanup', error=error, unconfirmed=True)
        if not reservation.cleanup_failed:
            if operation.browser_owner is not None:
                try:
                    registry.browser_lock.release(operation.browser_owner)
                    operation.browser_owner = None
                except BaseException as error:
                    registry.fail_reservation(reservation, phase='body-owner-cleanup', error=error)
            with registry.paper_gate():
                reservation.access_operation = None
            operation.future.set_result(None)
        else:
            error = _CleanupUnconfirmed('Download access cleanup is unconfirmed')
            operation.future.set_exception(error)
            raise error


def _consume_access(reservation, repository, files, candidate, progress):
    from allfold.application.collection_runtime import BodyAccessRevoked
    try:
        with _access_operation(reservation, repository, candidate.access) as operation:
            value = _consume(operation, repository, files, candidate, progress)
            if not (value[0].pdf_type and value[0].transfer_complete) and value[0].kind != 'local_failure':
                reservation.registry._guard(operation, repository)
            return value
    except BodyAccessRevoked:
        # Recheck only the parent: user cancel/expiry/stale Paper must still end
        # the whole attempt. Service loss ends just this already settled access.
        reservation.registry._guard(reservation, repository)
        if reservation.output is not None:
            files.cleanup(reservation.output)
            repository.record_download_output(reservation.download_token, None)
            reservation.output = None
        return CandidateResult.failed('service-invalidated'), None, ''


def _consume(reservation, repository, files, candidate, progress):
    registry = reservation.registry
    registry._guard(reservation, repository)
    from allfold.application.native_body_downloads import native_applicable, transfer_native
    if native_applicable(candidate):
        native = transfer_native(reservation, repository, files, candidate, progress)
        if not (native.result.pdf_type and native.result.transfer_complete) and native.output is not None:
            files.cleanup(native.output)
            repository.record_download_output(reservation.download_token, None)
            reservation.output = None
            return native.result, None, native.final_url
        return native.result, native.output, native.final_url
    if candidate.action:
        return CandidateResult('skipped', diagnostic='native-unavailable'), None, ''
    credential = None
    if candidate.credential:
        from allfold.pdf_http import _API_SCOPES
        secret = dict((reservation.body_request.http_options or {}).get('credentials', ())).get(candidate.credential)
        scope = _API_SCOPES.get(candidate.credential)
        url = urlsplit(candidate.url)
        if not secret or not scope:
            return CandidateResult('skipped', diagnostic='credential-unavailable'), None, ''
        if (url.scheme != 'https' or url.hostname != scope[0] or (url.port or 443) != 443
                or not url.path.startswith(scope[1])):
            return CandidateResult.failed('credential-scope'), None, ''
        credential = dict(kind=candidate.credential, value=secret)
    output = files.prepare()
    reservation.output = output
    try:
        repository.record_download_output(reservation.download_token, output)
    except BaseException:
        files.cleanup(output)
        raise
    registry._guard(reservation, repository)
    registry._ensure_browser_owner(reservation)
    remaining = reservation.deadline - time.monotonic()
    payload = reservation.authority.native_access().payload() | dict(
        workspace_identity=browser_workspace_identity(registry.workspace, registry._identity[0]),
        workspace_root=str(registry.workspace), paper_id=str(reservation.paper_id),
        output=output.model_dump(mode='json'), attempt=reservation.download_token.attempt,
        attempt_id=f'{reservation.lifecycle_id}:{reservation.download_token.attempt}',
        url=candidate.url, referer=candidate.referer, deadline_ms=int((time.time()+remaining)*1000),
        workflow_id=reservation.workflow_id, task_id=reservation.task_id,
        parent_task_id=reservation.parent_task_id)
    if credential is not None:
        payload['pdf_credential'] = credential
    if candidate.recover_access:
        payload['recover_access'] = True
    with registry.paper_gate():
        registry._require_live(reservation)
        repository.require_download(reservation.download_token)
        future = registry.bridge.execute('stream_paper_body', payload, progress,
            verify_recovery=lambda: registry._guard(reservation))
        if not isinstance(future, Future):
            raise TypeError('Body transport requires a real native Future')
        reservation.native_future = future
    value = future.result()  # The authenticated native terminal follows pipeline and fd close.
    if future.cancelled():
        raise RuntimeError('Native Future cancellation does not prove file close')
    if not isinstance(value, dict):
        raise ValueError('Invalid body transport result')
    if value.get('resource_closed') is False:
        error = RuntimeError('Native writer close is unconfirmed')
        registry.fail_reservation(reservation, phase='body-native-cleanup', error=error, unconfirmed=True)
        raise error
    kind = value.get('kind')
    if (kind == 'pdf' and value.get('outcome') == 'stream_complete' and value.get('pdf_type') is True
            and value.get('transfer_complete') is True and tuple(value.get('output_file', ())) == output.file
            and type(value.get('size_bytes')) is int and value['size_bytes'] >= 0):
        return CandidateResult.pdf(transfer_complete=True), output, value['final_url']
    if kind == 'redirect':
        current = value.get('response', {})
        response = CurrentResponse(url=current['url'], content_type='', status=current['status'],
            redirect_url=current['location'])
        result = (CandidateResult.current(response) if parse_current_response(candidate, response)
            else CandidateResult.failed('redirect-scope'))
    elif kind == 'response':
        current = value.get('response', {})
        access=current.get('access')
        if access is None:
            from allfold.http_access import html_access
            detected = html_access(current['body'], current['status'])
            access = {'cloudflare': 'challenge', 'login': 'login'}.get(detected)
        result = CandidateResult('response', response=CurrentResponse(url=current['url'], content_type=current['content_type'],
            status=current['status'], body=current['body'].encode(), access=access, partial=current.get('partial', False),
            context_changed=current.get('context_changed', False), context_key=current.get('context_key')),
            diagnostic='access-'+access if access in {'challenge','login','authorization'} else None)
    else:
        reason = 'file-io' if kind == 'local_failure' else None
        if kind == 'failed' and value.get('diagnostic_code') == 'access-challenge':
            reason = 'access-challenge'
        result = CandidateResult(kind if kind in {'pending','failed','local_failure','cancelled','stale','expired'} else 'failed',
            diagnostic=reason)
    # Never start the next candidate until this writer/output actually settled.
    files.cleanup(output)
    repository.record_download_output(reservation.download_token, None)
    reservation.output = None
    return result, None, ''


def _document_candidates(reservation, repository, candidate, response=None):
    """Use fixed article/reader Document access under the original body authority."""
    reader = reader_context(candidate, response.url) if response is not None else None
    if reader is None:
        article = candidate.target.article_url
        confirmed = urlsplit(article or '')
        current = urlsplit(response.url) if response is not None else confirmed
        if (article is None or (current.scheme,current.netloc,current.path) != (confirmed.scheme,confirmed.netloc,confirmed.path)
                or confirmed.hostname not in {'www.sciencedirect.com', 'sciencedirect.com'}):
            return None
    from allfold.application.pdf_discovery import PdfDiscoveryContext
    from allfold.application.document_metadata import read_document_pdf_clues, DocumentMetadataFailed
    context = PdfDiscoveryContext(reservation, repository)
    blocked = False
    try:
        try:
            parsed = read_document_pdf_clues(context,
                confirmed_article_url=candidate.target.article_url, reader=reader)
        except DocumentMetadataFailed:
            parsed = None
            value = context.native[-1].result() if context.native else None
            diagnostic = value.get('diagnostic', {}) if isinstance(value, dict) else {}
            if isinstance(diagnostic, dict):
                blocked = (diagnostic.get('code') in {'verification_page','content_access_blocked','site_restricted'}
                    or diagnostic.get('code') == 'http_error' and diagnostic.get('status') in {401,403,407,418,429})
    finally:
        try:
            context.close_native()
        except BaseException as error:
            from allfold.application.collection_runtime import _CleanupUnconfirmed
            reservation.registry.fail_reservation(reservation, phase='body-reader-cleanup', error=error,
                unconfirmed=isinstance(error, _CleanupUnconfirmed))
            raise
    if time.monotonic() >= reservation.deadline:
        raise TimeoutError('Body reader parent deadline expired')
    context.guard()
    if blocked:
        raise PdfSourceReadError('Reader access refused', diagnostic='access-blocked')
    return replace(parsed, current_candidates=tuple(replace(candidate, url=item.url, reader_kind=item.reader_kind,
        referer=item.referer, action=item.action, credential=None, accept=None)
        for item in parsed.current_candidates)) if parsed is not None else None


class _BodyDiscoveryIO:
    """Reuse scoped PDF/API IO and the established live reader under this owner."""
    def __init__(self, reservation, repository):
        from allfold.application.pdf_discovery import PdfDiscoveryContext
        from allfold.pdf_http import PdfDiscoveryIO
        self.reservation, self.repository = reservation, repository
        self.context = PdfDiscoveryContext(reservation, repository)
        self.io = PdfDiscoveryIO(None, document_context=self.context)
        self.resources = ExitStack()
        self.oce_authority = None
        self.challenge_endpoints = set()
        self.openalex_available = reservation.body_request.candidates is None

    def _http(self):
        if self.io.http is None:
            http, openalex = self.resources.enter_context(self.reservation.registry.factory.open_pdf_discovery(
                cancel_event=self.reservation.cancel_event, request_guard=self.context.guard,
                deadline=self.reservation.deadline, http_options=self.reservation.body_request.http_options))
            self.io.http, self.io._openalex = http, openalex
        return self.io

    def query_missing(self, *args):
        yield from self._http().query_missing(*args)

    def openalex(self, doi):
        from allfold.application.collection_runtime import BodyAccessRevoked
        authority = self.reservation.body_request.provider_authority
        if isinstance(authority, Exception):
            raise PdfSourceReadError('Optional PDF Provider is unavailable', diagnostic='provider-unavailable') from None
        try:
            with _access_operation(self.reservation, self.repository, authority) as operation:
                clients = ExitStack()
                try:
                    _http, openalex = clients.enter_context(self.reservation.registry.factory.open_pdf_discovery(cancel_event=operation.cancel_event,
                        request_guard=operation.guard, deadline=operation.deadline,
                        http_options=self.reservation.body_request.http_options))
                    raw = openalex.get_work_by_doi(doi)
                    operation.guard()
                    return raw
                finally:
                    self._close_clients(clients)
        except (BodyAccessRevoked, Cancelled):
            self.reservation.registry._guard(self.reservation, self.repository)
            raise PdfSourceReadError('Optional PDF Provider is unavailable', diagnostic='provider-unavailable') from None

    def document(self, target):
        return self._read(lambda operation, io: io.document(target))

    def reader(self, candidate, response):
        # The same live parser also handles a ScienceDirect article fallback.
        def read(operation, _io):
            parsed = _document_candidates(operation, self.repository, candidate, response)
            if (parsed is not None or response.access != 'challenge' or candidate.action
                    or candidate.credential or candidate.recover_access):
                return parsed
            actual = urlsplit(response.url)
            # Signed query variants of the same endpoint must not reopen an
            # unchanged access barrier within this Download and Service scope.
            endpoint = (actual.scheme, actual.netloc, actual.path, operation.service_id)
            if endpoint in self.challenge_endpoints or reader_context(candidate, response.url):
                return None
            self.challenge_endpoints.add(endpoint)
            # Recovery and transfer share one native owner so the actual Page
            # context is available to the succeeding Session GET.
            return SimpleNamespace(current_candidates=(replace(candidate, url=response.url,
                reader_kind=None, recover_access=True),))
        return self._read(read, candidate.access)

    def oce_access(self, candidate, response):
        if response.status != 200 or access_limited(response):
            return False
        from allfold.application.task_authority import ServiceAccessUnavailable
        request = self.reservation.body_request
        if request.service_reason:
            raise PdfSourceReadError('Institutional Reader needs an unambiguous saved Service',
                diagnostic=request.service_reason, service_id=request.service_id, service_ids=request.service_ids)
        if self.oce_authority is None:
            try:
                self.oce_authority = self.reservation.registry._authority(request.service_id, ())
            except ServiceAccessUnavailable as error:
                raise PdfSourceReadError('Institutional Reader access is unavailable',
                    diagnostic=error.diagnostic, service_id=request.service_id) from None
            except (OSError, ValueError, RuntimeError):
                raise PdfSourceReadError('Institutional Reader access changed',
                    diagnostic='service-invalidated', service_id=request.service_id) from None
        return self._read(lambda operation, io: io.oce_access(candidate, response), self.oce_authority)

    def oce_reader(self, candidate, response):
        parsed = self._read(lambda operation, io: io.oce_reader(candidate, response), self.oce_authority)
        if parsed is not None:
            # The retained institution capability also owns its observed PDF,
            # including HTTPS/CDN continuations. P5 starts independently.
            values = parsed.current_candidates
            if not values and parsed.reader_result is not None:
                navigation = parsed.reader_result
                values = (replace(candidate, url=navigation.url, referer=navigation.referer,
                    action=None, reader_kind=None),)
            parsed = replace(parsed, current_candidates=tuple(replace(candidate,
                url=item.url, referer=item.referer, action=item.action, reader_kind=item.reader_kind,
                access=self.oce_authority) for item in values))
        return parsed

    def _read(self, read, authority=None):
        from allfold.application.collection_runtime import BodyAccessRevoked, _CleanupUnconfirmed
        from allfold.application.pdf_discovery import PdfDiscoveryContext
        from allfold.pdf_http import PdfDiscoveryIO
        try:
            with _access_operation(self.reservation, self.repository, authority) as operation:
                context = PdfDiscoveryContext(operation, self.repository)
                try:
                    try:
                        parsed = read(operation, PdfDiscoveryIO(None, document_context=context))
                        context.guard()
                        return parsed
                    except PdfSourceReadError:
                        context.guard()
                        value = context.native[-1].result() if context.native else None
                        diagnostic = value.get('diagnostic', {}) if isinstance(value, dict) else {}
                        if isinstance(diagnostic, dict) and (diagnostic.get('code') in {
                                'verification_page', 'content_access_blocked', 'site_restricted'}
                                or diagnostic.get('code') == 'http_error' and diagnostic.get('status') in {401,403,407,418,429}):
                            raise PdfSourceReadError('Document access refused', diagnostic='access-blocked') from None
                        raise
                finally:
                    try:
                        context.close_native()
                    except BaseException as error:
                        self.reservation.registry.fail_reservation(self.reservation, phase='body-reader-cleanup', error=error,
                            unconfirmed=isinstance(error, _CleanupUnconfirmed))
                        raise
        except BodyAccessRevoked:
            self.reservation.registry._guard(self.reservation, self.repository)
            raise PdfSourceReadError('Institutional Reader access changed', diagnostic='service-invalidated',
                service_id=authority.service_id if authority else None) from None

    def close(self):
        from allfold.application.collection_runtime import _CleanupUnconfirmed
        try:
            self.context.close_native()
        except BaseException as error:
            self.reservation.registry.fail_reservation(self.reservation, phase='body-native-cleanup', error=error,
                unconfirmed=isinstance(error, _CleanupUnconfirmed))
        finally:
            self._close_clients(self.resources)

    def _close_clients(self, resources):
        try:
            resources.close()
        except BaseException as error:
            self.reservation.registry.fail_reservation(self.reservation, phase='discovery-client-cleanup', error=error)


def _run(reservation, request, progress):
    registry = reservation.registry
    result = BodyResult('failed')
    timer = threading.Timer(max(0, reservation.deadline-time.monotonic()),
        lambda: registry._cancel_target(reservation, 'expired'))
    timer.daemon = True
    timer.start()
    try:
        with registry._repository() as repository:
            try:
                registry._guard(reservation, repository)
                repository.mark_download_running(reservation.download_token)
                with ExitStack() as resources:
                    files = resources.enter_context(ManagedBodyFiles(registry.workspace, reservation.paper_id,
                        reservation.download_token.attempt, expected_workspace=registry._identity[0]))
                    io = _BodyDiscoveryIO(reservation, repository)
                    resources.callback(io.close)
                    options = request.http_options or {}
                    capabilities = frozenset(name for name, secret in dict(options.get('credentials', ())).items() if secret)
                    selected = PdfRuleInputs(request.target, credentials=capabilities)
                    transferred = {}
                    def consume(candidate):
                        nonlocal result
                        candidate_result, output, final_url = _consume_access(reservation, repository, files, candidate, progress)
                        result = BodyResult(candidate_result.kind, candidate_result=candidate_result)
                        if output is not None:
                            transferred.update(output=output, final_url=final_url)
                        if candidate_result.pdf_type and candidate_result.transfer_complete:
                            timer.cancel()
                            timer.join()
                        return candidate_result
                    coordinator = PdfDiscovery(request.target, facts=request.facts, inputs=selected, io=io,
                        candidates=request.candidates, guard=lambda: registry._guard(reservation, repository),
                        cancel_event=reservation.cancel_event, deadline=reservation.deadline,
                        observe=lambda value: _record_source(reservation, value['stage'], value['rule'], value['reason'],
                            value['attempt'], origin=value['origin'], fallback=value['fallback'], service_id=value.get('service_id')))
                    discovery = coordinator.run(consume)
                    if discovery.status == 'transferred':
                        saved = complete_attempt(reservation, repository, files, transferred['output'],
                            source_url=_source_projection(transferred['final_url']), pdf_source=discovery.pdf_source,
                            fallback_used=discovery.fallback_used)
                        result = BodyResult('completed', saved, CandidateResult.pdf(transfer_complete=True))
                        _record_source(reservation, discovery.pdf_source, discovery.candidate.rule_id, 'transferred',
                            coordinator.source_attempt,
                            origin=transferred['final_url'], fallback=discovery.fallback_used)
                    elif discovery.status in {'cancelled', 'stale', 'expired', 'local-failure'}:
                        result = BodyResult(discovery.status.replace('-', '_'), candidate_result=result.candidate_result)
                    elif discovery.status == 'exhausted' and any(reason == 'native-unsupported'
                            for _, _, reason in discovery.diagnostics):
                        result = BodyResult('failed', candidate_result=CandidateResult('skipped', diagnostic='native-unsupported'))
                    elif result.status == 'skipped':
                        result = BodyResult('failed', candidate_result=result.candidate_result)
                    else:
                        reason = (result.candidate_result.diagnostic if result.candidate_result else None) or next((code
                            for _, _, code in reversed(discovery.diagnostics) if code not in {'partial-response','no-pdf-entry'}), None)
                        result = BodyResult('failed', candidate_result=CandidateResult.failed(reason or 'no-pdf-candidates'))
            except (TimeoutError, ProviderBudgetExceeded):
                result = BodyResult('expired')
            except Cancelled:
                result = BodyResult('expired' if time.monotonic() >= reservation.deadline else 'cancelled')
            except StaleWriteError:
                result = BodyResult('cancelled' if reservation.cancel_event.is_set() else 'stale')
            except InvalidPaperState:
                result = BodyResult('cancelled' if reservation.cancel_event.is_set() or registry.stopped else 'stale')
            except FileExistsError:
                result = BodyResult('local_failure', candidate_result=CandidateResult('local_failure', diagnostic='path-conflict'))
            except LibraryError:
                if result.status != 'completed':
                    result = BodyResult('local_failure', candidate_result=CandidateResult('local_failure', diagnostic='storage-error'))
            except Exception:
                if result.status != 'completed':
                    result = BodyResult('local_failure', candidate_result=CandidateResult('local_failure', diagnostic='local-completion'))
            finally:
                # Native uncertainty is resource uncertainty, unlike a closed
                # output whose unlink failed. Preserve occupancy in the former.
                native = getattr(reservation, 'native_future', None)
                if native is not None and (not native.done() or native.cancelled()):
                    error = RuntimeError('Native body resource settlement is unconfirmed')
                    registry.fail_reservation(reservation, phase='body-native-cleanup', error=error, unconfirmed=True)
                    raise error
                if result.status != 'completed' and not reservation.cleanup_failed:
                    cleanup_reason = None
                    if reservation.output is not None:
                        try:
                            with ManagedBodyFiles(registry.workspace, reservation.paper_id, reservation.download_token.attempt,
                                    expected_workspace=registry._identity[0]) as files:
                                files.cleanup(reservation.output)
                            repository.record_download_output(reservation.download_token, None)
                            reservation.output = None
                        except (OSError, ValueError, LibraryError) as error:
                            registry._fault(reservation, 'body-file-cleanup', error)
                            cleanup_reason = 'output-cleanup'
                            result = BodyResult('local_failure', candidate_result=CandidateResult('local_failure', diagnostic=cleanup_reason))
                    repository.finish_download(reservation.download_token,
                        status='cancelled' if result.status in {'cancelled','stale','expired'} else 'failed',
                        reason=cleanup_reason or (result.candidate_result.diagnostic if result.candidate_result else None) or result.status)
    except Exception as error:
        if result.status != 'completed':
            raise
        registry._fault(reservation, 'body-owner-cleanup', error)
    finally:
        timer.cancel()
        timer.join()
        if reservation.browser_owner is not None and not reservation.cleanup_failed:
            try:
                registry.browser_lock.release(reservation.browser_owner)
                reservation.browser_owner = None
            except BaseException as error:
                registry.fail_reservation(reservation, phase='body-owner-cleanup', error=error)
    return result


def _settled(reservation, actual):
    registry = reservation.registry
    if reservation.future.done():
        return
    try:
        result = actual.result()
    except BaseException as error:
        registry.fail_reservation(reservation, phase='body-terminal-write', error=error)
        if not reservation.cleanup_failed:
            with registry.paper_gate():
                if registry._reservations.get(reservation.paper_id) is reservation:
                    registry._ended_attempts[reservation.paper_id] = reservation.download_token
        result, failure = None, error
    else:
        failure = None
    finally:
        reservation.cleanup_ended = True
        if not reservation.cleanup_failed:
            try:
                registry.release(reservation)
            except Exception as error:
                registry._fault(reservation, 'body-owner-cleanup', error)
        else:
            with registry._settled_condition:
                registry._settled_condition.notify_all()
    if failure is not None:
        reservation.future.set_exception(failure)
    else:
        reservation.future.set_result(result)


def _discard(reservation, reason):
    with reservation.registry._repository() as repository:
        repository.finish_download(reservation.download_token, status='cancelled', reason=reason)
    return BodyResult('expired' if reason == 'expired' else 'cancelled')


def submit_body_download(host, paper, *, candidates=None, service_id=None, deadline=None, progress=None,
                         target=None, facts=(), http_options=None, provider_authority=None, service_reason=None, service_ids=()):
    """Trusted composition entry; public callers supply identities through the service."""
    registry = host.current()
    if registry.workspace_id != paper.workspace_id:
        raise StaleWriteError('Download belongs to another Workspace')
    # Local content and accepted work win before target validation, access or gate.
    with registry.paper_gate():
        with registry._repository() as repository:
            current = repository.get(paper.id)
            if current.body is not None:
                return BodyResult('completed', current)
        existing = registry._reservations.get(paper.id)
        if existing is not None and existing.kind == 'body':
            return existing
    primary = paper.primary_identity
    direct = tuple((item.namespace, item.value) for item in paper.identities)
    if candidates is not None:
        candidates = tuple(candidates)
        if not candidates or sum(len(item.url.encode()) for item in candidates) > 1048576:
            raise ValueError('Confirmed candidates must fit the task memory budget')
        target = candidates[0].target
        for candidate in candidates:
            if (not isinstance(candidate, PdfCandidate) or candidate.target != target
                    or candidate.target.paper_id != str(paper.id)
                    or candidate.target.identity_doi != (primary.value if primary.namespace == 'doi' else None)
                    or candidate.target.direct_identities != direct
                    or candidate.target.content_type not in SUPPORTED_PDF_TARGET_TYPES):
                raise ValueError('Candidate must bind the original saved Paper identity')
    if (not isinstance(target, PdfTarget) or target.paper_id != str(paper.id) or target.direct_identities != direct
            or target.content_type not in SUPPORTED_PDF_TARGET_TYPES):
        raise ValueError('Original saved Paper target is required')
    if registry.bridge is None or not registry.bridge.connected:
        raise InvalidPaperState('Selected Session bridge is unavailable')
    reservation = registry.reserve(paper.id, kind='body', expected_token=paper.token,
        service_id=service_id, deadline=registry._deadline(deadline),
        body_request=_BodyRequest(primary, candidates, progress, target, tuple(facts), http_options, direct, provider_authority,
            paper.download.token.attempt if paper.download else 0, service_id,
            service_reason or ('service-unassigned' if service_id is None else None),
            tuple(service_ids or ((service_id,) if service_id else ()))))
    if isinstance(reservation, PaperRecord):
        return BodyResult('completed', reservation)
    with registry.paper_gate():
        if reservation.scheduled is not None:
            return reservation
        reservation.progress = dict(received_bytes=0, total_bytes=None, sequence=0)
        reservation.deadline_ms = int((time.time()+reservation.deadline-time.monotonic())*1000)
        def report(value):
            # Only finite byte observations cross into public projection. Native
            # ownership facts, URLs and credentials remain inside the transport.
            if not isinstance(value, dict):
                return
            with registry.paper_gate():
                if registry._reservations.get(paper.id) is not reservation or reservation.future.done():
                    return
                received, total = value.get('received_bytes'), value.get('total_bytes')
                if type(received) is int and 0 <= received <= 9007199254740991:
                    reservation.progress['received_bytes'] = max(reservation.progress['received_bytes'], received)
                if type(total) is int and 0 < total <= 9007199254740991:
                    reservation.progress['total_bytes'] = total
                reservation.progress['sequence'] += 1
            if progress is not None:
                progress(value)
        try:
            reservation.scheduled = registry._scheduler.submit(reservation.service_id,
                lambda: _run(reservation, reservation.body_request, report), cancel_event=reservation.cancel_event,
                deadline=reservation.deadline, discarded=lambda reason: _discard(reservation, reason))
            reservation.scheduled.add_done_callback(lambda actual: _settled(reservation, actual))
        except BaseException:
            actual = Future()
            try:
                result = _discard(reservation, 'submission-failed')
            except BaseException as error:
                actual.set_exception(error)
                _settled(reservation, actual)
                raise
            actual.set_result(result)
            _settled(reservation, actual)
            raise
    return reservation


def body_qualification(paper, *, occupied=False, connected=False, available=True, ended=None):
    """The same finite Paper rule drives both UI and server admission."""
    if paper.body is not None:
        return False, 'local-body'
    if paper.excluded:
        return False, 'excluded'
    if paper.metadata is None or paper.primary_identity is None:
        return False, 'metadata-required'
    if paper.metadata.publication_type == 'preprint':
        return False, 'unsupported-content-type'
    if (occupied or paper.collection is not None and paper.collection.active and ended != 'collection'
            or paper.download is not None and paper.download.active and ended != 'body'):
        return False, 'paper-busy'
    if not connected or not available:
        return False, 'access-unavailable'
    return True, None


def saved_pdf_target(paper):
    """Only direct identities and target-qualified source facts may route a body."""
    from allfold.pdf_facts import discovery_target_matches
    direct = tuple((item.namespace, item.value) for item in paper.identities)
    primary = paper.primary_identity
    doi = primary.value if primary is not None and primary.namespace == 'doi' else None
    facts = tuple(fact for fact in paper.metadata.discovery_facts if discovery_target_matches(fact, direct)
        and not (doi and fact.target_doi and fact.target_doi != doi))
    article = next((fact.landing_url for fact in facts if fact.source == 'document' and fact.landing_url), None)
    if article is None:
        article = next((link.url for fact in facts if fact.source == 'crossref' for link in fact.links if link.kind == 'landing'), None)
    if article is None:
        article = next((fact.landing_url for fact in facts if fact.landing_url), None)
    if article and doi:
        import re
        from urllib.parse import unquote
        from allfold.identifiers import valid_doi
        spelling = re.search(r'10\.[0-9]{4,9}/.+', unquote(urlsplit(article).path))
        if spelling and valid_doi(spelling[0]) == doi:
            doi = spelling[0]
    # Preprint source relationships and arbitrary MetadataSource URLs are not
    # authoritative article targets. P5 exact Work facts remain independent.
    content_type = {'journal':'journal-article', 'conference':'conference-paper', 'preprint':'preprint'}.get(paper.metadata.publication_type, 'unknown')
    return PdfTarget(str(paper.id), doi=doi, article_url=article, content_type=content_type,
        direct_identities=direct), facts


class BodyDownloadService:
    """Identity-only public composition; no renderer-supplied network capability."""
    def __init__(self, host, *, local_body=None, http_options=None):
        self.host, self.local_body, self.http_options = host, local_body, http_options

    def _service(self, paper):
        from allfold.application.workspace import paper_service_assignment, journals_for_paper
        from allfold.config import load_config
        journals = load_config(self.host.config_path).journals
        service_id, assignment = paper_service_assignment(paper.metadata, journals)
        related = tuple(sorted({journal.access_service_id for journal in journals_for_paper(paper.metadata, journals)
            if journal.access_service_id}))
        return service_id, {'ambiguous': 'service-ambiguous', 'unassigned': 'service-unassigned'}.get(assignment), related

    def projection(self, paper, *, cleanup_pending=False):
        registry = self.host.peek()
        owner = None
        if registry is not None and registry.workspace_id == paper.workspace_id:
            with registry.paper_gate():
                item = registry._reservations.get(paper.id)
                if item is not None and item.kind == 'body' and paper.download is not None and item.download_token == paper.download.token:
                    owner = item
        access = not self.host.changing and registry is not None and not registry.stopped
        ended = registry.ended_kind(paper) if registry else None
        permitted, reason = body_qualification(paper, occupied=cleanup_pending, ended=ended,
            connected=bool(self.host.bridge and self.host.bridge.connected), available=access)
        saved = paper.download
        active = owner is not None
        warning = None
        if registry is not None and saved and not active:
            messages = {'body-file-cleanup':'下载已结束，但临时文件清理失败。',
                'body-native-cleanup':'下载已结束，但辅助页面清理失败。',
                'discovery-client-cleanup':'下载已结束，但客户端关闭时发生错误。',
                'body-owner-cleanup':'下载已结束，但浏览器占用释放通知失败。'}
            warning = next((messages[fault['phase']] for fault in reversed(registry.faults)
                if fault['paper_id'] == str(paper.id) and fault['attempt'] == saved.token.attempt
                and fault['phase'] in messages), None)
        progress = dict(getattr(owner, 'progress', {})) if owner else {}
        observations = []
        if registry is not None and saved:
            with registry.paper_gate():
                records = [item for item in registry.body_observations
                    if item['paper_id'] == str(paper.id) and item['attempt'] == saved.token.attempt]
            for index, item in enumerate(records):
                observations.append({key: value for key, value in item.items() if key not in {'paper_id','attempt'}} | {
                    'subsequent_attempted': any(later['pdf_attempt'] > item['pdf_attempt'] for later in records[index+1:])})
        return dict(status='failed' if ended == 'body' else saved.status if saved else 'not_started',
            attempt=saved.token.attempt if saved else 0, reason='storage-error' if ended == 'body' else saved.reason if saved else None,
            warning=warning, source_observations=observations,
            active=active, cleaning_up=bool(active and (owner.cancel_event.is_set() or saved and not saved.active)),
            available=permitted, unavailable_reason=reason,
            task_id=owner.task_id if owner else None,
            deadline_ms=getattr(owner, 'deadline_ms', None) if owner else None,
            cancel_available=bool(active and not owner.cancel_event.is_set() and not owner.cleanup_failed),
            received_bytes=progress.get('received_bytes', 0), total_bytes=progress.get('total_bytes'),
            progress_sequence=progress.get('sequence', 0),
            pdf_source=paper.body.pdf_source if paper.body else None,
            fallback_used=paper.body.fallback_used if paper.body else None,
            qualification=dict(metadata_generation=paper.metadata_generation,
                operation_generation=paper.operation_generation, body_generation=paper.body_generation,
                attempt=saved.token.attempt if saved else 0))

    def start(self, paper_id, workspace_id, *, qualification=None):
        from uuid import UUID
        registry = self.host.current()
        if registry.workspace_id != UUID(str(workspace_id)):
            raise StaleWriteError('Different Workspace')
        with registry.paper_gate():
            registry.settle_ended(paper_id)
            with registry._repository() as repository:
                paper = repository.get(paper_id)
            if paper.body is not None:
                if qualification is not None and qualification.get('body_generation') != paper.body_generation:
                    raise StaleWriteError('Original local body changed')
                local = True
            else:
                local = False
                existing = registry._reservations.get(paper.id)
                if existing is not None and existing.kind == 'body':
                    return existing
                permitted, _ = body_qualification(paper, occupied=registry.busy(paper.id),
                    connected=bool(registry.bridge and registry.bridge.connected), available=not self.host.changing and not registry.stopped)
                if not permitted:
                    raise InvalidPaperState('Paper is unavailable for Download')
                expected = dict(metadata_generation=paper.metadata_generation,
                    operation_generation=paper.operation_generation, body_generation=paper.body_generation,
                    attempt=paper.download.token.attempt if paper.download else 0)
                if qualification != expected:
                    raise StaleWriteError('Original Download qualification changed')
        if local:
            return self.local_body(paper, action='open') if self.local_body is not None else BodyResult('local-body', paper)
        service_id, service_reason, service_ids = self._service(paper)
        # Keep the original optional Provider epoch without making an earlier
        # successful P1/native path depend on that unused credential.
        try:
            provider_authority = self.host._capture_authority(None, ('openalex',))
        except (OSError, ValueError, RuntimeError, LibraryError) as error:
            provider_authority = error
        target, facts = saved_pdf_target(paper)
        return submit_body_download(self.host, paper, target=target, facts=facts, service_id=service_id,
            service_reason=service_reason, service_ids=service_ids, provider_authority=provider_authority, http_options=self.http_options)

    def cancel(self, paper_id, workspace_id, task_id, attempt):
        from uuid import UUID
        registry = self.host.peek()
        if registry is None or registry.workspace_id != UUID(str(workspace_id)):
            return False
        with registry.paper_gate():
            owner = registry._reservations.get(UUID(str(paper_id)))
            if (owner is None or owner.kind != 'body' or owner.task_id != task_id
                    or owner.download_token.attempt != attempt):
                return False
            accepted = registry._prepare_cancel_target(owner)
        if accepted:
            registry.signal_cancel_targets((owner,))
        return accepted
