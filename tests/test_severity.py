from __future__ import annotations

import pytest

from app.domain import EvidenceStrength, PracticeType, Severity
from app.severity import (
    DATA_CATEGORIES,
    assess_evidence_strength,
    assess_severity,
    detect_categories,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("We collect precise location data from your device.", {"location"}),
        ("We collect your name and email address.", {"identity", "contact"}),
        ("We share payment and billing details with partners.", {"financial"}),
        ("We do not collect anything here.", set()),
    ],
)
def test_detect_categories(text: str, expected: set[str]) -> None:
    labels = set(detect_categories(text))
    keys = {key for key, (label, _) in DATA_CATEGORIES.items() if label in labels}
    assert keys == expected


def test_location_collection_is_high_impact() -> None:
    severity, factors = assess_severity(
        PracticeType.DATA_COLLECTION,
        "With your permission, we collect precise location data from your mobile device.",
    )
    assert severity is Severity.HIGH
    assert any("location" in factor for factor in factors)


def test_generic_collection_is_low_impact() -> None:
    severity, _ = assess_severity(
        PracticeType.DATA_COLLECTION,
        "We collect information that you choose to provide to us.",
    )
    assert severity is Severity.LOW


def test_third_party_sharing_is_high_impact() -> None:
    severity, factors = assess_severity(
        PracticeType.DATA_SHARING,
        "We share personal data with third party advertising partners.",
    )
    assert severity is Severity.HIGH
    assert factors


def test_open_ended_retention_is_high_impact() -> None:
    severity, factors = assess_severity(
        PracticeType.DATA_RETENTION,
        "We retain records for as long as necessary to resolve disputes.",
    )
    assert severity is Severity.HIGH
    assert any("open ended" in factor for factor in factors)


def test_explicit_retention_is_low_impact() -> None:
    severity, _ = assess_severity(
        PracticeType.DATA_RETENTION,
        "We retain your account information for 24 months after you close your account.",
    )
    assert severity is Severity.LOW


def test_children_statement_is_high_impact() -> None:
    severity, _ = assess_severity(
        PracticeType.CHILDREN,
        "Nimbus Notes is not intended for children under 18.",
    )
    assert severity is Severity.HIGH


def test_control_statements_are_not_scored() -> None:
    severity, factors = assess_severity(
        PracticeType.USER_CONTROL,
        "You can withdraw consent at any time.",
    )
    assert severity is Severity.UNABLE_TO_ASSESS
    assert factors


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("We share data.", EvidenceStrength.WEAK),
        ("We share personal data with third party analytics partners for advertising.", EvidenceStrength.MODERATE),
        ("We " + "share personal data with partners " * 6 + "for advertising.", EvidenceStrength.STRONG),
    ],
)
def test_evidence_strength_uses_span_context(quote: str, expected: EvidenceStrength) -> None:
    assert assess_evidence_strength(quote) is expected
