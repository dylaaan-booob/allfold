"""Convert current Run evidence into the single Paper library contract."""
from __future__ import annotations

from dataclasses import dataclass

from allfold.models import EvidenceDateKind, ProviderRecordRef
from allfold.paper_dates import date_value, known_preprint_families, preprint_query_refs
from allfold.persistence.library_models import PaperMetadata, PaperRecord, PreprintResult


@dataclass(frozen=True)
class RunIdentityIndex:
    by_identifier: dict[tuple[str, str], PaperRecord]

    @classmethod
    def read(cls, repository):
        return cls({(identity.namespace, identity.value): paper
            for paper in repository.list_papers() for identity in paper.identities})

    def owners(self, keys):
        return {self.by_identifier[key].id for key in keys if key in self.by_identifier}

    def target(self, keys, initial_papers):
        owners = self.owners(keys)
        if len(owners) > 1:
            return False
        if not owners:
            return True
        paper = next(self.by_identifier[key] for key in keys if key in self.by_identifier)
        initial = initial_papers.get(paper.id)
        return (not paper.excluded and paper.metadata is None and initial is not None
            and initial.token == paper.token and not initial.excluded and initial.metadata is None)


def metadata_from_run(paper, *, records=()):
    """Keep bibliography and independent proof; no old workflow status is stored."""
    ordinary = tuple(date_value(item) for item in paper.date_evidence
        if item.kind != EvidenceDateKind.PREPRINT and item.publication_type != 'preprint'
        and item.month is not None and item.provider != 'workspace')
    preprint_evidence = tuple(item for item in paper.date_evidence if item.kind == EvidenceDateKind.PREPRINT)
    relations = set(preprint_query_refs(preprint_evidence))
    # Preserve only families established by the existing relation algorithm.
    # A preprint's link back to its formal article must not become another
    # unresolved Preprint family on the saved formal Paper.
    for identity, family in known_preprint_families(records).items():
        namespace, _, identifier = identity.partition(':')
        relations.add(ProviderRecordRef(provider=namespace, record_id=identifier,
            relation='preprint', version_family=family))
    preprints = []
    for item in preprint_evidence:
        if item.provider not in {'arxiv', 'biorxiv', 'medrxiv', 'europe_pmc', 'crossref'} or not item.record_id:
            continue
        identifier = item.record_id
        if item.provider in {'biorxiv', 'medrxiv'} and identifier.rpartition(':')[2].isdigit():
            identifier = identifier.rpartition(':')[0]
        try:
            preprints.append(PreprintResult(provider=item.provider, identifier=identifier, date=date_value(item),
                version=item.version, url=item.url, version_family=item.version_family, first_version=item.first_version))
        except ValueError:
            # The complete native fact above remains available; a source record
            # label is not always a supported normalized query identifier.
            pass
    return PaperMetadata(**paper.metadata.model_dump(exclude={'first_public_at'}),
        discovered_at=paper.workflow.discovered_at, authors=paper.authors,
        journal_issns=paper.journal_issns, indexed_terms=paper.indexed_terms,
        sources=paper.sources, ordinary_dates=ordinary, preprints=tuple(preprints),
        preprint_evidence=preprint_evidence,
        preprint_relations=tuple(sorted(relations, key=lambda ref: ref.model_dump_json())),
        first_public_at=paper.metadata.first_public_at)
