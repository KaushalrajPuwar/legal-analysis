"""Domain model for policy observations and analysis reports.

The domain deliberately separates four things that a naive implementation would
blend together:

1. what the analysed document says (``SourceSpan``),
2. what the system inferred from it (``PracticeObservation``),
3. how serious that may be for a person (``Severity``),
4. how well the inference is supported (``EvidenceStrength``).

Legal conclusions are not part of this model yet. ``legal_mapping_status``
exists so the missing evidence layer is explicit rather than implied.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DocumentKind(StrEnum):
    PRIVACY_POLICY = "privacy_policy"
    TERMS = "terms"
    COMBINED = "combined"
    UNKNOWN = "unknown"


class PracticeType(StrEnum):
    DATA_COLLECTION = "data_collection"
    DATA_USE = "data_use"
    DATA_SHARING = "data_sharing"
    DATA_RETENTION = "data_retention"
    USER_CONTROL = "user_control"
    CHILDREN = "children"
    SECURITY = "security"


class ObservationStatus(StrEnum):
    DISCLOSED_IN_DOCUMENT = "disclosed_in_document"


class EvidenceStrength(StrEnum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNABLE_TO_ASSESS = "unable_to_assess"


class SourceSpan(BaseModel):
    """A verbatim slice of the analysed document and where it came from."""

    model_config = ConfigDict(frozen=True)

    section: str | None = None
    page: int | None = Field(default=None, ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)

    def matches(self, document_text: str) -> bool:
        return document_text[self.start : self.end] == self.quote


class PracticeObservation(BaseModel):
    practice_type: PracticeType
    status: ObservationStatus = ObservationStatus.DISCLOSED_IN_DOCUMENT
    data_categories: list[str] = Field(default_factory=list)
    purpose: str | None = None
    recipients: list[str] = Field(default_factory=list)
    retention: str | None = None
    user_controls: list[str] = Field(default_factory=list)
    source_spans: list[SourceSpan] = Field(min_length=1)
    extraction_method: str
    confidence: float = Field(ge=0, le=1)
    severity: Severity
    severity_factors: list[str] = Field(default_factory=list)
    evidence_strength: EvidenceStrength
    legal_mapping_status: str = "not_available"


class DocumentMetadata(BaseModel):
    source_type: str
    source_url: str | None = None
    retrieved_at: str
    title: str | None = None
    publisher: str | None = None
    content_sha256: str
    document_kind: DocumentKind
    page_count: int | None = Field(default=None, ge=1)
    warnings: list[str] = Field(default_factory=list)


class AnalysisReport(BaseModel):
    analysis_id: str
    created_at: str
    expires_at: str
    metadata: DocumentMetadata
    summary: str
    observations: list[PracticeObservation]
    limitations: list[str]
