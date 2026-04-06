from __future__ import annotations

import json
from pathlib import Path

from stellanex_telemetry.cli import main


def test_cli_validate_demo_dataset_reports_valid_status(
    isolated_cli_runtime_env: Path,
    capsys,
) -> None:
    exit_code = main(["validate", "--dataset", "demo"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Dataset Validation" in captured.out
    assert "Status: VALID" in captured.out
    assert "Stations: 24" in captured.out
    assert captured.err == ""


def test_cli_report_writes_json_export(
    isolated_cli_runtime_env: Path,
    tmp_path: Path,
    capsys,
) -> None:
    output_path = tmp_path / "artifacts" / "demo_report.json"

    exit_code = main(
        [
            "report",
            "--dataset",
            "demo",
            "--format",
            "json",
            "--output",
            str(output_path),
            "--top-stations",
            "3",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert output_path.exists()
    assert payload["dataset"]["key"] == "demo"
    assert payload["fleet"]["station_count"] == 24
    assert len(payload["priority_stations"]) == 3
    assert "Wrote output to" in captured.out
    assert captured.err == ""


def test_cli_validate_invalid_source_returns_nonzero(tmp_path: Path, capsys) -> None:
    invalid_dataset_dir = tmp_path / "empty-source"
    invalid_dataset_dir.mkdir()

    exit_code = main(["validate", "--source", str(invalid_dataset_dir)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Status: INVALID" in captured.out
    assert "Dataset validation requires a station catalog." in captured.out
    assert "Dataset validation requires at least one telemetry reading." in captured.out
    assert captured.err == ""
