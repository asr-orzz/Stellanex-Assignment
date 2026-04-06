from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol, Sequence

from stellanex_telemetry.domain import (
    Alert,
    AlertSeverity,
    StationStatus,
    Substation,
    TelemetryQuality,
    TelemetryReading,
)


@dataclass(frozen=True, slots=True)
class StationQuery:
    station_ids: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    statuses: tuple[StationStatus, ...] = ()
    required_tags: tuple[str, ...] = ()
    search_text: str | None = None
    limit: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "station_ids", tuple(station_id.strip() for station_id in self.station_ids if station_id.strip()))
        object.__setattr__(self, "regions", tuple(region.strip() for region in self.regions if region.strip()))
        object.__setattr__(self, "required_tags", tuple(tag.strip().lower() for tag in self.required_tags if tag.strip()))
        if self.search_text is not None:
            normalized = self.search_text.strip()
            object.__setattr__(self, "search_text", normalized or None)
        if self.limit is not None and self.limit <= 0:
            raise ValueError("limit must be greater than zero")


@dataclass(frozen=True, slots=True)
class TelemetryQuery:
    station_ids: tuple[str, ...] = ()
    start_at: datetime | None = None
    end_at: datetime | None = None
    qualities: tuple[TelemetryQuality, ...] = ()
    limit: int | None = None
    newest_first: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "station_ids", tuple(station_id.strip() for station_id in self.station_ids if station_id.strip()))
        if self.start_at and self.end_at and self.start_at > self.end_at:
            raise ValueError("start_at must be earlier than or equal to end_at")
        if self.limit is not None and self.limit <= 0:
            raise ValueError("limit must be greater than zero")


@dataclass(frozen=True, slots=True)
class AlertQuery:
    station_ids: tuple[str, ...] = ()
    severities: tuple[AlertSeverity, ...] = ()
    active_only: bool = True
    limit: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "station_ids", tuple(station_id.strip() for station_id in self.station_ids if station_id.strip()))
        if self.limit is not None and self.limit <= 0:
            raise ValueError("limit must be greater than zero")


@dataclass(frozen=True, slots=True)
class IngestionIssue:
    message: str
    severity: str = "error"
    row_number: int | None = None
    field_name: str | None = None

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("message must not be empty")
        if self.row_number is not None and self.row_number <= 0:
            raise ValueError("row_number must be greater than zero")
        if self.field_name is not None and not self.field_name.strip():
            raise ValueError("field_name must not be empty when provided")
        severity = self.severity.strip().lower()
        if severity not in {"warning", "error"}:
            raise ValueError("severity must be either 'warning' or 'error'")
        object.__setattr__(self, "severity", severity)
        if self.field_name is not None:
            object.__setattr__(self, "field_name", self.field_name.strip())


@dataclass(frozen=True, slots=True)
class IngestionBatch:
    source_path: Path
    stations: tuple[Substation, ...] = ()
    readings: tuple[TelemetryReading, ...] = ()
    issues: tuple[IngestionIssue, ...] = ()
    imported_at: datetime | None = None

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)


@dataclass(frozen=True, slots=True)
class IngestionSummary:
    files_processed: int
    stations_loaded: int
    readings_loaded: int
    issues: tuple[IngestionIssue, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.files_processed < 0:
            raise ValueError("files_processed must be >= 0")
        if self.stations_loaded < 0:
            raise ValueError("stations_loaded must be >= 0")
        if self.readings_loaded < 0:
            raise ValueError("readings_loaded must be >= 0")

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)


class StationRepository(Protocol):
    def list_stations(self, query: StationQuery | None = None) -> Sequence[Substation]:
        """Return stations that match the provided query."""

    def get_station(self, station_id: str) -> Substation | None:
        """Return a single station by identifier when present."""

    def upsert_stations(self, stations: Sequence[Substation]) -> None:
        """Insert or replace station metadata."""


class TelemetryRepository(Protocol):
    def list_readings(self, query: TelemetryQuery | None = None) -> Sequence[TelemetryReading]:
        """Return telemetry readings that match the provided query."""

    def get_latest_reading(self, station_id: str) -> TelemetryReading | None:
        """Return the latest telemetry reading for a station."""

    def append_readings(self, readings: Sequence[TelemetryReading]) -> None:
        """Persist telemetry readings."""


class AlertRepository(Protocol):
    def list_alerts(self, query: AlertQuery | None = None) -> Sequence[Alert]:
        """Return alerts that match the provided query."""

    def upsert_alerts(self, alerts: Sequence[Alert]) -> None:
        """Insert or replace alerts."""


class TelemetryBatchParser(Protocol):
    def parse(self, source_path: Path) -> IngestionBatch:
        """Parse a file into normalized stations, telemetry readings, and issues."""


class TelemetryImportSource(Protocol):
    def discover(self) -> Sequence[Path]:
        """Return import files ready for ingestion."""


class TelemetryIngestionCoordinator(Protocol):
    def ingest_available(self) -> IngestionSummary:
        """Load all available import files into the configured repositories."""

