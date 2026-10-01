"""
SSRF / public-host protection for asset fetching.

Nothing in this codebase does this yet (confirmed by searching the whole
repo) - this is written fresh, not reused from anything, despite the
Website Intelligence & Asset Pipeline ticket's wording ("keep SSRF/public-
host protections from the temporary cache path"). If that code exists on
a teammate's branch, prefer wiring into that instead of this.

Approach: resolve the hostname ourselves and check the actual IP address
against private/loopback/link-local/reserved ranges - checking the
hostname string alone (e.g. blocking "localhost") is not enough, since a
public-looking hostname can resolve to an internal address, and a
redirect can point anywhere. So every hop must be re-validated, not just
the first URL.
"""

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}


class SSRFBlockedError(Exception):
    """Raised when a URL (or a redirect target) resolves to a non-public address."""


def _is_public_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local  # covers 169.254.169.254 cloud metadata
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_safe_url(url: str) -> None:
    """
    Raises SSRFBlockedError if `url` is not safe to fetch. Call this on
    the original URL AND on every redirect target before following it.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SSRFBlockedError(f"Scheme not allowed: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFBlockedError("URL has no hostname")

    if hostname.lower() == "localhost":
        raise SSRFBlockedError("localhost is not allowed")

    try:
        # getaddrinfo resolves via the OS resolver and returns every
        # address family the host has - check all of them, since only
        # one needs to be internal for this to be an SSRF vector.
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SSRFBlockedError(f"Could not resolve host: {hostname}") from exc

    resolved_ips = {info[4][0] for info in addr_info}

    for ip_str in resolved_ips:
        if not _is_public_ip(ip_str):
            raise SSRFBlockedError(
                f"{hostname} resolves to a non-public address ({ip_str})"
            )