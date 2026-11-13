"""Captured read-only PDF discovery; production Download registration is deferred.

The existing Paper scheduler owns the actual worker Future. Its reservation is
released only after that worker's clients, native Futures and pages have settled.
No collection token, branch write, metadata emit or body association is involved.
"""
from concurrent.futures import Future
from contextlib import ExitStack
from dataclasses import replace
import threading
import time

from allfold.application.browser_services import browser_workspace_identity
from allfold.application.dynamic_dispatch import SettledFuture
from allfold.pdf_discovery import DiscoveryResult, PdfDiscovery
from allfold.pdf_http import PdfDiscoveryIO
from allfold.pdf_rules import PdfRuleInputs, PdfTarget
from allfold.persistence.paper_repository import InvalidPaperState, StaleWriteError
from allfold.providers.provider_http import Cancelled, ProviderBudgetExceeded


class PdfDiscoveryContext:
    """One worker's original WriteToken, connection and exact native ownership."""

    def __init__(self, reservation, repository):
        self.reservation, self.repository = reservation, repository
        self.registry = reservation.registry
        self.token = reservation.token
        self.cancel_event, self.deadline = reservation.cancel_event, reservation.deadline
        self.workflow_id, self.task_id = reservation.workflow_id, reservation.task_id
        self.native = []
        self.native_started = False

    def guard(self):
        self.registry._guard(self.reservation, self.repository)

    def read_paper(self):
        self.guard()
        with self.registry.paper_gate():
            self.registry._require_live(self.reservation)
            return self.registry._require_reservation(self.reservation, self.repository)

    def native_payload(self):
        self.guard()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('PDF discovery parent deadline expired')
        return self.reservation.authority.native_access().payload() | dict(
            workspace_identity=browser_workspace_identity(self.registry.workspace, self.registry._identity[0]),
            paper_id=str(self.token.paper_id), deadline_ms=int((time.time() + remaining) * 1000))

    def execute_native(self, action, data, *, progress=None):
        if action != 'extract_paper_pdf_clues':
            raise ValueError('Read-only discovery only permits the fixed PDF clues action')
        self.guard()
        if self.registry.bridge is None:
            raise RuntimeError('No native bridge is available')
        self.registry._ensure_browser_owner(self.reservation)
        with self.registry.paper_gate():
            self.registry._require_live(self.reservation)
            self.registry._require_reservation(self.reservation, self.repository)
            self.native_started = True
            future = self.registry.bridge.execute(action,
                dict(data) | {'workflow_id': self.workflow_id, 'task_id': self.task_id}, progress,
                verify_recovery=lambda: self.registry._guard(self.reservation))
            if not isinstance(future, Future):
                raise TypeError('Native discovery requires a real Future')
            self.native.append(future)
        protected = SettledFuture()
        def terminal(actual):
            try:
                protected.set_result(actual.result())
            except BaseException as error:
                protected.set_exception(error)
        future.add_done_callback(terminal)
        return protected

    def close_native(self):
        cancelled = False
        for future in self.native:
            try:
                future.result()  # A cancellation request never proves physical exit.
            except BaseException:
                cancelled = cancelled or future.cancelled()
        if cancelled:
            raise RuntimeError('Cancelled native Future does not prove resource settlement')
        if self.native_started:
            self.registry.bridge.execute('release_workflow_pages', {
                'workflow_id': self.workflow_id, 'task_id': self.task_id}).result()


