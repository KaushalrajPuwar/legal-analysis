"""URL validation for public-document fetching.

A policy analyser accepts arbitrary user-supplied URLs, which makes
server-side request forgery the most important early security concern. The
checks here reject non-HTTP schemes, credentials, unusual ports, local host
names and any hostname that resolves to a non-global address.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from fastapi import HTTPException

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443}


def _parse(url: str):
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid URL") from exc
    return parsed, port


def _resolve(host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        records = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise HTTPException(status_code=422, detail="URL host could not be resolved") from exc
    return [ipaddress.ip_address(record[4][0]) for record in records]


def validate_public_http_url(url: str) -> str:
    """Return ``url`` unchanged or raise a 422 describing why it is unsafe."""
    parsed, port = _parse(url)

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise HTTPException(status_code=422, detail="Only HTTP and HTTPS URLs are supported")
    if not parsed.hostname:
        raise HTTPException(status_code=422, detail="URL must include a hostname")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="URLs with embedded credentials are not allowed")
    if port not in ALLOWED_PORTS:
        raise HTTPException(status_code=422, detail="Non-standard ports are not allowed")
    if len(url) > 2048:
        raise HTTPException(status_code=422, detail="URL exceeds the 2048 character limit")

    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".home.arpa")):
        raise HTTPException(status_code=422, detail="Local network URLs are not allowed")

    effective_port = port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        addresses = _resolve(host, effective_port)

    if not addresses or any(not address.is_global for address in addresses):
        raise HTTPException(status_code=422, detail="URL must resolve only to public addresses")

    return url
