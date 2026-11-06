# Python HTTP and proxies

Project-owned synchronous HTTPX callers use `allfold.http_client.create_http_client`.
It returns a normal owned `httpx.Client`; use `with` or close it after the operation.
Timeouts, redirects, streaming, request errors and Provider retry/pacing logic stay
with HTTPX and the caller. Each client owns its direct/proxy connection pools and
snapshots its configuration at creation. It changes neither `os.environ` nor user
network settings. A failed proxy request never falls back to direct access.

## Configuration

The default `proxy_policy="environment"` reads `urllib.request.getproxies()` once.
This preserves standard-library environment precedence: lowercase overrides
uppercase, including empty lowercase values; CGI ignores uppercase `HTTP_PROXY`.
It also preserves the macOS system-proxy fallback when no environment map is
available. HTTP and HTTPS use their scheme-specific proxy, then `ALL_PROXY`, then
the macOS system SOCKS proxy, then direct access if none is configured. The system
SOCKS fallback is only initialized when a scheme would otherwise lack a proxy.
CPython's `socks` entry uses an `http://` address wrapper; it is normalized to
SOCKS5 without changing the endpoint or credentials. Scheme-less HTTP/HTTPS/ALL
proxy addresses mean HTTP.

HTTPX handles HTTP/HTTPS proxies and CONNECT. SOCKS5/SOCKS5H require HTTPX's optional
`socksio` dependency, absent from the current lock. Missing SOCKS support and
invalid proxy addresses produce explicit, credential-free configuration errors.
No new dependency, proxy UI, PAC evaluator or proxy discovery service is added.

`NO_PROXY`/`no_proxy` is a comma-separated list:

| Rule | Bypass behavior |
| --- | --- |
| `example.com` or `*example.com` | Domain itself and dot-delimited subdomains |
| `.example.com` or `*.example.com` | Subdomains only, preserving HTTPX semantics |
| `localhost` | Exact host only, preserving HTTPX semantics |
| IPv4, IPv6, `[IPv6]` | Exact address, including equivalent IPv6 spellings |
| `192.168.0.0/16`, `fe80::/10`, `[fc00::]/7` | IP literals inside the network; no DNS lookup for domain targets |
| `host:8080`, `[::1]:8080` | Host rule restricted to the target port (including default 80/443) |
| `http://example.com`, `https://example.com:443` | Exact host and optional port restricted to that scheme; `all://` accepts either scheme; explicit wildcards retain their domain meaning |
| `*` | All targets; `*:443` restricts this to one port |

Names are case-insensitive, IDNA-aware and accept a trailing DNS dot. URL-style
rules may end in a single `/`. Malformed entries (including paths, credentials,
invalid prefixes/ports, scoped CIDRs and arbitrary globs) are skipped individually;
they never become broader bypass rules. CIDRs use `ipaddress` with host bits
normalized, and do not accept port suffixes. Even `NO_PROXY=*` does not hide an
invalid proxy-server configuration.

`proxy_policy="direct"` skips proxy discovery. Zotero Local API explicitly uses
this policy and retains `trust_env=False`, no redirects and Server-ID validation.
Other clients retain HTTPX TLS defaults, including `SSL_CERT_FILE`, `SSL_CERT_DIR`
and explicit SSL contexts. `trust_env=False` disables both environmental proxy
discovery and environmental CA handling as in HTTPX. An explicit `transport=`
(including `MockTransport`) bypasses proxy discovery completely and is owned and
closed by the returned client as usual. Standard Client options are forwarded;
`proxy`/`mounts` are excluded to avoid competing routing policies.

## Verification and scope

Run `uv run --locked pytest tests/test_http_client.py tests/test_resource_resolver.py`.
These tests use isolated loopback origins/proxies, a public test-only TLS
certificate, controlled environment variables and transport fixtures. No live
data sources, accounts or Zotero Library are contacted.

This layer applies only to Python. Electron/Chromium has its own Session and
network stack. CARSI first login, SP Cookie expiry and WoS authentication remain
separate manual compatibility checks; this fix makes no claim about their IPv4/
IPv6 behavior. With user authorization, manually check real catalog/GOKB fetches
under the user's proxy and IPv6 CIDRs, direct access where reachable, and record
any Chromium CARSI session failure separately. No particular proxy product or
global IPv6 setting is a prerequisite.

Mechanism references: [HTTPX public transports](https://www.python-httpx.org/advanced/transports/),
[Mistral Vibe explicit proxy transport](https://github.com/mistralai/mistral-vibe/blob/338ad4bf0f73c4dd879d667cf7ab011555ae1751/vibe/utils/http.py),
[HTTPX2 CIDR matching](https://github.com/pydantic/httpx2/pull/1165) and
[invalid-entry handling](https://github.com/pydantic/httpx2/pull/1267).
The [CPython system proxy adapter](https://github.com/python/cpython/blob/v3.12.14/Modules/_scproxy.c)
defines the macOS SOCKS configuration format.
The implementation uses original HTTPX and the standard library; upstream source
is not vendored or modified.

## Integrated Providers

Discovery and identifier-only completion reuse one selected Provider client and
shared per-host pacing. The client handles bounded 429 and temporary
500/502/503/504 retries, Retry-After, cancellation and HTML access restrictions.
Ordinary HTML service errors can be retried. DBLP's known Anubis v1.27.0
metarefresh permits one bounded, cancellable exchange in the same HTTP session;
only valid metadata for the original query establishes recovery. Other recognized
verification pages, or failed recovery, stop that client for the rest of the Run
without changing route or identity.
arXiv ID lookups use a conservative three-second interval; DBLP uses two seconds;
bioRxiv and medRxiv share their API host pacing.
See [Provider contracts and limits](providers.md).
