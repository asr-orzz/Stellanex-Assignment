from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from stellanex_telemetry.application import (
    DatasetDescriptor,
    DatasetImportReport,
    DatasetRuntime,
    DatasetWorkspace,
    IngestionBatch,
    IngestionIssue,
    TelemetryImportSource,
)
from stellanex_telemetry.infrastructure.csv_parser import CsvTelemetryBatchParser
from stellanex_telemetry.infrastructure.station_repository import IndexedStationRepository
from stellanex_telemetry.infrastructure.telemetry_repository import IndexedTelemetryRepository


class FilesystemImportSource(TelemetryImportSource):
    """Discover dataset candidates staged in the shared imports directory."""

    def __init__(self, imports_dir: Path) -> None:
        self._imports_dir = Path(imports_dir).resolve()

    def discover(self) -> Sequence[Path]:
        if not self._imports_dir.exists():
            return ()

        reserved_root_names = {"manifest.json", "stations.csv", "telemetry_readings.csv"}
        discovered: list[Path] = []
        seen: set[Path] = set()

        root_manifest = self._imports_dir / "manifest.json"
        root_station_csv = self._imports_dir / "stations.csv"
        root_telemetry_csv = self._imports_dir / "telemetry_readings.csv"
        if root_manifest.exists() or (root_station_csv.exists() and root_telemetry_csv.exists()):
            seen.add(self._imports_dir)
            discovered.append(self._imports_dir)

        for child in sorted(self._imports_dir.iterdir(), key=lambda path: (not path.is_dir(), path.name.casefold())):
            if child.name.startswith("."):
                continue
            resolved = child.resolve()
            if resolved in seen:
                continue
            if child.is_dir():
                discovered.append(resolved)
                seen.add(resolved)
                continue
            if child.name in reserved_root_names:
                continue
            if child.suffix.lower() in {".json", ".csv"}:
                discovered.append(resolved)
                seen.add(resolved)

        return tuple(discovered)


