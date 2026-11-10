from __future__ import annotations

import json
from pathlib import Path

from app.cli import main


def test_cli_analyses_pdf_without_store(
    sample_pdf_bytes: bytes, tmp_path: Path, capsys
) -> None:
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(sample_pdf_bytes)

    exit_code = main(["--no-store", str(pdf)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert len(output["analysis_id"]) == 36
    assert output["metadata"]["source_type"] == "pdf_upload"
    assert output["observations"]


def test_cli_rejects_missing_file(tmp_path: Path, capsys) -> None:
    exit_code = main(["--no-store", str(tmp_path / "missing.pdf")])

    assert exit_code == 2
    assert "No such file" in capsys.readouterr().err
