from __future__ import annotations

import socket

import httpx
import pytest
from fastapi import HTTPException

from app.ingestion import fetch_url


def _public_dns(host: str, port: int, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


@pytest.fixture(autouse=True)
def allow_public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)


def _client(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_fetch_html_document(sample_html_bytes: bytes) -> None:
    transport = _client(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=sample_html_bytes,
        )
    )

    document = fetch_url("https://nimbus.example/privacy", transport=transport)

    assert document.source_type == "url"
    assert document.source_url == "https://nimbus.example/privacy"
    assert document.title == "Nimbus Notes Privacy Policy"
    assert document.page_count is None
    assert document.blocks
    for block in document.blocks:
        assert document.text[block.start : block.end] == block.text


def test_fetch_pdf_by_content_type(sample_pdf_bytes: bytes) -> None:
    transport = _client(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=sample_pdf_bytes,
        )
    )

    document = fetch_url("https://nimbus.example/policy.pdf", transport=transport)

    assert document.page_count == 1
    assert document.blocks


def test_fetch_follows_public_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://nimbus.example/new"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><head><title>Policy</title></head><body><main><p>We collect email.</p></main></body></html>",
        )

    document = fetch_url("https://nimbus.example/old", transport=_client(handler))

    assert document.source_url == "https://nimbus.example/new"
    assert "We collect email." in document.text


def test_fetch_rejects_redirect_loop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://nimbus.example/again"})

    with pytest.raises(HTTPException) as error:
        fetch_url("https://nimbus.example/again", transport=_client(handler))

    assert error.value.status_code == 422
    assert "redirect" in str(error.value.detail)


def test_fetch_rejects_unsupported_content_type() -> None:
    transport = _client(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"policy": "not html"},
        )
    )

    with pytest.raises(HTTPException) as error:
        fetch_url("https://nimbus.example/privacy", transport=transport)

    assert error.value.status_code == 415


def test_fetch_reports_http_error() -> None:
    transport = _client(lambda request: httpx.Response(404))

    with pytest.raises(HTTPException) as error:
        fetch_url("https://nimbus.example/missing", transport=transport)

    assert error.value.status_code == 422
    assert "404" in str(error.value.detail)


def test_fetch_enforces_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.ingestion.MAX_DOCUMENT_BYTES", 64)
    transport = _client(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html><body>" + b"a" * 200 + b"</body></html>",
        )
    )

    with pytest.raises(HTTPException) as error:
        fetch_url("https://nimbus.example/privacy", transport=transport)

    assert error.value.status_code == 413


def test_fetch_rejects_declared_oversize(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.ingestion.MAX_DOCUMENT_BYTES", 64)
    transport = _client(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html", "content-length": "1000"},
            content=b"<html></html>",
        )
    )

    with pytest.raises(HTTPException) as error:
        fetch_url("https://nimbus.example/privacy", transport=transport)

    assert error.value.status_code == 413
