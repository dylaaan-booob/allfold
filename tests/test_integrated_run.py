from datetime import date, datetime, timezone
from dataclasses import replace
from pathlib import Path

from allfold.config import load_config, JournalConfig, render_settings_list_text
from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
from allfold.providers.integrated import DiscoveryResult


def config(tmp_path, enabled=('europe_pmc','dblp')):
    path=tmp_path/'monitor.yaml'
    path.write_text('keyword_expression: learning\noutput_dir: workspace\nfrom_month: 2026-01\nto_month: 2026-03\n')
    scope=tmp_path/'list.md'
    scope.write_text(render_settings_list_text(None,(JournalConfig(name='Test',issn='0006-341X'),),path=scope,groups=(),custom_labels=(),access_services=()))
    return path,replace(load_config(path), enabled_providers=enabled)


def test_only_selected_discovery_providers_run_and_one_failure_preserves_hits(tmp_path):
    from allfold.application.integrated_run import discover_selected
    path,settings=config(tmp_path)
    calls=[]
    class Client:
        def __init__(self,provider,**kwargs): self.provider=provider;calls.append(provider)
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def discover(self,source,*a):
            if self.provider=='dblp':return DiscoveryResult('dblp',source,'failed',limitations=('Access limited',))
            record=ProviderWorkEvidence(title='Native result',journal='Test',external_ids=ExternalIds(europe_pmc='MED:42'),provenance=MetadataSource(provider='europe_pmc',record_id='MED:42',retrieved_at=datetime.now(timezone.utc)))
            return DiscoveryResult(self.provider,source,'complete',(record,),candidates=1,total=1)
    result=discover_selected(settings,path,client_factory=Client)
    assert sorted(calls)==['dblp','europe_pmc']
    assert result.status=='partial'
    assert len(result.records)==1
    assert {r.status for r in result.providers}=={'complete','failed'}
