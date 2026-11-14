"""Current managed-body reading and independent Trash deletion."""
from concurrent.futures import Future
from dataclasses import dataclass
from uuid import UUID, uuid4

from allfold.application.history import observe
from allfold.persistence.local_body_files import CurrentBodyFile
from allfold.persistence.paper_repository import InvalidPaperState, StaleWriteError, LibraryError


@dataclass(frozen=True)
class LocalBodyResult:
    status: str

    @property
    def failed(self):
        return self.status in {'local_failure', 'file_failure', 'association_failure', 'stale'}


class LocalBodyService:
    def __init__(self, host):
        self.host = host

    def perform(self, paper_id, workspace_id, *, action, body_generation):
        registry = self.host.current()
        if registry.workspace_id != UUID(str(workspace_id)):
            raise StaleWriteError('Different Workspace')
        with registry.paper_gate(), registry._repository() as repository:
            paper = repository.get(paper_id)
            if paper.body_generation != body_generation:
                raise StaleWriteError('Body generation changed')
        return self(paper, action=action)

    def __call__(self, paper, *, action='open'):
        if action not in {'open', 'locate', 'delete'} or paper.body is None:
            raise InvalidPaperState('A current body is required')
        with self.host.local_operation(paper, destructive=action == 'delete') as owner:
            owner.task_id = uuid4().hex
            context = dict(request_id=owner.task_id, task_id=owner.task_id, workflow_id='local-body',
                workspace_id=str(paper.workspace_id), paper_id=str(paper.id), action='local_paper_body', stage='attachment')
            observe(self.host.diagnostics, 'event', 'task_started', context)
            result = LocalBodyResult('local_failure')
            try:
                result = self._use(owner, action)
            except StaleWriteError:
                result = LocalBodyResult('stale')
            except OSError:
                result = LocalBodyResult('file_failure')
            finally:
                observe(self.host.diagnostics, 'event', 'task_finished', context | dict(outcome=result.status))
            return result

    @staticmethod
    def _use(owner, action):
        registry, paper = owner.registry, owner.paper
        with CurrentBodyFile(registry.workspace, paper.body, expected_workspace=registry._identity[0]) as file:
            owner.guard()
            if not file.verify():
                return LocalBodyService._missing(owner, file)
            if action == 'delete':
                with registry.paper_gate():
                    owner.guard()
                    file.delete(owner.guard)
                    return LocalBodyService._missing(owner, file, status='deleted')
            with registry.paper_gate():
                owner.guard()
                future = registry.bridge.execute('local_paper_body', dict(action=action,
                    workspace_root=str(registry.workspace), workspace_id=str(paper.workspace_id),
                    paper_id=str(paper.id), body_generation=paper.body_generation, body=file.payload(),
                    workflow_id='local-body', task_id=owner.task_id), verify_recovery=owner.guard)
                if not isinstance(future, Future):
                    raise TypeError('Local body operation requires a native terminal Future')
                owner.native_future = future
            result = future.result()
            if isinstance(result, dict) and result.get('resource_closed') is False:
                owner.cleanup_failed = True
                return LocalBodyResult('local_failure')
            owner.guard()
            present = file.verify()
            outcome = result.get('outcome') if isinstance(result, dict) else None
            if outcome == 'missing' and not present:
                return LocalBodyService._missing(owner, file)
            if not present or outcome != ('opened' if action == 'open' else 'locate_requested'):
                return LocalBodyResult('local_failure')
            return LocalBodyResult(outcome)

    @staticmethod
    def _missing(owner, file, *, status='missing'):
        owner.guard()
        if file.verify():
            raise StaleWriteError('Missing body reappeared')
        with owner.registry.paper_gate(), owner.registry._repository() as repository:
            owner.guard()
            if file.verify():
                raise StaleWriteError('Missing body reappeared')
            try:
                repository.clear_current_body(owner.paper.token, owner.paper.body, require_excluded=owner.destructive)
            except StaleWriteError:
                raise
            except LibraryError:
                return LocalBodyResult('association_failure')
        return LocalBodyResult(status)
