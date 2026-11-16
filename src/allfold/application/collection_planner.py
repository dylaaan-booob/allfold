"""Production Paper collection and explicit single-Paper retry composition."""
from dataclasses import replace
from uuid import UUID

from allfold.application.collection_runtime import BranchSpec
from allfold.application.document_metadata import document_metadata_branch
from allfold.application.necessary_metadata import necessary_metadata_branch, necessary_requests, necessary_work_requests
from allfold.config import load_config
from allfold.persistence.paper_repository import InvalidPaperState, PaperRepository, StaleWriteError
from allfold.providers.integrated import PROVIDERS


class ProductionCollectionService:
    """Own only composition; the Workspace registry owns every task and resource."""
    def __init__(self, host):
        self.host = host

    def plan(self, *, paper=None, metadata=None, identities=(), records=(), facts=(), required=(), config=None):
        if paper is not None:
            metadata = paper.metadata
            identities = set(identities) | {(item.namespace, item.value) for item in paper.identities}
        if metadata is None:
            raise InvalidPaperState('Collection requires complete Paper metadata')
        config = config or load_config(self.host.config_path)
        records, facts = tuple(records), tuple(facts)
        if paper is not None and not records:
            from allfold.application.necessary_metadata import paper_evidence_records
            records = paper_evidence_records(paper)
        # A declared related Work is a purpose; an ordinary field gap is not.
        required = tuple(sorted(set(required) | necessary_work_requests(records)))
        if any(namespace == 'doi' for namespace, _ in identities):
            from allfold.application.workspace import paper_service_assignment
            service_id, assignment = paper_service_assignment(metadata, config.journals)
            if assignment == 'ambiguous':
                def fail_access(context):
                    raise InvalidPaperState('Paper has ambiguous Access Service assignment')
                document = BranchSpec('document', fail_access, service_id=None)
            else:
                document = replace(document_metadata_branch(), service_id=service_id)
        else:
            document = BranchSpec('document', skip_reason='No reliable DOI or confirmed article entrance', service_id=None)
        api = replace(necessary_metadata_branch(providers=PROVIDERS, records=records, facts=facts,
            required=tuple(sorted(required))), service_id=None, mailto=config.crossref_mailto)
        return document, api

    def base_metadata(self, canonical, *, identities, records=(), facts=(), required=()):
        """Publish a new First public only after the complete purpose graph settles.

        A record containing native v1 proof does not certify a complete response.
        Explicit partial capabilities remain required even when positive proof
        satisfies the family heuristic. Existing qualified saved values survive.
        """
        from allfold.persistence.run_library import metadata_from_run
        purposes = tuple(sorted(set(required) | necessary_work_requests(records)
            | {fact.request for fact in facts if not fact.complete}))
        complete = not necessary_requests(records, root_ids=set(identities), providers=PROVIDERS,
            facts=facts, required=purposes)
        return metadata_from_run(canonical, records=records, first_public_complete=complete)

    def _retry(self, paper_id, *, workspace_id, expected_token, expected_attempt, bind=True):
        if expected_token is None or type(expected_attempt) is not int or expected_attempt < 1:
            raise StaleWriteError('Retry requires the exact Paper token and collection attempt')
        registry = self.host.current() if bind else self.host.peek()
        if registry is None:
            raise InvalidPaperState('Workspace collection is not bound')
        if UUID(str(workspace_id)) != registry.workspace_id:
            raise StaleWriteError('Retry belongs to another Workspace')
        with PaperRepository.open(registry.workspace, expected_workspace_id=registry.workspace_id) as repository:
            paper = repository.get(UUID(str(paper_id)))
        return registry, self.plan(paper=paper)

    def check_retry(self, paper_id, *, workspace_id, expected_token, expected_attempt, expected_revision=None):
        """Read-only eligibility; successful branches do not recapture old access."""
        registry, branches = self._retry(paper_id, workspace_id=workspace_id,
            expected_token=expected_token, expected_attempt=expected_attempt, bind=False)
        return registry.check_retry(paper_id, branches=branches, expected_token=expected_token,
            expected_attempt=expected_attempt, expected_revision=expected_revision)

    def cleanup_pending(self, paper_id, workspace_id):
        registry = self.host.peek()
        return bool(registry and registry.busy(paper_id, workspace_id, include_local_reads=False))

    def retry(self, paper_id, *, workspace_id, expected_token, expected_attempt, expected_revision=None, deadline=None):
        registry, branches = self._retry(paper_id, workspace_id=workspace_id,
            expected_token=expected_token, expected_attempt=expected_attempt)
        return registry.retry(paper_id, branches=branches, expected_token=expected_token,
            expected_attempt=expected_attempt, expected_revision=expected_revision, deadline=deadline)
