"""Reject crawl and HEAD targets that point at the local machine or a private net."""
import ipaddress
from urllib.parse import urlparse


_LOCAL_NAMES = {"localhost", "localhost.localdomain"}


def is_public_http_url(url: str) -> bool:
    """True for http(s) URLs whose host is not loopback, link-local, or RFC 1918.

    Hostnames are not resolved. An IP literal is classified with the standard
    library. ``localhost`` is refused. A public https URL is allowed.
    """
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.hostname
    if not host:
        return False
    host = host.strip("[]").lower().rstrip(".")
    if host in _LOCAL_NAMES or host.endswith(".localhost"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        return False
    return True