class RuntimeDatasetWorkspace(DatasetWorkspace):
    """Manage demo and imported datasets that can be loaded into the desktop runtime."""

    def __init__(
        self,
        *,
        demo_data_dir: Path,
        imports_dir: Path,
        runtime_dir: Path,
        parser: CsvTelemetryBatchParser | None = None,
        import_source: TelemetryImportSource | None = None,
    ) -> None:
        self._demo_data_dir = Path(demo_data_dir).resolve()
        self._imports_dir = Path(imports_dir).resolve()
        self._runtime_dir = Path(runtime_dir).resolve()
        self._runtime_dataset_dir = self._runtime_dir / "datasets"
        self._runtime_dataset_dir.mkdir(parents=True, exist_ok=True)
        self._parser = parser or CsvTelemetryBatchParser()
        self._import_source = import_source or FilesystemImportSource(self._imports_dir)
        self._catalog: dict[str, DatasetDescriptor] = {}
        self.refresh_catalog()

    def list_datasets(self) -> Sequence[DatasetDescriptor]:
        return tuple(self._catalog.values())

    def refresh_catalog(self) -> Sequence[DatasetDescriptor]:
        descriptors: list[DatasetDescriptor] = []
        descriptors.append(self._build_demo_descriptor())

        if self._runtime_dataset_dir.exists():
            for dataset_dir in sorted(self._runtime_dataset_dir.iterdir(), key=lambda path: path.name.casefold()):
                if not dataset_dir.is_dir():
                    continue
                descriptor = self._build_imported_descriptor(dataset_dir)
                if descriptor is not None:
                    descriptors.append(descriptor)

        descriptors.sort(key=_dataset_sort_key)
        self._catalog = {descriptor.dataset_key: descriptor for descriptor in descriptors}
        return tuple(descriptors)

    def load_dataset(self, dataset_key: str) -> DatasetRuntime:
        descriptor = self._catalog.get(dataset_key)
        if descriptor is None:
            self.refresh_catalog()
            descriptor = self._catalog.get(dataset_key)
        if descriptor is None:
            raise LookupError(f"Dataset '{dataset_key}' is not available.")

        batch = self._parser.parse(descriptor.source_path)
        issues = list(batch.issues)
        if not batch.stations:
            issues.append(
                IngestionIssue(
                    message=f"Dataset '{descriptor.label}' does not contain any station metadata.",
                    severity="error",
                )
            )
        if not batch.readings:
            issues.append(
                IngestionIssue(
                    message=f"Dataset '{descriptor.label}' does not contain any telemetry readings.",
                    severity="error",
                )
            )

        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            formatted = "\n".join(f"- {issue.message}" for issue in errors)
            raise RuntimeError(f"Unable to load dataset '{descriptor.label}':\n{formatted}")

        return DatasetRuntime(
            descriptor=descriptor,
            station_repository=IndexedStationRepository.from_batch(batch),
            telemetry_repository=IndexedTelemetryRepository.from_batch(batch),
            issues=tuple(issues),
        )

    def import_available(self) -> DatasetImportReport:
        sources = tuple(self._import_source.discover())
        if not sources:
            return DatasetImportReport(
                discovered_sources=0,
                issues=(
                    IngestionIssue(
                        message=f"No import-ready datasets were found in '{self._imports_dir}'.",
                        severity="warning",
                    ),
                ),
            )

        imported_descriptors: list[DatasetDescriptor] = []
        issues: list[IngestionIssue] = []
        used_slugs = {
            path.name
            for path in self._runtime_dataset_dir.iterdir()
            if path.is_dir()
        }

        for source in sources:
            batch = self._parser.parse(source)
            issues.extend(batch.issues)
            if any(issue.severity == "error" for issue in batch.issues):
                continue
            if not batch.stations or not batch.readings:
                issues.append(
                    IngestionIssue(
                        message=f"Skipped '{source.name}' because it does not contain both station and telemetry data.",
                        severity="warning",
                    )
                )
                continue

            label = _resolve_import_label(source)
            slug = _unique_slug(_slugify(label), used_slugs)
            destination_dir = self._runtime_dataset_dir / slug
            imported_at = datetime.now(timezone.utc)
            _write_runtime_dataset(
                batch,
                destination_dir=destination_dir,
                label=label,
                imported_at=imported_at,
                source_path=source,
            )
            imported_descriptors.append(
                DatasetDescriptor(
                    dataset_key=f"import:{slug}",
                    label=label,
                    source_path=destination_dir,
                    origin="import",
                    description=f"Imported from {source.name}",
                    station_count=len(batch.stations),
                    reading_count=len(batch.readings),
                    updated_at=imported_at,
                )
            )

        self.refresh_catalog()
        return DatasetImportReport(
            discovered_sources=len(sources),
            imported_datasets=tuple(imported_descriptors),
            issues=tuple(issues),
        )

    def _build_demo_descriptor(self) -> DatasetDescriptor:
        payload = _read_manifest_payload(self._demo_data_dir)
        dataset_name = _read_text(payload, "dataset_name") or "Bundled Demo Dataset"
        station_count = _read_int(payload, "station_count")
        reading_count = _read_int(payload, "reading_count")
        updated_at = _read_datetime(payload, "generated_at") or _read_datetime(payload, "start_at")
        return DatasetDescriptor(
            dataset_key="demo",
            label=dataset_name,
            source_path=self._demo_data_dir,
            origin="demo",
            description="Bundled deterministic demo dataset",
            station_count=station_count,
            reading_count=reading_count,
            updated_at=updated_at,
        )

    def _build_imported_descriptor(self, dataset_dir: Path) -> DatasetDescriptor | None:
        payload = _read_manifest_payload(dataset_dir)
        if payload is None:
            return None

        dataset_name = _read_text(payload, "dataset_name") or dataset_dir.name.replace("-", " ").title()
        station_count = _read_int(payload, "station_count")
        reading_count = _read_int(payload, "reading_count")
        updated_at = _read_datetime(payload, "imported_at")
        source_name = _read_text(payload, "source_name") or dataset_dir.name
        return DatasetDescriptor(
            dataset_key=f"import:{dataset_dir.name}",
            label=dataset_name,
            source_path=dataset_dir,
            origin="import",
            description=f"Imported from {source_name}",
            station_count=station_count,
            reading_count=reading_count,
            updated_at=updated_at,
        )


def _write_runtime_dataset(
    batch: IngestionBatch,
    *,
    destination_dir: Path,
    label: str,
    imported_at: datetime,
    source_path: Path,
) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    _write_station_catalog(batch.stations, destination_dir / "stations.csv")
    _write_telemetry_readings(batch.readings, destination_dir / "telemetry_readings.csv")
    _write_manifest(
        destination=destination_dir / "manifest.json",
        label=label,
        station_count=len(batch.stations),
        reading_count=len(batch.readings),
        imported_at=imported_at,
        source_path=source_path,
    )


