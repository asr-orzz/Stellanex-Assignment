from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import fmean

from stellanex_telemetry.application.alerting import ThresholdAlertPolicyEngine
from stellanex_telemetry.application.anomaly_detection import TelemetryAnomalyDetector
from stellanex_telemetry.application.contracts import StationQuery, StationRepository, TelemetryQuery, TelemetryRepository
from stellanex_telemetry.application.fleet_health import FleetHealthAggregator, StationHealthSnapshot
from stellanex_telemetry.domain import Alert, AlertCategory, AlertSeverity, Substation, TelemetryQuality, TelemetryReading


@dataclass(frozen=True, slots=True)
class StationDetailQuery:
    station_id: str
    history_limit: int = 48

    def __post_init__(self) -> None:
        normalized_station_id = self.station_id.strip()
        if not normalized_station_id:
            raise ValueError("station_id must not be empty")
        object.__setattr__(self, "station_id", normalized_station_id)
        if self.history_limit <= 0:
            raise ValueError("history_limit must be greater than zero")


@dataclass(frozen=True, slots=True)
class StationTelemetryPoint:
    recorded_at: datetime
    voltage_kv: float
    load_percent: float
    temperature_c: float
    quality: TelemetryQuality


@dataclass(frozen=True, slots=True)
class StationMetricSummary:
    metric_name: str
    label: str
    unit: str
    current_value: float | None
    average_value: float | None
    minimum_value: float | None
    maximum_value: float | None
    delta_from_start: float | None
    lower_bound: float | None = None
    upper_bound: float | None = None
    utilization_ratio: float | None = None


@dataclass(frozen=True, slots=True)
class StationAlertSummary:
    source: str
    alert_id: str
    severity: AlertSeverity
    category: AlertCategory
    message: str
    triggered_at: datetime
    metric_name: str | None = None
    observed_value: float | None = None
    threshold_value: float | None = None


@dataclass(frozen=True, slots=True)
class StationDetailResult:
    station: Substation
    generated_at: datetime
    reference_time: datetime
    history_start_at: datetime | None
    history_end_at: datetime | None
    latest_reading: TelemetryReading | None
    health_snapshot: StationHealthSnapshot
    metric_summaries: tuple[StationMetricSummary, ...]
    history_points: tuple[StationTelemetryPoint, ...]
    threshold_alerts: tuple[StationAlertSummary, ...]
    anomaly_alerts: tuple[StationAlertSummary, ...]
    active_alerts: tuple[StationAlertSummary, ...]

    @property
    def history_point_count(self) -> int:
        return len(self.history_points)


class StationDetailQueryService:
    """Assemble a single station detail model for the desktop presentation layer."""

    def __init__(
        self,
        *,
        alert_engine: ThresholdAlertPolicyEngine | None = None,
        anomaly_detector: TelemetryAnomalyDetector | None = None,
        health_aggregator: FleetHealthAggregator | None = None,
    ) -> None:
        self._alert_engine = alert_engine or ThresholdAlertPolicyEngine()
        self._anomaly_detector = anomaly_detector or TelemetryAnomalyDetector()
        self._health_aggregator = health_aggregator or FleetHealthAggregator(alert_engine=self._alert_engine)

    def get_station_detail(
        self,
        station_repository: StationRepository,
        telemetry_repository: TelemetryRepository,
        query: StationDetailQuery,
    ) -> StationDetailResult:
        station = station_repository.get_station(query.station_id)
        if station is None:
            raise LookupError(f"Station '{query.station_id}' was not found.")

        generated_at = datetime.now(timezone.utc)
        reference_time = _resolve_reference_time(telemetry_repository, station.station_id)
        reading_history = tuple(
            reversed(
                telemetry_repository.list_readings(
                    TelemetryQuery(
                        station_ids=(station.station_id,),
                        end_at=reference_time,
                        newest_first=True,
                        limit=query.history_limit,
                    )
                )
            )
        )
        latest_reading = reading_history[-1] if reading_history else None

        health_snapshot = _resolve_health_snapshot(
            station_repository=station_repository,
            telemetry_repository=telemetry_repository,
            aggregator=self._health_aggregator,
            station_id=station.station_id,
            reference_time=reference_time,
        )
        threshold_alerts = tuple(
            _to_alert_summary(alert, source="threshold")
            for alert in self._alert_engine.evaluate_station(station, latest_reading)
        )
        anomaly_alerts = tuple(
            _to_alert_summary(alert, source="anomaly")
            for alert in self._anomaly_detector.evaluate_station(
                station,
                reading_history,
                reference_time=reference_time,
            )
        )
        active_alerts = tuple(sorted((*threshold_alerts, *anomaly_alerts), key=_alert_summary_sort_key))

        return StationDetailResult(
            station=station,
            generated_at=generated_at,
            reference_time=reference_time,
            history_start_at=reading_history[0].recorded_at if reading_history else None,
            history_end_at=reading_history[-1].recorded_at if reading_history else None,
            latest_reading=latest_reading,
            health_snapshot=health_snapshot,
            metric_summaries=_build_metric_summaries(station, reading_history, health_snapshot),
            history_points=tuple(
                StationTelemetryPoint(
                    recorded_at=reading.recorded_at,
                    voltage_kv=reading.voltage_kv,
                    load_percent=reading.load_percent,
                    temperature_c=reading.temperature_c,
                    quality=reading.quality,
                )
                for reading in reading_history
            ),
            threshold_alerts=threshold_alerts,
            anomaly_alerts=anomaly_alerts,
            active_alerts=active_alerts,
        )


