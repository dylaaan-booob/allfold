"""One Paper owner coordinates lazy discovery, Session transport and completion."""
from concurrent.futures import Future
from contextlib import ExitStack
from dataclasses import dataclass, replace, field
import threading
import time
from urllib.parse import parse_qs, urldefrag, urlsplit, urlunsplit

from allfold.application.browser_services import browser_workspace_identity
from allfold.pdf_discovery import CandidateResult, CurrentResponse, PdfDiscovery, SUPPORTED_PDF_TARGET_TYPES
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


@dataclass(frozen=True)
class BodyResult:
    status: str
    paper: PaperRecord | None = None
    candidate_result: CandidateResult | None = None


class _BodyAccessBlocked(Exception):
    """A verified native access refusal is terminal, not an empty source."""


def complete_attempt(reservation, repository, files, output, *, source_url=None, pdf_source=None, fallback_used=None):
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
        # Short inode qualification at the final boundary, independent of PDF
        # content/length validation and after any publication interleaving.
        size_bytes = files.verify_published(output)
        return repository.complete_download(reservation.download_token, size_bytes=size_bytes, source_url=source_url,
            pdf_source=pdf_source, fallback_used=fallback_used, direct_identities=reservation.body_request.direct)


def _source_projection(url):
    # Signed/session request spelling stays operation-local, never in provenance.
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, '/', '', ''))[:2048]


def _consume(reservation, repository, files, candidate, progress):
    registry = reservation.registry
    registry._guard(reservation, repository)
    try:
        from allfold.application.native_body_downloads import native_applicable, transfer_native
    except ImportError:
        native_applicable = lambda value: bool(value.action)
        transfer_native = None
    if native_applicable(candidate):
        if transfer_native is None:
            return CandidateResult.failed('native-unavailable'), None, ''
        native = transfer_native(reservation, repository, files, candidate, progress)
        if not (native.result.pdf_type and native.result.transfer_complete) and native.output is not None:
            files.cleanup(native.output)
            repository.record_download_output(reservation.download_token, None)
            return native.result, None, native.final_url
        return native.result, native.output, native.final_url
    if candidate.action:
        return CandidateResult.failed('native-unavailable'), None, ''
    credential = None
    if candidate.credential:
        from allfold.pdf_http import _API_SCOPES
        secret = dict((reservation.body_request.http_options or {}).get('credentials', ())).get(candidate.credential)
        scope = _API_SCOPES.get(candidate.credential)
        url = urlsplit(candidate.url)
        if not secret or not scope:
            return CandidateResult.failed('credential-unavailable'), None, ''
        if (url.scheme != 'https' or url.hostname != scope[0] or (url.port or 443) != 443
                or not url.path.startswith(scope[1])):
            return CandidateResult.failed('credential-scope'), None, ''
        credential = dict(kind=candidate.credential, value=secret)
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
    if credential is not None:
        payload['pdf_credential'] = credential
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
        result = CandidateResult('response', response=CurrentResponse(url=current['url'], content_type=current['content_type'],
            status=current['status'], body=current['body'].encode(), access=access),
            diagnostic='access-'+access if access in {'challenge','login','authorization'} else None)
    else:
        result = CandidateResult(kind if kind in {'pending','failed','local_failure','cancelled','stale','expired'} else 'failed',
            diagnostic='file-io' if kind=='local_failure' else None)
    # Never start the next candidate until this writer/output actually settled.
    files.cleanup(output)
    repository.record_download_output(reservation.download_token, None)
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
            return ()
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
                blocked = (diagnostic.get('code') in {'verification_page','content_access_blocked','site_restricted',
                        'article_identity_unconfirmed','article_identity_conflict'}
                    or diagnostic.get('code') == 'http_error' and diagnostic.get('status') in {401,403,407,418,429})
    finally:
        try:
            context.close_native()
        except BaseException as error:
            reservation.registry.fail_reservation(reservation, phase='body-reader-cleanup', error=error)
            raise
    if time.monotonic() >= reservation.deadline:
        raise TimeoutError('Body reader parent deadline expired')
    context.guard()
    if blocked:
        raise _BodyAccessBlocked()
    return tuple(replace(candidate, url=item.url, reader_kind=item.reader_kind,
        referer=item.referer, action=item.action, credential=None, accept=None)
        for item in parsed.current_candidates) if parsed is not None else ()


