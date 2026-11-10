from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.ingestion import IngestedDocument
from app.main import create_app
from app.service import analyse_document
from app.store import AnalysisStore


@pytest.fixture
def client(store: AnalysisStore):
    with TestClient(create_app(store=store)) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_pdf_upload_returns_traceable_analysis(client: TestClient, sample_pdf_bytes: bytes) -> None:
    response = client.post(
        "/v1/analyses/pdf",
        files={"file": ("policy.pdf", sample_pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["metadata"]["source_type"] == "pdf_upload"
    assert body["metadata"]["page_count"] == 1
    assert len(body["metadata"]["content_sha256"]) == 64
    assert body["observations"]
    assert body["limitations"]
    assert all(
        observation["legal_mapping_status"] == "not_available"
        for observation in body["observations"]
    )
    for observation in body["observations"]:
        for span in observation["source_spans"]:
            assert span["quote"]
            assert span["end"] > span["start"]


def test_get_and_delete_analysis(client: TestClient, sample_pdf_bytes: bytes) -> None:
    created = client.post(
        "/v1/analyses/pdf",
        files={"file": ("policy.pdf", sample_pdf_bytes, "application/pdf")},
    ).json()

    fetched = client.get(f"/v1/analyses/{created['analysis_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["analysis_id"] == created["analysis_id"]

    deleted = client.delete(f"/v1/analyses/{created['analysis_id']}")
    assert deleted.status_code == 204

    assert client.get(f"/v1/analyses/{created['analysis_id']}").status_code == 404
    assert client.delete(f"/v1/analyses/{created['analysis_id']}").status_code == 404


def test_rejects_non_pdf_upload(client: TestClient) -> None:
    response = client.post(
        "/v1/analyses/pdf",
        files={"file": ("policy.html", b"<html>policy</html>", "text/html")},
    )

    assert response.status_code == 415


def test_rejects_pdf_claim_without_pdf_content(client: TestClient) -> None:
    response = client.post(
        "/v1/analyses/pdf",
        files={"file": ("policy.pdf", b"not really a pdf", "application/pdf")},
    )

    assert response.status_code == 415


def test_url_analysis_uses_injected_fetcher(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    sample_document: IngestedDocument,
) -> None:
    monkeypatch.setattr("app.main.fetch_url", lambda url: sample_document)

    response = client.post("/v1/analyses/url", json={"url": "https://nimbus.example/privacy"})

    assert response.status_code == 201
    body = response.json()
    assert body["metadata"]["source_url"] == "https://nimbus.example/privacy"
    assert body["observations"]


def test_expired_analysis_is_not_served(client: TestClient, sample_document: IngestedDocument) -> None:
    store: AnalysisStore = client.app.state.store
    report = analyse_document(sample_document, store=store)
    expired = report.model_copy(
        update={"expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}
    )
    store.delete(report.analysis_id)
    store.save(expired)

    assert client.get(f"/v1/analyses/{expired.analysis_id}").status_code == 404


def test_report_carries_no_compliance_verdict(
    client: TestClient, sample_pdf_bytes: bytes
) -> None:
    body = client.post(
        "/v1/analyses/pdf",
        files={"file": ("policy.pdf", sample_pdf_bytes, "application/pdf")},
    ).json()

    serialised = str(body).lower()
    assert "non-compliant" not in serialised
    assert "compliant" not in serialised
    assert "verdict" not in serialised
