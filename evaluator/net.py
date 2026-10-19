"""SSRF checks for caller-supplied target URLs."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urljoin, urlparse


class UnsafeTargetUrl(Exception):
    pass


def allowed_hosts() -> set[str]:
    raw = os.environ.get("SSRF_ALLOWED_HOSTS", "mcp,rag")
    return {item.strip() for item in raw.split(",") if item.strip()}


def ensure_safe_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeTargetUrl("Target URL must be http or https")
    host = parsed.hostname
    if host in allowed_hosts():
        return
    addresses = _addresses(host)
    for address in addresses:
        if _blocked(address):
            raise UnsafeTargetUrl("Target URL resolves to a blocked address")


def redirected(current: str, location: str) -> str:
    nxt = urljoin(current, location)
    ensure_safe_url(nxt)
    return nxt


def _addresses(host: str) -> list[str]:
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeTargetUrl("Target host did not resolve") from exc
    return [item[4][0] for item in infos]


def _blocked(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )
