"""OpenAlex journal lookup and on-demand Import PDF fallback HTTP client."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import replace
from enum import Enum
from typing import Any
from urllib.parse import urlencode, quote

import httpx

from allfold.http_client import create_http_client
from allfold.identifiers import normalize_doi
from allfold.progress import ActivityKind, ActivityUpdate, ProgressCallback, ProgressEvent

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
    CIRCUIT_OPEN = "circuit_open"


class OpenAlexRequestError(OpenAlexError):
    """A remote request failed or returned an invalid response."""

    def __init__(self, message: str, *, kind: OpenAlexFailureKind = OpenAlexFailureKind.RECOVERABLE):
        super().__init__(message)
        self.kind = kind

    @property
    def terminal(self) -> bool:
        return self.kind is not OpenAlexFailureKind.RECOVERABLE


def _report_activity(
    callback: ProgressCallback | None,
    activity: ActivityUpdate | None,
) -> None:
    if callback is not None and activity is not None:
        callback(ProgressEvent(activity=activity))


class OpenAlexClient:
    """Own one pooled HTTP client; close it after each execution, usually with `with`."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = OPENALEX_BASE_URL,
        timeout: float = 30,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key.strip() if api_key and api_key.strip() else None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http_client = create_http_client(
            transport=transport,
            timeout=timeout,
            follow_redirects=True,
        )
        self._sleep = sleep
        self._terminal_failure: OpenAlexRequestError | None = None

    def close(self) -> None:
        self._http_client.close()

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
        if self._terminal_failure is not None:
            raise OpenAlexRequestError(
                "OpenAlex execution circuit is open", kind=OpenAlexFailureKind.CIRCUIT_OPEN,
            ) from self._terminal_failure
        url = f"{self.base_url}{path}?{urlencode(params)}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "allfold/0.1.0",
        }
        if self.api_key is not None:
            headers["Authorization"] = f"Bearer {self.api_key}"

        for attempt in range(3):
            attempt_number = attempt + 1
            if activity is not None:
                _report_activity(
                    progress_callback,
                    replace(
                        activity,
                        kind=ActivityKind.WORKING,
                        label="Requesting OpenAlex",
                        detail=(
                            f"{activity.detail} · attempt {attempt_number}/3"
                            if activity.detail
                            else f"attempt {attempt_number}/3"
                        ),
                    ),
                )
            try:
                response = self._http_client.get(url, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                payload = json.loads(response.content)
                if not isinstance(payload, dict):
                    raise OpenAlexRequestError("OpenAlex returned a non-object JSON response")
                if activity is not None:
                    _report_activity(
                        progress_callback,
                        replace(
                            activity,
                            kind=ActivityKind.WORKING,
                            label="Received OpenAlex response",
                            detail=(
                                f"{activity.detail} · attempt {attempt_number}/3"
                                if activity.detail
                                else f"attempt {attempt_number}/3"
                            ),
                        ),
                    )
                return payload
            except httpx.HTTPStatusError as error:
                status_code = error.response.status_code
                if status_code == 404 and not_found_message is not None:
                    raise OpenAlexNotFoundError(not_found_message) from error
                if (status_code == 429 or status_code >= 500) and attempt < 2:
                    delay = 2**attempt
                    if activity is not None:
                        # retry 事件必须先于 sleep，避免 backoff 被误判成无活动。
                        _report_activity(
                            progress_callback,
                            replace(
                                activity,
                                kind=ActivityKind.RETRYING,
                                label="Retrying OpenAlex request",
                                detail=(
                                    f"{activity.detail} · HTTP {status_code} · "
                                    f"backoff {delay}s"
                                    if activity.detail
                                    else f"HTTP {status_code} · backoff {delay}s"
                                ),
                            ),
                        )
                    self._sleep(delay)
                    continue
                kind = (OpenAlexFailureKind.AUTHORIZATION if status_code in {401, 403}
                        else OpenAlexFailureKind.QUOTA if status_code in {402, 429}
                        else OpenAlexFailureKind.RECOVERABLE)
                failure = OpenAlexRequestError(f"OpenAlex request failed with HTTP {status_code}", kind=kind)
                if failure.terminal:
                    self._terminal_failure = failure
                raise failure from error
            except httpx.RequestError as error:
                if attempt < 2:
                    delay = 2**attempt
                    if activity is not None:
                        _report_activity(
                            progress_callback,
                            replace(
                                activity,
                                kind=ActivityKind.RETRYING,
                                label="Retrying OpenAlex request",
                                detail=(
                                    f"{activity.detail} · transport failure · "
                                    f"backoff {delay}s"
                                    if activity.detail
                                    else f"transport failure · backoff {delay}s"
                                ),
                            ),
                        )
                    self._sleep(delay)
                    continue
                raise OpenAlexRequestError(f"OpenAlex request failed: {error}") from error
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise OpenAlexRequestError("OpenAlex returned invalid JSON") from error

        raise AssertionError("unreachable")
