"""Result-driven, lazy PDF source discovery, without collection or file writes.

The consumer owns the current transfer and reports its actual result. Merely
returning a response with a PDF Content-Type does not complete a transfer here.
IO capabilities are task-owned and are called only at their reached stage.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
import time
from threading import Event
from urllib.parse import parse_qs, urldefrag, urlsplit

from allfold.pdf_facts import PdfDiscoveryFacts, crossref_pdf_refresh_required, discovery_target_matches
from allfold.pdf_catalog import API_CATALOG, RULE_CATALOG
from allfold.pdf_rules import (ARTICLE_TYPES, PdfCandidate, PdfRuleInputs, PdfTarget, KnownPdfUrl,
    content_platform, iter_p1_candidates, iter_p2_candidates, needs_p2_query)
from allfold.providers.provider_http import Cancelled, ProviderBudgetExceeded
from allfold.providers.openalex import OpenAlexNotFoundError, OpenAlexRequestError
from allfold.url_safety import normalize_public_http_url


SUPPORTED_PDF_TARGET_TYPES = ARTICLE_TYPES | {'unknown'}


@dataclass(frozen=True)
class CurrentResponse:
    """One bounded already-requested response; never a license to probe its URL."""
    url: str = field(repr=False)
    content_type: str
    body: bytes = field(repr=False, default=b'')
    status: int = 200
    access: str | None = None

    def __post_init__(self):
        normalize_public_http_url(self.url)
        if not isinstance(self.url, str) or len(self.url) > 8192 or not isinstance(self.body, bytes) or len(self.body) > 262144:
            raise ValueError('Current response exceeds the finite parse budget')


@dataclass(frozen=True)
class CandidateResult:
    kind: str
    response: CurrentResponse | None = field(default=None, repr=False)
    pdf_type: bool = False
    transfer_complete: bool = False
    diagnostic: str | None = None

    def __post_init__(self):
        if self.kind not in {'pdf', 'failed', 'response', 'retry', 'pending', 'local_failure', 'cancelled', 'stale', 'expired'}:
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


def _eligible(candidate):
    item = RULE_CATALOG.get(candidate.rule_id) or API_CATALOG.get(candidate.rule_id)
    parsed = urlsplit(candidate.url)
    return not (item and item.status in {'historical', 'extension', 'non-pdf', 'reference'}
        or candidate.rule_id not in {'GENERIC', 'OPENALEX'} and item is None
        or parsed.hostname == 'journals.plos.org' and 'manuscript' in parse_qs(parsed.query).get('type', ()))


def openalex_pdf_urls(raw, doi):
    """Historical exact-DOI/best-first/four-candidate algorithm on CURRENT data.

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
            if len(found) == 4:
                break
        except ValueError:
            continue
    return tuple(found)


