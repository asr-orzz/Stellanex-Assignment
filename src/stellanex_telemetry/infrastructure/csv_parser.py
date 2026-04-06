from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from stellanex_telemetry.application import IngestionBatch, IngestionIssue, TelemetryBatchParser
from stellanex_telemetry.domain import (
    GeoCoordinate,
    OperatingEnvelope,
    StationStatus,
    Substation,
    TelemetryQuality,
    TelemetryReading,
)

STATION_REQUIRED_COLUMNS = {
    "station_id",
    "name",
    "region",
    "status",
    "capacity_mw",
    "nominal_voltage_kv",
}

STATION_ALLOWED_COLUMNS = STATION_REQUIRED_COLUMNS | {
    "min_voltage_kv",
    "max_voltage_kv",
    "max_load_percent",
    "max_temperature_c",
    "latitude",
    "longitude",
    "commissioned_on",
    "tags",
}

TELEMETRY_REQUIRED_COLUMNS = {
    "station_id",
    "recorded_at",
    "voltage_kv",
    "load_percent",
    "temperature_c",
    "quality",
    "source",
}

TELEMETRY_ALLOWED_COLUMNS = TELEMETRY_REQUIRED_COLUMNS | {"sequence_number"}


@dataclass(frozen=True, slots=True)
class CsvDatasetFiles:
    station_path: Path | None = None
    telemetry_path: Path | None = None


class CsvTelemetryBatchParser(TelemetryBatchParser):
    """Parse dataset directories, manifest files, or individual CSV exports."""

    def parse(self, source_path: Path) -> IngestionBatch:
        issues: list[IngestionIssue] = []
        source = Path(source_path).resolve()
        files = self._resolve_dataset_files(source, issues)
        stations = ()
        readings = ()

        if files.station_path is not None:
            stations = parse_station_catalog_csv(files.station_path, issues=issues)

        known_station_ids = {station.station_id for station in stations} if stations else None
        if files.telemetry_path is not None:
            readings = parse_telemetry_readings_csv(
                files.telemetry_path,
                issues=issues,
                known_station_ids=known_station_ids,
            )

        if files.station_path is None and files.telemetry_path is None and not issues:
            issues.append(
                IngestionIssue(
                    message=f"No supported CSV inputs were found at '{source.name}'.",
                    severity="error",
                )
            )

        return IngestionBatch(
            source_path=source,
            stations=stations,
            readings=readings,
            issues=tuple(issues),
            imported_at=datetime.now(timezone.utc),
        )

    def _resolve_dataset_files(self, source_path: Path, issues: list[IngestionIssue]) -> CsvDatasetFiles:
        if not source_path.exists():
            issues.append(
                IngestionIssue(
                    message=f"Input path '{source_path}' does not exist.",
                    severity="error",
                )
            )
            return CsvDatasetFiles()

        if source_path.is_dir():
            return self._resolve_directory_files(source_path, issues)

        if source_path.suffix.lower() == ".json":
            return self._resolve_manifest_files(source_path, issues)

        if source_path.suffix.lower() == ".csv":
            schema = _classify_csv_file(source_path, issues)
            if schema == "stations":
                return CsvDatasetFiles(station_path=source_path)
            if schema == "telemetry":
                return CsvDatasetFiles(telemetry_path=source_path)
            return CsvDatasetFiles()

        issues.append(
            IngestionIssue(
                message=f"Unsupported input type '{source_path.suffix or '<none>'}' for '{source_path.name}'.",
                severity="error",
            )
        )
        return CsvDatasetFiles()

    def _resolve_directory_files(self, directory: Path, issues: list[IngestionIssue]) -> CsvDatasetFiles:
        manifest_path = directory / "manifest.json"
        if manifest_path.exists():
            return self._resolve_manifest_files(manifest_path, issues)

        station_path = directory / "stations.csv"
        telemetry_path = directory / "telemetry_readings.csv"

        if not station_path.exists():
            issues.append(
                IngestionIssue(
                    message=f"Station catalog 'stations.csv' was not found in '{directory.name}'.",
                    severity="warning",
                )
            )
            station_path = None
        if not telemetry_path.exists():
            issues.append(
                IngestionIssue(
                    message=f"Telemetry export 'telemetry_readings.csv' was not found in '{directory.name}'.",
                    severity="warning",
                )
            )
            telemetry_path = None

        return CsvDatasetFiles(station_path=station_path, telemetry_path=telemetry_path)

    def _resolve_manifest_files(self, manifest_path: Path, issues: list[IngestionIssue]) -> CsvDatasetFiles:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            issues.append(
                IngestionIssue(
                    message=f"Manifest '{manifest_path.name}' does not exist.",
                    severity="error",
                )
            )
            return CsvDatasetFiles()
        except json.JSONDecodeError as exc:
            issues.append(
                IngestionIssue(
                    message=f"Manifest '{manifest_path.name}' is not valid JSON: {exc.msg}.",
                    severity="error",
                )
            )
            return CsvDatasetFiles()

        file_map = payload.get("files", {}) if isinstance(payload, dict) else {}
        station_reference = file_map.get("stations", "stations.csv")
        telemetry_reference = file_map.get("telemetry", "telemetry_readings.csv")
        base_dir = manifest_path.parent

        station_path = _resolve_relative_path(base_dir, station_reference)
        telemetry_path = _resolve_relative_path(base_dir, telemetry_reference)

        if station_path is not None and not station_path.exists():
            issues.append(
                IngestionIssue(
                    message=f"Manifest references missing station file '{station_reference}'.",
                    severity="error",
                )
            )
            station_path = None
        if telemetry_path is not None and not telemetry_path.exists():
            issues.append(
                IngestionIssue(
                    message=f"Manifest references missing telemetry file '{telemetry_reference}'.",
                    severity="error",
                )
            )
            telemetry_path = None

        return CsvDatasetFiles(station_path=station_path, telemetry_path=telemetry_path)


