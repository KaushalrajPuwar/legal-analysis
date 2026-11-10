"""Document ingestion for public URLs and PDF uploads.

Every ingested document is represented as plain text plus a list of
``DocumentBlock`` values. A block carries its character range in the canonical
text and, where available, its page, section heading and whether it is itself a
heading. Extraction runs over non-heading blocks so that a section title such as
"Information We Collect" cannot be reported as a practice statement.

The canonical text is the single offset space used by every downstream span.
"""

from __future__ import annotations

import hashlib
import ipaddress
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import httpx
import pymupdf
from bs4 import BeautifulSoup
from fastapi import HTTPException, UploadFile

from app.security import validate_public_http_url

MAX_DOCUMENT_BYTES = 12 * 1024 * 1024
MAX_PDF_PAGES = 250
MAX_REDIRECTS = 4
FETCH_TIMEOUT_SECONDS = 15.0
HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}
PDF_CONTENT_TYPE = "application/pdf"
HEADING_TAGS = {"h1", "h2", "h3", "h4"}
TEXT_TAGS = ["h1", "h2", "h3", "h4", "p", "li", "td", "th"]
BOLD_FLAG = 16
HEADING_SIZE_RATIO = 1.15
MAX_HEADING_WORDS = 14
TERMINAL_PUNCTUATION = (".", ":", ";")


@dataclass(frozen=True)
class DocumentBlock:
    text: str
    start: int
    end: int
    page: int | None = None
    section: str | None = None
    is_heading: bool = False


@dataclass(frozen=True)
class IngestedDocument:
    text: str
    blocks: list[DocumentBlock]
    source_type: str
    source_url: str | None
    retrieved_at: str
    title: str | None
    publisher: str | None
    content_sha256: str
    page_count: int | None
    warnings: list[str]


@dataclass(frozen=True)
class _Fragment:
    text: str
    page: int | None
    section: str | None
    is_heading: bool


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _pack(fragments: list[_Fragment]) -> tuple[str, list[DocumentBlock]]:
    """Join fragments into one canonical text while tracking exact offsets."""
    parts: list[str] = []
    blocks: list[DocumentBlock] = []
    offset = 0
    for fragment in fragments:
        if not fragment.text:
            continue
        if parts:
            parts.append(" ")
            offset += 1
        start = offset
        parts.append(fragment.text)
        offset += len(fragment.text)
        blocks.append(
            DocumentBlock(
                text=fragment.text,
                start=start,
                end=offset,
                page=fragment.page,
                section=fragment.section,
                is_heading=fragment.is_heading,
            )
        )
    return "".join(parts), blocks


def extract_html(content: bytes, source_url: str) -> tuple[str, str | None, str | None, list[DocumentBlock]]:
    soup = BeautifulSoup(content, "html.parser")
    for node in soup(["script", "style", "noscript", "svg", "nav", "footer", "form"]):
        node.decompose()

    title = soup.title.get_text(" ", strip=True) if soup.title else None
    publisher = None
    if tag := soup.find("meta", attrs={"property": "og:site_name"}):
        publisher = tag.get("content")

    main = soup.find("main") or soup.find("article") or soup.body or soup
    fragments: list[_Fragment] = []
    section: str | None = None
    for node in main.find_all(TEXT_TAGS):
        value = " ".join(node.stripped_strings)
        if not value:
            continue
        is_heading = node.name in HEADING_TAGS
        if is_heading:
            section = value
        fragments.append(_Fragment(value, None, section, is_heading))

    text, blocks = _pack(fragments)
    if not text.strip():
        raise HTTPException(status_code=422, detail="No readable policy text was found at the URL")
    return text, title, publisher or urlsplit(source_url).hostname, blocks


def _pdf_page_fragments(page: pymupdf.Page, page_number: int) -> list[_Fragment]:
    """Extract paragraphs and headings, using typography to separate them.

    PyMuPDF can group a heading and the following paragraph into one block, so
    heading detection runs per line rather than per block. Consecutive body
    lines in a block are joined into one paragraph fragment.
    """
    page_dict = page.get_text("dict")
    raw_blocks = [block for block in page_dict.get("blocks", []) if block.get("type") == 0]

    sizes: list[float] = []
    for block in raw_blocks:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    sizes.append(float(span.get("size", 0)))
    body_size = statistics.median(sizes) if sizes else 0.0

    fragments: list[_Fragment] = []
    section: str | None = None
    for block in raw_blocks:
        paragraph: list[str] = []
        for line in block.get("lines", []):
            spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
            if not spans:
                continue
            text = " ".join("".join(span.get("text", "") for span in spans).split())
            if not text:
                continue

            max_size = max(float(span.get("size", 0)) for span in spans)
            all_bold = all(bool(span.get("flags", 0) & BOLD_FLAG) for span in spans)
            large = body_size > 0 and max_size >= body_size * HEADING_SIZE_RATIO
            short = len(text.split()) <= MAX_HEADING_WORDS
            is_heading = short and not text.endswith(TERMINAL_PUNCTUATION) and (large or all_bold)

            if is_heading:
                if paragraph:
                    fragments.append(_Fragment(" ".join(paragraph), page_number, section, False))
                    paragraph = []
                section = text
                fragments.append(_Fragment(text, page_number, section, True))
            else:
                paragraph.append(text)

        if paragraph:
            fragments.append(_Fragment(" ".join(paragraph), page_number, section, False))

    return fragments


