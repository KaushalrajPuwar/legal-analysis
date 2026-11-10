from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.corpus import load_document
from app.ingestion import IngestedDocument
from app.store import AnalysisStore

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus"


@pytest.fixture
def sample_document() -> IngestedDocument:
    """A real Indian consumer platform policy from the curated corpus."""
    return load_document("zomato-privacy", CORPUS)


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


@pytest.fixture
def sample_html_bytes() -> bytes:
    """Minimal HTML policy for parser and fetcher tests."""
    return b"""<!doctype html>
<html><head><title>Acme Privacy Policy</title>
<meta property="og:site_name" content="Acme Ltd"></head>
<body><main>
<h1>Acme Privacy Policy</h1>
<p>We collect your name and email address when you create an account.</p>
<h2>Information We Collect</h2>
<p>We collect device information such as your browser type and IP address.</p>
<h2>Data Retention</h2>
<p>We retain account information for 24 months after you close your account.</p>
</main></body></html>"""