def parse_station_catalog_csv(
    source_path: Path,
    *,
    issues: list[IngestionIssue] | None = None,
) -> tuple[Substation, ...]:
    collected_issues = issues if issues is not None else []
    rows = _read_csv_rows(source_path, required_columns=STATION_REQUIRED_COLUMNS, allowed_columns=STATION_ALLOWED_COLUMNS, issues=collected_issues)
    stations: list[Substation] = []
    seen_station_ids: set[str] = set()

    for row_number, row in rows:
        station = _build_station_from_row(row, row_number=row_number, source_path=source_path, issues=collected_issues)
        if station is None:
            continue
        if station.station_id in seen_station_ids:
            collected_issues.append(
                IngestionIssue(
                    message=f"Duplicate station_id '{station.station_id}' found in '{source_path.name}'.",
                    severity="error",
                    row_number=row_number,
                    field_name="station_id",
                )
            )
            continue
        seen_station_ids.add(station.station_id)
        stations.append(station)

    return tuple(stations)


def parse_telemetry_readings_csv(
    source_path: Path,
    *,
    issues: list[IngestionIssue] | None = None,
    known_station_ids: set[str] | None = None,
) -> tuple[TelemetryReading, ...]:
    collected_issues = issues if issues is not None else []
    rows = _read_csv_rows(
        source_path,
        required_columns=TELEMETRY_REQUIRED_COLUMNS,
        allowed_columns=TELEMETRY_ALLOWED_COLUMNS,
        issues=collected_issues,
    )
    readings: list[TelemetryReading] = []
    seen_keys: set[tuple[str, datetime]] = set()

    for row_number, row in rows:
        reading = _build_reading_from_row(row, row_number=row_number, source_path=source_path, issues=collected_issues)
        if reading is None:
            continue
        if known_station_ids is not None and reading.station_id not in known_station_ids:
            collected_issues.append(
                IngestionIssue(
                    message=(
                        f"Telemetry row references station_id '{reading.station_id}' "
                        f"that is not present in the station catalog."
                    ),
                    severity="error",
                    row_number=row_number,
                    field_name="station_id",
                )
            )
            continue
        dedupe_key = (reading.station_id, reading.recorded_at)
        if dedupe_key in seen_keys:
            collected_issues.append(
                IngestionIssue(
                    message=(
                        f"Duplicate telemetry reading for station_id '{reading.station_id}' "
                        f"at '{reading.recorded_at.isoformat()}'."
                    ),
                    severity="error",
                    row_number=row_number,
                    field_name="recorded_at",
                )
            )
            continue
        seen_keys.add(dedupe_key)
        readings.append(reading)

    return tuple(readings)