class _BodyDiscoveryIO:
    """Reuse scoped PDF/API IO and the established live reader under this owner."""
    def __init__(self, reservation, repository):
        from allfold.application.pdf_discovery import PdfDiscoveryContext
        from allfold.pdf_http import PdfDiscoveryIO
        self.reservation, self.repository = reservation, repository
        self.context = PdfDiscoveryContext(reservation, repository)
        self.io = PdfDiscoveryIO(None, document_context=self.context)
        self.resources = ExitStack()
        self.prepared = set()
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
        authority = self.reservation.body_request.provider_authority
        if isinstance(authority, Exception):
            raise InvalidPaperState('Optional PDF Provider is unavailable') from None
        if authority is not None:
            authority.verify()
            with self.reservation.registry.paper_gate():
                self.reservation.registry._check_admission(authority)
                self.reservation.providers = ('openalex',)
                self.reservation.pdf_provider_authority = authority
        return self._http().openalex(doi)

    def document(self, target):
        return self._read(lambda: self.io.document(target))

    def reader(self, candidate, response):
        # The same live parser also handles a ScienceDirect article fallback.
        values = _document_candidates(self.reservation, self.repository, candidate, response)
        if values:
            from types import SimpleNamespace
            return SimpleNamespace(current_candidates=values)
        return None

    def _read(self, read):
        from allfold.pdf_discovery import PdfSourceReadError
        try:
            return read()
        except PdfSourceReadError:
            value = self.context.native[-1].result() if self.context.native else None
            diagnostic = value.get('diagnostic', {}) if isinstance(value, dict) else {}
            if isinstance(diagnostic, dict) and (diagnostic.get('code') in {
                    'verification_page', 'content_access_blocked', 'site_restricted',
                    'article_identity_unconfirmed', 'article_identity_conflict'}
                    or diagnostic.get('code') == 'http_error' and diagnostic.get('status') in {401,403,407,418,429}):
                raise _BodyAccessBlocked() from None
            raise

    def prepare(self, candidate):
        try:
            from allfold.application.native_body_downloads import native_applicable
            if native_applicable(candidate):
                return ()
        except ImportError:
            pass
        key = (urldefrag(candidate.url)[0], candidate.action)
        reader = reader_context(candidate)
        if (reader and reader['platform'] == 'sciencedirect' and candidate.target.article_url
                and not candidate.action and not candidate.credential
                and not parse_qs(urlsplit(candidate.url).query).get('md5') and key not in self.prepared):
            self.prepared.add(key)
            return _document_candidates(self.reservation, self.repository, candidate)
        return ()

    def close(self):
        try:
            self.context.close_native()
        except BaseException as error:
            self.reservation.registry.fail_reservation(self.reservation, phase='body-native-cleanup', error=error)
            raise
        finally:
            try:
                self.resources.close()
            except BaseException as error:
                self.reservation.registry.fail_reservation(self.reservation, phase='discovery-client-cleanup', error=error)
                raise


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
                        candidate_result, output, final_url = _consume(reservation, repository, files, candidate, progress)
                        result = BodyResult(candidate_result.kind, candidate_result=candidate_result)
                        if output is not None:
                            transferred.update(output=output, final_url=final_url)
                        return candidate_result
                    discovery = PdfDiscovery(request.target, facts=request.facts, inputs=selected, io=io,
                        candidates=request.candidates, guard=lambda: registry._guard(reservation, repository),
                        cancel_event=reservation.cancel_event, deadline=reservation.deadline, stop_on_access=True).run(consume)
                    if discovery.status == 'transferred':
                        saved = complete_attempt(reservation, repository, files, transferred['output'],
                            source_url=_source_projection(transferred['final_url']), pdf_source=discovery.pdf_source,
                            fallback_used=discovery.fallback_used)
                        result = BodyResult('completed', saved, CandidateResult.pdf(transfer_complete=True))
                    elif discovery.status in {'cancelled', 'stale', 'expired', 'local-failure'}:
                        result = BodyResult(discovery.status.replace('-', '_'), candidate_result=result.candidate_result)
            except _BodyAccessBlocked:
                result = BodyResult('failed', candidate_result=CandidateResult.failed('access-blocked'))
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


def submit_body_download(host, paper, *, candidates=None, service_id=None, deadline=None, progress=None,
                         target=None, facts=(), http_options=None, provider_authority=None):
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
        if not 1 <= len(candidates) <= 16:
            raise ValueError('A bounded set of confirmed candidates is required')
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
            paper.download.token.attempt if paper.download else 0))
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
            _discard(reservation, 'submission-failed')
            registry.release(reservation)
            raise
    return reservation


def body_qualification(paper, *, occupied=False, connected=False, available=True):
    """The same finite Paper rule drives both UI and server admission."""
    if paper.body is not None:
        return False, 'local-body'
    if paper.excluded:
        return False, 'excluded'
    if paper.metadata is None or paper.primary_identity is None:
        return False, 'metadata-required'
    if paper.metadata.publication_type == 'preprint':
        return False, 'unsupported-content-type'
    if occupied or paper.collection is not None and paper.collection.active or paper.download is not None and paper.download.active:
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
        from allfold.application.workspace import paper_service_assignment
        from allfold.config import load_config
        service_id, assignment = paper_service_assignment(paper.metadata, load_config(self.host.config_path).journals)
        if assignment == 'ambiguous':
            raise InvalidPaperState('Paper Access Service assignment is ambiguous')
        return service_id

    def projection(self, paper, *, cleanup_pending=False):
        registry = self.host.peek()
        owner = None
        if registry is not None and registry.workspace_id == paper.workspace_id:
            with registry.paper_gate():
                item = registry._reservations.get(paper.id)
                if item is not None and item.kind == 'body' and paper.download is not None and item.download_token == paper.download.token:
                    owner = item
        access = not self.host.changing and registry is not None and not registry.stopped
        if access and paper.body is None and owner is None and paper.metadata is not None and not paper.excluded:
            try:
                self.host._capture_authority(self._service(paper), ())
            except (OSError, ValueError, RuntimeError, LibraryError):
                access = False
        permitted, reason = body_qualification(paper, occupied=cleanup_pending,
            connected=bool(self.host.bridge and self.host.bridge.connected), available=access)
        saved = paper.download
        active = owner is not None
        progress = dict(getattr(owner, 'progress', {})) if owner else {}
        return dict(status=saved.status if saved else 'not_started',
            attempt=saved.token.attempt if saved else 0, reason=saved.reason if saved else None,
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
            with registry._repository() as repository:
                paper = repository.get(paper_id)
            if paper.body is not None:
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
        service_id = self._service(paper)
        # Keep the original optional Provider epoch without making an earlier
        # successful P1/native path depend on that unused credential.
        try:
            provider_authority = self.host._capture_authority(None, ('openalex',))
        except (OSError, ValueError, RuntimeError, LibraryError) as error:
            provider_authority = error
        target, facts = saved_pdf_target(paper)
        return submit_body_download(self.host, paper, target=target, facts=facts, service_id=service_id,
            provider_authority=provider_authority, http_options=self.http_options)

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
