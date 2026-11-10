from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.ingestion import IngestedDocument, extract_html
from app.store import AnalysisStore

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_HTML = ROOT / "sample_data" / "nimbus_privacy_policy.html"


@pytest.fixture
def sample_html_bytes() -> bytes:
    return SAMPLE_HTML.read_bytes()


@pytest.fixture
def sample_document(sample_html_bytes: bytes) -> IngestedDocument:
    text, title, publisher, blocks = extract_html(sample_html_bytes, "https://nimbus.example/privacy")
    return IngestedDocument(
        text=text,
        blocks=blocks,
        source_type="url",
        source_url="https://nimbus.example/privacy",
        retrieved_at="2026-10-30T00:00:00+00:00",
        title=title,
        publisher=publisher,
        content_sha256="0" * 64,
        page_count=None,
        warnings=[],
    )


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    lines = [
        "Nimbus Notes Privacy Policy",
        "",
        "We collect your name, email address and account details when you create an account.",
        "",
        "We collect precise location data from your mobile device.",
        "",
        "We share personal data with third party advertising partners.",
        "",
        "We retain account information for 24 months after you close your account.",
        "",
        "You can access, correct or delete your personal data in the application settings.",
        "",
        "Nimbus Notes is not intended for children under 18.",
    ]
    y = 64
    for line in lines:
        if line:
            page.insert_text((64, y), line, fontsize=10)
        y += 18
    content = document.tobytes()
    document.close()
    return content


@pytest.fixture
def store(tmp_path: Path) -> AnalysisStore:
    return AnalysisStore(tmp_path / "analyses.sqlite3", retention_hours=24)
