"""One original browser response; source order and durable completion stay with its caller."""
from concurrent.futures import Future
from dataclasses import dataclass
import threading
import time

from allfold.application.browser_services import browser_workspace_identity
from allfold.application.document_metadata import _paper_identity
from allfold.pdf_discovery import CandidateResult
from allfold.pdf_responses import reader_context
from allfold.persistence.body_files import ManagedBodyFiles


@dataclass(frozen=True)
class NativeTransferResult:
    result: CandidateResult
    output: object = None
    final_url: str = ''


def native_applicable(candidate):
    """Select fixed action/current-reader contexts, never arbitrary URL likeness."""
    if candidate.credential:
        return False
    if candidate.action:
        return (candidate.action == 'refresh_form' and candidate.platform == 'microbiology'
            and candidate.rule_id == 'R059')
    if candidate.platform != 'sciencedirect' or candidate.rule_id != 'R024':
        return False
    return (reader_context(candidate) or {}).get('platform') == 'sciencedirect'


def transfer_native(reservation, repository, files, candidate, progress=None):
    """Await actual native item/page terminal, returning only proven completed output.

    Private inode observations are persisted immediately for scoped cleanup after
    interruption. They never enter the caller's public progress projection.
    """
    if not native_applicable(candidate):
        return NativeTransferResult(CandidateResult.failed('native-inapplicable'))
    registry = reservation.registry
    registry._guard(reservation, repository)
    pending = files.prepare_native()
    try:
        repository.record_download_output(reservation.download_token, pending)
    except BaseException:
        files.cleanup(pending)
        raise
    registry._ensure_browser_owner(reservation)
    remaining = reservation.deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Body parent deadline expired')
    paper = repository.get(reservation.paper_id)
    payload = reservation.authority.native_access().payload() | dict(
        workspace_identity=browser_workspace_identity(registry.workspace, registry._identity[0]),
        workspace_root=str(registry.workspace), paper_id=str(reservation.paper_id),
        identity=_paper_identity(paper, candidate.target.article_url),
        output=pending.model_dump(mode='json'), attempt=reservation.download_token.attempt,
        attempt_id=f'{reservation.lifecycle_id}:{reservation.download_token.attempt}',
        candidate=dict(url=candidate.url, action=candidate.action, platform=candidate.platform, rule_id=candidate.rule_id),
        deadline_ms=int((time.time() + remaining)*1000), workflow_id=reservation.workflow_id, task_id=reservation.task_id)
    observed, lock = {'output': pending, 'error': None}, threading.Lock()

    def native_progress(value):
        with lock:
            if 'native_output_file' in value:
                try:
                    pair = value['native_output_file']
                    if (not isinstance(pair, (tuple, list)) or len(pair) != 2
                            or any(type(item) is not int or item < 1 for item in pair)):
                        raise ValueError('Invalid native output observation')
                    current = observed['output']
                    if current.file is not None:
                        if tuple(pair) != current.file:
                            raise ValueError('Native output object changed')
                    else:
                        with ManagedBodyFiles(registry.workspace, reservation.paper_id, reservation.download_token.attempt,
                                expected_workspace=registry._identity[0]) as native_files:
                            actual = native_files.adopt_native(pending, pair)
                        with registry._repository() as progress_repository:
                            progress_repository.adopt_native_output(reservation.download_token, pending, actual)
                        observed['output'] = actual
                except BaseException as error:
                    observed['error'] = error
                    registry._cancel_target(reservation, 'native-output')
            if progress is not None:
                public = {key: value[key] for key in ('received_bytes', 'total_bytes') if key in value}
                if public:
                    progress(public)

    with registry.paper_gate():
        registry._require_live(reservation)
        repository.require_download(reservation.download_token)
        future = registry.bridge.execute('native_paper_body', payload, native_progress,
            verify_recovery=lambda: registry._guard(reservation))
        if not isinstance(future, Future):
            raise TypeError('Native body transport requires a real Future')
        reservation.native_future = future
    value = future.result()  # Actual item done and runTask source destruction; cancellation unlink can remain queued.
    if future.cancelled() or not isinstance(value, dict) or value.get('resource_closed') is False:
        error = RuntimeError('Native body resource settlement is unconfirmed')
        registry.fail_reservation(reservation, phase='body-native-cleanup', error=error)
        raise error
    with lock:
        output, error = observed['output'], observed['error']
    if error is not None:
        return NativeTransferResult(CandidateResult('local_failure', diagnostic='native-output'), output)
    if (value.get('kind') == 'pdf' and value.get('outcome') == 'native_complete'
            and value.get('pdf_type') is True and value.get('transfer_complete') is True
            and output.file is not None and tuple(value.get('output_file', ())) == output.file
            and isinstance(value.get('final_url'), str)):
        return NativeTransferResult(CandidateResult.pdf(transfer_complete=True), output, value['final_url'])
    kind = value.get('kind')
    if kind not in {'failed', 'local_failure', 'cancelled', 'stale', 'expired'}:
        kind = 'local_failure'
    diagnostic = value.get('diagnostic_code')
    if diagnostic not in {'interrupted', 'native-interrupted', 'native-output', 'entry-unavailable', 'native-action', 'access-blocked'}:
        diagnostic = 'native-action'
    return NativeTransferResult(CandidateResult(kind, diagnostic=diagnostic), output)
