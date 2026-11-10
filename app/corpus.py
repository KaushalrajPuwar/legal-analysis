"""Load documents from the curated corpus into the analysis pipeline.

The corpus stores one canonical text per source plus a structural index whose
nodes carry character offsets into that text. This module turns a corpus entry
into the same ``IngestedDocument`` the live ingestion path produces, so the
extraction and severity stages do not care where a document came from.

Corpus text is already normalised, so blocks are taken from the structural
index rather than re-parsed. Each block keeps its heading path, which gives
observations a section label.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from app.ingestion import DocumentBlock, IngestedDocument

DEFAULT_CORPUS_ROOT = Path(__file__).resolve().parents[1] / "corpus"


@dataclass(frozen=True)
class CorpusEntry:
    slug: str
    kind: str
    title: str
    publisher: str
    source_url: str
    text_path: Path
    structure_path: Path
    metadata_path: Path


def _load_metadata(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def list_entries(root: Path = DEFAULT_CORPUS_ROOT) -> list[CorpusEntry]:
    """Return every source in the corpus manifest, in manifest order."""
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(status_code=500, detail="Corpus manifest is missing")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries: list[CorpusEntry] = []
    for item in manifest.get("sources", []):
        slug = item["slug"]
        kind = item["kind"]
        directory = root / kind / slug
        entries.append(
            CorpusEntry(
                slug=slug,
                kind=kind,
                title=item["title"],
                publisher=item["publisher"],
                source_url=item["source_url"],
                text_path=directory / "text" / "content.md",
                structure_path=directory / "structure" / "index.json",
                metadata_path=directory / "metadata.json",
            )
        )
    return entries


def get_entry(slug: str, root: Path = DEFAULT_CORPUS_ROOT) -> CorpusEntry:
    for entry in list_entries(root):
        if entry.slug == slug:
            return entry
    raise HTTPException(status_code=404, detail=f"Unknown corpus source: {slug}")


def _flatten_structure(structure: dict) -> list[dict]:
    """Return leaf-level nodes in document order, with their heading path."""
    flat: list[dict] = []

    def walk(nodes: list[dict], path: list[str]) -> None:
        for node in nodes:
            title = node.get("title") or ""
            current_path = [*path, title] if title else path
            children = node.get("children") or []
            if children:
                walk(children, current_path)
            else:
                flat.append({**node, "path": current_path})

    if "chapters" in structure:
        walk(structure["chapters"], [])
    else:
        walk(structure.get("headings", []), [])
    return flat


def load_document(slug: str, root: Path = DEFAULT_CORPUS_ROOT) -> IngestedDocument:
    """Build an ``IngestedDocument`` from a corpus entry."""
    entry = get_entry(slug, root)
    if not entry.text_path.is_file():
        raise HTTPException(status_code=500, detail=f"Corpus text is missing for {slug}")

    text = entry.text_path.read_text(encoding="utf-8")
    structure = json.loads(entry.structure_path.read_text(encoding="utf-8"))
    metadata = _load_metadata(entry.metadata_path) if entry.metadata_path.is_file() else {}

    blocks: list[DocumentBlock] = []
    for node in _flatten_structure(structure):
        start, end = node["start"], node["end"]
        raw = text[start:end]
        if not raw.strip():
            continue

        path = node.get("path") or []
        section = path[-1] if path else None
        first_line, _, remainder = raw.partition("\n")

        if first_line.lstrip().startswith("#") or node.get("kind") in {
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "chapter",
        }:
            heading_body = first_line.strip()
            if heading_body:
                leading = len(raw) - len(raw.lstrip())
                blocks.append(
                    DocumentBlock(
                        text=heading_body,
                        start=start + leading,
                        end=start + leading + len(heading_body),
                        section=section,
                        is_heading=True,
                    )
                )
            raw = remainder
            start = start + len(first_line) + 1

        body = raw.strip()
        if not body:
            continue
        leading = len(raw) - len(raw.lstrip())
        blocks.append(
            DocumentBlock(
                text=body,
                start=start + leading,
                end=start + leading + len(body),
                section=section,
                is_heading=False,
            )
        )

    return IngestedDocument(
        text=text,
        blocks=blocks,
        source_type=f"corpus_{entry.kind}",
        source_url=entry.source_url,
        retrieved_at=metadata.get("retrieved_at", ""),
        title=entry.title,
        publisher=entry.publisher,
        content_sha256=(metadata.get("files") or {}).get("text_sha256", ""),
        page_count=None,
        warnings=[],
    )
