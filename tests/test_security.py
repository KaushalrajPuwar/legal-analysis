from __future__ import annotations

import socket

import pytest
from fastapi import HTTPException

from app.security import validate_public_http_url


def _public_dns(host: str, port: int, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def _private_dns(host: str, port: int, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.4", port))]


def test_accepts_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    assert validate_public_http_url("https://example.com/privacy") == "https://example.com/privacy"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/policy",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://localhost/privacy",
        "https://api.localhost/privacy",
        "http://127.0.0.1/privacy",
        "http://[::1]/privacy",
        "http://10.0.0.1/privacy",
        "http://169.254.169.254/latest/meta-data",
        "https://user:pass@example.com/privacy",
        "https://example.com:8443/privacy",
    ],
)
def test_rejects_unsafe_urls(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    with pytest.raises(HTTPException) as error:
        validate_public_http_url(url)
    assert error.value.status_code == 422


def test_rejects_hostname_resolving_to_private_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _private_dns)
    with pytest.raises(HTTPException):
        validate_public_http_url("https://internal.example/privacy")


def test_rejects_unresolvable_host(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(HTTPException):
        validate_public_http_url("https://does-not-exist.example/privacy")


def test_rejects_overlong_url() -> None:
    with pytest.raises(HTTPException):
        validate_public_http_url("https://example.com/" + "a" * 2100)


def test_accepts_fragment_and_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    url = "https://example.com/privacy?lang=en#collection"
    assert validate_public_http_url(url) == url
