"""Internal Session consumer: one host-visible attempt owns transfer and completion.

Only caller-confirmed candidates enter here. No HTTP route, automatic collection
hook or public Download UI is installed. WF10 can reuse complete_attempt with
its own original DownloadItem transport.
"""
from concurrent.futures import Future
from dataclasses import dataclass
import threading
import time
from urllib.parse import urlsplit, urlunsplit

from allfold.application.browser_services import browser_workspace_identity
from allfold.pdf_discovery import CandidateResult, CurrentResponse, SUPPORTED_PDF_TARGET_TYPES
from allfold.pdf_rules import PdfCandidate
from allfold.persistence.body_files import ManagedBodyFiles
from allfold.persistence.paper_repository import PaperRecord, StaleWriteError, InvalidPaperState, LibraryError


@dataclass(frozen=True)
class BodyResult:
    status: str
    paper: PaperRecord | None = None
    candidate_result: CandidateResult | None = None


def complete_attempt(reservation, repository, files, output, *, source_url=None):
    """Common closed-transport completion; original qualification at both commits.

    The caller must already have awaited the actual transport/writer terminal.
    No SQLite write transaction surrounds filesystem publication.
    """
    registry = reservation.registry
    registry._guard(reservation, repository)
    size_bytes = files.publish(output)
    registry._guard(reservation, repository)
    with registry.paper_gate():
        registry._require_live(reservation)
        return repository.complete_download(reservation.download_token, size_bytes=size_bytes, source_url=source_url)


def _source_projection(url):
    # Signed/session request spelling stays operation-local, never in provenance.
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, '/', '', ''))[:2048]


def _consume(reservation, repository, files, candidate, progress):
    registry = reservation.registry
    registry._guard(reservation, repository)
    if candidate.action or candidate.credential:
        # Action/POST and explicit API-secret candidates retain their native or
        # scoped API semantics. Do not emulate them with Session GET/header input.
        return CandidateResult('pending'), None
    output = files.prepare()
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
        workflow_id=reservation.workflow_id, task_id=reservation.task_id)
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
        registry.fail_reservation(reservation, phase='body-native-cleanup', error=error)
        raise error
    kind = value.get('kind')
    if (kind == 'pdf' and value.get('outcome') == 'stream_complete' and value.get('pdf_type') is True
            and value.get('transfer_complete') is True and tuple(value.get('output_file', ())) == output.file
            and type(value.get('size_bytes')) is int and value['size_bytes'] >= 0):
        saved = complete_attempt(reservation, repository, files, output,
            source_url=_source_projection(value['final_url']))
        return CandidateResult.pdf(transfer_complete=True), saved
    if kind == 'response':
        current = value.get('response', {})
        access=current.get('access')
        result = CandidateResult('response', response=CurrentResponse(url=current['url'], content_type=current['content_type'],
            status=current['status'], body=current['body'].encode(), access=access),
            diagnostic='access-'+access if access in {'challenge','login','authorization'} else None)
    else:
        result = CandidateResult(kind if kind in {'pending','failed','local_failure','cancelled','stale','expired'} else 'failed',
            diagnostic='file-io' if kind=='local_failure' else None)
    # Never start the next candidate until this writer/output actually settled.
    files.cleanup(output)
    repository.record_download_output(reservation.download_token, None)
    return result, None


