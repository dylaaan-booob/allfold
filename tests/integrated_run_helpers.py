"""Isolated Run transports; helper APIs remain enabled and exercised."""
from allfold.application.integrated_run import run_integrated as production_run
from allfold.providers.integrated import DiscoveryResult


class EmptyCompletion:
    def __init__(self, provider, **kwargs): self.provider=provider
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def lookup_many(self, namespace, ids, **kwargs): return {identity:() for identity in ids}
    def lookup(self,*args): return ()
    def lookup_preprints(self,ids): return {identity:() for identity in ids}


def run_integrated(*args, **kwargs):
    kwargs.setdefault('completion_factory', EmptyCompletion)
    return production_run(*args, **kwargs)
