"""Transparent severity and evidence-strength rubric.

Severity describes potential impact on a person if a disclosed practice applies.
It is not a legal risk score and must never be presented as one.

The rubric is deliberately rule based: it is repeatable, explainable and easy to
audit. A learned scorer should only replace it once there is a labelled
evaluation set and evidence that the learned model is better.
"""

from __future__ import annotations

import re

from app.domain import EvidenceStrength, PracticeType, Severity

# Canonical data categories with display labels and detection patterns.
DATA_CATEGORIES: dict[str, tuple[str, re.Pattern[str]]] = {
    "identity": ("identity data", re.compile(r"\b(name|date of birth|identity|government id|aadhaar|pan)\b", re.I)),
    "contact": ("contact data", re.compile(r"\b(e-?mail|phone|telephone|postal address|contact details)\b", re.I)),
    "device": (
        "device data",
        re.compile(
            r"\b(device (?:data|information|identifier|id)|browser type|operating system|"
            r"cookie|ip address|advertising id)\b",
            re.I,
        ),
    ),
    "usage": ("usage data", re.compile(r"\b(usage|activity|interaction|browsing|log data|behaviou?r)\b", re.I)),
    "location": ("location data", re.compile(r"\b(location|geolocation|gps|precise location)\b", re.I)),
    "financial": ("financial data", re.compile(r"\b(payment|financial|card|bank|transaction|billing)\w*\b", re.I)),
    "health": ("health data", re.compile(r"\b(health|medical|diagnos\w*|wellness)\b", re.I)),
    "biometric": ("biometric data", re.compile(r"\b(biometric|fingerprint|facial recognition|face scan)\b", re.I)),
    "communications": (
        "communications data",
        re.compile(r"\b(message|chat|call log|communications?|email content)\b", re.I),
    ),
}

HIGH_IMPACT_CATEGORIES = {"location", "financial", "health", "biometric", "communications"}

SCORED_PRACTICES = {
    PracticeType.DATA_COLLECTION,
    PracticeType.DATA_USE,
    PracticeType.DATA_SHARING,
    PracticeType.DATA_RETENTION,
    PracticeType.CHILDREN,
}

SHARING_SCOPE = re.compile(
    r"\b(third[- ]part(?:y|ies)|affiliates?|partners?|advertis\w*|public(?:ly)?|sell|sale|transfer)\b",
    re.I,
)
OPEN_ENDED_RETENTION = re.compile(
    r"\b(indefinit\w*|as long as|until (?:you|the|it|we)|no fixed|perpetu\w*|at our discretion)\b",
    re.I,
)
EXPLICIT_RETENTION = re.compile(
    r"\b\d+\s*(?:day|week|month|year)s?\b"
    r"|\b(?:seven|thirty|sixty|ninety|one hundred eighty)\s+days\b",
    re.I,
)
CHILDREN_PATTERN = re.compile(r"\b(?:child|children|minors?|under (?:the age of )?(?:13|16|18))\b", re.I)


def detect_categories(text: str) -> list[str]:
    """Return canonical category labels mentioned in ``text``."""
    return [label for key, (label, pattern) in DATA_CATEGORIES.items() if pattern.search(text)]


def category_keys(text: str) -> set[str]:
    return {key for key, (_, pattern) in DATA_CATEGORIES.items() if pattern.search(text)}


def assess_severity(
    practice_type: PracticeType,
    text: str,
) -> tuple[Severity, list[str]]:
    """Return a severity level and the human-readable factors behind it."""
    if practice_type not in SCORED_PRACTICES:
        return Severity.UNABLE_TO_ASSESS, [
            "statement describes a control or safeguard; impact is not scored independently"
        ]

    keys = category_keys(text)

    if practice_type is PracticeType.CHILDREN and CHILDREN_PATTERN.search(text):
        return Severity.HIGH, ["statement concerns children's or minors' data"]

    if practice_type in {PracticeType.DATA_COLLECTION, PracticeType.DATA_USE}:
        if keys & HIGH_IMPACT_CATEGORIES:
            sensitive = ", ".join(sorted(keys & HIGH_IMPACT_CATEGORIES))
            return Severity.HIGH, [f"mentions high-impact data categories: {sensitive}"]
        if keys:
            return Severity.MEDIUM, [f"mentions categories: {', '.join(sorted(keys))}"]
        return Severity.LOW, ["practice is mentioned without a specific high-impact category"]

    if practice_type is PracticeType.DATA_SHARING:
        if SHARING_SCOPE.search(text):
            return Severity.HIGH, ["sharing extends beyond a named service-provider context"]
        return Severity.MEDIUM, ["sharing is mentioned without a defined recipient scope"]

    if practice_type is PracticeType.DATA_RETENTION:
        if OPEN_ENDED_RETENTION.search(text):
            return Severity.HIGH, ["retention appears open ended or discretionary"]
        if not EXPLICIT_RETENTION.search(text):
            return Severity.MEDIUM, ["retention is mentioned without an explicit duration"]
        return Severity.LOW, ["retention statement includes an explicit duration"]

    return Severity.LOW, []


def assess_evidence_strength(quote: str) -> EvidenceStrength:
    """Estimate how much context the matched statement provides.

    This is a heuristic on the extracted span only. It is not a measure of legal
    sufficiency and must not be shown as a probability.
    """
    compact = " ".join(quote.split())
    if len(compact) >= 140:
        return EvidenceStrength.STRONG
    if len(compact) >= 60:
        return EvidenceStrength.MODERATE
    return EvidenceStrength.WEAK


_CONFIDENCE_BY_STRENGTH = {
    EvidenceStrength.STRONG: 0.86,
    EvidenceStrength.MODERATE: 0.79,
    EvidenceStrength.WEAK: 0.68,
}


def confidence_for(strength: EvidenceStrength) -> float:
    return _CONFIDENCE_BY_STRENGTH[strength]
