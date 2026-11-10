"""Create a demonstration PDF from the bundled sample policy HTML."""

from __future__ import annotations

from pathlib import Path

import pymupdf
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "sample_data" / "nimbus_privacy_policy.html"
TARGET = ROOT / "sample_data" / "nimbus_privacy_policy.pdf"

PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN = 56
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN
FONT = pymupdf.Font("helv")


def wrap(text: str, size: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if FONT.text_length(candidate, fontsize=size) <= CONTENT_WIDTH or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def main() -> None:
    soup = BeautifulSoup(SOURCE.read_text(encoding="utf-8"), "html.parser")
    main_node = soup.find("main") or soup

    blocks: list[tuple[str, float, float]] = []
    for node in main_node.find_all(["h1", "h2", "p"]):
        text = " ".join(node.stripped_strings)
        if not text:
            continue
        if node.name == "h1":
            blocks.append((text, 17, 18))
        elif node.name == "h2":
            blocks.append((text, 12.5, 14))
        else:
            blocks.append((text, 10, 6))

    document = pymupdf.open()
    document.set_metadata({"title": "Nimbus Notes Privacy Policy", "author": "Nimbus Labs"})
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    y = MARGIN

    for text, size, space_before in blocks:
        lines = wrap(text, size)
        needed = space_before + len(lines) * size * 1.45
        if y + needed > PAGE_HEIGHT - MARGIN:
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            y = MARGIN
        y += space_before
        for line in lines:
            page.insert_text((MARGIN, y), line, fontsize=size, fontname="helv")
            y += size * 1.45

    document.save(TARGET, garbage=4, deflate=True)
    document.close()
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
