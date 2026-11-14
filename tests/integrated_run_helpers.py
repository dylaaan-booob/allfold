"""Isolated Run transports; drain only at the test boundary, outside foreground Run."""
from allfold.application.integrated_run import run_integrated as production_run
from allfold.providers.integrated import DiscoveryResult


class EmptyLookup:
    def __init__(self, provider, **kwargs): self.provider=provider
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def lookup_many(self, namespace, ids, **kwargs): return {identity:() for identity in ids}
    def lookup(self,*args): return ()
    def lookup_preprints(self,ids): return {identity:() for identity in ids}
    def resolve_pubmed_dois(self, ids): return {identity:() for identity in ids}


def run_integrated(config_path, **kwargs):
    from contextlib import ExitStack
    from allfold.application.run_commit import capture_run_workspace
    from allfold.application.workspace_tasks import WorkspaceTaskHost
    from allfold.application.task_clients import IndependentClientFactory
    if kwargs.get('workspace_tasks') is not None:
        return production_run(config_path, **kwargs)
    kwargs.setdefault('lookup_factory', EmptyLookup)
    with ExitStack() as resources:
        snapshot = kwargs.get('workspace_snapshot') or resources.enter_context(capture_run_workspace(
            config_path, kwargs.get('loaded_config')))
        kwargs['workspace_snapshot'] = snapshot
        factory = IndependentClientFactory(config_path, pacing_state=kwargs.get('pacing_state'),
            client_factory=kwargs['lookup_factory'])
        host = WorkspaceTaskHost(config_path, factory=factory)
        kwargs['workspace_tasks'] = host
        try:
            result = production_run(config_path, **kwargs)
            registry = host.peek()
            if registry is not None:
                # This wrapper deliberately observes background settlement for old
                # library assertions; production HTTP never performs this wait.
                for target in tuple(registry._tasks.values()):
                    target.future.result(15)
            return result
        finally:
            host.shutdown()
            host.join()
            factory.close()
