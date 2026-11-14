"""Purpose-driven Provider clients, batch lookup and identity binding helpers."""
from dataclasses import dataclass

from allfold.identifiers import strong_identifiers, related_identifiers
from allfold.models import ExternalIds, ProviderRecordRef, ProviderWorkEvidence


def provider_client(provider, **kwargs):
    from allfold.providers.integrated import DiscoveryClient, DISCOVERY_PROVIDERS
    from allfold.providers.supplemental import SupplementalClient

    if provider in DISCOVERY_PROVIDERS:
        kwargs.pop('mailto', None)
        return DiscoveryClient(provider, **kwargs)
    kwargs.pop('api_key', None)
    return SupplementalClient(provider, **kwargs)


class LookupSettlement:
    """Keep replay callbacks only for lookups with transient HTTP failures."""

    def __init__(self):
        self.pending = []

    def capture(self, client, lookup, update):
        if not hasattr(client, 'capture_transient_failures'):
            return lookup()
        with client.capture_transient_failures() as failures:
            result = lookup()
        if failures:
            self.pending.append((client, lookup, update))
        return result

    def settle(self, cancel_event):
        if not self.pending or cancel_event.is_set():
            return False
        for client in dict.fromkeys(client for client, _, _ in self.pending):
            client.begin_settlement()
        for _, lookup, update in self.pending:
            if cancel_event.is_set():
                break
            update(lookup())
        return True


@dataclass(frozen=True)
class LookupIssue:
    provider: str
    identifier: str
    message: str
    status: str = 'failed'


@dataclass(frozen=True)
class LookupFact:
    provider: str
    namespace: str
    identifier: str
    status: str
    capability: str | None = None


def _identities(record):
    return set(related_identifiers(record))


def formal_records(records, root_ids):
    """Expand direct formal identities only; declared relations never own a root."""
    pending = [record for record in records if record.publication_type != 'preprint']
    accepted, keys = [], set(root_ids)
    while pending:
        matches = [record for record in pending if keys & strong_identifiers(record.external_ids)]
        if not matches:
            break
        for record in matches:
            pending.remove(record)
            accepted.append(record)
            keys.update(strong_identifiers(record.external_ids))
    return tuple(accepted)


def _batch_lookup(client, provider, namespace, identifiers, capability, cancel_event):
    from allfold.providers.integrated import Cancelled, DiscoveryError
    from allfold.providers.supplemental import PartialLookup
    if cancel_event is not None and cancel_event.is_set():
        return {identifier: Cancelled('Necessary metadata cancelled') for identifier in identifiers}
    try:
        if client is None:
            raise DiscoveryError('Selected metadata adapter is unavailable')
        if provider == 'crossref' and capability == 'preprints':
            result = client.lookup_preprints(identifiers)
        elif provider == 'pubmed':
            result = client.lookup_many(namespace, identifiers, capability='fetch' if capability == 'fetch-preprint' else capability)
        else:
            result = client.lookup_many(namespace, identifiers)
        if isinstance(result, dict):
            values = {identifier: result.get(identifier, DiscoveryError('Incomplete metadata batch response')) for identifier in identifiers}
            if provider == 'pubmed' and capability == 'fetch-preprint':
                from allfold.models import EvidenceDateKind
                for identifier, rows in values.items():
                    if isinstance(rows, Exception):
                        continue
                    values[identifier] = tuple(record.model_copy(update={'publication_type': 'preprint', 'journal': None,
                        'dates': tuple(item.model_copy(update={'publication_type': 'preprint',
                            'kind': EvidenceDateKind.PREPRINT if item.kind in {EvidenceDateKind.PUBLISHED, EvidenceDateKind.PUBLISHED_ONLINE}
                                else item.kind, 'first_version': False}) for item in record.dates)}) for record in rows)
            return values
        output = {}
        for identifier in identifiers:
            accepted, _ = bind_records(result.records, {(namespace, identifier)})
            if provider == 'openalex' and namespace == 'doi':
                work_ids = {work for ns, requested, work in getattr(result, 'bindings', ())
                    if ns == namespace and requested == identifier}
                mapped = [record for record in result.records if
                    any(('openalex', work) in strong_identifiers(record.external_ids) for work in work_ids)]
                anchors = [ProviderWorkEvidence(provenance=record.provenance.model_copy(update={
                    'record_id': f'{record.provenance.record_id}:binding:{identifier}',
                    'note': 'Exact requested DOI matched an explicit Work location; linked Work identity remains separate'}),
                    external_ids=ExternalIds(doi=identifier), publication_type='journal',
                    related_ids=(ProviderRecordRef(provider='openalex', record_id=work),))
                    for record in mapped for work in sorted(work_ids)
                    if ('openalex', work) in strong_identifiers(record.external_ids)
                    and ('doi', identifier) not in strong_identifiers(record.external_ids)]
                accepted, _ = bind_records((*accepted, *anchors, *mapped), {(namespace, identifier)})
            if provider == 'pubmed' and hasattr(client, 'cached_lookup'):
                cached = client.cached_lookup(namespace, identifier, 'fetch' if capability == 'fetch-preprint' else capability)
                if isinstance(cached, Exception):
                    output[identifier] = cached
                    continue
                if cached is not None:
                    accepted = list(cached)
            if provider == 'pubmed' and capability == 'fetch-preprint':
                from allfold.models import EvidenceDateKind
                accepted = [record.model_copy(update={'publication_type': 'preprint', 'journal': None,
                    'dates': tuple(item.model_copy(update={'publication_type': 'preprint',
                        'kind': EvidenceDateKind.PREPRINT if item.kind in {EvidenceDateKind.PUBLISHED, EvidenceDateKind.PUBLISHED_ONLINE}
                            else item.kind, 'first_version': False}) for item in record.dates)}) for record in accepted]
            if provider == 'pubmed' and accepted:
                output[identifier] = tuple(accepted)
                continue
            if result.status in {'failed', 'partial', 'cancelled'}:
                message = '; '.join(result.limitations) or 'Incomplete metadata batch response'
                output[identifier] = (PartialLookup(message, accepted) if accepted else
                    Cancelled(message) if result.status == 'cancelled' else DiscoveryError(message))
            else:
                output[identifier] = tuple(accepted)
        return output
    except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as error:
        return {identifier: error for identifier in identifiers}


def bind_records(supplements, identities):
    """A primary response identity establishes the root, never a related alias.

    A native reverse response may also contain details linked by that root.
    """
    pending = list(supplements)
    accepted, identities = [], set(identities)
    while pending:
        matched = [record for record in pending if identities & set(strong_identifiers(record.external_ids))]
        if not matched:
            break
        for record in matched:
            pending.remove(record)
            accepted.append(record)
            identities.update(_identities(record))
    return accepted, pending
