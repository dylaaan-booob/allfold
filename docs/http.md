# Python HTTP and proxies

Project-owned synchronous HTTPX callers use `allfold.http_client.create_http_client`.
It returns an owned `httpx.Client`. Use `with` or close it after the operation.
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

`proxy_policy="direct"` skips proxy discovery. The retired Zotero Local API no
longer creates a client or exposes a business endpoint.
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
The deadline transport uses HTTPX's asynchronous transport and the already
locked AnyIO [shared blocking portal](https://anyio.readthedocs.io/en/stable/threads.html#starting-an-on-demand-shared-blocking-portal).

## Journal Run and native preprint APIs

Run, the Info preprint lookup and independent collection attempts use owned
clients over the shared HTTP policy and application-owned pacing. The application
injects the same pacing state into each creation path; another Run, client or
attempt does not reset the actual-origin spacing. Request and adapter caches stay
within their owning operation/attempt, rather than becoming global caches.
Network requests hold no Workspace write lock.
Run reuses verified DOI/Work evidence across Discovery and metadata completion.
It batches quoted PubMed article identifiers after saved-Paper exclusion,
checking each returned PMID against its direct DOI and reusing fetched records.

Exact identifier batches use capability-aware caches. PubMed EFetch can satisfy
ESummary goals, and ESummary supports date/relationship lookups. OpenAlex full
locations are required for full-detail reuse. Shared host locks reserve pacing
across parallel producers and locators. PubMed uses 0.35-second anonymous or
0.11-second keyed spacing. Keys travel in form POST without redirects. Anonymous
OpenAlex basic first-page access reports incomplete coverage if further cursor
paging needs a key.

Discovery, Completion and standalone OpenAlex reads use one request policy.
Safe reads include PubMed's existing read-only form POST. Connect, read and
write timeouts, ordinary connect/read/write transport failures, and HTTP
429/500/502/503/504 are eligible for up to three regular attempts. TLS,
permanent DNS, proxy authentication, other protocol/configuration failures,
and invalid Provider data stop the request. Retry delays are 5 and 10 seconds
for ordinary transient failures, or 1 and 2 seconds for a 429 without a valid
Retry-After, plus up to 25% jitter. Waits are cancellable and recheck the
caller's authority.

The Python application process owns in-memory cooldowns across its Provider
clients. The actual request origin and authentication context determine scope.
bioRxiv and medRxiv share their API origin. Discovery/Completion and standalone
OpenAlex share a cooldown when they use the same origin and credential. The
scope of a redirect uses the headers HTTPX prepared for that hop. HTTP 429
and transient server statuses with a valid Retry-After extend only their scope.
Retry-After accepts delta-seconds and HTTP dates. The deadline can only move
later while active, even if the sender has exhausted its attempts. Responses
already in flight keep their own deadlines. New dispatches recheck the cooldown after
waiting. Expired entries are discarded, and process exit clears the in-memory
state.

The 90-second logical request budget begins with the first attempt and covers
pacing, backoff, cooldown, redirects and any final Completion check. A shorter
caller deadline takes precedence. Provider clients keep synchronous request and
response hooks and opt in to cancellable I/O through HTTPX's async transport.
Connection setup, waiting for headers and blocked body reads use the remaining
time from the same absolute deadline. Expiry cancels the active I/O, releases
the response and prevents another attempt. A cooldown already published from
response headers remains in force. If a cooldown cannot fit, the current
operation ends. Final Completion settlement can send the exact
failed prepared request once, with its original budget, successful cached
prefixes and the redirect's applied authorization policy. Counts include each
physical dispatch, including redirects and the final check. Cache hits and
attempts stopped before dispatch add no requests.

Recognized verification pages stop the client. OpenAlex explicit authorization
and quota errors stop the standalone client. Ordinary 429 responses remain
transient. Invalid envelopes, Entrez application errors, wrong identities and
shortened pages are explicit failures or incomplete results. Valid empty exact
responses count as no-match.

arXiv uses a three-second interval; bioRxiv and medRxiv share their API host
pacing. Browser/Prepare continue to use their separate Chromium Session. Active
webpage Enrich and its Translator transport are retired; Provider HTTP remains
independent of Browser authentication.
See [Provider contracts and limits](providers.md).

`IndependentClientFactory.open` creates one worker-owned context with its own
clients, request cache, captured cancellation/authority and absolute deadline.
The runtime owns the corresponding thread-confined repository connections and
Workspace/Paper/attempt checks; the HTTP factory never borrows a returned Run's
snapshot, connection, cancellation event or `ExitStack`. Provider credentials are
captured when the context opens, and the supplied guard runs before client use
and every physical request. Existing adapter selection, request budgets,
Retry-After, redirects and cooldown authentication scopes remain unchanged.
Injected transports keep their existing isolated cooldown state unless a test
explicitly shares it. Factory close stops new contexts and waits for existing
contexts to close after runtime cancellation/drain. It does not treat a cancelled
Future or a returned business result as resource settlement. This internal
factory does not register production Run Papers or execute the full ordinary
metadata-completion workflow; WF06 supplies the collection branches.


## Local task cancellation and configuration writes

The loopback `POST /api/ui-next/run/cancel` and legacy
`POST /api/ui-next/run-wos/cancel` require CSRF plus a nonempty captured `task_id`.
Missing identity is a validation error; a stale/nonrunning identity returns 409
with `accepted: false`. The coordinator compares and sets cancellation under one
lock and forwards the captured same ID to WoS after releasing it. Shutdown has its
own internal drain and does not use an identity-free public cancellation action.
Login and Covers continue to require their captured workflow/request identities.

Ordinary settings autosave preserves revision checks and retained drafts. An
independent Browser owner no longer blocks unrelated patches. Overlapping access
changes and foreground Run/WoS/Preprint snapshot writers return `TASK_ACTIVE` until
the affected work settles. Saved access changes clean only captured old native
keys; the HTTP worker awaits cleanup outside configuration/database locks.
Authenticated native `access_pages_closed` notifications revoke exact retained
Page authority. Internal `release_workflow_pages` carries the completed WoS
workflow/task identity and runs outside its cancelled execution authority; its
settlement precedes Python owner release. It cannot release another workflow loan. Browser revision/correlation data grants no Page or access rights.

## Browser resource configuration and native maintenance

Settings projection/autosave uses `managed_page_global_limit` (16, 4–64) and
`managed_page_service_limit` (4, 3–16), independently of Prepare worker concurrency.
Successful saves publish one effective pair through authenticated `page_limits`;
ordinary workflow payloads cannot alter it. Invalid drafts and stale revisions
preserve the existing saved values and draft/conflict behavior.

Authenticated native `invalidate_access` takes a scope plus captured old
preparation-key map/authentication key, and closes only matching contexts after
scoped admission. `release_workflow_pages` takes captured workflow/task IDs and
idempotently releases only that results-page loan. Actual retained-page destruction
reports bounded exact Page IDs through `access_pages_closed`. Keys are authority
inputs, never diagnostic fields. See [resource limits and rollback](browser-pages.md).