def _run(reservation, candidates, progress):
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
                with ManagedBodyFiles(registry.workspace, reservation.paper_id, reservation.download_token.attempt,
                        expected_workspace=registry._identity[0]) as files:
                    for candidate in candidates:
                        candidate_result, saved = _consume(reservation, repository, files, candidate, progress)
                        if saved is not None:
                            # A committed body remains authoritative even if later
                            # notification, cancellation or the guard fails.
                            result = BodyResult('completed', saved, candidate_result)
                            break
                        result = BodyResult(candidate_result.kind, candidate_result=candidate_result)
                        if candidate_result.kind != 'failed':
                            break
            except TimeoutError:
                result = BodyResult('expired')
            except StaleWriteError:
                result = BodyResult('cancelled' if reservation.cancel_event.is_set() else 'stale')
            except InvalidPaperState:
                result = BodyResult('cancelled' if reservation.cancel_event.is_set() or registry.stopped else 'stale')
            except FileExistsError:
                result = BodyResult('local_failure', candidate_result=CandidateResult('local_failure', diagnostic='path-conflict'))
            except Exception:
                result = BodyResult('local_failure', candidate_result=CandidateResult('local_failure', diagnostic='local-completion'))
            finally:
                # Native uncertainty is resource uncertainty, unlike a closed
                # output whose unlink failed. Preserve occupancy in the former.
                native = getattr(reservation, 'native_future', None)
                if native is not None and (not native.done() or native.cancelled()):
                    error = RuntimeError('Native body resource settlement is unconfirmed')
                    registry.fail_reservation(reservation, phase='body-native-cleanup', error=error)
                    raise error
                current = repository.get(reservation.paper_id)
                if current.download.status == 'completed':
                    result = BodyResult('completed', current, CandidateResult.pdf(transfer_complete=True))
                elif not reservation.cleanup_failed:
                    cleanup_reason = None
                    if current.download.output is not None:
                        try:
                            with ManagedBodyFiles(registry.workspace, reservation.paper_id, reservation.download_token.attempt,
                                    expected_workspace=registry._identity[0]) as files:
                                files.cleanup(current.download.output)
                            repository.record_download_output(reservation.download_token, None)
                        except (OSError, ValueError, LibraryError):
                            result = BodyResult('local_failure')
                            cleanup_reason = 'output-cleanup'
                    repository.finish_download(reservation.download_token,
                        status='cancelled' if result.status in {'cancelled','stale','expired'} else 'failed',
                        reason=cleanup_reason or (result.candidate_result.diagnostic if result.candidate_result else None) or result.status)
    finally:
        timer.cancel()
        timer.join()
        if reservation.browser_owner is not None and not reservation.cleanup_failed:
            try:
                registry.browser_lock.release(reservation.browser_owner)
                reservation.browser_owner = None
            except BaseException as error:
                registry.fail_reservation(reservation, phase='body-owner-cleanup', error=error)
                raise
    return result


def _settled(reservation, actual):
    registry = reservation.registry
    try:
        result = actual.result()
        if not reservation.cleanup_failed:
            registry.release(reservation)
        reservation.future.set_result(result)
    except BaseException as error:
        registry.fail_reservation(reservation, phase='body-terminal-write', error=error)
        reservation.future.set_exception(error)


def _discard(reservation, reason):
    with reservation.registry._repository() as repository:
        repository.finish_download(reservation.download_token, status='cancelled', reason=reason)
    return BodyResult('expired' if reason == 'expired' else 'cancelled')


def submit_body_download(host, paper, *, candidates, service_id=None, deadline=None, progress=None):
    """Trusted internal entry. Caller confirms saved Paper and qualified candidates."""
    candidates = tuple(candidates)
    if not 1 <= len(candidates) <= 16:
        raise ValueError('A bounded set of confirmed candidates is required')
    primary = paper.primary_identity
    direct = tuple((item.namespace, item.value) for item in paper.identities)
    for candidate in candidates:
        if (not isinstance(candidate, PdfCandidate) or candidate.target.paper_id != str(paper.id)
                or candidate.target.identity_doi != (primary.value if primary.namespace == 'doi' else None)
                or candidate.target.direct_identities != direct
                or candidate.target.content_type not in SUPPORTED_PDF_TARGET_TYPES):
            raise ValueError('Candidate must bind the original saved Paper identity')
    registry = host.current()
    if registry.workspace_id != paper.workspace_id:
        raise StaleWriteError('Download belongs to another Workspace')
    with registry.paper_gate():
        existing = registry._reservations.get(paper.id)
        if existing is not None and existing.kind == 'body':
            return existing
        with registry._repository() as repository:
            current = repository.get(paper.id)
            if current.body is not None and not current.excluded:
                return BodyResult('completed', current)
    if registry.bridge is None or not registry.bridge.connected:
        raise InvalidPaperState('Selected Session bridge is unavailable')
    reservation = registry.reserve(paper.id, kind='body', expected_token=paper.token,
        service_id=service_id, deadline=registry._deadline(deadline))
    if isinstance(reservation, PaperRecord):
        return BodyResult('completed', reservation)
    with registry.paper_gate():
        if reservation.scheduled is not None:
            return reservation
        try:
            reservation.scheduled = registry._scheduler.submit(service_id,
                lambda: _run(reservation, candidates, progress), cancel_event=reservation.cancel_event,
                deadline=reservation.deadline, discarded=lambda reason: _discard(reservation, reason))
            reservation.scheduled.add_done_callback(lambda actual: _settled(reservation, actual))
        except BaseException:
            _discard(reservation, 'submission-failed')
            registry.release(reservation)
            raise
    return reservation
