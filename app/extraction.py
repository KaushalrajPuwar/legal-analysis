"""Deterministic, sentence-level extraction of policy practice observations.

Each sentence in a non-heading document block is classified by a decision list:
the first practice type whose cue pattern appears wins. A statement usually
describes one practice, so assigning one dominant type per sentence avoids the
cross-type false positives that token-window patterns produce, for example
reporting a sharing clause as data collection because it contains the word
"process".

The quote attached to an observation is always the full sentence, which keeps
evidence readable and makes the source span easy to verify.
"""

from __future__ import annotations

import re

from app.domain import DocumentKind, PracticeObservation, PracticeType, SourceSpan
from app.ingestion import DocumentBlock, IngestedDocument
from app.severity import assess_evidence_strength, assess_severity, confidence_for, detect_categories

PRACTICE_CUES: list[tuple[PracticeType, re.Pattern[str]]] = [
    (
        PracticeType.CHILDREN,
        re.compile(r"\b(?:child|children|minors?|under (?:the age of )?(?:13|16|18))\b", re.I),
    ),
    (
        PracticeType.DATA_SHARING,
        re.compile(
            r"\b(?:share|shared|sharing|disclose|disclosed|disclosure|transfer|transferred|sell|sold|sale)\b",
            re.I,
        ),
    ),
    (
        PracticeType.DATA_RETENTION,
        re.compile(
            r"\b(?:retain|retained|retention|store|stored|storage|period of)\b"
            r"|\bkeep\b.{0,40}?\b(?:for|until)\b",
            re.I,
        ),
    ),
    (
        PracticeType.SECURITY,
        re.compile(
            r"\b(?:security|protect|protected|safeguard|encrypt|encrypted|unauthori[sz]ed access|breach)\b",
            re.I,
        ),
    ),
    (
        PracticeType.USER_CONTROL,
        re.compile(
            r"\b(?:withdraw|access request|correct|correction|erase|delete|opt[- ]out|consent|"
            r"grievance|complaint|portability)\b",
            re.I,
        ),
    ),
    (
        PracticeType.DATA_COLLECTION,
        re.compile(
            r"\b(?:collect|collected|collecting|gather|receive|obtain|record|register)\b",
            re.I,
        ),
    ),
    (
        PracticeType.DATA_USE,
        re.compile(r"\b(?:use|used|using|process|processed|analyse|analyze|analysed|utilise|utilize)\b", re.I),
    ),
]

SENTENCE_PATTERN = re.compile(r"[^.!?]+(?:[.!?]+|$)")

RECIPIENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "third parties": re.compile(r"\bthird[- ]part(?:y|ies)\b", re.I),
    "service providers": re.compile(r"\bservice providers?\b|\bprocessors?\b", re.I),
    "affiliates": re.compile(r"\baffiliates?\b|\bsubsidiaries\b", re.I),
    "partners": re.compile(r"\bpartners?\b", re.I),
    "advertisers": re.compile(r"\badvertis\w*\b", re.I),
    "public authorities": re.compile(r"\bpublic authorities\b|\blaw enforcement\b|\bgovernment\b", re.I),
}

CONTROL_PATTERNS: dict[str, re.Pattern[str]] = {
    "access": re.compile(r"\baccess\b", re.I),
    "correction": re.compile(r"\bcorrect(?:ion)?\b", re.I),
    "erasure": re.compile(r"\b(?:erase|deletion|delete)\w*\b", re.I),
    "consent withdrawal": re.compile(r"\bwithdraw\w*\b.{0,40}\bconsent\b", re.I | re.S),
    "opt-out": re.compile(r"\bopt[- ]out\b", re.I),
    "grievance redressal": re.compile(r"\bgrievance\b|\bcomplaint\b", re.I),
}


