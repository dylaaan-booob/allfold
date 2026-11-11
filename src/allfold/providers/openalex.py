"""OpenAlex journal lookup and on-demand Import PDF fallback HTTP client."""

from __future__ import annotations

from dataclasses import replace
from enum import Enum
from typing import Any
from urllib.parse import quote

from allfold.identifiers import normalize_doi
from allfold.progress import ActivityKind, ActivityUpdate, ProgressCallback, ProgressEvent
from allfold.providers.provider_http import DiscoveryError, ProviderHTTPError, ProviderReadClient, object_json

OPENALEX_BASE_URL = "https://api.openalex.org"
SOURCE_FIELDS = (
    "id,display_name,issn_l,issn,type,alternate_titles,abbreviated_title,"
    "host_organization,host_organization_name,homepage_url"
)


class OpenAlexError(RuntimeError):
    """Base class for OpenAlex request and response failures."""


class OpenAlexNotFoundError(OpenAlexError):
    """The requested singleton external identifier was not found."""


class OpenAlexFailureKind(str, Enum):
    RECOVERABLE = "recoverable"
    AUTHORIZATION = "authorization"
    QUOTA = "quota"


class OpenAlexRequestError(OpenAlexError):
    """A remote request failed or returned an invalid response."""

    def __init__(self, message: str, *, kind: OpenAlexFailureKind = OpenAlexFailureKind.RECOVERABLE):
        super().__init__(message)
        self.kind = kind


class OpenAlexClient:
    """OpenAlex endpoints outside Run share the same HTTP policy and cooldowns."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = OPENALEX_BASE_URL,
        **http_options,
    ) -> None:
        self.api_key = api_key.strip() if api_key and api_key.strip() else None
        self.base_url = base_url.rstrip("/")
        self._reader = ProviderReadClient('openalex', **http_options)
        self._access_denial: OpenAlexRequestError | None = None

    def close(self) -> None:
        self._reader.http.close()

    def __enter__(self) -> OpenAlexClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def get_work_by_doi(self, doi: str) -> dict[str, Any]:
        """Retrieve one exact DOI work for the on-demand Import PDF fallback."""
        normalized = normalize_doi(doi)
        if normalized is None:
            raise ValueError("Invalid DOI")
        return self._request_json(
            f"/works/https://doi.org/{quote(normalized, safe='/')}",
            {"select": "id,doi,best_oa_location,locations"},
            not_found_message="DOI is not present in OpenAlex",
        )

    def get_source_by_issn(
        self,
        issn: str,
        *,
        progress_callback: ProgressCallback | None = None,
        activity: ActivityUpdate | None = None,
    ) -> dict[str, Any]:
        if activity is None and progress_callback is not None:
            activity = ActivityUpdate(
                kind=ActivityKind.WORKING,
                source="openalex",
                operation="source_resolution",
                label="Resolving OpenAlex source",
                detail=f"ISSN {issn}",
                unit="issn",
            )
        return self._request_json(
            f"/sources/issn:{issn}",
            {"select": SOURCE_FIELDS},
            not_found_message=f"ISSN {issn} is not present in OpenAlex",
            progress_callback=progress_callback,
            activity=activity,
        )

    def search_sources(self, query: str) -> dict[str, Any]:
        return self._request_json("/sources", {
            "search": query, "filter": "type:journal", "select": SOURCE_FIELDS, "per_page": "50",
        })

    def _request_json(
        self,
        path: str,
        params: dict[str, str],
        *,
        not_found_message: str | None = None,
        progress_callback: ProgressCallback | None = None,
        activity: ActivityUpdate | None = None,
    ) -> dict[str, Any]:
        if self._access_denial is not None:
            raise self._access_denial
        headers = {"Accept": "application/json", "User-Agent": "allfold/0.1.0"}
        if self.api_key is not None:
            headers["Authorization"] = f"Bearer {self.api_key}"

        def prepare():
            return self._reader.http.build_request('GET', self.base_url + path, params=params, headers=headers)

        def report(kind, label, detail):
            if progress_callback is None or activity is None:
                return
            progress_callback(ProgressEvent(activity=replace(
                activity, kind=kind, label=label or (
                    'Requesting OpenAlex' if detail == 'Request dispatched' else 'Received OpenAlex response'),
                detail=f'{activity.detail} · {detail}' if activity.detail else detail,
            )))

        try:
            return self._reader.read(prepare, self._reader.operation(report),
                decode=lambda response: object_json('OpenAlex', response), follow_redirects=True)
        except ProviderHTTPError as error:
            if error.status == 404 and not_found_message is not None:
                raise OpenAlexNotFoundError(not_found_message) from None
            kind = (OpenAlexFailureKind.AUTHORIZATION if error.status in {401, 403} else
                    OpenAlexFailureKind.QUOTA if error.status == 402 else OpenAlexFailureKind.RECOVERABLE)
            failure = OpenAlexRequestError(str(error), kind=kind)
            if kind is not OpenAlexFailureKind.RECOVERABLE:
                self._access_denial = failure
            raise failure from None
        except DiscoveryError as error:
            raise OpenAlexRequestError(str(error)) from None
