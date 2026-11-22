"""Result-driven, lazy PDF source discovery, without collection or file writes.

The consumer owns the current transfer and reports its actual result. Merely
returning a response with a PDF Content-Type does not complete a transfer here.
IO capabilities are task-owned and are called only at their reached stage.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
import re
from hashlib import sha256
import time
from threading import Event
from urllib.parse import parse_qs, urldefrag, urlsplit

from allfold.pdf_facts import PdfDiscoveryFacts, crossref_pdf_refresh_required, discovery_target_matches
from allfold.pdf_catalog import API_CATALOG, RULE_CATALOG
from allfold.pdf_rules import (ARTICLE_TYPES, ATYPON_HOSTS, PdfCandidate, PdfRuleInputs, PdfTarget, KnownPdfUrl,
    content_platform, iter_p1_candidates, iter_p2_candidates, needs_p2_query)
from allfold.providers.provider_http import Cancelled, ProviderBudgetExceeded
from allfold.providers.openalex import OpenAlexNotFoundError, OpenAlexRequestError
from allfold.url_safety import normalize_public_http_url


SUPPORTED_PDF_TARGET_TYPES = ARTICLE_TYPES | {'unknown'}


def _request_key(candidate):
    # The same endpoint can receive a qualified request in a different access
    # context, including a Reader's observed Referer or its absence.
    return (sha256(urldefrag(candidate.url)[0].encode()).digest(),
            sha256((candidate.referer or '').encode()).digest(), candidate.action, candidate.credential,
            getattr(candidate.access, 'service_scope', None))


@dataclass(frozen=True)
class CurrentResponse:
    """One already-requested response; never a license to probe its URL."""
    url: str = field(repr=False)
    content_type: str
    body: bytes = field(repr=False, default=b'')
    status: int = 200
    access: str | None = None
    redirect_url: str | None = field(default=None, repr=False)
    partial: bool = False
    context_changed: bool = False
    context_key: str | None = field(default=None, repr=False)

    def __post_init__(self):
        if (not isinstance(self.url, str) or not normalize_public_http_url(self.url) or not isinstance(self.body, bytes)
                or type(self.partial) is not bool or type(self.context_changed) is not bool
                or self.context_key is not None and (not isinstance(self.context_key, str)
                    or not re.fullmatch(r'[a-f0-9]{64}', self.context_key))):
            raise ValueError('Invalid current response')
        if self.redirect_url is not None and not normalize_public_http_url(self.redirect_url):
            raise ValueError('Invalid current redirect')


@dataclass(frozen=True)
class CandidateResult:
    kind: str
    response: CurrentResponse | None = field(default=None, repr=False)
    pdf_type: bool = False
    transfer_complete: bool = False
    diagnostic: str | None = None

    def __post_init__(self):
        if self.kind not in {'pdf', 'failed', 'response', 'retry', 'pending', 'skipped', 'local_failure', 'cancelled', 'stale', 'expired'}:
            raise ValueError('Unknown candidate outcome')
        if self.diagnostic is not None and not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', self.diagnostic):
            raise ValueError('Diagnostics contain bounded reason codes only')

    @classmethod
    def pdf(cls, *, transfer_complete=False):
        return cls('pdf', pdf_type=True, transfer_complete=transfer_complete)

    @classmethod
    def failed(cls, diagnostic='source-failed'):
        return cls('failed', diagnostic=diagnostic)

    @classmethod
    def current(cls, response):
        return cls('response', response=response)


@dataclass(frozen=True)
class DiscoveryResult:
    status: str
    pdf_source: str | None = None
    fallback_used: bool = False
    candidate: PdfCandidate | None = field(default=None, repr=False)
    diagnostics: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class P2Resolution:
    inputs: PdfRuleInputs
    article_url: str | None = field(default=None, repr=False)
    diagnostic: str | None = None


class PdfSourceReadError(RuntimeError):
    """A finite source read failed after task authority was independently checked."""

    def __init__(self, message, *, diagnostic='parse-failed', service_id=None, service_ids=()):
        super().__init__(message)
        self.diagnostic = diagnostic
        self.service_id = service_id
        self.service_ids = service_ids


def _eligible(candidate):
    item = RULE_CATALOG.get(candidate.rule_id) or API_CATALOG.get(candidate.rule_id)
    parsed = urlsplit(candidate.url)
    return not (item and item.status in {'historical', 'extension', 'non-pdf', 'reference'}
        or candidate.rule_id not in {'GENERIC', 'OPENALEX'} and item is None
        or parsed.hostname == 'journals.plos.org' and 'manuscript' in parse_qs(parsed.query).get('type', ()))


def openalex_pdf_urls(raw, doi):
    """Exact-DOI, best-first, deduplicated candidates on current data.

    Do not pass current signed URLs through the durable-fact projection: that
    projection correctly removes credentials but cannot supply this operation.
    """
    from allfold.identifiers import normalize_doi
    try:
        if not doi or normalize_doi(raw.get('doi')) != normalize_doi(doi):
            return ()
    except (ValueError, AttributeError):
        return ()
    rows = [raw.get('best_oa_location'), *(raw.get('locations') if isinstance(raw.get('locations'), list) else [])]
    found = []
    for row in rows:
        value = row.get('pdf_url') if isinstance(row, dict) else None
        if not isinstance(value, str):
            continue
        try:
            url = normalize_public_http_url(value)
            host = (urlsplit(url).hostname or '').lower().rstrip('.') if url else ''
            if not url or host == 'openalex.org' or host.endswith('.openalex.org'):
                continue
            url = urldefrag(url)[0]
            if url not in found:
                found.append(url)
        except ValueError:
            continue
    return tuple(found)


class PdfDiscovery:
    """One invocation binds one immutable Paper and never renews its authority.

    io may expose query_missing(target, inputs, facts), document(target),
    reader(candidate), ebsco_candidates(target), and openalex(doi). query_missing is a lazy iterator of
    qualified PdfRuleInputs so the first sufficient answer stops further queries.
    Every IO/consumer dispatch is preceded and followed by the captured guard.
    """
    def __init__(self, target, *, facts=(), inputs=None, io=None, cancel_event=None,
                 guard=lambda: None, deadline=None, monotonic=time.monotonic,
                 max_retries=1, candidates=None, observe=None):
        if not isinstance(target, PdfTarget) or inputs is not None and inputs.target != target:
            raise ValueError('Original PDF target binding is required')
        if not isinstance(facts, tuple) or any(not isinstance(f, PdfDiscoveryFacts) for f in facts):
            raise ValueError('Discovery requires immutable verified facts')
        self.target, self.io = target, io
        self._route = target
        self._cancel = cancel_event if cancel_event is not None else Event()
        self._guard, self._now = guard, monotonic
        self.deadline = monotonic() + 120 if deadline is None else float(deadline)
        if not 0 < self.deadline < float('inf') or max_retries < 0:
            raise ValueError('Finite discovery budgets are required')
        roots = (*target.direct_identities, *((('doi', target.identity_doi),) if target.identity_doi else ()))
        self.facts = tuple(f for f in facts if discovery_target_matches(f, roots)
            and not (target.identity_doi and f.target_doi and f.target_doi != target.identity_doi))
        self.inputs = self._facts_inputs(inputs or PdfRuleInputs(target))
        for snapshot in self.facts:
            if not target.article_url and snapshot.source == 'document' and snapshot.landing_url:
                self._route = replace(target, article_url=snapshot.landing_url)
        self._route = self._facts_route(self._route)
        self._retries = max_retries
        self._seen, self._diagnostics = set(), []
        self._failed, self._fallback, self._used = False, False, False
        self._document_attempted = False
        self._publisher_access_blocked = False
        self._ebsco_attempted = False
        self._ebsco_viewer_attempted = False
        self._initial = tuple(candidates) if candidates is not None else None
        self._consumed = 0
        self._observe = observe
        self._source_attempt, self._attempt_count = 0, 0
        self._current_candidate = None

    @property
    def source_attempt(self):
        return self._source_attempt

    def _observation(self, stage, rule, reason, candidate=None, service_id=None):
        if self._observe is None:
            return
        if candidate is None and self._current_candidate is not None:
            current = self._current_candidate
            if (current.stage, current.rule_id) == (stage, rule):
                candidate = current
        value = dict(stage=stage, rule=rule, reason=reason, attempt=self._source_attempt,
            fallback=self._fallback, origin=candidate.url if candidate is not None else None,
            service_id=service_id or getattr(getattr(candidate, 'access', None), 'service_id', None))
        try:
            self._observe(value)
        except Exception:
            # Telemetry alone cannot change source/transport outcomes.
            pass

    def _note(self, stage, rule, reason, service_id=None):
        self._diagnostics.append((stage, rule, reason))
        self._observation(stage, rule, reason, service_id=service_id)

    def check(self):
        if self._cancel.is_set():
            raise Cancelled('PDF discovery cancelled')
        self._guard()
        if self._now() >= self.deadline:
            raise ProviderBudgetExceeded('PDF discovery parent deadline expired')

    def _call(self, function, *args):
        self.check()
        try:
            value = function(*args)
        except BaseException:
            self.check()  # A retry's prior remote failure must not hide revocation/expiry.
            raise
        if not (isinstance(value, CandidateResult) and value.kind == 'pdf'
                and value.pdf_type and value.transfer_complete):
            self.check()
        return value

    def _rules(self, stage):
        inputs = replace(self.inputs, target=self._route)
        generator = iter_p1_candidates if stage == 'P1' else iter_p2_candidates
        for candidate in generator(self._route, inputs):
            yield replace(candidate, target=self.target)

    def _facts_inputs(self, initial, snapshots=None):
        identifiers, alternatives, known = list(initial.identifiers), list(initial.alternative_ids), list(initial.known_pdf_urls)
        for snapshot in self.facts if snapshots is None else snapshots:
            for item in snapshot.identifiers:
                if item.kind == 'alternative-id':
                    if item.value not in alternatives:
                        alternatives.append(item.value)
                elif (item.kind, item.value) not in identifiers:
                    identifiers.append((item.kind, item.value))
            for item in snapshot.candidates:
                # Saved article clues retain P3/P4; form actions are never GETs.
                if item.stage == 'P2' and item.url and not item.action:
                    try:
                        candidate = KnownPdfUrl(item.url, item.rule_id, item.field or 'pdf', item.referer, item.reader_kind)
                        if candidate not in known:
                            known.append(candidate)
                    except ValueError:
                        continue
        return replace(initial, identifiers=tuple(identifiers), alternative_ids=tuple(alternatives),
            known_pdf_urls=tuple(known))

    def _facts_route(self, route):
        # Resource/landing fields supply article routing and IDs, never direct
        # PDF candidates. A current actual content Host outranks older registry
        # evidence; complete existing IDs need no second route either.
        inputs = replace(self.inputs, target=route, known_pdf_urls=(), credentials=frozenset())
        if tuple(iter_p2_candidates(route, inputs)):
            return route
        actual_host = urlsplit(route.article_url).hostname if route.article_url else None
        fallback = route
        for snapshot in self.facts:
            if snapshot.source != 'crossref':
                continue
            for link in snapshot.links:
                if link.kind != 'landing' or actual_host and urlsplit(link.url).hostname != actual_host:
                    continue
                proposed = replace(route, article_url=link.url)
                if not content_platform(proposed):
                    continue
                if not actual_host:
                    fallback = proposed
                if tuple(iter_p2_candidates(proposed, replace(inputs, target=proposed))):
                    return proposed
        return fallback

    def _saved(self, stage):
        values = [(snapshot, item) for snapshot in self.facts if snapshot.source == 'document'
                  for item in snapshot.candidates if item.stage == stage]
        if stage == 'P3':
            values.sort(key=lambda pair: 0 if pair[1].field == 'citation_pdf_url' else 1)
        elif stage == 'P4':
            values.sort(key=lambda pair: pair[1].rule_id == 'GENERIC')
        for snapshot, item in values:
            if item.url and not item.action:
                yield PdfCandidate(self.target, stage, item.rule_id, snapshot.platform or self._platform,
                    item.url, item.reader_kind, item.referer, item.field)
        if stage == 'P4':
            for snapshot in self.facts:
                if snapshot.source == 'document':
                    yield from self._lww_viewer(snapshot)

    def _lww_viewer(self, snapshot):
        landing = snapshot.landing_url
        if not landing or snapshot.platform != 'lww' or urlsplit(landing).hostname != 'journals.lww.com':
            return
        slug = urlsplit(landing).path.split('/')[1]
        numbers = {item.value for item in snapshot.identifiers if item.kind == 'an'
            and re.fullmatch(r'[0-9]{8}-[0-9]{9}-[0-9]{5}', item.value)}
        an = next(iter(numbers)) if len(numbers) == 1 else None
        if an and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', slug):
            yield PdfCandidate(self.target, 'P4', 'R060', 'lww', 'https://journals.lww.com/' + slug
                + '/_layouts/15/oaks.journals/downloadpdf.aspx?trckng_src_pg=ArticleViewer&an=' + an, 'lww')

    @property
    def _platform(self):
        return content_platform(self.target) or self.target.platform or 'unknown'

    def _document_needed(self):
        saved = next((f for f in self.facts if f.source == 'document'), None)
        if saved is None or saved.status != 'complete':
            return True
        refresh = [c for c in saved.candidates if c.refresh or c.action]
        # AN + article slug already supply the qualified refresh reader; do not
        # reopen the original article merely to rediscover that same next hop.
        if refresh and all(c.stage == 'P4' and c.rule_id == 'R060' for c in refresh) and tuple(self._lww_viewer(saved)):
            return False
        return bool(refresh)

    def _document(self):
        if self.io is None or not callable(getattr(type(self.io), 'document', None)):
            return ()
        try:
            result = self._call(self.io.document, self.target)
        except PdfSourceReadError as error:
            self._note('P3', 'DOCUMENT', error.diagnostic)
            return ()
        if result is None:
            return ()
        if result.facts.status == 'failed':
            for reason in result.facts.diagnostics:
                self._note('P3', 'DOCUMENT', reason)
            return ()
        self._document_attempted = True
        self.inputs = self._facts_inputs(self.inputs, (result.facts,))
        landing = getattr(result, 'current_landing_url', None) or result.facts.landing_url
        if landing:
            self._route = replace(self.target, article_url=landing)
        # Native's current candidates preserve signed values. Only the adapter
        # validates the live Document; this core never holds a Page or persists it.
        values = getattr(result, 'current_candidates', ())
        platform = getattr(getattr(result, 'facts', None), 'platform', None) or self._platform
        return (*tuple(PdfCandidate(self.target, c.stage, c.rule_id, platform, c.url,
            c.reader_kind, c.referer, c.field, action=c.action) for c in values),
            *self._lww_viewer(result.facts))

    @staticmethod
    def _reader_entry(candidate):
        from allfold.pdf_responses import reader_context
        parsed = urlsplit(candidate.url)
        reader = reader_context(candidate) if parsed.path == '/stamp/stamp.jsp' else None
        return bool(candidate.action or candidate.reader_kind
            or reader and reader['platform'] == 'ieee'
            or parsed.hostname in ATYPON_HOSTS and re.search(r'/doi/(?:epdf|pdfplus)/', parsed.path))

    def _ordered_entries(self, candidates):
        # Rank only already qualified entries. This does not fetch new clues or
        # claim a response is a PDF; the consumer still verifies actual saving.
        return sorted(candidates, key=self._reader_entry)

    @staticmethod
    def _entry_scope(candidate):
        parsed = urlsplit(candidate.url)
        return candidate.rule_id, parsed.scheme, parsed.netloc, parsed.path

    def _available_direct(self, candidate):
        return (not self._reader_entry(candidate) and _eligible(candidate)
            and self._entry_key(candidate) not in self._seen)

    def _entry_request(self, candidate):
        if (self._initial is None and not candidate.action and not candidate.referer_observed
                and candidate.referer is None and self._route.article_url):
            return replace(candidate, referer=self._route.article_url)
        return candidate

    def _entry_key(self, candidate):
        return _request_key(self._entry_request(candidate))

    def _ebsco_candidates(self):
        if self._ebsco_attempted or self.io is None or not callable(getattr(type(self.io), 'ebsco_candidates', None)):
            return ()
        self._ebsco_attempted = True
        try:
            return self._call(self.io.ebsco_candidates, self.target)
        except PdfSourceReadError as error:
            self._note('P4', 'R073', error.diagnostic, service_id=error.service_id)
            return ()

    def _ebsco_viewer(self, candidate):
        if (self._ebsco_viewer_attempted or candidate.rule_id != 'R073' or candidate.field != 'ebsco_download_link'
                or self.io is None or not callable(getattr(type(self.io), 'ebsco_viewer', None))):
            return ()
        self._ebsco_viewer_attempted = True
        try:
            return self._call(self.io.ebsco_viewer, candidate)
        except PdfSourceReadError as error:
            self._note('P4', 'R073', error.diagnostic, service_id=error.service_id)
            return ()

    def _candidate_batches(self):
        if self._initial is not None:
            yield self._initial
            return
        p1 = tuple(self._rules('P1'))
        existing = tuple(self._rules('P2'))
        saved_p3 = tuple(self._saved('P3'))
        saved_p4 = tuple(self._saved('P4'))
        yield self._ordered_entries((*p1, *existing, *saved_p3, *saved_p4))
        # A publisher access obstacle can be followed by the assigned institution
        # source before opening the article again. Later publisher clues still
        # run when that separate source cannot produce a body.
        if self._publisher_access_blocked and not self._ebsco_attempted:
            yield self._ebsco_candidates()
        if (needs_p2_query(self._route, replace(self.inputs, target=self._route), known_refresh=crossref_pdf_refresh_required(self.facts))
                and self.io is not None and callable(getattr(type(self.io), 'query_missing', None))):
            # IO is an iterator: no second interface is requested until the
            # first response has been considered, and sufficient IDs stop it.
            query_target = self._route
            stream = self.io.query_missing(query_target, replace(self.inputs, target=query_target), self.facts)
            while True:
                try:
                    resolved = self._call(next, stream)
                except StopIteration:
                    break
                previous_route = self._route
                if isinstance(resolved, P2Resolution):
                    updated = resolved.inputs
                    if resolved.article_url:
                        self._route = replace(self.target, article_url=resolved.article_url)
                    if resolved.diagnostic:
                        self._note('P2', 'QUERY', resolved.diagnostic)
                else:
                    updated = resolved
                if updated.target != query_target:
                    raise ValueError('Query result changed original PDF target')
                self.inputs = replace(updated, target=self.target)
                candidates = tuple(c for c in self._rules('P2') if self._entry_key(c) not in self._seen)
                # A newly applicable template is an attempt, not a complete
                # input answer that suppresses an already configured API.
                sufficient_inputs = bool(candidates)
                if self._route != previous_route:
                    # A newly resolved content Host may have a DOI template
                    # whose inputs were unavailable earlier. Continue this P2
                    # path in place rather than restarting the discovery chain.
                    candidates += tuple(replace(c, stage='P2') for c in self._rules('P1'))
                candidates = tuple(c for c in candidates if self._entry_key(c) not in self._seen)
                yield self._ordered_entries(candidates)
                if self._publisher_access_blocked and not self._ebsco_attempted:
                    yield self._ebsco_candidates()
                if sufficient_inputs:
                    break
        # Stable body URLs already have authority to be tried. A qualified
        # Reader refreshes its own entry inside the chain, not the article.
        failed_p4 = any(not c.reader_kind and self._entry_key(c) in self._seen for c in saved_p4)
        current = self._document() if self._document_needed() or failed_p4 else ()
        current_entries = (*sorted((c for c in current if c.stage == 'P3'),
            key=lambda c: 0 if c.field == 'citation_pdf_url' else 1),
            *sorted((c for c in current if c.stage == 'P4'), key=lambda c: c.rule_id == 'GENERIC'))
        templates = []
        if self._document_attempted:
            # A resolved content page can qualify a previously unavailable
            # template. Keep current links first and never replay a tried URL
            # or restart the missing-input API queries.
            for stage in ('P1', 'P2'):
                templates.extend(c for c in self._rules(stage)
                    if self._entry_key(c) not in self._seen)
        yield self._ordered_entries((*current_entries, *templates))
        if not self._ebsco_attempted:
            yield self._ebsco_candidates()
        cached = next((f for f in self.facts if f.source == 'openalex'), None)
        refreshed = False
        if cached and cached.status in {'complete', 'partial'}:
            stable = []
            for item in cached.candidates:
                if item.refresh and not refreshed:
                    # Refresh at its best-first position, then retain every
                    # stable cached location even if that optional read fails.
                    yield self._ordered_entries(stable)
                    stable.clear()
                    refreshed = True
                    yield self._ordered_entries(self._openalex_candidates())
                if item.url:
                    stable.append(PdfCandidate(self.target, 'P5', 'OPENALEX', 'openalex', item.url, field=item.field))
            yield self._ordered_entries(stable)
            if refreshed or cached.status == 'complete':
                return
        yield self._ordered_entries(self._openalex_candidates())

    def _openalex_candidates(self):
        if not self.target.identity_doi or self.io is None or not callable(getattr(type(self.io), 'openalex', None)):
            return
        if getattr(self.io, 'openalex_available', True) is False:
            return
        try:
            raw = self._call(self.io.openalex, self.target.identity_doi)
        except PdfSourceReadError as error:
            self._note('P5', 'OPENALEX', error.diagnostic)
            return
        except OpenAlexNotFoundError:
            self._note('P5', 'OPENALEX', 'not-found')
            return
        except OpenAlexRequestError as error:
            self._note('P5', 'OPENALEX', error.kind.value)
            return
        for url in openalex_pdf_urls(raw, self.target.identity_doi):
            yield PdfCandidate(self.target, 'P5', 'OPENALEX', 'openalex', url)

    def _chain(self, original, consume, *, viewer_fallback):
        from allfold.pdf_responses import parse_current_response, reader_context, access_limited
        original = self._entry_request(original)
        # Explicit next-hop relationships, not an expected publisher hop count.
        # Keep fingerprints of the used requests and responses to detect
        # repeated edges without retaining their bodies or signed URLs.
        pending = [(original, None, object())]
        edges, responses = set(), set()
        attempts = {}
        request_context_key, reader_context_key = None, None
        while pending:
            candidate, evidence, lineage = pending.pop()
            self._current_candidate = candidate
            self.check()
            if candidate.target != self.target:
                raise ValueError('Candidate target changed')
            if not _eligible(candidate):
                continue
            key = _request_key(candidate)
            edge = (key, evidence)
            if edge in edges or candidate.action and key in self._seen:
                continue
            if key in self._seen and evidence is None:
                continue
            edges.add(edge)
            self._seen.add(key)
            result = self._call(consume, candidate)
            retries = 0
            while isinstance(result, CandidateResult) and result.kind == 'retry' and retries < self._retries:
                retries += 1
                result = self._call(consume, candidate)
            if not isinstance(result, CandidateResult):
                raise TypeError('Consumer must report a CandidateResult')
            if result.kind == 'skipped':
                self._note(original.stage, original.rule_id, result.diagnostic or 'condition-unavailable')
                continue
            self._consumed += retries + 1
            if lineage not in attempts:
                self._attempt_count += 1
                attempts[lineage] = self._attempt_count
            self._source_attempt = attempts[lineage]
            if self._failed or self._attempt_count > 1:
                self._fallback = True
            if not result.transfer_complete:
                reason = result.diagnostic or ('access-blocked' if result.response is not None and access_limited(result.response)
                    else 'response-observed' if result.kind == 'response' else result.kind)
                self._observation(original.stage, original.rule_id, reason, candidate)
            if result.kind == 'local_failure':
                return DiscoveryResult('local-failure', fallback_used=self._fallback,
                    candidate=candidate, diagnostics=tuple(self._diagnostics))
            if result.kind in {'cancelled', 'stale', 'expired'}:
                return DiscoveryResult(result.kind, fallback_used=self._fallback, diagnostics=tuple(self._diagnostics))
            if result.pdf_type and result.transfer_complete:
                return DiscoveryResult('transferred', original.stage, self._fallback, candidate, tuple(self._diagnostics))
            if result.kind in {'pending', 'pdf'}:
                return DiscoveryResult('pending', fallback_used=self._fallback, candidate=candidate, diagnostics=tuple(self._diagnostics))
            following = ()
            observation = None
            fresh_reader = False
            ebsco_direct = candidate.rule_id == 'R073' and candidate.field == 'ebsco_download_link'
            if result.kind == 'response' and result.response is not None:
                response = result.response
                publisher_blocked = False
                if response.access in {'authorization', 'challenge'} and self._route.article_url:
                    publisher, entry = urlsplit(self._route.article_url), urlsplit(original.url)
                    publisher_blocked = (publisher.scheme, publisher.netloc) == (entry.scheme, entry.netloc)
                    self._publisher_access_blocked |= publisher_blocked
                # Entry and Reader can have different Cookie paths. Keep both
                # observations; either can advance, while A -> B -> A repeats.
                if response.context_key is not None:
                    request_context_key = response.context_key
                observation = (key, sha256(response.url.encode()).digest(), response.status, response.content_type,
                    sha256(response.body).digest(), sha256((response.redirect_url or '').encode()).digest(),
                    response.partial, response.access, request_context_key, reader_context_key)
                if observation in responses:
                    self._note(original.stage, original.rule_id, 'response-loop')
                    self._failed = True
                    continue
                responses.add(observation)
                following = parse_current_response(candidate, response,
                    report=lambda code: self._note(original.stage, original.rule_id, code))
                reader = reader_context(candidate, response.url)
                article_backlink = False
                if reader and reader['platform'] == 'sciencedirect' and following:
                    entry = urlsplit(reader['url'])
                    pii = reader['identifier']
                    article_paths = {f'/science/article/pii/{pii}', f'/science/article/abs/pii/{pii}'}
                    article_backlink = all((current := urlsplit(item.url)).scheme == entry.scheme
                        and current.netloc == entry.netloc and current.path in article_paths for item in following)
                if article_backlink:
                    following = ()
                if (not following and not ebsco_direct and self.io is not None
                        and callable(getattr(type(self.io), 'reader', None))):
                    # The response attempt has settled. Suspend only this local
                    # chain so other qualified direct entries can avoid Reader IO.
                    if not article_backlink:
                        yield publisher_blocked and response.access == 'challenge'
                    self._current_candidate = candidate
                    self._source_attempt = attempts[lineage]
                    try:
                        parsed = self._call(self.io.reader, candidate, response)
                    except PdfSourceReadError as error:
                        self._note(original.stage, original.rule_id, error.diagnostic)
                        parsed = None
                    if parsed is not None:
                        fresh_reader = True
                        following = tuple(replace(candidate, url=c.url, reader_kind=c.reader_kind,
                            referer=c.referer, action=c.action, credential=None, accept=None,
                            access=getattr(c, 'access', candidate.access),
                            recover_access=getattr(c, 'recover_access', False))
                            for c in parsed.current_candidates)
                        navigation = getattr(parsed, 'reader_result', None)
                        if navigation is not None:
                            reader_context_key = navigation.context_key
                            if not following and (navigation.url != response.url
                                    or navigation.context_changed or access_limited(response)):
                                following = (replace(candidate, url=navigation.url, referer=navigation.referer,
                                    reader_kind=None, action=None, credential=None, accept=None, recover_access=False),)
                if (not following and self.io is not None and (reader or {}).get('platform') == 'lww'
                        and callable(getattr(type(self.io), 'oce_access', None))
                        and callable(getattr(type(self.io), 'oce_reader', None))):
                    try:
                        if self._call(self.io.oce_access, candidate, response):
                            self._failed = True
                            parsed = self._call(self.io.oce_reader, candidate, response)
                            if parsed is not None:
                                following = tuple(replace(candidate, url=c.url, platform='oce', reader_kind=c.reader_kind,
                                    referer=c.referer, action=c.action, credential=None, accept=None, recover_access=False,
                                    access=getattr(c, 'access', candidate.access))
                                    for c in parsed.current_candidates)
                    except PdfSourceReadError as error:
                        for service_id in error.service_ids or (error.service_id,):
                            self._note(original.stage, original.rule_id, error.diagnostic, service_id)
                if access_limited(response):
                    self._note(original.stage, original.rule_id, result.diagnostic or 'access-blocked')
            if not following and ebsco_direct and viewer_fallback() and result.diagnostic != 'service-invalidated':
                following = self._ebsco_viewer(original)
                if following:
                    # The actual Viewer can issue the same URL in a new request context.
                    fresh_reader = True
                    observation = object()
            if not following:
                self._note(original.stage, original.rule_id, result.diagnostic or 'no-pdf-entry')
                self._failed = True
            else:
                eligible = tuple(item for item in following
                    if _request_key(item) != key or fresh_reader
                    or result.response is not None and result.response.context_changed)
                if not eligible:
                    self._note(original.stage, original.rule_id, 'response-loop')
                    self._failed = True
                pending.extend((item, observation, lineage if index == 0 else object())
                    for index, item in reversed(tuple(enumerate(eligible))))
            result = response = None
        return None

    def _run_batch(self, candidates, consume):
        entries = deque(candidates)
        deferred = deque()
        active = None
        prepared_before_recovery = False
        def viewer_fallback():
            return not any(item.rule_id == 'R073' and item.field == 'ebsco_download_link'
                and self._available_direct(item) for item in entries)

        try:
            while entries or deferred or active is not None:
                if active is None:
                    candidate = None
                    if deferred:
                        scopes = {scope for _, _, scope in deferred}
                        candidate = next((item for item in entries if self._available_direct(item)
                            and self._entry_scope(item) not in scopes), None)
                        if candidate is None:
                            if prepared_before_recovery:
                                prepared_before_recovery = False
                                prepared = self._ebsco_candidates()
                                if prepared:
                                    entries.extend(prepared)
                                    continue
                            active = deferred.popleft()
                        else:
                            entries.remove(candidate)
                    else:
                        candidate = entries.popleft()
                    if candidate is not None:
                        self.check()
                        if (not _eligible(candidate)
                                or self._entry_key(candidate) in self._seen):
                            continue
                        chain = self._chain(candidate, consume, viewer_fallback=viewer_fallback)
                        active = (chain, self._consumed, self._entry_scope(candidate))
                chain, before, scope = active
                try:
                    publisher_challenge = next(chain)
                except StopIteration as done:
                    active = None
                    if done.value is not None:
                        return done.value
                    self._failed = self._failed or self._consumed > before
                else:
                    if self._initial is not None:
                        continue
                    # Query variants of the same rule/endpoint remain that
                    # source's fallbacks, not a reason to interrupt its Reader.
                    try_prepared = publisher_challenge and not self._ebsco_attempted
                    blocked = {scope, *(item[2] for item in deferred)}
                    if any(self._available_direct(item) and self._entry_scope(item) not in blocked
                            for item in entries):
                        deferred.append(active)
                    elif try_prepared:
                        # Preserve this Reader's turn after the EBSCO attempt.
                        deferred.appendleft(active)
                    else:
                        continue
                    prepared_before_recovery |= try_prepared
                    active = None
        finally:
            if active is not None:
                active[0].close()
            for chain, _, _ in deferred:
                chain.close()

    def run(self, consume):
        if self._used:
            raise RuntimeError('A PDF discovery invocation is single-use')
        self._used = True
        self.check()
        if self.target.content_type not in SUPPORTED_PDF_TARGET_TYPES:
            return DiscoveryResult('not-applicable', diagnostics=(('P1', 'SCOPE', 'unsupported-content-type'),))
        for candidates in self._candidate_batches():
            result = self._run_batch(candidates, consume)
            if result is not None:
                return result
        self.check()
        return DiscoveryResult('exhausted', fallback_used=self._fallback, diagnostics=tuple(self._diagnostics))
