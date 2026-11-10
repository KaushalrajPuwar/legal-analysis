"""Command-line entry point for analysing a corpus source, a local PDF or a URL.

Usage:
    python -m app.cli --corpus zomato-privacy
    python -m app.cli --corpus dpdp-act-2023 --no-store
    python -m app.cli policy.pdf
    python -m app.cli --url https://example.com/privacy
    python -m app.cli --list-corpus
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.corpus import list_entries, load_document
from app.ingestion import fetch_url, ingest_pdf_bytes
from app.service import analyse_document
from app.store import AnalysisStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyse a policy document")
    parser.add_argument("source", nargs="?", help="Path to a PDF, or a URL when --url is set")
    parser.add_argument("--url", action="store_true", help="Treat the source as a public URL")
    parser.add_argument("--corpus", metavar="SLUG", help="Analyse a curated corpus source by slug")
    parser.add_argument("--list-corpus", action="store_true", help="List corpus sources and exit")
    parser.add_argument("--db", default="./legal_analysis.sqlite3", help="Analysis store path")
    parser.add_argument("--no-store", action="store_true", help="Analyse without persisting the report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.list_corpus:
        for entry in list_entries():
            print(f"{entry.slug:20} {entry.kind:9} {entry.title}")
        return 0

    if args.corpus:
        document = load_document(args.corpus)
    elif args.url:
        if not args.source:
            print("--url requires a URL argument", file=sys.stderr)
            return 2
        document = fetch_url(args.source)
    else:
        if not args.source:
            print("A PDF path, --url or --corpus is required", file=sys.stderr)
            return 2
        path = Path(args.source)
        if not path.is_file():
            print(f"No such file: {path}", file=sys.stderr)
            return 2
        document = ingest_pdf_bytes(path.read_bytes(), path.name)

    store = None if args.no_store else AnalysisStore(Path(args.db))
    report = analyse_document(
        document,
        store=store,
        retention_hours=store.retention_hours if store else 24,
    )

    print(json.dumps(json.loads(report.model_dump_json()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
