# bioRxiv and medRxiv DOI path routing

Verified against the public APIs on 2026-11-14. The failure is a path-encoding
problem: the first DOI slash must remain literal, while each later slash must
be sent as `%252F`. Ordinary percent encoding (`%2F`) does not solve this case.

## Community evidence and interface

The official API documents `/pubs/{server}/{DOI}/na/json` for reverse lookup
from a published DOI, followed by `/details/{server}/{preprint DOI}/na/json`
for native versions. It does not document the extra-slash encoding rule.
See [bioRxiv API](https://api.biorxiv.org/) and
[publication endpoint help](https://api.biorxiv.org/pubs/help).

The maintainer of `cyanheads/biorxiv-mcp-server` reported the same second-slash
failure, including an Oxford journal DOI, in
[issue #73](https://github.com/cyanheads/biorxiv-mcp-server/issues/73).
[Issue #74](https://github.com/cyanheads/biorxiv-mcp-server/issues/74) records a
successful reverse lookup for `10.1093/molbev/msag238` when its second slash is
double encoded; the maintainer confirms it shipped in 0.4.2. The current
[DOI path encoder](https://github.com/cyanheads/biorxiv-mcp-server/blob/ff3a064a3e12eee147ee684acf81dbc0f76e6aa4/src/services/biorxiv/biorxiv-service.ts#L226-L240)
retains the registrant separator and joins separately encoded suffix segments
with `%252F`. This is a community client workaround, not published bioRxiv
backend source or an official encoding guarantee.
The client's explanation of two decoding stages is therefore a community
explanation consistent with the observed routing, not verified backend code.

The earlier [issue #1](https://github.com/cyanheads/biorxiv-mcp-server/issues/1)
addresses a different part of the same boundary: encoding the first slash breaks
ordinary preprint DOI routing. Preserving every slash only solves that earlier
case; it does not preserve journal DOIs with additional slashes.

The related [issue #32](https://github.com/cyanheads/biorxiv-mcp-server/issues/32)
documents an availability failure incorrectly presented as an absent DOI.
Encoding repair must preserve the distinction between an exact empty response
and a service, malformed-response or identity failure.

## Direct observations

All requests below were read-only public HTTPS through Allfold's existing
`create_http_client`, without application configuration, accounts or Workspace
data. Every listed response was HTTP 200.

| Request | API result |
| --- | --- |
| [Raw NAR DOI](https://api.biorxiv.org/pubs/biorxiv/10.1093/nar/gkac1225/na/json) | Empty collection, but the status names only `10.1093/nar`; this is not an exact no-match. |
| [Encoded NAR DOI](https://api.biorxiv.org/pubs/biorxiv/10.1093/nar%252Fgkac1225/na/json) | Empty collection; the not-found status names the complete `10.1093/nar/gkac1225`. |
| [Second NAR DOI](https://api.biorxiv.org/pubs/biorxiv/10.1093/nar%252Fgkac1238/na/json) | Empty collection; the not-found status names the complete `10.1093/nar/gkac1238`. |
| [medRxiv NAR lookup](https://api.biorxiv.org/pubs/medrxiv/10.1093/nar%252Fgkac1225/na/json) | Exact complete-DOI not-found, also observed for `gkac1238`. |
| [bioRxiv positive control](https://api.biorxiv.org/pubs/biorxiv/10.1093/molbev%252Fmsag238/na/json) | `ok`; exact `published_doi=10.1093/molbev/msag238`, `preprint_doi=10.1101/2025.10.01.679802`, platform bioRxiv. |
| [medRxiv positive control](https://api.biorxiv.org/pubs/medrxiv/10.1093/ofid%252Fofag649/na/json) | `ok`; exact `published_doi=10.1093/ofid/ofag649`, `preprint_doi=10.64898/2026.04.29.26352095`, platform medRxiv. |
| [Native version and single-slash control](https://api.biorxiv.org/details/biorxiv/10.1101/2025.10.01.679802/na/json) | Unchanged single-slash path; `ok`, one version in the entire returned collection: `1`, date `2025-10-03`, exact native DOI and matching published DOI. No pagination fields. |

Thus the NAR examples establish successful exact identifier lookup with no
recorded publication link, rather than a discovered preprint. The two positive
controls establish that this encoding can also recover real native links.
Empty crosswalk results do not prove a paper was never preprinted.

## Allfold application boundary

Use the native path encoding in `SupplementalClient` for both actual requests
and their provenance URLs. Single-slash native preprint requests keep their
existing paths. Keep exact formal DOI, preprint DOI, platform and native-version
validation; a truncated not-found subject must continue to fail validation.
The existing `/pubs` then `/details` request flow remains sufficient, so this
repair needs no new provider, date-window scan, title matching, retry policy or
identity conversion. Native version 1 remains the first-version proof required
by [provider contracts](providers.md).

During investigation, Crossref's exact reverse relation filter returned
`total-results=0` for both
[gkac1225](https://api.crossref.org/works?filter=relation.type%3Ais-preprint-of%2Crelation.object%3A10.1093%2Fnar%2Fgkac1225&rows=100)
and
[gkac1238](https://api.crossref.org/works?filter=relation.type%3Ais-preprint-of%2Crelation.object%3A10.1093%2Fnar%2Fgkac1238&rows=100).
That was not evidence for a recovered link or a necessary fallback. No browser,
installed Electron workflow or live Paper write was exercised by these API
observations.
