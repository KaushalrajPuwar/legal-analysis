from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.domain import AnalysisReport, DocumentMetadata
from app.extraction import classify_document, extract_observations, make_summary
from app.ingestion import IngestedDocument
from app.service import analyse_document
from app.store import AnalysisStore


def _report(document: IngestedDocument, expires_at: str) -> AnalysisReport:
    kind = classify_document(document.text)
    return AnalysisReport(
        analysis_id="analysis-1",
        created_at=datetime.now(UTC).isoformat(),
        expires_at=expires_at,
        metadata=DocumentMetadata(
            source_type=document.source_type,
            source_url=document.source_url,
            retrieved_at=document.retrieved_at,
            title=document.title,
            publisher=document.publisher,
            content_sha256=document.content_sha256,
            document_kind=kind,
            page_count=document.page_count,
        ),
        summary=make_summary(kind, 0),
        observations=extract_observations(document),
        limitations=[],
    )


def test_save_get_and_delete(tmp_path: Path, sample_document: IngestedDocument) -> None:
    store = AnalysisStore(tmp_path / "db.sqlite3")
    report = _report(sample_document, (datetime.now(UTC) + timedelta(hours=1)).isoformat())

    store.save(report)
    loaded = store.get(report.analysis_id)

    assert loaded is not None
    assert loaded.analysis_id == report.analysis_id
    assert loaded.observations

    assert store.delete(report.analysis_id) is True
    assert store.get(report.analysis_id) is None
    assert store.delete(report.analysis_id) is False


def test_expired_reports_are_not_returned_or_purged_twice(
    tmp_path: Path, sample_document: IngestedDocument
) -> None:
    store = AnalysisStore(tmp_path / "db.sqlite3")
    expired = _report(sample_document, (datetime.now(UTC) - timedelta(minutes=1)).isoformat())

    store.save(expired)
    assert store.get(expired.analysis_id) is None
    assert store.purge_expired() == 1
    assert store.purge_expired() == 0


def test_expiry_is_derived_from_retention(tmp_path: Path) -> None:
    store = AnalysisStore(tmp_path / "db.sqlite3", retention_hours=6)
    created = datetime(2026, 1, 1, tzinfo=UTC)

    assert store.expiry_for(created) == "2026-01-01T06:00:00+00:00"


def test_retention_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        AnalysisStore(tmp_path / "db.sqlite3", retention_hours=0)


def test_service_persists_and_returns_traceable_report(
    store: AnalysisStore, sample_document: IngestedDocument
) -> None:
    report = analyse_document(sample_document, store=store, retention_hours=store.retention_hours)

    assert store.get(report.analysis_id) is not None
    assert report.expires_at > report.created_at
    for observation in report.observations:
        for span in observation.source_spans:
            assert span.matches(sample_document.text)
