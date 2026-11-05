from functools import partial

import httpx
import pytest

from allfold.application.integrated_run import run_integrated
from allfold.config import JournalConfig, render_settings_list_text
from allfold.providers.integrated import DiscoveryClient
from allfold.providers.supplemental import SupplementalClient


@pytest.mark.parametrize("formal_date, expected", [("2026-10-01", 0), ("2026-02-01", 1), (None, 1)])
def test_year_candidate_uses_confirmed_same_version_date_before_creation(tmp_path, monkeypatch, formal_date, expected):
    config = tmp_path / "monitor.yaml"
    config.write_text("keyword_expression: learning\noutput_dir: workspace\nfrom_month: 2026-01\n"
                      "to_month: 2026-03\nenabled_providers: [dblp, crossref]\n")
    scope = tmp_path / "list.md"
    scope.write_text(render_settings_list_text(None, (JournalConfig(name="Journal of Machine Learning Research", issn="1532-4435"),),
        path=scope, groups=(), custom_labels=(), access_services=()))
    def response(request):
        if request.url.host == "dblp.org":
            return httpx.Response(200, json={"result": {"hits": {"@total": "1", "@computed": "1", "@first": "0",
                "hit": [{"info": {"key": "journals/jmlr/Example26", "title": "Learning", "year": "2026", "doi": "10.5555/formal"}}]}}})
        doi = request.url.path.removeprefix("/works/")
        preprint = doi.endswith("preprint")
        day = [2022, 1, 1] if preprint else [int(part) for part in formal_date.split("-")] if formal_date else None
        return httpx.Response(200, json={"message": {"DOI": doi, "title": ["Learning"],
            "type": "posted-content" if preprint else "journal-article",
            "container-title": [] if preprint else ["Journal of Machine Learning Research"],
            **({"published-online": {"date-parts": [day]}} if day else {}), "ISSN": ["1532-4435"],
            "relation": {} if preprint else {"has-preprint": [{"id-type": "doi", "id": "10.5555/preprint"}]}}})
    monkeypatch.setattr("allfold.providers.supplemental.SupplementalClient", partial(SupplementalClient,
        transport=httpx.MockTransport(response), interval=0))
    result = run_integrated(config, client_factory=partial(DiscoveryClient, transport=httpx.MockTransport(response), interval=0))
    assert result.created_papers == expected
    assert len(tuple((tmp_path / "workspace" / "Papers").glob("*.md"))) == expected
    if expected:
        saved = next((tmp_path / "workspace" / "Papers").glob("*.md")).read_text()
        assert "first_public_at: '2022-01-01'" in saved


def test_one_valid_source_hit_keeps_work_when_another_version_is_outside_range():
    from datetime import date, datetime, timezone
    from allfold.application.source_dates import filter_source_dates
    from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
    def record(provider, doi, date_value, role):
        return ProviderWorkEvidence(provenance=MetadataSource(provider=provider, record_id=doi,
            retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc), role=role),
            external_ids=ExternalIds(doi=doi, openalex="W123"), title="Title", journal="Journal",
            publication_type="journal", publication_date=date_value)
    outside = record("dblp", "10.5555/out", "2026", "discovery")
    exact = record("crossref", "10.5555/out", "2026-10-01", "supplement")
    inside = record("europe_pmc", "10.5555/in", "2026-02-01", "discovery")
    result = filter_source_dates((outside, exact, inside), date(2026, 1, 1), date(2026, 3, 31))
    assert result.excluded == 1 and inside in result.records and outside not in result.records
