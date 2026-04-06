from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import fmean
from typing import Sequence

from stellanex_telemetry.application.alerting import ThresholdAlertPolicyEngine
from stellanex_telemetry.application.contracts import StationQuery, StationRepository, TelemetryRepository
from stellanex_telemetry.domain import Alert, AlertSeverity, OperatingEnvelope, StationStatus, Substation, TelemetryReading


@dataclass(frozen=True, slots=True)
class FleetHealthScoringConfig:
    critical_alert_penalty: int = 35
    warning_alert_penalty: int = 14
    info_alert_penalty: int = 4
    critical_status_penalty: int = 18
    warning_status_penalty: int = 8
    maintenance_status_penalty: int = 5
    unknown_status_penalty: int = 10
    missing_reading_penalty: int = 65
    load_stress_penalty: int = 12
    temperature_stress_penalty: int = 10
    voltage_stress_penalty: int = 10
    stress_penalty_floor_ratio: float = 0.7

    def __post_init__(self) -> None:
        integer_fields = (
            "critical_alert_penalty",
            "warning_alert_penalty",
            "info_alert_penalty",
            "critical_status_penalty",
            "warning_status_penalty",
            "maintenance_status_penalty",
            "unknown_status_penalty",
            "missing_reading_penalty",
            "load_stress_penalty",
            "temperature_stress_penalty",
            "voltage_stress_penalty",
        )
        for field_name in integer_fields:
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be >= 0")
        if not 0.0 <= self.stress_penalty_floor_ratio < 1.0:
            raise ValueError("stress_penalty_floor_ratio must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class StationHealthSnapshot:
    station: Substation
    latest_reading: TelemetryReading | None
    alerts: tuple[Alert, ...]
    health_score: int
    derived_status: StationStatus
    status_reason: str
    generated_at: datetime
    load_utilization_ratio: float | None = None
    temperature_utilization_ratio: float | None = None
    voltage_boundary_risk: float | None = None

    @property
    def primary_alert(self) -> Alert | None:
        return self.alerts[0] if self.alerts else None

    @property
    def alert_count(self) -> int:
        return len(self.alerts)

    @property
    def highest_alert_severity(self) -> AlertSeverity | None:
        return self.primary_alert.severity if self.primary_alert is not None else None

    @property
    def risk_index(self) -> float:
        return round((100 - self.health_score) / 100, 4)


@dataclass(frozen=True, slots=True)
class RegionHealthSnapshot:
    region: str
    station_count: int
    healthy_stations: int
    warning_stations: int
    critical_stations: int
    maintenance_stations: int
    offline_stations: int
    average_health_score: float
    active_alert_count: int


@dataclass(frozen=True, slots=True)
class FleetHealthSnapshot:
    generated_at: datetime
    station_snapshots: tuple[StationHealthSnapshot, ...]
    region_snapshots: tuple[RegionHealthSnapshot, ...]
    fleet_health_score: float
    active_alerts: tuple[Alert, ...]
    total_stations: int
    healthy_stations: int
    warning_stations: int
    critical_stations: int
    maintenance_stations: int
    offline_stations: int

    @property
    def active_alert_count(self) -> int:
        return len(self.active_alerts)

    def top_priority_stations(self, limit: int = 5) -> tuple[StationHealthSnapshot, ...]:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        return self.station_snapshots[:limit]


class FleetHealthAggregator:
    """Build operator-facing fleet health views from the latest station telemetry."""

    def __init__(
        self,
        *,
        alert_engine: ThresholdAlertPolicyEngine | None = None,
        scoring_config: FleetHealthScoringConfig | None = None,
    ) -> None:
        self._alert_engine = alert_engine or ThresholdAlertPolicyEngine()
        self._scoring_config = scoring_config or FleetHealthScoringConfig()

    @property
    def alert_engine(self) -> ThresholdAlertPolicyEngine:
        return self._alert_engine

    @property
    def scoring_config(self) -> FleetHealthScoringConfig:
        return self._scoring_config

    def build_snapshot(
        self,
        station_repository: StationRepository,
        telemetry_repository: TelemetryRepository,
        *,
        station_query: StationQuery | None = None,
        generated_at: datetime | None = None,
    ) -> FleetHealthSnapshot:
        if generated_at is not None and (generated_at.tzinfo is None or generated_at.utcoffset() is None):
            raise ValueError("generated_at must be timezone-aware")
        snapshot_time = generated_at or datetime.now(timezone.utc)
        stations = tuple(station_repository.list_stations(query=station_query))

        station_snapshots: list[StationHealthSnapshot] = []
        active_alerts: list[Alert] = []
        for station in stations:
            latest_reading = telemetry_repository.get_latest_reading(station.station_id)
            alerts = self._alert_engine.evaluate_station(station, latest_reading)
            station_snapshot = self._build_station_snapshot(
                station=station,
                latest_reading=latest_reading,
                alerts=alerts,
                generated_at=snapshot_time,
            )
            station_snapshots.append(station_snapshot)
            active_alerts.extend(alerts)

        ordered_station_snapshots = tuple(sorted(station_snapshots, key=_station_snapshot_sort_key))
        ordered_alerts = tuple(sorted(active_alerts, key=_alert_sort_key))
        region_snapshots = self._build_region_snapshots(ordered_station_snapshots)

        return FleetHealthSnapshot(
            generated_at=snapshot_time,
            station_snapshots=ordered_station_snapshots,
            region_snapshots=region_snapshots,
            fleet_health_score=_mean_score(ordered_station_snapshots),
            active_alerts=ordered_alerts,
            total_stations=len(ordered_station_snapshots),
            healthy_stations=sum(1 for snapshot in ordered_station_snapshots if snapshot.derived_status is StationStatus.HEALTHY),
            warning_stations=sum(1 for snapshot in ordered_station_snapshots if snapshot.derived_status is StationStatus.WARNING),
            critical_stations=sum(1 for snapshot in ordered_station_snapshots if snapshot.derived_status is StationStatus.CRITICAL),
            maintenance_stations=sum(1 for snapshot in ordered_station_snapshots if snapshot.derived_status is StationStatus.MAINTENANCE),
            offline_stations=sum(1 for snapshot in ordered_station_snapshots if snapshot.derived_status is StationStatus.OFFLINE),
        )

    def _build_station_snapshot(
        self,
        *,
        station: Substation,
        latest_reading: TelemetryReading | None,
        alerts: tuple[Alert, ...],
        generated_at: datetime,
    ) -> StationHealthSnapshot:
        load_ratio = None
        temperature_ratio = None
        voltage_risk = None
        if latest_reading is not None and station.envelope is not None:
            load_ratio = latest_reading.load_percent / station.envelope.max_load_percent if station.envelope.max_load_percent else None
            temperature_ratio = (
                latest_reading.temperature_c / station.envelope.max_temperature_c
                if station.envelope.max_temperature_c
                else None
            )
            voltage_risk = _compute_voltage_boundary_risk(latest_reading, station.envelope)

        health_score = self._score_station(
            station=station,
            latest_reading=latest_reading,
            alerts=alerts,
            load_ratio=load_ratio,
            temperature_ratio=temperature_ratio,
            voltage_risk=voltage_risk,
        )
        derived_status, status_reason = self._derive_status(
            station=station,
            latest_reading=latest_reading,
            alerts=alerts,
            health_score=health_score,
        )
        return StationHealthSnapshot(
            station=station,
            latest_reading=latest_reading,
            alerts=alerts,
            health_score=health_score,
            derived_status=derived_status,
            status_reason=status_reason,
            generated_at=generated_at,
            load_utilization_ratio=_round_ratio(load_ratio),
            temperature_utilization_ratio=_round_ratio(temperature_ratio),
            voltage_boundary_risk=_round_ratio(voltage_risk),
        )

    def _score_station(
        self,
        *,
        station: Substation,
        latest_reading: TelemetryReading | None,
        alerts: Sequence[Alert],
        load_ratio: float | None,
        temperature_ratio: float | None,
        voltage_risk: float | None,
    ) -> int:
        config = self._scoring_config
        score = 100

        score -= _base_status_penalty(station.status, config)

        if latest_reading is None:
            score -= config.missing_reading_penalty
            return max(0, score)

        for alert in alerts:
            if alert.severity is AlertSeverity.CRITICAL:
                score -= config.critical_alert_penalty
            elif alert.severity is AlertSeverity.WARNING:
                score -= config.warning_alert_penalty
            else:
                score -= config.info_alert_penalty

        score -= _stress_penalty(
            load_ratio,
            max_penalty=config.load_stress_penalty,
            floor_ratio=config.stress_penalty_floor_ratio,
        )
        score -= _stress_penalty(
            temperature_ratio,
            max_penalty=config.temperature_stress_penalty,
            floor_ratio=config.stress_penalty_floor_ratio,
        )
        score -= _stress_penalty(
            voltage_risk,
            max_penalty=config.voltage_stress_penalty,
            floor_ratio=config.stress_penalty_floor_ratio,
        )

        return max(0, min(100, round(score)))

    def _derive_status(
        self,
        *,
        station: Substation,
        latest_reading: TelemetryReading | None,
        alerts: Sequence[Alert],
        health_score: int,
    ) -> tuple[StationStatus, str]:
        if any(alert.severity is AlertSeverity.CRITICAL for alert in alerts):
            primary = next(alert for alert in alerts if alert.severity is AlertSeverity.CRITICAL)
            return (StationStatus.CRITICAL, primary.message)

        if latest_reading is None:
            if station.status is StationStatus.MAINTENANCE:
                return (StationStatus.MAINTENANCE, "No telemetry is available while the station is marked for maintenance.")
            return (StationStatus.OFFLINE, "No telemetry is available for this station.")

        if any(alert.severity is AlertSeverity.WARNING for alert in alerts):
            primary = next(alert for alert in alerts if alert.severity is AlertSeverity.WARNING)
            return (StationStatus.WARNING, primary.message)

        if station.status is StationStatus.MAINTENANCE:
            return (StationStatus.MAINTENANCE, "Station is marked for maintenance and telemetry remains within configured thresholds.")

        if station.status is StationStatus.OFFLINE:
            return (StationStatus.OFFLINE, "Station metadata still marks this site as offline.")

        if station.status is StationStatus.CRITICAL:
            return (StationStatus.CRITICAL, "Station metadata currently flags this site as critical.")

        if station.status is StationStatus.WARNING:
            return (StationStatus.WARNING, "Station metadata currently flags this site for operator review.")

        if health_score < 80:
            return (StationStatus.WARNING, "Station is operating close to one or more configured limits.")

        return (StationStatus.HEALTHY, "Station is operating within configured limits.")

    def _build_region_snapshots(
        self,
        station_snapshots: Sequence[StationHealthSnapshot],
    ) -> tuple[RegionHealthSnapshot, ...]:
        grouped: dict[str, list[StationHealthSnapshot]] = defaultdict(list)
        for snapshot in station_snapshots:
            grouped[snapshot.station.region].append(snapshot)

        region_snapshots: list[RegionHealthSnapshot] = []
        for region in sorted(grouped, key=str.casefold):
            snapshots = grouped[region]
            region_snapshots.append(
                RegionHealthSnapshot(
                    region=region,
                    station_count=len(snapshots),
                    healthy_stations=sum(1 for snapshot in snapshots if snapshot.derived_status is StationStatus.HEALTHY),
                    warning_stations=sum(1 for snapshot in snapshots if snapshot.derived_status is StationStatus.WARNING),
                    critical_stations=sum(1 for snapshot in snapshots if snapshot.derived_status is StationStatus.CRITICAL),
                    maintenance_stations=sum(1 for snapshot in snapshots if snapshot.derived_status is StationStatus.MAINTENANCE),
                    offline_stations=sum(1 for snapshot in snapshots if snapshot.derived_status is StationStatus.OFFLINE),
                    average_health_score=_mean_score(snapshots),
                    active_alert_count=sum(snapshot.alert_count for snapshot in snapshots),
                )
            )
        return tuple(region_snapshots)


def _base_status_penalty(status: StationStatus, config: FleetHealthScoringConfig) -> int:
    penalties = {
        StationStatus.HEALTHY: 0,
        StationStatus.WARNING: config.warning_status_penalty,
        StationStatus.CRITICAL: config.critical_status_penalty,
        StationStatus.MAINTENANCE: config.maintenance_status_penalty,
        StationStatus.OFFLINE: config.missing_reading_penalty,
        StationStatus.UNKNOWN: config.unknown_status_penalty,
    }
    return penalties[status]


def _stress_penalty(
    ratio: float | None,
    *,
    max_penalty: int,
    floor_ratio: float,
) -> int:
    if ratio is None or max_penalty <= 0:
        return 0
    if ratio <= floor_ratio:
        return 0
    normalized_ratio = min(ratio, 1.0)
    penalty_fraction = (normalized_ratio - floor_ratio) / (1.0 - floor_ratio)
    return round(max_penalty * max(0.0, penalty_fraction))


def _compute_voltage_boundary_risk(reading: TelemetryReading, envelope: OperatingEnvelope) -> float | None:
    voltage_range = envelope.max_voltage_kv - envelope.min_voltage_kv
    if voltage_range <= 0:
        return None

    if reading.voltage_kv <= envelope.min_voltage_kv or reading.voltage_kv >= envelope.max_voltage_kv:
        return 1.0

    midpoint = envelope.min_voltage_kv + (voltage_range / 2.0)
    half_range = voltage_range / 2.0
    if half_range == 0:
        return None
    distance_from_midpoint = abs(reading.voltage_kv - midpoint)
    return min(distance_from_midpoint / half_range, 1.0)


def _mean_score(snapshots: Sequence[StationHealthSnapshot]) -> float:
    if not snapshots:
        return 0.0
    return round(fmean(snapshot.health_score for snapshot in snapshots), 2)


def _round_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 4)


def _status_rank(status: StationStatus) -> int:
    return {
        StationStatus.CRITICAL: 0,
        StationStatus.OFFLINE: 1,
        StationStatus.WARNING: 2,
        StationStatus.MAINTENANCE: 3,
        StationStatus.UNKNOWN: 4,
        StationStatus.HEALTHY: 5,
    }[status]


def _station_snapshot_sort_key(snapshot: StationHealthSnapshot) -> tuple[int, int, int, str]:
    return (
        _status_rank(snapshot.derived_status),
        snapshot.health_score,
        -snapshot.alert_count,
        snapshot.station.station_id.casefold(),
    )


def _alert_sort_key(alert: Alert) -> tuple[int, float, str, str]:
    return (
        -alert.severity.rank,
        -alert.triggered_at.timestamp(),
        alert.station_id.casefold(),
        alert.alert_id,
    )