def _run(reservation, target, facts, inputs, transfer, http_options):
    registry = reservation.registry
    resources, context = ExitStack(), None
    timer = threading.Timer(max(0, reservation.deadline - time.monotonic()),
        lambda: registry._cancel_target(reservation, 'expired'))
    timer.daemon = True
    timer.start()
    try:
        repository = resources.enter_context(registry._repository())
        context = PdfDiscoveryContext(reservation, repository)
        current = context.read_paper()
        primary = current.primary_identity
        current_doi = primary.value if primary is not None and primary.namespace == 'doi' else None
        if target.identity_doi != current_doi:
            raise StaleWriteError('Original Paper discovery target changed')
        if reservation.authority.service_scope is not None:
            registry._ensure_browser_owner(reservation)
            context.guard()
        http, openalex = resources.enter_context(registry.factory.open_pdf_discovery(
            cancel_event=context.cancel_event, request_guard=context.guard,
            deadline=context.deadline, http_options=http_options))
        # Capability names describe only credentials available in this task.
        selected = replace(inputs or PdfRuleInputs(target), credentials=http.capabilities)
        io = PdfDiscoveryIO(http, document_context=context if registry.bridge is not None else None,
            openalex_client=openalex)
        return PdfDiscovery(target, facts=facts, inputs=selected, io=io,
            guard=context.guard, cancel_event=context.cancel_event, deadline=context.deadline).run(
                lambda candidate: http.consume(candidate, transfer=transfer))
    except Cancelled:
        return DiscoveryResult('cancelled')
    except (ProviderBudgetExceeded, TimeoutError):
        return DiscoveryResult('expired')
    except StaleWriteError:
        return DiscoveryResult('stale')
    except InvalidPaperState:
        if reservation.cancel_event.is_set() or registry.stopped:
            return DiscoveryResult('cancelled')
        raise
    finally:
        try:
            if context is not None:
                try:
                    context.close_native()
                except BaseException as error:
                    registry.fail_reservation(reservation, phase='discovery-native-cleanup', error=error)
                    raise
        finally:
            try:
                try:
                    resources.close()
                except BaseException as error:
                    registry.fail_reservation(reservation, phase='discovery-client-cleanup', error=error)
                    raise
            finally:
                timer.cancel()
                timer.join()
                if reservation.browser_owner is not None and not reservation.cleanup_failed:
                    try:
                        registry.browser_lock.release(reservation.browser_owner)
                        reservation.browser_owner = None
                    except BaseException as error:
                        registry.fail_reservation(reservation, phase='discovery-owner-cleanup', error=error)
                        raise


def _settled(reservation, actual):
    result, error = None, None
    try:
        result = actual.result()
    except BaseException as failure:
        error = failure
    if not reservation.cleanup_failed:
        try:
            reservation.registry.release(reservation)
        except BaseException as failure:
            error = failure
    if error is not None:
        reservation.future.set_exception(error)
    else:
        reservation.future.set_result(result)


def submit_pdf_discovery(host, paper, *, target, service_id=None, deadline=None,
                         inputs=None, transfer=None, http_options=None):
    """Run the real discovery core for an already saved Paper, including completed.

    target is a caller-confirmed immutable identity/content target, never inferred
    from ordinary MetadataSource URLs. transfer is an optional downstream current-
    response consumer; absent it, a PDF response remains pending. This function
    does not expose a public Download action or install a production collector.
    """
    if not isinstance(target, PdfTarget) or target.paper_id != str(paper.id):
        raise ValueError('PDF target must belong to the original saved Paper')
    primary = paper.primary_identity
    doi = primary.value if primary is not None and primary.namespace == 'doi' else None
    if target.identity_doi != doi:
        raise ValueError('PDF target DOI must match the original saved Paper')
    if inputs is not None and inputs.target != target:
        raise ValueError('PDF inputs must belong to the original saved Paper')
    registry = host.current()
    if registry.workspace_id != paper.workspace_id:
        raise StaleWriteError('PDF discovery belongs to another Workspace')
    deadline = registry._deadline(deadline)
    reservation = registry.reserve(paper.id, expected_token=paper.token, service_id=service_id,
        providers=('openalex',), deadline=deadline)
    with registry.paper_gate():
        if reservation.scheduled is not None:
            raise InvalidPaperState('Another discovery task already owns this Paper')
        if reservation.token != paper.token or reservation.deadline != deadline:
            raise InvalidPaperState('Another operation owns this Paper reservation')
        try:
            registry._require_live(reservation)
            facts = tuple(paper.metadata.discovery_facts) if paper.metadata else ()
            reservation.scheduled = registry._scheduler.submit(service_id,
                lambda: _run(reservation, target, facts, inputs, transfer, http_options),
                cancel_event=reservation.cancel_event, deadline=deadline,
                discarded=lambda reason: DiscoveryResult('expired' if reason == 'expired' else 'cancelled'))
            reservation.scheduled.add_done_callback(lambda actual: _settled(reservation, actual))
        except BaseException:
            registry.release(reservation)
            raise
    return reservation
