"""Infrastructure adapters for datasets and persistence."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "CsvTelemetryBatchParser",
    "DemoDataset",
    "DemoDatasetSpec",
    "IndexedStationRepository",
    "build_demo_dataset",
    "build_demo_readings",
    "build_demo_stations",
    "parse_station_catalog_csv",
    "parse_telemetry_readings_csv",
    "write_demo_dataset",
]

_EXPORT_MODULES = {
    "CsvTelemetryBatchParser": "stellanex_telemetry.infrastructure.csv_parser",
    "DemoDataset": "stellanex_telemetry.infrastructure.demo_dataset",
    "DemoDatasetSpec": "stellanex_telemetry.infrastructure.demo_dataset",
    "IndexedStationRepository": "stellanex_telemetry.infrastructure.station_repository",
    "build_demo_dataset": "stellanex_telemetry.infrastructure.demo_dataset",
    "build_demo_readings": "stellanex_telemetry.infrastructure.demo_dataset",
    "build_demo_stations": "stellanex_telemetry.infrastructure.demo_dataset",
    "parse_station_catalog_csv": "stellanex_telemetry.infrastructure.csv_parser",
    "parse_telemetry_readings_csv": "stellanex_telemetry.infrastructure.csv_parser",
    "write_demo_dataset": "stellanex_telemetry.infrastructure.demo_dataset",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is not None:
        module = import_module(module_name)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
