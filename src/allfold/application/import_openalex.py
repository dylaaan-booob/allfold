"""One on-demand OpenAlex lookup; credentials and provider HTTP stay in Python."""
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from allfold.identifiers import normalize_doi
from allfold.integrations.openalex_credentials import read_credential
from allfold.providers.openalex import (
    OpenAlexClient, OpenAlexNotFoundError, OpenAlexRequestError, OpenAlexFailureKind,
)
from allfold.url_safety import normalize_public_http_url

MAX_PDF_CANDIDATES = 4


def lookup_pdf_candidates(doi: str, *, config_path: Path | None = None,
                          client: OpenAlexClient | None = None, cancel_event=None, recovery_observer=None,
                          deadline: float | None = None) -> dict:
    """Return bounded direct PDF URLs only, never landing pages or provider secrets."""
    if client is None:
        try:
            key, _ = read_credential(config_path, provider="openalex")
            with OpenAlexClient(api_key=key, cancel_event=cancel_event, recovery_observer=recovery_observer,
                                deadline=deadline) as owned:
                return lookup_pdf_candidates(doi, client=owned)
        except (OSError, ValueError):
            return {"candidates": [], "diagnostic": {"code": "openalex_credential_unavailable"}}
    try:
        work = client.get_work_by_doi(doi)
    except OpenAlexNotFoundError:
        return {"candidates": [], "diagnostic": {"code": "openalex_not_found"}}
    except OpenAlexRequestError as error:
        code = {OpenAlexFailureKind.AUTHORIZATION: "authorization_required",
                OpenAlexFailureKind.QUOTA: "quota"}.get(error.kind, "lookup_failed")
        return {"candidates": [], "diagnostic": {"code": "openalex_" + code}}
    try:
        matches = normalize_doi(work.get("doi")) == normalize_doi(doi)
    except ValueError:
        matches = False
    if not matches:
        return {"candidates": [], "diagnostic": {"code": "doi_mismatch"}}
    locations = [work.get("best_oa_location"), *(work.get("locations") if isinstance(work.get("locations"), list) else [])]
    candidates = []
    for location in locations:
        value = location.get("pdf_url") if isinstance(location, dict) else None
        if not isinstance(value, str):
            continue
        try:
            url = normalize_public_http_url(value)
            if not url:
                continue
            parsed = urlsplit(url)
            if parsed.hostname == 'openalex.org' or parsed.hostname.endswith('.openalex.org'):
                continue  # OpenAlex hosted-content downloads are outside this fallback.
            url = urlunsplit(parsed._replace(fragment=''))
        except ValueError:
            continue
        if url and url not in candidates:
            candidates.append(url)
        if len(candidates) == MAX_PDF_CANDIDATES:
            break
    return {"candidates": candidates} if candidates else {"candidates": [], "diagnostic": {"code": "openalex_no_pdf"}}
