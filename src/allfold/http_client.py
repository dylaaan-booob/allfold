"""Synchronous HTTPX clients with per-request environment/system proxy routing.

Only this module interprets proxy configuration. Explicit transports retain
HTTPX's injection semantics and never consult proxy settings. No process state
is changed, and a failed proxy request is never retried through a direct route.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import ipaddress
import re
from typing import Literal
import urllib.request

import httpx


class ProxyConfigurationError(httpx.InvalidURL):
    """Invalid proxy configuration, with a message safe for diagnostics."""


@dataclass(frozen=True)
class _BypassRule:
    host: str = ""
    mode: Literal["exact", "domain", "subdomains", "all"] = "exact"
    network: ipaddress.IPv4Network | ipaddress.IPv6Network | None = None
    scheme: str | None = None
    port: int | None = None

    def matches(self, url: httpx.URL) -> bool:
        if self.scheme is not None and self.scheme != url.scheme:
            return False
        port = url.port or {"http": 80, "https": 443}.get(url.scheme)
        if self.port is not None and self.port != port:
            return False
        host = url.raw_host.decode("ascii").removesuffix(".").lower()
        if self.network is not None:
            try:
                return ipaddress.ip_address(host) in self.network
            except ValueError:
                return False  # Never resolve DNS to decide whether to bypass.
        if self.mode == "all":
            return True
        if self.mode != "subdomains" and host == self.host:
            return True
        return self.mode in ("domain", "subdomains") and host.endswith("." + self.host)


def _bypass_rule(value: str) -> _BypassRule | None:
    """Accept only complete rules; malformed entries cannot widen bypass scope."""
    value = value.strip()
    if not value or re.search(r"\s|[?#@\\%]", value):
        return None
    scheme = None
    explicit_scheme = "://" in value
    if explicit_scheme:
        scheme, value = value.split("://", 1)
        scheme = scheme.lower()
        if scheme not in ("http", "https", "all"):
            return None
        scheme = None if scheme == "all" else scheme
        if value.count("/") == 1:
            value = value.removesuffix("/")

    # Networks have exactly one numeric prefix; ports on CIDRs are ambiguous.
    if "/" in value:
        match = re.fullmatch(r"(\[[0-9a-fA-F:]+\]|[^\[\]/]+)/([0-9]+)", value)
        if match is None:
            return None
        address, prefix = match.groups()
        try:
            network = ipaddress.ip_network(f"{address.strip('[]')}/{prefix}", strict=False)
        except ValueError:
            return None
        return _BypassRule(network=network, scheme=scheme)

    port = None
    if value.startswith("["):
        match = re.fullmatch(r"\[([^\]]+)\](?::([0-9]+))?", value)
        if match is None:
            return None
        value, raw_port = match.groups()
        if raw_port and len(raw_port) > 5:
            return None
        port = int(raw_port) if raw_port else None
        try:
            ipaddress.IPv6Address(value)
        except ValueError:
            return None
    elif value.count(":") == 1:
        value, raw_port = value.split(":")
        if len(raw_port) > 5 or not raw_port.isascii() or not raw_port.isdigit():
            return None
        port = int(raw_port)
    if port is not None and not 1 <= port <= 65535:
        return None
    if value == "*":
        return _BypassRule(mode="all", scheme=scheme, port=port)
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        address = None
    if address is not None:
        return _BypassRule(network=ipaddress.ip_network(address), scheme=scheme, port=port)
    if ":" in value or "[" in value or "]" in value:
        return None

    # HTTPX: a bare domain includes its subdomains; a leading dot excludes
    # the apex. URL-style entries are exact unless a wildcard is explicit.
    mode = "exact" if explicit_scheme or value.lower() == "localhost" else "domain"
    if value.startswith("*.") or value.startswith("."):
        mode, value = "subdomains", value.removeprefix("*").removeprefix(".")
    elif value.startswith("*"):
        mode, value = "domain", value[1:]
    try:
        host = value.removesuffix(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    if not host or any(not re.fullmatch(r"[a-z0-9_](?:[a-z0-9_-]*[a-z0-9_])?", label)
                       for label in host.split(".")):
        return None
    return _BypassRule(host=host, mode=mode, scheme=scheme, port=port)


def _proxy(value: str, scheme: str) -> httpx.Proxy:
    # HTTPX accepts scheme-less proxies from getproxies() as HTTP proxies.
    try:
        if re.search(r"\s", value) or value.endswith(":"):
            raise ValueError
        url = httpx.URL(value if "://" in value else f"http://{value}")
        if (not url.host or url.port is not None and not 1 <= url.port <= 65535
                or url.path != "/" or url.query or url.fragment
                or url.netloc.endswith(b":")):
            raise ValueError
        return httpx.Proxy(url)
    except (ValueError, httpx.InvalidURL):
        # Never expose URLs, credentials or the contents of the proxy map.
        raise ProxyConfigurationError(f"Invalid {scheme.upper()}_PROXY configuration") from None


class _EnvironmentProxyTransport(httpx.BaseTransport):
    def __init__(self, **options):
        settings = urllib.request.getproxies()
        proxies = {scheme: _proxy(settings[scheme], scheme) for scheme in ("http", "https", "all")
                   if settings.get(scheme)}
        self._bypass = tuple(rule for value in settings.get("no", "").split(",")
                             if (rule := _bypass_rule(value)) is not None)
        self._resources = ExitStack()
        try:
            self._direct = httpx.HTTPTransport(**options)
            self._resources.callback(self._direct.close)
            self._proxies = {}
            for scheme, proxy in proxies.items():
                try:
                    transport = httpx.HTTPTransport(proxy=proxy, **options)
                except ImportError:
                    raise ProxyConfigurationError(
                        f"{scheme.upper()}_PROXY requires HTTPX's optional SOCKS dependency (socksio)"
                    ) from None
                self._resources.callback(transport.close)
                self._proxies[scheme] = transport
        except BaseException:
            self._resources.close()
            raise

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if any(rule.matches(request.url) for rule in self._bypass):
            transport = self._direct
        else:
            transport = self._proxies.get(request.url.scheme, self._proxies.get("all", self._direct))
        return transport.handle_request(request)

    def close(self) -> None:
        self._resources.close()


def create_http_client(*, proxy_policy: Literal["environment", "direct"] = "environment",
                       transport: httpx.BaseTransport | None = None, **options) -> httpx.Client:
    """Create an owned HTTPX client; callers close it normally or use ``with``.

    ``environment`` snapshots stdlib getproxies() per client (lowercase wins,
    macOS system fallback). ``direct`` never reads proxy settings. ``trust_env``
    still controls HTTPX's TLS environment handling; False also disables proxies.
    An injected transport is used unchanged, without reading any proxy settings.
    Normal Client options are forwarded, except proxy/mounts: choose a policy or
    supply a transport instead of combining competing routing mechanisms.
    """
    if proxy_policy not in ("environment", "direct"):
        raise ValueError("Unknown HTTP proxy policy")
    if "proxy" in options or "mounts" in options:
        raise ValueError("Use proxy_policy or transport to configure HTTP routing")
    if transport is not None:
        return httpx.Client(transport=transport, **options)
    transport_options = {key: options[key] for key in ("verify", "cert", "trust_env", "http1", "http2", "limits")
                         if key in options}
    if proxy_policy == "environment" and options.get("trust_env", True):
        owned = _EnvironmentProxyTransport(**transport_options)
    else:
        owned = httpx.HTTPTransport(**transport_options)
    try:
        # An explicit transport prevents HTTPX 0.28 from constructing its broken
        # NO_PROXY URLPattern map, while leaving TLS trust_env enabled as before.
        return httpx.Client(transport=owned, **options)
    except BaseException:
        owned.close()
        raise