def classify_document(text: str) -> DocumentKind:
    lower = text.lower()
    has_privacy = any(
        term in lower
        for term in ("privacy policy", "personal data", "personal information", "data we collect")
    )
    has_terms = any(
        term in lower
        for term in ("terms and conditions", "terms of service", "terms of use", "governing law")
    )
    if has_privacy and has_terms:
        return DocumentKind.COMBINED
    if has_privacy:
        return DocumentKind.PRIVACY_POLICY
    if has_terms:
        return DocumentKind.TERMS
    return DocumentKind.UNKNOWN


def _sentences(text: str) -> list[tuple[str, int, int]]:
    """Return (text, start, end) sentence units with offsets inside ``text``."""
    units: list[tuple[str, int, int]] = []
    for match in SENTENCE_PATTERN.finditer(text):
        raw = match.group(0)
        stripped = raw.strip()
        if not stripped:
            continue
        leading = len(raw) - len(raw.lstrip())
        start = match.start() + leading
        units.append((stripped, start, start + len(stripped)))
    return units


def _runs(blocks: list[DocumentBlock]) -> list[list[DocumentBlock]]:
    """Group consecutive non-heading blocks so sentences can span block breaks."""
    runs: list[list[DocumentBlock]] = []
    current: list[DocumentBlock] = []
    for block in blocks:
        if block.is_heading:
            if current:
                runs.append(current)
                current = []
            continue
        current.append(block)
    if current:
        runs.append(current)
    return runs


def _block_at(blocks: list[DocumentBlock], offset: int) -> DocumentBlock:
    for block in blocks:
        if block.start <= offset < block.end:
            return block
    return blocks[-1]


def _classify_sentence(text: str) -> PracticeType | None:
    for practice_type, pattern in PRACTICE_CUES:
        if pattern.search(text):
            return practice_type
    return None


def _recipients(text: str) -> list[str]:
    return [label for label, pattern in RECIPIENT_PATTERNS.items() if pattern.search(text)]


def _controls(text: str) -> list[str]:
    return [label for label, pattern in CONTROL_PATTERNS.items() if pattern.search(text)]


def extract_observations(document: IngestedDocument) -> list[PracticeObservation]:
    observations: list[PracticeObservation] = []
    seen: set[tuple[PracticeType, int]] = set()

    for run in _runs(document.blocks):
        run_text = " ".join(block.text for block in run)
        run_start = run[0].start

        for sentence, start, end in _sentences(run_text):
            practice_type = _classify_sentence(sentence)
            if practice_type is None:
                continue

            absolute_start = run_start + start
            dedupe_key = (practice_type, absolute_start)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            block = _block_at(run, absolute_start)
            span = SourceSpan(
                section=block.section,
                page=block.page,
                start=absolute_start,
                end=run_start + end,
                quote=sentence,
            )
            severity, factors = assess_severity(practice_type, sentence)
            strength = assess_evidence_strength(sentence)

            observations.append(
                PracticeObservation(
                    practice_type=practice_type,
                    data_categories=detect_categories(sentence),
                    recipients=_recipients(sentence)
                    if practice_type is PracticeType.DATA_SHARING
                    else [],
                    retention=sentence if practice_type is PracticeType.DATA_RETENTION else None,
                    user_controls=_controls(sentence)
                    if practice_type is PracticeType.USER_CONTROL
                    else [],
                    source_spans=[span],
                    extraction_method="deterministic_sentence_v2",
                    confidence=confidence_for(strength),
                    severity=severity,
                    severity_factors=factors,
                    evidence_strength=strength,
                )
            )
    return observations


def make_summary(kind: DocumentKind, observation_count: int) -> str:
    if observation_count == 0:
        return (
            f"The document was classified as {kind.value.replace('_', ' ')}. "
            "The first-pass extractor did not identify supported practice statements. "
            "That is not evidence that the document omits any practice."
        )
    return (
        f"The document was classified as {kind.value.replace('_', ' ')}. "
        f"The first-pass extractor identified {observation_count} practice statements for review. "
        "Each statement quotes the analysed document; none is a legal conclusion. "
        "Official DPDP evidence has not yet been linked."
    )