def _resolve_reference_time(
    telemetry_repository: TelemetryRepository,
    station_id: str,
) -> datetime:
    fleet_latest = telemetry_repository.list_readings(TelemetryQuery(newest_first=True, limit=1))
    if fleet_latest:
        return fleet_latest[0].recorded_at

    station_latest = telemetry_repository.get_latest_reading(station_id)
    if station_latest is not None:
        return station_latest.recorded_at

    return datetime.now(timezone.utc)


def _resolve_health_snapshot(
    *,
    station_repository: StationRepository,
    telemetry_repository: TelemetryRepository,
    aggregator: FleetHealthAggregator,
    station_id: str,
    reference_time: datetime,
) -> StationHealthSnapshot:
    snapshot = aggregator.build_snapshot(
        station_repository,
        telemetry_repository,
        station_query=StationQuery(station_ids=(station_id,)),
        generated_at=reference_time,
    )
    if not snapshot.station_snapshots:
        raise LookupError(f"Station '{station_id}' was not found.")
    return snapshot.station_snapshots[0]


def _build_metric_summaries(
    station: Substation,
    readings: tuple[TelemetryReading, ...],
    health_snapshot: StationHealthSnapshot,
) -> tuple[StationMetricSummary, ...]:
    return (
        _build_metric_summary(
            readings,
            metric_name="voltage_kv",
            label="Voltage",
            unit="kV",
            lower_bound=station.envelope.min_voltage_kv if station.envelope else None,
            upper_bound=station.envelope.max_voltage_kv if station.envelope else None,
            utilization_ratio=health_snapshot.voltage_boundary_risk,
        ),
        _build_metric_summary(
            readings,
            metric_name="load_percent",
            label="Load",
            unit="%",
            lower_bound=0.0,
            upper_bound=station.envelope.max_load_percent if station.envelope else 100.0,
            utilization_ratio=health_snapshot.load_utilization_ratio,
        ),
        _build_metric_summary(
            readings,
            metric_name="temperature_c",
            label="Temperature",
            unit="C",
            lower_bound=None,
            upper_bound=station.envelope.max_temperature_c if station.envelope else None,
            utilization_ratio=health_snapshot.temperature_utilization_ratio,
        ),
    )


def _build_metric_summary(
    readings: tuple[TelemetryReading, ...],
    *,
    metric_name: str,
    label: str,
    unit: str,
    lower_bound: float | None,
    upper_bound: float | None,
    utilization_ratio: float | None,
) -> StationMetricSummary:
    if not readings:
        return StationMetricSummary(
            metric_name=metric_name,
            label=label,
            unit=unit,
            current_value=None,
            average_value=None,
            minimum_value=None,
            maximum_value=None,
            delta_from_start=None,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            utilization_ratio=utilization_ratio,
        )

    values = [getattr(reading, metric_name) for reading in readings]
    return StationMetricSummary(
        metric_name=metric_name,
        label=label,
        unit=unit,
        current_value=round(values[-1], 3),
        average_value=round(fmean(values), 3),
        minimum_value=round(min(values), 3),
        maximum_value=round(max(values), 3),
        delta_from_start=round(values[-1] - values[0], 3),
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        utilization_ratio=utilization_ratio,
    )


def _to_alert_summary(alert: Alert, *, source: str) -> StationAlertSummary:
    return StationAlertSummary(
        source=source,
        alert_id=alert.alert_id,
        severity=alert.severity,
        category=alert.category,
        message=alert.message,
        triggered_at=alert.triggered_at,
        metric_name=alert.metric_name,
        observed_value=alert.observed_value,
        threshold_value=alert.threshold_value,
    )


def _alert_summary_sort_key(alert: StationAlertSummary) -> tuple[int, float, str, str]:
    return (
        -alert.severity.rank,
        -alert.triggered_at.timestamp(),
        alert.source,
        alert.alert_id,
    )
