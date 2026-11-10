from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.ingestion import extract_html, ingest_pdf_bytes


def test_html_blocks_map_back_to_canonical_text(sample_html_bytes: bytes) -> None:
    text, title, publisher, blocks = extract_html(sample_html_bytes, "https://nimbus.example/privacy")

    assert title == "Nimbus Notes Privacy Policy"
    assert publisher == "Nimbus Labs Pvt. Ltd."
    assert blocks
    assert text
    for block in blocks:
        assert text[block.start : block.end] == block.text


def test_html_sections_are_preserved(sample_html_bytes: bytes) -> None:
    _, _, _, blocks = extract_html(sample_html_bytes, "https://nimbus.example/privacy")
    sections = {block.section for block in blocks}
    assert "Information We Collect" in sections
    assert "Data Retention" in sections


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
    import pymupdf

    document = pymupdf.open()
    document.new_page()
    content = document.tobytes()
    document.close()

    with pytest.raises(HTTPException) as error:
        ingest_pdf_bytes(content, "blank.pdf")

    assert error.value.status_code == 422
    assert "OCR" in str(error.value.detail)
