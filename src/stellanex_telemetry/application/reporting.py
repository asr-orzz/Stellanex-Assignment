from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from stellanex_telemetry.application.anomaly_detection import TelemetryAnomalyDetector
from stellanex_telemetry.application.contracts import TelemetryQuery
from stellanex_telemetry.application.dataset_management import DatasetRuntime
from stellanex_telemetry.application.fleet_health import FleetHealthAggregator, RegionHealthSnapshot
from stellanex_telemetry.application.operator_insights import OperatorInsightService
from stellanex_telemetry.application.station_detail import StationDetailQuery, StationDetailQueryService
from stellanex_telemetry.domain import Alert, AlertCategory, AlertSeverity, StationStatus


@dataclass(frozen=True, slots=True)
class FleetReportSignal:
    source: str
    station_id: str
    station_name: str
    severity: AlertSeverity
    category: AlertCategory
    message: str
    triggered_at: datetime
    metric_name: str | None = None
    observed_value: float | None = None
    threshold_value: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "station_id": self.station_id,
            "station_name": self.station_name,
            "severity": self.severity.value,
            "category": self.category.value,
            "message": self.message,
            "triggered_at": self.triggered_at.isoformat(),
            "metric_name": self.metric_name,
            "observed_value": self.observed_value,
            "threshold_value": self.threshold_value,
        }


@dataclass(frozen=True, slots=True)
class FleetReportPriorityStation:
    station_id: str
    station_name: str
    region: str
    derived_status: StationStatus
    health_score: int
    active_signal_count: int
    status_reason: str
    latest_reading_at: datetime | None
    voltage_kv: float | None
    load_percent: float | None
    temperature_c: float | None
    operator_summary: str
    next_action: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "station_id": self.station_id,
            "station_name": self.station_name,
            "region": self.region,
            "derived_status": self.derived_status.value,
            "health_score": self.health_score,
            "active_signal_count": self.active_signal_count,
            "status_reason": self.status_reason,
            "latest_reading_at": self.latest_reading_at.isoformat() if self.latest_reading_at is not None else None,
            "voltage_kv": self.voltage_kv,
            "load_percent": self.load_percent,
            "temperature_c": self.temperature_c,
            "operator_summary": self.operator_summary,
            "next_action": self.next_action,
        }


@dataclass(frozen=True, slots=True)
class FleetReportRegion:
    region: str
    station_count: int
    average_health_score: float
    warning_stations: int
    critical_stations: int
    maintenance_stations: int
    offline_stations: int
    active_alert_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "region": self.region,
            "station_count": self.station_count,
            "average_health_score": self.average_health_score,
            "warning_stations": self.warning_stations,
            "critical_stations": self.critical_stations,
            "maintenance_stations": self.maintenance_stations,
            "offline_stations": self.offline_stations,
            "active_alert_count": self.active_alert_count,
        }


@dataclass(frozen=True, slots=True)
class FleetOperationalReport:
    dataset_key: str
    dataset_label: str
    dataset_origin: str
    dataset_description: str
    source_path: str
    generated_at: datetime
    reference_time: datetime
    station_count: int
    reading_count: int
    fleet_health_score: float
    healthy_stations: int
    warning_stations: int
    critical_stations: int
    maintenance_stations: int
    offline_stations: int
    threshold_alert_count: int
    anomaly_alert_count: int
    issue_warning_count: int
    issue_error_count: int
    region_summaries: tuple[FleetReportRegion, ...]
    priority_stations: tuple[FleetReportPriorityStation, ...]
    threshold_signal_previews: tuple[FleetReportSignal, ...]
    anomaly_signal_previews: tuple[FleetReportSignal, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "dataset": {
                "key": self.dataset_key,
                "label": self.dataset_label,
                "origin": self.dataset_origin,
                "description": self.dataset_description,
                "source_path": self.source_path,
            },
            "generated_at": self.generated_at.isoformat(),
            "reference_time": self.reference_time.isoformat(),
            "fleet": {
                "station_count": self.station_count,
                "reading_count": self.reading_count,
                "fleet_health_score": self.fleet_health_score,
                "healthy_stations": self.healthy_stations,
                "warning_stations": self.warning_stations,
                "critical_stations": self.critical_stations,
                "maintenance_stations": self.maintenance_stations,
                "offline_stations": self.offline_stations,
                "threshold_alert_count": self.threshold_alert_count,
                "anomaly_alert_count": self.anomaly_alert_count,
            },
            "ingestion": {
                "warning_count": self.issue_warning_count,
                "error_count": self.issue_error_count,
            },
            "regions": [item.to_dict() for item in self.region_summaries],
            "priority_stations": [item.to_dict() for item in self.priority_stations],
            "threshold_signal_previews": [item.to_dict() for item in self.threshold_signal_previews],
            "anomaly_signal_previews": [item.to_dict() for item in self.anomaly_signal_previews],
        }


