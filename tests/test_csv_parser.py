from __future__ import annotations

from pathlib import Path

from stellanex_telemetry.infrastructure import CsvTelemetryBatchParser


def test_parse_demo_dataset_directory_returns_expected_counts(demo_data_dir: Path) -> None:
    batch = CsvTelemetryBatchParser().parse(demo_data_dir)

    assert len(batch.stations) == 24
    assert len(batch.readings) == 4600
    assert batch.issues == ()


def test_parse_invalid_dataset_collects_row_level_validation_issues(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "invalid-dataset"
    dataset_dir.mkdir()

    (dataset_dir / "stations.csv").write_text(
        "\n".join(
            [
                "station_id,name,region,status,capacity_mw,nominal_voltage_kv,min_voltage_kv,max_voltage_kv,max_load_percent,max_temperature_c,latitude,longitude,commissioned_on,tags",
                "ST-001,Alpha Prime,North,healthy,100,220,210,230,95,80,28.61,77.21,2020-01-01,urban",
                "ST-001,Alpha Duplicate,North,warning,100,220,210,230,95,80,28.61,77.21,2020-01-01,urban",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (dataset_dir / "telemetry_readings.csv").write_text(
        "\n".join(
            [
                "station_id,recorded_at,voltage_kv,load_percent,temperature_c,quality,source,sequence_number",
                "ST-001,2026-01-01T00:00:00Z,221.0,75.0,42.0,ok,rtu-1,1",
                "ST-001,2026-01-01T00:00:00Z,221.2,76.0,42.5,ok,rtu-1,2",
                "ST-999,2026-01-01T00:15:00Z,220.8,74.0,41.8,ok,rtu-2,3",
                "ST-001,2026-01-01T00:30:00,220.5,73.0,41.7,ok,rtu-1,4",
                "ST-001,2026-01-01T00:45:00Z,220.2,72.0,41.0,bad,rtu-1,5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    batch = CsvTelemetryBatchParser().parse(dataset_dir)
    issue_messages = [issue.message for issue in batch.issues]

    assert len(batch.stations) == 1
    assert len(batch.readings) == 1
    assert any("Duplicate station_id" in message for message in issue_messages)
    assert any("Duplicate telemetry reading" in message for message in issue_messages)
    assert any("not present in the station catalog" in message for message in issue_messages)
    assert any("must include timezone information" in message for message in issue_messages)
    assert any("Unsupported telemetry quality" in message for message in issue_messages)
