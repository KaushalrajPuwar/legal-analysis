from __future__ import annotations

from pathlib import Path

import pytest

from app.corpus import DEFAULT_CORPUS_ROOT, get_entry, list_entries, load_document
from app.extraction import classify_document, extract_observations

CORPUS = DEFAULT_CORPUS_ROOT


def test_manifest_lists_every_source() -> None:
    entries = list_entries(CORPUS)
    slugs = [entry.slug for entry in entries]

    assert "dpdp-act-2023" in slugs
    assert "google-privacy" in slugs
    assert "zomato-privacy" in slugs
    assert "tiktok-privacy" in slugs
    assert len(slugs) == len(set(slugs))


def test_every_source_has_text_and_structure() -> None:
    for entry in list_entries(CORPUS):
        assert entry.text_path.is_file(), entry.slug
        assert entry.structure_path.is_file(), entry.slug
        assert entry.metadata_path.is_file(), entry.slug
        assert entry.text_path.stat().st_size > 1000, entry.slug


def test_unknown_slug_is_rejected() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        get_entry("does-not-exist", CORPUS)

    assert error.value.status_code == 404


def test_act_structure_covers_all_sections() -> None:
    import json

    entry = get_entry("dpdp-act-2023", CORPUS)
    structure = json.loads(entry.structure_path.read_text(encoding="utf-8"))
    sections = [
        child for chapter in structure["chapters"] for child in chapter.get("children", [])
    ]

    assert structure["chapter_count"] == 9
    assert structure["section_count"] == 44
    assert structure["missing_sections"] == []
    assert len(sections) == 44
    assert [int(section["label"]) for section in sections] == list(range(1, 45))


def test_act_section_offsets_point_at_their_own_text() -> None:
    import json

    entry = get_entry("dpdp-act-2023", CORPUS)
    text = entry.text_path.read_text(encoding="utf-8")
    structure = json.loads(entry.structure_path.read_text(encoding="utf-8"))

    for chapter in structure["chapters"]:
        for section in chapter.get("children", []):
            body = text[section["start"] : section["end"]]
            assert body.lstrip().startswith(f"{section['label']}."), section["label"]


def test_policy_structure_has_headings() -> None:
    for slug in ("google-privacy", "zomato-privacy", "tiktok-privacy"):
        entry = get_entry(slug, CORPUS)
        document = load_document(slug, CORPUS)
        assert entry.structure_path.is_file()
        assert document.blocks
        assert all(block.text for block in document.blocks)
        assert all(document.text[block.start : block.end] == block.text for block in document.blocks)


def test_corpus_document_is_classified_as_a_policy() -> None:
    document = load_document("zomato-privacy", CORPUS)

    assert classify_document(document.text).value in {"privacy_policy", "combined"}


def test_corpus_extraction_produces_traceable_observations() -> None:
    document = load_document("zomato-privacy", CORPUS)
    observations = extract_observations(document)

    assert observations
    for observation in observations:
        for span in observation.source_spans:
            assert span.matches(document.text), span.quote[:80]


def test_tiktok_carries_its_blocking_provenance() -> None:
    import json

    entry = get_entry("tiktok-privacy", CORPUS)
    metadata = json.loads(entry.metadata_path.read_text(encoding="utf-8"))

    assert metadata["profile"] == "platform blocked in India"
    assert metadata["blocking_order"]["date"] == "2020-06-29"
    assert "69A" in metadata["blocking_order"]["instrument"]
    assert Path(CORPUS / "sources" / "pib-1635206-59-apps-blocked.md").is_file()
