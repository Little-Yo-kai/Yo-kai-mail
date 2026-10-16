"""
SSRF / public-host protection for asset fetching.

Approach: resolve the hostname ourselves and check the actual IP address
against private/loopback/link-local/reserved ranges - checking the
hostname string alone (e.g. blocking "localhost") is not enough, since a
public-looking hostname can resolve to an internal address, and a
redirect can point anywhere. So every hop must be re-validated, not just
the first URL.
"""

import ipaddress
import re
import socket
from urllib.parse import quote, urljoin, urlparse

ALLOWED_SCHEMES = {"http", "https"}


class SSRFBlockedError(Exception):
    """Raised when a URL (or a redirect target) resolves to a non-public address."""


def normalize_public_asset_url(value, base_url: str | None = None) -> str | None:
    """Normalize scraped image URLs without making network requests.

    This rejects unsafe URL syntax and local destinations that are evident
    without DNS. Fetchers must still check DNS on every redirect using
    ``assert_safe_url``; normalization does not prove public reachability.
    HTTP remains accepted for legacy sources cached into inline attachments.
    """
    if not isinstance(value, str) or any(
        ord(char) < 32 or ord(char) == 127 or char == "\\" for char in value
    ):
        return None

    value = value.strip()
    if not value or value.startswith("#"):
        return None

    try:
        parsed = urlparse(urljoin(base_url or "", value))
        hostname = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port  # Also rejects malformed/out-of-range ports.
        if (
            parsed.scheme not in ALLOWED_SCHEMES
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or hostname == "localhost"
            or hostname.endswith((".localhost", ".local"))
        ):
            return None

        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            hostname = hostname.encode("idna").decode("ascii")
            if (
                "." not in hostname
                or not re.fullmatch(r"[a-z0-9.-]+", hostname)
                # Resolvers may interpret shorthand/octal IPv4 as loopback.
                or re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*", hostname)
            ):
                return None
        else:
            if not _is_public_ip(str(ip)):
                return None
            hostname = f"[{hostname}]" if ip.version == 6 else hostname

        netloc = hostname + (f":{port}" if port is not None else "")
        return parsed._replace(
            netloc=netloc,
            path=quote(parsed.path, safe="/%:@!$&'()*+,;=-._~"),
            query=quote(parsed.query, safe="%=&?/:@!$'()*+,;~-._"),
        ).geturl()
    except (ValueError, UnicodeError):
        return None


def _is_public_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return ip.is_global and not (
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
    normalized = normalize_public_asset_url(url)
    if not normalized:
        raise SSRFBlockedError("URL is not a safe public HTTP(S) destination")
    parsed = urlparse(normalized)

    hostname = parsed.hostname
    if not hostname:
        raise SSRFBlockedError("URL has no hostname")

    try:
        # getaddrinfo resolves via the OS resolver and returns every
        # address family the host has - check all of them, since only
        # one needs to be internal for this to be an SSRF vector.
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SSRFBlockedError(f"Could not resolve host: {hostname}") from exc

    resolved_ips = {info[4][0] for info in addr_info}
    if not resolved_ips:
        raise SSRFBlockedError(f"Could not resolve host: {hostname}")

    for ip_str in resolved_ips:
        if not _is_public_ip(ip_str):
            raise SSRFBlockedError(
                f"{hostname} resolves to a non-public address ({ip_str})"
            )
