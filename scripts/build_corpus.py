"""Build the corpus: canonical text, structural indices and a manifest.

The corpus has two kinds of source, and they are structured differently.

Legal sources are organised by citation: chapter, section, subsection, clause.
Policy documents are organised by author headings: section, sub-section.

Each source becomes one canonical text file plus a JSON structural index whose
nodes carry exact character offsets into that same text. Keeping a single
canonical text is what allows a later stage to quote and cite without guessing.

Headings are preserved in the canonical text, because the structure index is
derived from them and the offsets must refer to the file that is actually read.

Run from the repository root:

    uv run python scripts/build_corpus.py
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus"

ROMAN = r"[IVXLC]+"
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
CHAPTER = re.compile(rf"^CHAPTER\s+({ROMAN})$", re.IGNORECASE)
SECTION = re.compile(r"^(\d{1,2})\.\s")


@dataclass
class Node:
    kind: str
    label: str
    title: str | None
    start: int
    end: int
    children: list[Node] = field(default_factory=list)

    def as_dict(self) -> dict:
        payload = {
            "kind": self.kind,
            "label": self.label,
            "title": self.title,
            "start": self.start,
            "end": self.end,
        }
        if self.children:
            payload["children"] = [child.as_dict() for child in self.children]
        return payload


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonicalise(raw: str) -> str:
    """Produce readable markdown with stable offsets.

    Removes scrape artefacts: hard-break backslashes, link targets, image
    syntax, emphasis markers, inline code fences and table pipes. Heading
    markers are kept because they carry the document structure.
    """
    text = raw.replace("\r\n", "\n")
    text = re.sub(r"\\\n", "\n", text)
    text = re.sub(r"\\([.\[\]()*_`#>+\-])", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"\1", text)
    text = re.sub(r"`{1,3}", "", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\|(.*)\|\s*$", lambda m: " ".join(m.group(1).split("|")).strip(), text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def join_wrapped_lines(text: str) -> str:
    """Join wrapped lines inside a block while preserving headings and blanks."""
    output: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            output.append(" ".join(buffer))
            buffer.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            output.append("")
        elif HEADING.match(stripped):
            flush()
            plain = HEADING.match(stripped).group(2)
            if re.match(r"^\d{1,2}\.\s", plain):
                output.append(plain)
            else:
                output.append(stripped)
        else:
            buffer.append(stripped)
    flush()
    result = "\n".join(output)
    return re.sub(r"\n{3,}", "\n\n", result).strip() + "\n"


def line_offsets(text: str) -> list[int]:
    offsets, cursor = [], 0
    for line in text.splitlines(keepends=True):
        offsets.append(cursor)
        cursor += len(line)
    return offsets


def build_act_structure(text: str) -> dict:
    lines = text.splitlines()
    offsets = line_offsets(text)

    chapters: list[Node] = []
    sections: list[Node] = []
    pending_chapter: tuple[str, int] | None = None
    expected_section = 1

    for index, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue

        heading = HEADING.match(line)
        plain = heading.group(2) if heading else line

        if heading and CHAPTER.match(plain):
            pending_chapter = (CHAPTER.match(plain).group(1).upper(), offsets[index])
            continue

        if pending_chapter and heading and not CHAPTER.match(plain):
            number, start = pending_chapter
            chapters.append(
                Node(kind="chapter", label=number, title=plain.title(), start=start, end=len(text))
            )
            pending_chapter = None
            continue

        match = SECTION.match(plain)
        if match and int(match.group(1)) == expected_section:
            sections.append(
                Node(
                    kind="section",
                    label=match.group(1),
                    title=None,
                    start=offsets[index],
                    end=len(text),
                )
            )
            expected_section += 1

    for position, chapter in enumerate(chapters):
        chapter.end = chapters[position + 1].start if position + 1 < len(chapters) else len(text)

    for position, section in enumerate(sections):
        section.end = sections[position + 1].start if position + 1 < len(sections) else len(text)
        chapter = next((c for c in chapters if c.start <= section.start < c.end), None)
        if chapter is not None:
            chapter.children.append(section)

    return {
        "document": "The Digital Personal Data Protection Act, 2023",
        "jurisdiction": "India",
        "structure": "chapter > section",
        "chapter_count": len(chapters),
        "section_count": len(sections),
        "missing_sections": [
            n for n in range(1, 45) if n not in {int(s.label) for s in sections}
        ],
        "chapters": [chapter.as_dict() for chapter in chapters],
        "title_status": "unresolved",
        "title_note": (
            "Marginal notes in the Gazette PDF are interleaved with body text by the "
            "extraction layer, so official section headings are not recovered "
            "automatically. Section numbers, text and offsets are reliable; titles "
            "require a curation pass against the printed Gazette."
        ),
    }


def build_policy_structure(text: str) -> dict:
    lines = text.splitlines()
    offsets = line_offsets(text)

    nodes: list[Node] = []
    for index, raw in enumerate(lines):
        heading = HEADING.match(raw.strip())
        if not heading:
            continue
        level = len(heading.group(1))
        title = heading.group(2).strip()
        if not title or len(title) > 200:
            continue
        if title.lower().startswith(("skip to", "on this page")):
            continue
        if nodes and nodes[-1].title == title:
            continue
        nodes.append(
            Node(kind=f"h{level}", label=title, title=title, start=offsets[index], end=len(text))
        )

    for position, node in enumerate(nodes):
        node.end = nodes[position + 1].start if position + 1 < len(nodes) else len(text)

    return {
        "structure": "heading > section",
        "heading_count": len(nodes),
        "headings": [node.as_dict() for node in nodes],
    }


def write_source(
    slug: str,
    kind: str,
    title: str,
    publisher: str,
    source_url: str,
    raw_path: Path | None,
    markdown_path: Path,
    extra: dict,
) -> dict:
    target_dir = CORPUS / kind / slug
    text_dir = target_dir / "text"
    structure_dir = target_dir / "structure"
    text_dir.mkdir(parents=True, exist_ok=True)
    structure_dir.mkdir(parents=True, exist_ok=True)

    canonical = join_wrapped_lines(canonicalise(markdown_path.read_text(encoding="utf-8")))
    text_path = text_dir / "content.md"
    text_path.write_text(canonical, encoding="utf-8")

    structure = build_act_structure(canonical) if kind == "legal" else build_policy_structure(canonical)
    structure_path = structure_dir / "index.json"
    structure_path.write_text(
        json.dumps(structure, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    metadata = {
        "slug": slug,
        "kind": kind,
        "title": title,
        "publisher": publisher,
        "source_url": source_url,
        "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": {
            "raw": str(raw_path.relative_to(ROOT)) if raw_path else None,
            "raw_sha256": sha256(raw_path) if raw_path and raw_path.exists() else None,
            "markdown": str(markdown_path.relative_to(ROOT)),
            "text": str(text_path.relative_to(ROOT)),
            "text_sha256": sha256(text_path),
            "structure": str(structure_path.relative_to(ROOT)),
        },
        "stats": {
            "characters": len(canonical),
            "words": len(canonical.split()),
            "lines": canonical.count("\n"),
        },
        **extra,
    }
    (target_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return metadata


POLICIES = [
    {
        "slug": "google-privacy",
        "title": "Google Privacy Policy",
        "publisher": "Google LLC",
        "url": "https://policies.google.com/privacy?hl=en&gl=IN",
        "path": CORPUS / "policies/google-privacy/text/privacy-policy.md",
        "extra": {
            "profile": "international platform operating in India",
            "selection_rationale": (
                "Globally dominant platform serving Indian users, publishing one global "
                "policy with jurisdiction-specific supplements."
            ),
        },
    },
    {
        "slug": "zomato-privacy",
        "title": "Eternal (formerly Zomato) Privacy Policy",
        "publisher": "Eternal Limited",
        "url": "https://www.zomato.com/privacy",
        "path": CORPUS / "policies/zomato-privacy/text/privacy-policy.md",
        "extra": {
            "profile": "Indian consumer internet platform",
            "selection_rationale": (
                "Indian-origin consumer platform handling identity, contact, location, "
                "payment and delivery-partner data under Indian law."
            ),
        },
    },
    {
        "slug": "tiktok-privacy",
        "title": "TikTok Privacy Policy (rest of world)",
        "publisher": "TikTok Technology Limited",
        "url": "https://www.tiktok.com/legal/page/row/privacy-policy/en",
        "path": CORPUS / "policies/tiktok-privacy/text/privacy-policy.md",
        "extra": {
            "profile": "platform blocked in India",
            "selection_rationale": (
                "TikTok is item 1 of 59 applications blocked by the Ministry of "
                "Electronics and Information Technology on 29 June 2020 under section "
                "69A of the Information Technology Act, 2000. It is retained as a "
                "comparison case for a service that does not lawfully operate in India."
            ),
            "blocking_order": {
                "authority": "Ministry of Electronics and Information Technology",
                "date": "2020-06-29",
                "instrument": "section 69A, Information Technology Act, 2000",
                "source_url": "https://www.pib.gov.in/PressReleseDetailm.aspx?PRID=1635206",
                "corpus_copy": "corpus/sources/pib-1635206-59-apps-blocked.md",
            },
            "scope_note": (
                "The captured policy is the rest-of-world version, not an India version, "
                "because the service is blocked in India. Any comparison must account "
                "for this difference in scope."
            ),
        },
    },
]


def main() -> None:
    entries = [
        write_source(
            slug="dpdp-act-2023",
            kind="legal",
            title="The Digital Personal Data Protection Act, 2023 (No. 22 of 2023)",
            publisher="Ministry of Law and Justice, Government of India",
            source_url=(
                "https://www.meity.gov.in/static/uploads/2024/06/"
                "2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf"
            ),
            raw_path=CORPUS / "legal/dpdp-act-2023/raw/dpdp-act-2023.pdf",
            markdown_path=CORPUS / "legal/dpdp-act-2023/text/dpdp-act-2023.md",
            extra={
                "authority": "Parliament of India",
                "assent_date": "2023-08-11",
                "status": "in force, partly commenced",
                "official_gazette": True,
                "notes": (
                    "Text obtained from the MeitY-hosted Gazette PDF. The Act is a "
                    "statute and is not subject to copyright. Chapter and section "
                    "offsets are derived from the canonical text; section titles "
                    "require curation."
                ),
            },
        )
    ]

    for policy in POLICIES:
        entries.append(
            write_source(
                slug=policy["slug"],
                kind="policies",
                title=policy["title"],
                publisher=policy["publisher"],
                source_url=policy["url"],
                raw_path=None,
                markdown_path=policy["path"],
                extra=policy["extra"],
            )
        )

    manifest = {
        "corpus_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "builder": "scripts/build_corpus.py",
        "sources": [
            {
                "slug": entry["slug"],
                "kind": entry["kind"],
                "title": entry["title"],
                "publisher": entry["publisher"],
                "source_url": entry["source_url"],
                "text": entry["files"]["text"],
                "structure": entry["files"]["structure"],
                "words": entry["stats"]["words"],
            }
            for entry in entries
        ],
        "provenance_sources": [
            {
                "slug": "pib-1635206",
                "title": "Government blocks 59 mobile apps",
                "publisher": "Press Information Bureau, Government of India",
                "source_url": "https://www.pib.gov.in/PressReleseDetailm.aspx?PRID=1635206",
                "path": "corpus/sources/pib-1635206-59-apps-blocked.md",
            }
        ],
    }
    (CORPUS / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    for entry in entries:
        print(f"{entry['slug']:20} {entry['stats']['words']:>7} words  {entry['files']['structure']}")


if __name__ == "__main__":
    main()