def _write_station_catalog(stations: Sequence[object], destination: Path) -> None:
    with destination.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(
            file_obj,
            fieldnames=[
                "station_id",
                "name",
                "region",
                "status",
                "capacity_mw",
                "nominal_voltage_kv",
                "min_voltage_kv",
                "max_voltage_kv",
                "max_load_percent",
                "max_temperature_c",
                "latitude",
                "longitude",
                "commissioned_on",
                "tags",
            ],
        )
        writer.writeheader()
        for station in stations:
            envelope = station.envelope
            writer.writerow(
                {
                    "station_id": station.station_id,
                    "name": station.name,
                    "region": station.region,
                    "status": station.status.value,
                    "capacity_mw": f"{station.capacity_mw:.1f}",
                    "nominal_voltage_kv": f"{station.nominal_voltage_kv:.1f}",
                    "min_voltage_kv": f"{envelope.min_voltage_kv:.1f}" if envelope else "",
                    "max_voltage_kv": f"{envelope.max_voltage_kv:.1f}" if envelope else "",
                    "max_load_percent": f"{envelope.max_load_percent:.1f}" if envelope else "",
                    "max_temperature_c": f"{envelope.max_temperature_c:.1f}" if envelope else "",
                    "latitude": f"{station.location.latitude:.4f}" if station.location else "",
                    "longitude": f"{station.location.longitude:.4f}" if station.location else "",
                    "commissioned_on": station.commissioned_on.isoformat() if station.commissioned_on else "",
                    "tags": "|".join(station.tags),
                }
            )


def _write_telemetry_readings(readings: Sequence[object], destination: Path) -> None:
    with destination.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(
            file_obj,
            fieldnames=[
                "station_id",
                "recorded_at",
                "voltage_kv",
                "load_percent",
                "temperature_c",
                "quality",
                "source",
                "sequence_number",
            ],
        )
        writer.writeheader()
        for reading in readings:
            writer.writerow(
                {
                    "station_id": reading.station_id,
                    "recorded_at": reading.recorded_at.isoformat().replace("+00:00", "Z"),
                    "voltage_kv": f"{reading.voltage_kv:.3f}",
                    "load_percent": f"{reading.load_percent:.3f}",
                    "temperature_c": f"{reading.temperature_c:.3f}",
                    "quality": reading.quality.value,
                    "source": reading.source,
                    "sequence_number": reading.sequence_number or "",
                }
            )


def _write_manifest(
    *,
    destination: Path,
    label: str,
    station_count: int,
    reading_count: int,
    imported_at: datetime,
    source_path: Path,
) -> None:
    payload = {
        "dataset_name": label,
        "origin": "import",
        "station_count": station_count,
        "reading_count": reading_count,
        "imported_at": imported_at.isoformat().replace("+00:00", "Z"),
        "source_path": str(source_path),
        "source_name": source_path.name,
        "files": {
            "stations": "stations.csv",
            "telemetry": "telemetry_readings.csv",
        },
    }
    with destination.open("w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, indent=2)
        file_obj.write("\n")


def _read_manifest_payload(dataset_path: Path) -> dict[str, object] | None:
    manifest_path = dataset_path / "manifest.json" if dataset_path.is_dir() else dataset_path
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_text(payload: dict[str, object] | None, key: str) -> str | None:
    if payload is None:
        return None
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_int(payload: dict[str, object] | None, key: str) -> int | None:
    if payload is None:
        return None
    value = payload.get(key)
    if isinstance(value, int):
        return value
    return None


def _read_datetime(payload: dict[str, object] | None, key: str) -> datetime | None:
    text = _read_text(payload, key)
    if text is None:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _resolve_import_label(source: Path) -> str:
    payload = _read_manifest_payload(source)
    if payload is not None:
        dataset_name = _read_text(payload, "dataset_name")
        if dataset_name is not None:
            return dataset_name
    base_name = source.name if source.is_dir() else source.stem
    normalized = re.sub(r"[-_]+", " ", base_name).strip()
    return normalized.title() or "Imported Dataset"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "imported-dataset"


def _unique_slug(base_slug: str, used_slugs: set[str]) -> str:
    candidate = base_slug
    suffix = 2
    while candidate in used_slugs:
        candidate = f"{base_slug}-{suffix}"
        suffix += 1
    used_slugs.add(candidate)
    return candidate


def _dataset_sort_key(descriptor: DatasetDescriptor) -> tuple[int, str]:
    origin_rank = 0 if descriptor.origin == "demo" else 1
    return (origin_rank, descriptor.label.casefold())
