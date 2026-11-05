"""On-demand DOI PDF lookup with an isolated provider transport."""
import httpx
from allfold.providers.openalex import OpenAlexClient
from allfold.application.import_openalex import lookup_pdf_candidates


def test_doi_lookup_uses_existing_client_and_only_safe_direct_pdf_locations(tmp_path):
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"doi": "https://doi.org/10.5555/fixture",
            "best_oa_location": {"pdf_url": None, "landing_page_url": "https://landing.example"},
            "locations": [{"pdf_url": value} for value in [
                "https://oa.example/a.pdf", "https://oa.example/a.pdf#viewer", "http://127.0.0.1/private.pdf",
                "file:///private.pdf", "https://content.openalex.org/works/W1.pdf", "https://oa.example/b.pdf", *[f"https://oa.example/{i}.pdf" for i in range(8)]]]})
    with OpenAlexClient(api_key="private-key", transport=httpx.MockTransport(respond)) as client:
        result = lookup_pdf_candidates("10.5555/FIXTURE", client=client)
    assert result == {"candidates": ["https://oa.example/a.pdf", "https://oa.example/b.pdf",
                                     "https://oa.example/0.pdf", "https://oa.example/1.pdf"]}
    assert len(seen) == 1
    assert seen[0].url.path == "/works/https://doi.org/10.5555/fixture"
    assert seen[0].headers["Authorization"] == "Bearer private-key"
    assert seen[0].url.params["select"] == "id,doi,best_oa_location,locations"


def test_mismatched_work_and_provider_failure_never_release_candidates():
    for status, payload, code in [(200, {"doi": "10.5555/other", "best_oa_location": {"pdf_url":"https://oa.example/a.pdf"}}, "doi_mismatch"),
                                  (404, {}, "openalex_not_found"), (401, {}, "openalex_authorization_required")]:
        with OpenAlexClient(transport=httpx.MockTransport(lambda _: httpx.Response(status, json=payload))) as client:
            result = lookup_pdf_candidates("10.5555/fixture", client=client)
        assert result == {"candidates": [], "diagnostic": {"code": code}}