class PdfDiscovery:
    """One invocation binds one immutable Paper and never renews its authority.

    io may expose query_missing(target, inputs, facts), document(target),
    reader(candidate), and openalex(doi). query_missing is a lazy iterator of
    qualified PdfRuleInputs so the first sufficient answer stops further queries.
    Every IO/consumer dispatch is preceded and followed by the captured guard.
    """
    def __init__(self, target, *, facts=(), inputs=None, io=None, cancel_event=None,
                 guard=lambda: None, deadline=None, monotonic=time.monotonic,
                 max_operations=48, max_hops=6, max_retries=1):
        if not isinstance(target, PdfTarget) or inputs is not None and inputs.target != target:
            raise ValueError('Original PDF target binding is required')
        if not isinstance(facts, tuple) or any(not isinstance(f, PdfDiscoveryFacts) for f in facts):
            raise ValueError('Discovery requires immutable verified facts')
        self.target, self.io = target, io
        self._route = target
        self._cancel = cancel_event if cancel_event is not None else Event()
        self._guard, self._now = guard, monotonic
        self.deadline = monotonic() + 120 if deadline is None else float(deadline)
        if not 0 < self.deadline < float('inf') or min(max_operations, max_hops) < 1 or max_retries < 0:
            raise ValueError('Finite discovery budgets are required')
        roots = (*target.direct_identities, *((('doi', target.identity_doi),) if target.identity_doi else ()))
        self.facts = tuple(f for f in facts if discovery_target_matches(f, roots)
            and not (target.identity_doi and f.target_doi and f.target_doi != target.identity_doi))
        self.inputs = self._facts_inputs(inputs or PdfRuleInputs(target))
        for snapshot in self.facts:
            if not target.article_url and snapshot.source == 'document' and snapshot.landing_url:
                self._route = replace(target, article_url=snapshot.landing_url)
        self._route = self._facts_route(self._route)
        self._remaining, self._hops, self._retries = max_operations, max_hops, max_retries
        self._seen, self._diagnostics = set(), []
        self._failed, self._fallback, self._used = False, False, False
        self._document_attempted = False

    def check(self):
        if self._cancel.is_set():
            raise Cancelled('PDF discovery cancelled')
        self._guard()
        if self._now() >= self.deadline:
            raise ProviderBudgetExceeded('PDF discovery parent deadline expired')

    def _call(self, function, *args):
        self.check()
        if self._remaining <= 0:
            raise ProviderBudgetExceeded('PDF discovery operation budget exhausted')
        self._remaining -= 1
        try:
            value = function(*args)
        except BaseException:
            self.check()  # A retry's prior remote failure must not hide revocation/expiry.
            raise
        self.check()
        return value

    def _fallback_io(self, function, *args):
        if self._failed:
            self._fallback = True
        return self._call(function, *args)

    def _rules(self, stage):
        inputs = replace(self.inputs, target=self._route)
        generator = iter_p1_candidates if stage == 'P1' else iter_p2_candidates
        for candidate in generator(self._route, inputs):
            yield replace(candidate, target=self.target)

    def _facts_inputs(self, initial):
        identifiers, alternatives, known = list(initial.identifiers), list(initial.alternative_ids), list(initial.known_pdf_urls)
        for snapshot in self.facts:
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
        return replace(initial, identifiers=tuple(identifiers[:24]), alternative_ids=tuple(alternatives[:24]),
            known_pdf_urls=tuple(known[:16]))

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
        except PdfSourceReadError:
            if self._failed:
                self._fallback = True
            self._failed = True
            self._diagnostics.append(('P3', 'DOCUMENT', 'parse-failed'))
            return ()
        if result is None:
            return ()
        self._document_attempted = True
        if self._failed:
            self._fallback = True
        # Native's current candidates preserve signed values. Only the adapter
        # validates the live Document; this core never holds a Page or persists it.
        values = getattr(result, 'current_candidates', ())
        platform = getattr(getattr(result, 'facts', None), 'platform', None) or self._platform
        return (*tuple(PdfCandidate(self.target, c.stage, c.rule_id, platform, c.url,
            c.reader_kind, c.referer, c.field, action=c.action) for c in values),
            *self._lww_viewer(result.facts))

    def _candidates(self):
        yield from self._rules('P1')
        existing = tuple(self._rules('P2'))
        yield from existing
        if ((needs_p2_query(self._route, replace(self.inputs, target=self._route)) or crossref_pdf_refresh_required(self.facts))
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
                    if self._failed:
                        self._fallback = True
                    updated = resolved.inputs
                    if resolved.article_url:
                        self._route = replace(self.target, article_url=resolved.article_url)
                    if resolved.diagnostic:
                        self._diagnostics.append(('P2', 'QUERY', resolved.diagnostic))
                else:
                    updated = resolved
                if updated.target != query_target:
                    raise ValueError('Query result changed original PDF target')
                self.inputs = replace(updated, target=self.target)
                candidates = tuple(self._rules('P2'))
                if self._route != previous_route:
                    # A newly resolved content Host may have a DOI template
                    # whose inputs were unavailable earlier. Continue this P2
                    # path in place rather than restarting the discovery chain.
                    candidates += tuple(replace(c, stage='P2') for c in self._rules('P1'))
                candidates = tuple(c for c in candidates if (urldefrag(c.url)[0], c.action) not in self._seen)
                yield from candidates
                if candidates:
                    break
        # An already qualified P3 clue can finish before refreshing missing
        # fields or a later dynamic P4 entrance in a partial snapshot.
        yield from self._saved('P3')
        current = self._document() if self._document_needed() else ()
        yield from sorted((c for c in current if c.stage == 'P3'),
            key=lambda c: 0 if c.field == 'citation_pdf_url' else 1)
        p4 = [*(c for c in current if c.stage == 'P4'), *self._saved('P4')]
        yield from sorted(p4, key=lambda c: c.rule_id == 'GENERIC')
        if self._document_attempted:
            self._failed = True
        cached = next((f for f in self.facts if f.source == 'openalex'), None)
        refresh = cached and any(c.refresh for c in cached.candidates)
        if cached and cached.status == 'complete':
            for item in cached.candidates:
                if item.refresh:
                    break  # Requery only after earlier stable candidates fail.
                if item.url:
                    yield PdfCandidate(self.target, 'P5', 'OPENALEX', 'openalex', item.url, field=item.field)
            if not refresh:
                return
        if not self.target.identity_doi or self.io is None or not callable(getattr(type(self.io), 'openalex', None)):
            return
        if getattr(self.io, 'openalex_available', True) is False:
            return
        try:
            raw = self._fallback_io(self.io.openalex, self.target.identity_doi)
        except OpenAlexNotFoundError:
            self._diagnostics.append(('P5', 'OPENALEX', 'not-found'))
            return
        except OpenAlexRequestError as error:
            self._diagnostics.append(('P5', 'OPENALEX', error.kind.value))
            return
        for url in openalex_pdf_urls(raw, self.target.identity_doi):
            yield PdfCandidate(self.target, 'P5', 'OPENALEX', 'openalex', url)

    def _chain(self, original, consume, depth=0):
        from allfold.pdf_responses import parse_current_response, reader_context
        candidate, retries, chain_seen = original, 0, set()
        for hop in range(depth, self._hops + 1):
            self.check()
            if candidate.target != self.target:
                raise ValueError('Candidate target changed')
            if not _eligible(candidate):
                return None
            key = (urldefrag(candidate.url)[0], candidate.action)
            if key in chain_seen or key in self._seen:
                return None
            chain_seen.add(key)
            self._seen.add(key)
            result = self._call(consume, candidate)
            while isinstance(result, CandidateResult) and result.kind == 'retry' and retries < self._retries:
                retries += 1
                result = self._call(consume, candidate)
            if not isinstance(result, CandidateResult):
                raise TypeError('Consumer must report a CandidateResult')
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
            if result.kind == 'response' and result.response is not None:
                following = parse_current_response(candidate, result.response)
                if not following and self.io is not None and callable(getattr(type(self.io), 'reader', None)):
                    try:
                        parsed = self._call(self.io.reader, candidate, result.response)
                    except PdfSourceReadError:
                        parsed = None
                    if parsed is not None:
                        following = tuple(replace(candidate, url=c.url, reader_kind=c.reader_kind,
                            referer=c.referer, action=c.action, credential=None, accept=None)
                            for c in parsed.current_candidates)
                if (not following and self.io is not None
                        and (reader_context(candidate, result.response.url) or {}).get('platform') == 'lww'
                        and callable(getattr(type(self.io), 'oce_access', None))
                        and callable(getattr(type(self.io), 'oce_reader', None))):
                    try:
                        if self._call(self.io.oce_access, candidate, result.response):
                            # LWW's empty viewer ended that path. OCE requires
                            # its own captured prepared target, not LWW access.
                            self._fallback = True
                            parsed = self._call(self.io.oce_reader, candidate, result.response)
                            if parsed is not None:
                                following = tuple(replace(candidate, url=c.url, platform='oce', reader_kind=c.reader_kind,
                                    referer=c.referer, action=c.action, credential=None, accept=None)
                                    for c in parsed.current_candidates)
                    except PdfSourceReadError:
                        self._diagnostics.append((original.stage, original.rule_id, 'parse-failed'))
            if not following:
                self._diagnostics.append((original.stage, original.rule_id, result.diagnostic or 'empty'))
                return None
            # Multiple links are alternatives within this source chain, not a
            # generic unbounded crawler. Branches use the same finite budget.
            branch_failed = False
            for next_candidate in following:
                if branch_failed and (urldefrag(next_candidate.url)[0], next_candidate.action) not in self._seen:
                    self._fallback = True
                before = len(self._seen)
                outcome = self._chain(next_candidate, consume, hop + 1) if len(following) > 1 else None
                if outcome is not None:
                    return outcome
                branch_failed = branch_failed or len(self._seen) > before
            if len(following) != 1:
                return None
            candidate = following[0]
        self._diagnostics.append((original.stage, original.rule_id, 'hop-limit'))
        return None

    def run(self, consume):
        if self._used:
            raise RuntimeError('A PDF discovery invocation is single-use')
        self._used = True
        self.check()
        if self.target.content_type not in SUPPORTED_PDF_TARGET_TYPES:
            return DiscoveryResult('not-applicable', diagnostics=(('P1', 'SCOPE', 'unsupported-content-type'),))
        for candidate in self._candidates():
            self.check()
            if not _eligible(candidate):
                continue
            if (urldefrag(candidate.url)[0], candidate.action) in self._seen:
                continue
            if self._failed:
                self._fallback = True
            result = self._chain(candidate, consume)
            if result is not None:
                return result
            self._failed = True
        self.check()
        return DiscoveryResult('exhausted', fallback_used=self._fallback, diagnostics=tuple(self._diagnostics))
