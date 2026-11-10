from __future__ import annotations

import pymupdf
import pytest
from fastapi import HTTPException

from app.ingestion import extract_html, ingest_pdf_bytes

SAMPLE_HTML = b"""<!doctype html>
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


def test_html_blocks_map_back_to_canonical_text() -> None:
    text, title, publisher, blocks = extract_html(SAMPLE_HTML, "https://acme.example/privacy")

    assert title == "Acme Privacy Policy"
    assert publisher == "Acme Ltd"
    assert blocks
    for block in blocks:
        assert text[block.start : block.end] == block.text


def test_html_sections_are_preserved() -> None:
    _, _, _, blocks = extract_html(SAMPLE_HTML, "https://acme.example/privacy")
    sections = {block.section for block in blocks}

    assert "Information We Collect" in sections
    assert "Data Retention" in sections


def test_html_headings_are_flagged() -> None:
    _, _, _, blocks = extract_html(SAMPLE_HTML, "https://acme.example/privacy")

    assert any(block.is_heading for block in blocks)
    assert not all(block.is_heading for block in blocks)


def test_pdf_ingest_preserves_pages(sample_pdf_bytes: bytes) -> None:
    document = ingest_pdf_bytes(sample_pdf_bytes, "policy.pdf")

    assert document.source_type == "pdf_upload"
    assert document.page_count == 1
    assert document.blocks
    assert all(block.page == 1 for block in document.blocks)
    assert "third party advertising partners" in document.text


def test_pdf_ingest_rejects_non_pdf() -> None:
    with pytest.raises(HTTPException) as error:
        ingest_pdf_bytes(b"not a pdf", "policy.pdf")

    assert error.value.status_code == 415


def test_pdf_ingest_rejects_empty_text() -> None:
    document = pymupdf.open()
    document.new_page()
    content = document.tobytes()
    document.close()

    with pytest.raises(HTTPException) as error:
        ingest_pdf_bytes(content, "blank.pdf")

    assert error.value.status_code == 422
    assert "OCR" in str(error.value.detail)
