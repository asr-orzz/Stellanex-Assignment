from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum


class StationStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    MAINTENANCE = "maintenance"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class TelemetryQuality(str, Enum):
    OK = "ok"
    ESTIMATED = "estimated"
    DEGRADED = "degraded"
    MISSING = "missing"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {
            AlertSeverity.INFO: 1,
            AlertSeverity.WARNING: 2,
            AlertSeverity.CRITICAL: 3,
        }[self]


class AlertCategory(str, Enum):
    VOLTAGE = "voltage"
    LOAD = "load"
    TEMPERATURE = "temperature"
    CONNECTIVITY = "connectivity"
    ANOMALY = "anomaly"
    SYSTEM = "system"


def _require_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _require_finite(value: float, field_name: str, *, minimum: float | None = None) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}")
    return value


def _require_aware_timestamp(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class GeoCoordinate:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        latitude = _require_finite(self.latitude, "latitude")
        longitude = _require_finite(self.longitude, "longitude")
        if not -90.0 <= latitude <= 90.0:
            raise ValueError("latitude must be between -90 and 90")
        if not -180.0 <= longitude <= 180.0:
            raise ValueError("longitude must be between -180 and 180")


@dataclass(frozen=True, slots=True)
class OperatingEnvelope:
    nominal_voltage_kv: float
    min_voltage_kv: float
    max_voltage_kv: float
    max_load_percent: float
    max_temperature_c: float

    def __post_init__(self) -> None:
        nominal_voltage_kv = _require_finite(self.nominal_voltage_kv, "nominal_voltage_kv", minimum=0.0)
        min_voltage_kv = _require_finite(self.min_voltage_kv, "min_voltage_kv", minimum=0.0)
        max_voltage_kv = _require_finite(self.max_voltage_kv, "max_voltage_kv", minimum=0.0)
        max_load_percent = _require_finite(self.max_load_percent, "max_load_percent", minimum=0.0)
        max_temperature_c = _require_finite(self.max_temperature_c, "max_temperature_c")
        if min_voltage_kv > nominal_voltage_kv:
            raise ValueError("min_voltage_kv must be less than or equal to nominal_voltage_kv")
        if nominal_voltage_kv > max_voltage_kv:
            raise ValueError("nominal_voltage_kv must be less than or equal to max_voltage_kv")


@dataclass(frozen=True, slots=True)
class Substation:
    station_id: str
    name: str
    region: str
    capacity_mw: float
    status: StationStatus = StationStatus.UNKNOWN
    nominal_voltage_kv: float = 0.0
    envelope: OperatingEnvelope | None = None
    location: GeoCoordinate | None = None
    commissioned_on: date | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "station_id", _require_text(self.station_id, "station_id"))
        object.__setattr__(self, "name", _require_text(self.name, "name"))
        object.__setattr__(self, "region", _require_text(self.region, "region"))
        object.__setattr__(self, "capacity_mw", _require_finite(self.capacity_mw, "capacity_mw", minimum=0.0))
        object.__setattr__(
            self,
            "nominal_voltage_kv",
            _require_finite(self.nominal_voltage_kv, "nominal_voltage_kv", minimum=0.0),
        )
        object.__setattr__(self, "tags", self._normalize_tags(self.tags))
        if self.envelope and self.nominal_voltage_kv and self.envelope.nominal_voltage_kv != self.nominal_voltage_kv:
            raise ValueError("nominal_voltage_kv must match the operating envelope nominal voltage")

    @staticmethod
    def _normalize_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
        normalized = sorted({_require_text(tag, "tag").lower() for tag in tags})
        return tuple(normalized)

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.station_id})"


@dataclass(frozen=True, slots=True)
class TelemetryReading:
    station_id: str
    recorded_at: datetime
    voltage_kv: float
    load_percent: float
    temperature_c: float
    quality: TelemetryQuality = TelemetryQuality.OK
    source: str = "unknown"
    sequence_number: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "station_id", _require_text(self.station_id, "station_id"))
        object.__setattr__(self, "recorded_at", _require_aware_timestamp(self.recorded_at, "recorded_at"))
        object.__setattr__(self, "voltage_kv", _require_finite(self.voltage_kv, "voltage_kv", minimum=0.0))
        object.__setattr__(self, "load_percent", _require_finite(self.load_percent, "load_percent", minimum=0.0))
        object.__setattr__(self, "temperature_c", _require_finite(self.temperature_c, "temperature_c"))
        object.__setattr__(self, "source", _require_text(self.source, "source"))
        if self.sequence_number is not None and self.sequence_number < 0:
            raise ValueError("sequence_number must be >= 0")

    def metric_map(self) -> dict[str, float]:
        return {
            "voltage_kv": self.voltage_kv,
            "load_percent": self.load_percent,
            "temperature_c": self.temperature_c,
        }


@dataclass(frozen=True, slots=True)
class Alert:
    alert_id: str
    station_id: str
    severity: AlertSeverity
    category: AlertCategory
    message: str
    triggered_at: datetime
    metric_name: str | None = None
    observed_value: float | None = None
    threshold_value: float | None = None
    reading: TelemetryReading | None = None
    acknowledged: bool = False
    acknowledged_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "alert_id", _require_text(self.alert_id, "alert_id"))
        object.__setattr__(self, "station_id", _require_text(self.station_id, "station_id"))
        object.__setattr__(self, "message", _require_text(self.message, "message"))
        object.__setattr__(self, "triggered_at", _require_aware_timestamp(self.triggered_at, "triggered_at"))
        if self.metric_name is not None:
            object.__setattr__(self, "metric_name", _require_text(self.metric_name, "metric_name"))
        if self.observed_value is not None:
            object.__setattr__(self, "observed_value", _require_finite(self.observed_value, "observed_value"))
        if self.threshold_value is not None:
            object.__setattr__(self, "threshold_value", _require_finite(self.threshold_value, "threshold_value"))
        if self.acknowledged_at is not None:
            object.__setattr__(
                self,
                "acknowledged_at",
                _require_aware_timestamp(self.acknowledged_at, "acknowledged_at"),
            )
        if self.acknowledged and self.acknowledged_at is None:
            raise ValueError("acknowledged_at is required when acknowledged is True")
        if not self.acknowledged and self.acknowledged_at is not None:
            raise ValueError("acknowledged must be True when acknowledged_at is provided")

    @property
    def is_active(self) -> bool:
        return not self.acknowledged

    def dedupe_key(self) -> tuple[str, AlertCategory, str | None]:
        return (self.station_id, self.category, self.metric_name)