class FleetReportingService:
    """Build reusable headless fleet reports from a loaded dataset runtime."""

    def __init__(
        self,
        *,
        health_aggregator: FleetHealthAggregator | None = None,
        anomaly_detector: TelemetryAnomalyDetector | None = None,
        station_detail_service: StationDetailQueryService | None = None,
        insight_service: OperatorInsightService | None = None,
    ) -> None:
        self._health_aggregator = health_aggregator or FleetHealthAggregator()
        self._anomaly_detector = anomaly_detector or TelemetryAnomalyDetector()
        self._station_detail_service = station_detail_service or StationDetailQueryService(
            health_aggregator=self._health_aggregator,
        )
        self._insight_service = insight_service or OperatorInsightService()

    def build_report(
        self,
        dataset_runtime: DatasetRuntime,
        *,
        priority_station_limit: int = 5,
        signal_preview_limit: int = 5,
    ) -> FleetOperationalReport:
        if priority_station_limit <= 0:
            raise ValueError("priority_station_limit must be greater than zero")
        if signal_preview_limit <= 0:
            raise ValueError("signal_preview_limit must be greater than zero")

        station_repository = dataset_runtime.station_repository
        telemetry_repository = dataset_runtime.telemetry_repository
        reference_time = _resolve_reference_time(telemetry_repository)
        snapshot = self._health_aggregator.build_snapshot(
            station_repository,
            telemetry_repository,
            generated_at=reference_time,
        )
        anomaly_alerts = self._anomaly_detector.evaluate_latest(
            station_repository,
            telemetry_repository,
            generated_at=reference_time,
        )

        priority_stations = tuple(
            self._build_priority_station(dataset_runtime, snapshot_item.station.station_id)
            for snapshot_item in snapshot.station_snapshots[:priority_station_limit]
        )
        regions = tuple(_to_region_summary(item) for item in snapshot.region_snapshots)
        threshold_previews = tuple(
            _to_signal_preview(alert, source="threshold", dataset_runtime=dataset_runtime)
            for alert in snapshot.active_alerts[:signal_preview_limit]
        )
        anomaly_previews = tuple(
            _to_signal_preview(alert, source="anomaly", dataset_runtime=dataset_runtime)
            for alert in anomaly_alerts[:signal_preview_limit]
        )
        issues = tuple(dataset_runtime.issues)

        return FleetOperationalReport(
            dataset_key=dataset_runtime.descriptor.dataset_key,
            dataset_label=dataset_runtime.descriptor.label,
            dataset_origin=dataset_runtime.descriptor.origin,
            dataset_description=dataset_runtime.descriptor.description,
            source_path=str(dataset_runtime.descriptor.source_path),
            generated_at=datetime.now(timezone.utc),
            reference_time=reference_time,
            station_count=_station_count(station_repository),
            reading_count=_reading_count(telemetry_repository),
            fleet_health_score=snapshot.fleet_health_score,
            healthy_stations=snapshot.healthy_stations,
            warning_stations=snapshot.warning_stations,
            critical_stations=snapshot.critical_stations,
            maintenance_stations=snapshot.maintenance_stations,
            offline_stations=snapshot.offline_stations,
            threshold_alert_count=snapshot.active_alert_count,
            anomaly_alert_count=len(anomaly_alerts),
            issue_warning_count=sum(1 for issue in issues if issue.severity == "warning"),
            issue_error_count=sum(1 for issue in issues if issue.severity == "error"),
            region_summaries=regions,
            priority_stations=priority_stations,
            threshold_signal_previews=threshold_previews,
            anomaly_signal_previews=anomaly_previews,
        )

    def _build_priority_station(
        self,
        dataset_runtime: DatasetRuntime,
        station_id: str,
    ) -> FleetReportPriorityStation:
        detail = self._station_detail_service.get_station_detail(
            dataset_runtime.station_repository,
            dataset_runtime.telemetry_repository,
            StationDetailQuery(station_id=station_id),
        )
        insight = self._insight_service.build_report(detail)
        latest_reading = detail.latest_reading
        next_action = insight.recommendations[0].title if insight.recommendations else None
        return FleetReportPriorityStation(
            station_id=detail.station.station_id,
            station_name=detail.station.name,
            region=detail.station.region,
            derived_status=detail.health_snapshot.derived_status,
            health_score=detail.health_snapshot.health_score,
            active_signal_count=len(detail.active_alerts),
            status_reason=detail.health_snapshot.status_reason,
            latest_reading_at=latest_reading.recorded_at if latest_reading is not None else None,
            voltage_kv=latest_reading.voltage_kv if latest_reading is not None else None,
            load_percent=latest_reading.load_percent if latest_reading is not None else None,
            temperature_c=latest_reading.temperature_c if latest_reading is not None else None,
            operator_summary=insight.summary_body,
            next_action=next_action,
        )


def _resolve_reference_time(telemetry_repository: object) -> datetime:
    latest = telemetry_repository.list_readings(TelemetryQuery(newest_first=True, limit=1))
    if latest:
        return latest[0].recorded_at
    return datetime.now(timezone.utc)


def _to_region_summary(snapshot: RegionHealthSnapshot) -> FleetReportRegion:
    return FleetReportRegion(
        region=snapshot.region,
        station_count=snapshot.station_count,
        average_health_score=snapshot.average_health_score,
        warning_stations=snapshot.warning_stations,
        critical_stations=snapshot.critical_stations,
        maintenance_stations=snapshot.maintenance_stations,
        offline_stations=snapshot.offline_stations,
        active_alert_count=snapshot.active_alert_count,
    )


def _to_signal_preview(
    alert: Alert,
    *,
    source: str,
    dataset_runtime: DatasetRuntime,
) -> FleetReportSignal:
    station = dataset_runtime.station_repository.get_station(alert.station_id)
    station_name = station.name if station is not None else alert.station_id
    return FleetReportSignal(
        source=source,
        station_id=alert.station_id,
        station_name=station_name,
        severity=alert.severity,
        category=alert.category,
        message=alert.message,
        triggered_at=alert.triggered_at,
        metric_name=alert.metric_name,
        observed_value=alert.observed_value,
        threshold_value=alert.threshold_value,
    )


def _station_count(station_repository: object) -> int:
    count = getattr(station_repository, "station_count", None)
    if isinstance(count, int):
        return count
    return len(station_repository.list_stations())


def _reading_count(telemetry_repository: object) -> int:
    count = getattr(telemetry_repository, "reading_count", None)
    if isinstance(count, int):
        return count
    return len(telemetry_repository.list_readings())