def _read_csv_rows(
    source_path: Path,
    *,
    required_columns: set[str],
    allowed_columns: set[str],
    issues: list[IngestionIssue],
) -> list[tuple[int, dict[str, str]]]:
    try:
        with source_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
            reader = csv.DictReader(file_obj)
            if reader.fieldnames is None:
                issues.append(
                    IngestionIssue(
                        message=f"CSV file '{source_path.name}' is missing a header row.",
                        severity="error",
                    )
                )
                return []

            normalized_headers = [header.strip() for header in reader.fieldnames if header is not None]
            header_set = set(normalized_headers)
            missing_headers = sorted(required_columns - header_set)
            if missing_headers:
                issues.append(
                    IngestionIssue(
                        message=(
                            f"CSV file '{source_path.name}' is missing required columns: "
                            f"{', '.join(missing_headers)}."
                        ),
                        severity="error",
                    )
                )
                return []

            extra_headers = sorted(header_set - allowed_columns)
            if extra_headers:
                issues.append(
                    IngestionIssue(
                        message=(
                            f"CSV file '{source_path.name}' contains unexpected columns: "
                            f"{', '.join(extra_headers)}."
                        ),
                        severity="warning",
                    )
                )

            rows: list[tuple[int, dict[str, str]]] = []
            for row_number, raw_row in enumerate(reader, start=2):
                normalized_row = _normalize_csv_row(raw_row)
                if not any(normalized_row.values()):
                    continue
                rows.append((row_number, normalized_row))
            return rows
    except FileNotFoundError:
        issues.append(
            IngestionIssue(
                message=f"CSV file '{source_path.name}' does not exist.",
                severity="error",
            )
        )
    except OSError as exc:
        issues.append(
            IngestionIssue(
                message=f"Unable to read CSV file '{source_path.name}': {exc}.",
                severity="error",
            )
        )

    return []


