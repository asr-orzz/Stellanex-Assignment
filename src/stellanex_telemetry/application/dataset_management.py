from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol, Sequence

from stellanex_telemetry.application.contracts import IngestionIssue, StationRepository, TelemetryRepository


@dataclass(frozen=True, slots=True)
class DatasetDescriptor:
    dataset_key: str
    label: str
    source_path: Path
    origin: str
    description: str
    station_count: int | None = None
    reading_count: int | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.dataset_key.strip():
            raise ValueError("dataset_key must not be empty")
        if not self.label.strip():
            raise ValueError("label must not be empty")
        if not self.origin.strip():
            raise ValueError("origin must not be empty")
        if not self.description.strip():
            raise ValueError("description must not be empty")
        if self.station_count is not None and self.station_count < 0:
            raise ValueError("station_count must be >= 0")
        if self.reading_count is not None and self.reading_count < 0:
            raise ValueError("reading_count must be >= 0")


@dataclass(frozen=True, slots=True)
class DatasetRuntime:
    descriptor: DatasetDescriptor
    station_repository: StationRepository
    telemetry_repository: TelemetryRepository
    issues: tuple[IngestionIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class DatasetImportReport:
    discovered_sources: int
    imported_datasets: tuple[DatasetDescriptor, ...] = ()
    issues: tuple[IngestionIssue, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.discovered_sources < 0:
            raise ValueError("discovered_sources must be >= 0")

    @property
    def imported_count(self) -> int:
        return len(self.imported_datasets)

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")


class DatasetWorkspace(Protocol):
    def list_datasets(self) -> Sequence[DatasetDescriptor]:
        """Return the datasets available to the operator UI."""

    def refresh_catalog(self) -> Sequence[DatasetDescriptor]:
        """Rescan the filesystem-backed dataset catalog and return the latest entries."""

    def load_dataset(self, dataset_key: str) -> DatasetRuntime:
        """Load a dataset into repositories ready for the application services."""

    def import_available(self) -> DatasetImportReport:
        """Normalize staged imports into the runtime dataset catalog."""