def _extract_pdf(content: bytes) -> tuple[str, list[DocumentBlock], int, list[str]]:
    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="The file is not a readable PDF") from exc

    try:
        page_count = document.page_count
        if page_count > MAX_PDF_PAGES:
            raise HTTPException(status_code=413, detail=f"PDF exceeds the {MAX_PDF_PAGES}-page limit")

        fragments: list[_Fragment] = []
        warnings: list[str] = []
        for page_number, page in enumerate(document, start=1):
            page_fragments = _pdf_page_fragments(page, page_number)
            if not page_fragments:
                warnings.append(f"Page {page_number} has no embedded text; OCR is not enabled.")
            fragments.extend(page_fragments)
    finally:
        document.close()

    text, blocks = _pack(fragments)
    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="The PDF contains no extractable text; scanned documents require OCR",
        )
    return text, blocks, page_count, warnings


def _check_peer(response: httpx.Response) -> None:
    """Reject connections whose peer address is not globally routable."""
    stream = response.extensions.get("network_stream")
    if stream is None:
        return
    try:
        peer = stream.get_extra_info("server_addr")
    except (AttributeError, ValueError, TypeError):
        return
    if not peer:
        return
    try:
        address = ipaddress.ip_address(peer[0])
    except (ValueError, IndexError):
        return
    if not address.is_global:
        raise HTTPException(status_code=422, detail="URL connected to a non-public address")


def _fetch_bytes(
    url: str, transport: httpx.BaseTransport | None = None
) -> tuple[bytes, str, str]:
    """Fetch a public URL, validating every redirect target before following it."""
    headers = {"User-Agent": "LegalAnalysisPrototype/0.1 (public policy fetcher)"}
    client_options: dict[str, object] = {
        "timeout": FETCH_TIMEOUT_SECONDS,
        "follow_redirects": False,
        "headers": headers,
    }
    if transport is not None:
        client_options["transport"] = transport

    current_url = url
    try:
        with httpx.Client(**client_options) as client:
            for redirect_index in range(MAX_REDIRECTS + 1):
                validate_public_http_url(current_url)
                with client.stream("GET", current_url) as response:
                    _check_peer(response)
                    if response.is_redirect:
                        if redirect_index == MAX_REDIRECTS:
                            raise HTTPException(status_code=422, detail="URL exceeded the redirect limit")
                        location = response.headers.get("location")
                        if not location:
                            raise HTTPException(status_code=422, detail="Redirect had no destination")
                        current_url = urljoin(current_url, location)
                        continue

                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    declared_length = response.headers.get("content-length")
                    if declared_length and declared_length.isdigit() and int(declared_length) > MAX_DOCUMENT_BYTES:
                        raise HTTPException(status_code=413, detail="URL document exceeds the 12 MB limit")

                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > MAX_DOCUMENT_BYTES:
                            raise HTTPException(status_code=413, detail="URL document exceeds the 12 MB limit")
                        chunks.append(chunk)
                    return b"".join(chunks), content_type, str(response.url)
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=422, detail=f"URL returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=422, detail=f"URL could not be fetched: {type(exc).__name__}") from exc

    raise HTTPException(status_code=422, detail="Unable to fetch URL")


def fetch_url(
    url: str, transport: httpx.BaseTransport | None = None
) -> IngestedDocument:
    content, content_type, final_url = _fetch_bytes(url, transport=transport)
    looks_like_html = b"<html" in content[:2048].lower() or b"<!doctype html" in content[:2048].lower()

    if content_type == PDF_CONTENT_TYPE or content.startswith(b"%PDF-"):
        text, blocks, page_count, warnings = _extract_pdf(content)
        title = None
        publisher = urlsplit(final_url).hostname
    elif content_type in HTML_CONTENT_TYPES or looks_like_html:
        text, title, publisher, blocks = extract_html(content, final_url)
        page_count = None
        warnings = []
    else:
        raise HTTPException(status_code=415, detail="URL must return HTML or PDF content")

    return IngestedDocument(
        text=text,
        blocks=blocks,
        source_type="url",
        source_url=final_url,
        retrieved_at=_now(),
        title=title,
        publisher=publisher,
        content_sha256=_sha256(content),
        page_count=page_count,
        warnings=warnings,
    )


def ingest_pdf_bytes(content: bytes, filename: str | None = None) -> IngestedDocument:
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="PDF exceeds the 12 MB limit")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="Content is not a PDF")

    text, blocks, page_count, warnings = _extract_pdf(content)
    return IngestedDocument(
        text=text,
        blocks=blocks,
        source_type="pdf_upload",
        source_url=None,
        retrieved_at=_now(),
        title=filename,
        publisher=None,
        content_sha256=_sha256(content),
        page_count=page_count,
        warnings=warnings,
    )


async def read_pdf_upload(upload: UploadFile) -> IngestedDocument:
    if upload.content_type not in {PDF_CONTENT_TYPE, "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Upload must be a PDF")
    content = await upload.read(MAX_DOCUMENT_BYTES + 1)
    return ingest_pdf_bytes(content, upload.filename)
