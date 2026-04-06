from __future__ import annotations

import pytest

from stellanex_telemetry.application import (
    FleetHealthAggregator,
    FleetReportingService,
    OperatorInsightService,
    StationDetailQueryService,
    ThresholdAlertPolicyEngine,
    TelemetryAnomalyDetector,
)


def test_fleet_reporting_service_builds_deterministic_demo_report(demo_runtime) -> None:
    alert_engine = ThresholdAlertPolicyEngine()
    anomaly_detector = TelemetryAnomalyDetector()
    health_aggregator = FleetHealthAggregator(alert_engine=alert_engine)
    station_detail_service = StationDetailQueryService(
        alert_engine=alert_engine,
        anomaly_detector=anomaly_detector,
        health_aggregator=health_aggregator,
    )
    reporting_service = FleetReportingService(
        health_aggregator=health_aggregator,
        anomaly_detector=anomaly_detector,
        station_detail_service=station_detail_service,
        insight_service=OperatorInsightService(),
    )

    report = reporting_service.build_report(
        demo_runtime,
        priority_station_limit=3,
        signal_preview_limit=3,
    )

    assert report.dataset_key == "demo"
    assert report.station_count == 24
    assert report.reading_count == 4600
    assert report.fleet_health_score == pytest.approx(97.5)
    assert report.threshold_alert_count == 0
    assert report.anomaly_alert_count == 2
    assert len(report.region_summaries) == 4
    assert tuple(item.station_id for item in report.priority_stations) == (
        "NG-003",
        "SG-005",
        "NG-006",
    )
    assert tuple(item.station_id for item in report.anomaly_signal_previews) == (
        "NG-006",
        "SG-005",
    )
    assert report.priority_stations[0].next_action == "Reconcile station status"
    assert "critical metadata state" in report.priority_stations[0].operator_summary
