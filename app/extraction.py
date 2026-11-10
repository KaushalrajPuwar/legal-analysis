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

DATA_NOUN = (
    r"(?:personal\s+|sensitive\s+|non-personal\s+)?"
    r"(?:information|data|details|records|identifiers?|"
    r"device\s+information|location\s+data|usage\s+data|account\s+information|"
    r"contact\s+details|financial\s+information|health\s+data|biometric\s+data|"
    r"personal\s+information|user\s+data)"
)
DETERMINER = r"(?:your|the|any|such|this|that|all|some|our|their|its|his|her)"
OBJECT = rf"(?:(?:{DETERMINER}\s+)?{DATA_NOUN}|(?:it|them|these|those))"
# Coordinated verbs share one object: "collect and process information".
COORDINATION = r"(?:\s*(?:,|and|or)\s*(?:\w+))?"

PRACTICE_CUES: list[tuple[PracticeType, re.Pattern[str]]] = [
    (
        PracticeType.CHILDREN,
        re.compile(r"\b(?:child|children|minors?|under (?:the age of )?(?:13|16|18))\b", re.I),
    ),
    (
        PracticeType.DATA_SHARING,
        re.compile(
            rf"\b(?:share|shares|shared|sharing|disclose|discloses|disclosed|disclosure|"
            rf"transfer|transfers|transferred|sell|sells|sold)\b{COORDINATION}\s+(?:of\s+)?{OBJECT}\b",
            re.I,
        ),
    ),
    (
        PracticeType.DATA_RETENTION,
        re.compile(
            rf"\b(?:retain|retains|retained|retention|store|stores|stored|storage)\b\s+"
            rf"(?:of\s+)?{OBJECT}\b"
            rf"|\bkeep\b{COORDINATION}\s+{OBJECT}\b\s*\b(?:for|until)\b",
            re.I,
        ),
    ),
    (
        PracticeType.SECURITY,
        re.compile(
            r"\b(?:security measures|protect|protected|safeguard|safeguards|encrypt|encrypted|"
            r"unauthori[sz]ed access|data breach|personal data breach)\b",
            re.I,
        ),
    ),
    (
        PracticeType.USER_CONTROL,
        re.compile(
            r"\b(?:withdraw|withdrawal|access request|correct|correction|rectif\w*|erase|erasure|"
            r"delete|deletion|opt[- ]out|portability|grievance|complaint)\b",
            re.I,
        ),
    ),
    (
        PracticeType.DATA_COLLECTION,
        re.compile(
            rf"\b(?:collect|collects|collected|collecting|gather|gathers|gathered|"
            rf"receive|receives|received|obtain|obtains|obtained|record|records|recorded)\b"
            rf"{COORDINATION}\s+(?:of\s+)?{OBJECT}\b",
            re.I,
        ),
    ),
    (
        PracticeType.DATA_USE,
        re.compile(
            rf"\b(?:use|uses|used|using|process|processes|processed|processing|"
            rf"analyse|analyses|analyze|analyzes|utilise|utilize)\b{COORDINATION}\s+(?:of\s+)?{OBJECT}\b",
            re.I,
        ),
    ),
]

SENTENCE_PATTERN = re.compile(r"[^.!?]+(?:[.!?]+|$)")
ABBREVIATIONS = (
    "e.g.",
    "i.e.",
    "etc.",
    "vs.",
    "no.",
    "sec.",
    "art.",
    "pvt.",
    "ltd.",
    "inc.",
    "co.",
    "mr.",
    "mrs.",
    "ms.",
    "dr.",
    "st.",
)

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
    """Return (text, start, end) sentence units with offsets inside ``text``.

    A split after a known abbreviation is merged back into the following unit,
    so "e.g." and "Pvt. Ltd." do not produce fragments that begin mid-sentence.
    Merging extends the end offset rather than concatenating strings, which
    keeps every quote an exact slice of the source text.
    """
    spans: list[tuple[int, int]] = []
    for match in SENTENCE_PATTERN.finditer(text):
        raw = match.group(0)
        stripped = raw.strip()
        if not stripped:
            continue
        leading = len(raw) - len(raw.lstrip())
        start = match.start() + leading
        spans.append((start, start + len(stripped)))

    merged: list[tuple[str, int, int]] = []
    carry_start: int | None = None
    for start, end in spans:
        if carry_start is not None:
            start = carry_start
            carry_start = None
        if text[start:end].lower().endswith(ABBREVIATIONS):
            carry_start = start
            continue
        merged.append((text[start:end], start, end))
    if carry_start is not None:
        merged.append((text[carry_start:], carry_start, len(text)))
    return merged


def _runs(document: IngestedDocument) -> list[tuple[int, str]]:
    """Group consecutive non-heading blocks into contiguous document slices.

    The slice is taken from the canonical text rather than by joining block
    texts, so sentence offsets stay exact even when blocks are separated by
    blank lines or other whitespace.
    """
    groups: list[list[DocumentBlock]] = []
    current: list[DocumentBlock] = []
    for block in document.blocks:
        if block.is_heading:
            if current:
                groups.append(current)
                current = []
            continue
        current.append(block)
    if current:
        groups.append(current)

    runs: list[tuple[int, str]] = []
    for group in groups:
        start = group[0].start
        end = group[-1].end
        runs.append((start, document.text[start:end]))
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

    for run_start, run_text in _runs(document):
        for sentence, start, end in _sentences(run_text):
            practice_type = _classify_sentence(sentence)
            if practice_type is None:
                continue

            absolute_start = run_start + start
            dedupe_key = (practice_type, absolute_start)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            block = _block_at(document.blocks, absolute_start)
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