def _normalize_csv_row(raw_row: dict[str | None, str | None]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in raw_row.items():
        if key is None:
            continue
        normalized[key.strip()] = (value or "").strip()
    return normalized


def _build_station_from_row(
    row: dict[str, str],
    *,
    row_number: int,
    source_path: Path,
    issues: list[IngestionIssue],
) -> Substation | None:
    station_id = _require_text_field(row, "station_id", row_number=row_number, source_path=source_path, issues=issues)
    name = _require_text_field(row, "name", row_number=row_number, source_path=source_path, issues=issues)
    region = _require_text_field(row, "region", row_number=row_number, source_path=source_path, issues=issues)
    status = _parse_station_status(row, row_number=row_number, source_path=source_path, issues=issues)
    capacity_mw = _parse_float_field(row, "capacity_mw", row_number=row_number, source_path=source_path, issues=issues)
    nominal_voltage_kv = _parse_float_field(
        row,
        "nominal_voltage_kv",
        row_number=row_number,
        source_path=source_path,
        issues=issues,
    )
    envelope = _parse_envelope(row, row_number=row_number, source_path=source_path, issues=issues)
    location = _parse_coordinate(row, row_number=row_number, source_path=source_path, issues=issues)
    commissioned_on = _parse_date_field(
        row,
        "commissioned_on",
        row_number=row_number,
        source_path=source_path,
        issues=issues,
        required=False,
    )
    tags = tuple(part.strip() for part in row.get("tags", "").split("|") if part.strip())

    if None in (station_id, name, region, status, capacity_mw, nominal_voltage_kv):
        return None

    try:
        return Substation(
            station_id=station_id,
            name=name,
            region=region,
            capacity_mw=capacity_mw,
            status=status,
            nominal_voltage_kv=nominal_voltage_kv,
            envelope=envelope,
            location=location,
            commissioned_on=commissioned_on,
            tags=tags,
        )
    except ValueError as exc:
        issues.append(
            IngestionIssue(
                message=f"Invalid station row in '{source_path.name}': {exc}.",
                severity="error",
                row_number=row_number,
            )
        )
        return None


def _build_reading_from_row(
    row: dict[str, str],
    *,
    row_number: int,
    source_path: Path,
    issues: list[IngestionIssue],
) -> TelemetryReading | None:
    station_id = _require_text_field(row, "station_id", row_number=row_number, source_path=source_path, issues=issues)
    recorded_at = _parse_datetime_field(row, "recorded_at", row_number=row_number, source_path=source_path, issues=issues)
    voltage_kv = _parse_float_field(row, "voltage_kv", row_number=row_number, source_path=source_path, issues=issues)
    load_percent = _parse_float_field(row, "load_percent", row_number=row_number, source_path=source_path, issues=issues)
    temperature_c = _parse_float_field(row, "temperature_c", row_number=row_number, source_path=source_path, issues=issues)
    quality = _parse_quality(row, row_number=row_number, source_path=source_path, issues=issues)
    source = _require_text_field(row, "source", row_number=row_number, source_path=source_path, issues=issues)
    sequence_number = _parse_int_field(
        row,
        "sequence_number",
        row_number=row_number,
        source_path=source_path,
        issues=issues,
        required=False,
    )

    if None in (station_id, recorded_at, voltage_kv, load_percent, temperature_c, quality, source):
        return None

    try:
        return TelemetryReading(
            station_id=station_id,
            recorded_at=recorded_at,
            voltage_kv=voltage_kv,
            load_percent=load_percent,
            temperature_c=temperature_c,
            quality=quality,
            source=source,
            sequence_number=sequence_number,
        )
    except ValueError as exc:
        issues.append(
            IngestionIssue(
                message=f"Invalid telemetry row in '{source_path.name}': {exc}.",
                severity="error",
                row_number=row_number,
            )
        )
        return None


def _parse_envelope(
    row: dict[str, str],
    *,
    row_number: int,
    source_path: Path,
    issues: list[IngestionIssue],
) -> OperatingEnvelope | None:
    envelope_fields = (
        "min_voltage_kv",
        "max_voltage_kv",
        "max_load_percent",
        "max_temperature_c",
    )
    if not any(row.get(field, "").strip() for field in envelope_fields):
        return None

    min_voltage = _parse_float_field(row, "min_voltage_kv", row_number=row_number, source_path=source_path, issues=issues)
    max_voltage = _parse_float_field(row, "max_voltage_kv", row_number=row_number, source_path=source_path, issues=issues)
    max_load = _parse_float_field(row, "max_load_percent", row_number=row_number, source_path=source_path, issues=issues)
    max_temperature = _parse_float_field(
        row,
        "max_temperature_c",
        row_number=row_number,
        source_path=source_path,
        issues=issues,
    )
    nominal_voltage = _parse_float_field(
        row,
        "nominal_voltage_kv",
        row_number=row_number,
        source_path=source_path,
        issues=issues,
    )

    if None in (nominal_voltage, min_voltage, max_voltage, max_load, max_temperature):
        return None

    try:
        return OperatingEnvelope(
            nominal_voltage_kv=nominal_voltage,
            min_voltage_kv=min_voltage,
            max_voltage_kv=max_voltage,
            max_load_percent=max_load,
            max_temperature_c=max_temperature,
        )
    except ValueError as exc:
        issues.append(
            IngestionIssue(
                message=f"Invalid operating envelope in '{source_path.name}': {exc}.",
                severity="error",
                row_number=row_number,
            )
        )
        return None


def _parse_coordinate(
    row: dict[str, str],
    *,
    row_number: int,
    source_path: Path,
    issues: list[IngestionIssue],
) -> GeoCoordinate | None:
    latitude_raw = row.get("latitude", "").strip()
    longitude_raw = row.get("longitude", "").strip()
    if not latitude_raw and not longitude_raw:
        return None
    if not latitude_raw or not longitude_raw:
        missing_field = "latitude" if not latitude_raw else "longitude"
        issues.append(
            IngestionIssue(
                message=(
                    f"Coordinate pair is incomplete in '{source_path.name}'; both latitude and longitude "
                    "must be provided together."
                ),
                severity="error",
                row_number=row_number,
                field_name=missing_field,
            )
        )
        return None

    latitude = _parse_float_field(row, "latitude", row_number=row_number, source_path=source_path, issues=issues)
    longitude = _parse_float_field(row, "longitude", row_number=row_number, source_path=source_path, issues=issues)
    if latitude is None or longitude is None:
        return None

    try:
        return GeoCoordinate(latitude=latitude, longitude=longitude)
    except ValueError as exc:
        issues.append(
            IngestionIssue(
                message=f"Invalid coordinate in '{source_path.name}': {exc}.",
                severity="error",
                row_number=row_number,
            )
        )
        return None


def _parse_station_status(
    row: dict[str, str],
    *,
    row_number: int,
    source_path: Path,
    issues: list[IngestionIssue],
) -> StationStatus | None:
    raw_value = _require_text_field(row, "status", row_number=row_number, source_path=source_path, issues=issues)
    if raw_value is None:
        return None
    try:
        return StationStatus(raw_value.lower())
    except ValueError:
        issues.append(
            IngestionIssue(
                message=(
                    f"Unsupported station status '{raw_value}' in '{source_path.name}'. "
                    f"Expected one of: {', '.join(status.value for status in StationStatus)}."
                ),
                severity="error",
                row_number=row_number,
                field_name="status",
            )
        )
        return None


def _parse_quality(
    row: dict[str, str],
    *,
    row_number: int,
    source_path: Path,
    issues: list[IngestionIssue],
) -> TelemetryQuality | None:
    raw_value = _require_text_field(row, "quality", row_number=row_number, source_path=source_path, issues=issues)
    if raw_value is None:
        return None
    try:
        return TelemetryQuality(raw_value.lower())
    except ValueError:
        issues.append(
            IngestionIssue(
                message=(
                    f"Unsupported telemetry quality '{raw_value}' in '{source_path.name}'. "
                    f"Expected one of: {', '.join(quality.value for quality in TelemetryQuality)}."
                ),
                severity="error",
                row_number=row_number,
                field_name="quality",
            )
        )
        return None


def _parse_datetime_field(
    row: dict[str, str],
    field_name: str,
    *,
    row_number: int,
    source_path: Path,
    issues: list[IngestionIssue],
    required: bool = True,
) -> datetime | None:
    raw_value = _get_field_value(
        row,
        field_name,
        row_number=row_number,
        source_path=source_path,
        issues=issues,
        required=required,
    )
    if raw_value is None:
        return None

    normalized = raw_value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        issues.append(
            IngestionIssue(
                message=(
                    f"Field '{field_name}' in '{source_path.name}' must be an ISO-8601 timestamp; "
                    f"received '{raw_value}'."
                ),
                severity="error",
                row_number=row_number,
                field_name=field_name,
            )
        )
        return None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        issues.append(
            IngestionIssue(
                message=(
                    f"Field '{field_name}' in '{source_path.name}' must include timezone information; "
                    f"received '{raw_value}'."
                ),
                severity="error",
                row_number=row_number,
                field_name=field_name,
            )
        )
        return None

    return parsed.astimezone(timezone.utc)


def _parse_date_field(
    row: dict[str, str],
    field_name: str,
    *,
    row_number: int,
    source_path: Path,
    issues: list[IngestionIssue],
    required: bool = True,
) -> date | None:
    raw_value = _get_field_value(
        row,
        field_name,
        row_number=row_number,
        source_path=source_path,
        issues=issues,
        required=required,
    )
    if raw_value is None:
        return None

    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        issues.append(
            IngestionIssue(
                message=(
                    f"Field '{field_name}' in '{source_path.name}' must be an ISO date (YYYY-MM-DD); "
                    f"received '{raw_value}'."
                ),
                severity="error",
                row_number=row_number,
                field_name=field_name,
            )
        )
        return None


def _parse_float_field(
    row: dict[str, str],
    field_name: str,
    *,
    row_number: int,
    source_path: Path,
    issues: list[IngestionIssue],
    required: bool = True,
) -> float | None:
    raw_value = _get_field_value(
        row,
        field_name,
        row_number=row_number,
        source_path=source_path,
        issues=issues,
        required=required,
    )
    if raw_value is None:
        return None

    try:
        return float(raw_value)
    except ValueError:
        issues.append(
            IngestionIssue(
                message=f"Field '{field_name}' in '{source_path.name}' must be numeric; received '{raw_value}'.",
                severity="error",
                row_number=row_number,
                field_name=field_name,
            )
        )
        return None


def _parse_int_field(
    row: dict[str, str],
    field_name: str,
    *,
    row_number: int,
    source_path: Path,
    issues: list[IngestionIssue],
    required: bool = True,
) -> int | None:
    raw_value = _get_field_value(
        row,
        field_name,
        row_number=row_number,
        source_path=source_path,
        issues=issues,
        required=required,
    )
    if raw_value is None:
        return None

    try:
        return int(raw_value)
    except ValueError:
        issues.append(
            IngestionIssue(
                message=f"Field '{field_name}' in '{source_path.name}' must be an integer; received '{raw_value}'.",
                severity="error",
                row_number=row_number,
                field_name=field_name,
            )
        )
        return None


def _require_text_field(
    row: dict[str, str],
    field_name: str,
    *,
    row_number: int,
    source_path: Path,
    issues: list[IngestionIssue],
) -> str | None:
    return _get_field_value(
        row,
        field_name,
        row_number=row_number,
        source_path=source_path,
        issues=issues,
        required=True,
    )


def _get_field_value(
    row: dict[str, str],
    field_name: str,
    *,
    row_number: int,
    source_path: Path,
    issues: list[IngestionIssue],
    required: bool,
) -> str | None:
    raw_value = row.get(field_name, "").strip()
    if raw_value:
        return raw_value
    if required:
        issues.append(
            IngestionIssue(
                message=f"Field '{field_name}' is required in '{source_path.name}'.",
                severity="error",
                row_number=row_number,
                field_name=field_name,
            )
        )
    return None


def _resolve_relative_path(base_dir: Path, relative_value: object) -> Path | None:
    if not isinstance(relative_value, str) or not relative_value.strip():
        return None
    return (base_dir / relative_value.strip()).resolve()


def _classify_csv_file(source_path: Path, issues: list[IngestionIssue]) -> str | None:
    try:
        with source_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
            reader = csv.reader(file_obj)
            header = next(reader, None)
    except OSError as exc:
        issues.append(
            IngestionIssue(
                message=f"Unable to inspect CSV file '{source_path.name}': {exc}.",
                severity="error",
            )
        )
        return None

    if not header:
        issues.append(
            IngestionIssue(
                message=f"CSV file '{source_path.name}' is empty.",
                severity="error",
            )
        )
        return None

    header_set = {column.strip() for column in header if column is not None}
    if STATION_REQUIRED_COLUMNS.issubset(header_set):
        return "stations"
    if TELEMETRY_REQUIRED_COLUMNS.issubset(header_set):
        return "telemetry"

    issues.append(
        IngestionIssue(
            message=(
                f"CSV file '{source_path.name}' does not match a supported schema. "
                "Expected a station catalog or telemetry export."
            ),
            severity="error",
        )
    )
    return None
