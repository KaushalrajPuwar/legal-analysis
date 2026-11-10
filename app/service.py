"""Application service: compose a document into a validated, optionally persisted report."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.domain import AnalysisReport, DocumentMetadata
from app.extraction import classify_document, extract_observations, make_summary
from app.ingestion import IngestedDocument
from app.store import AnalysisStore

LIMITATIONS = [
    "Practice extraction uses deterministic patterns and will miss paraphrases and context.",
    "Severity is a preliminary user-impact heuristic, not a legal or compliance score.",
    "No DPDP Act, notified-rule or official-guidance retrieval is connected yet.",
    "Scanned PDFs are not OCR processed; pages without embedded text are reported as warnings.",
    "Absence of an observation does not establish that the practice is absent from the document.",
]


def analyse_document(
    document: IngestedDocument,
    store: AnalysisStore | None = None,
    retention_hours: int = 24,
) -> AnalysisReport:
    created_at = datetime.now(UTC)
    kind = classify_document(document.text)
    observations = extract_observations(document)

    report = AnalysisReport(
        analysis_id=str(uuid.uuid4()),
        created_at=created_at.isoformat(),
        expires_at=(created_at + timedelta(hours=retention_hours)).isoformat(),
        metadata=DocumentMetadata(
            source_type=document.source_type,
            source_url=document.source_url,
            retrieved_at=document.retrieved_at,
            title=document.title,
            publisher=document.publisher,
            content_sha256=document.content_sha256,
            document_kind=kind,
            page_count=document.page_count,
            warnings=document.warnings,
        ),
        summary=make_summary(kind, len(observations)),
        observations=observations,
        limitations=LIMITATIONS,
    )

    _assert_spans_resolve(report, document.text)
    if store is not None:
        store.save(report)
    return report


def _assert_spans_resolve(report: AnalysisReport, text: str) -> None:
    """Guarantee the core invariant before anything is returned or persisted."""
    for observation in report.observations:
        for span in observation.source_spans:
            if not span.matches(text):
                raise ValueError(
                    f"Source span does not match the document for {observation.practice_type}"
                )
