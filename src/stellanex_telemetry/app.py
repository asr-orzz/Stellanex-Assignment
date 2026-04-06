from __future__ import annotations

from tkinter import TclError

from stellanex_telemetry.application import (
    FleetHealthAggregator,
    IngestionIssue,
    OperatorInsightService,
    StationDetailQueryService,
    ThresholdAlertPolicyEngine,
    TelemetryAnomalyDetector,
)
from stellanex_telemetry.config import AppConfig, load_config
from stellanex_telemetry.infrastructure import IndexedStationRepository, IndexedTelemetryRepository
from stellanex_telemetry.presentation import DesktopShellContext, launch_desktop_shell


def build_bootstrap_message(config: AppConfig, *, station_count: int, reading_count: int) -> str:
    """Return a simple fallback status message when the shell cannot open."""
    return (
        f"{config.app_name}\n"
        "Desktop shell bootstrap complete.\n"
        f"Stations loaded: {station_count}\n"
        f"Telemetry readings loaded: {reading_count}\n"
        f"Demo datasets: {config.paths.demo_data_dir}\n"
        f"Import drop zone: {config.paths.imports_dir}\n"
        f"Runtime workspace: {config.paths.runtime_dir}\n"
        "Shell launch requires a local desktop session."
    )


def build_desktop_context(config: AppConfig) -> DesktopShellContext:
    issues: list[IngestionIssue] = []
    station_repository = IndexedStationRepository.from_csv(
        config.paths.demo_data_dir / "stations.csv",
        issues=issues,
    )
    telemetry_repository = IndexedTelemetryRepository.from_csv(
        config.paths.demo_data_dir / "telemetry_readings.csv",
        issues=issues,
    )
    _raise_for_bootstrap_issues(config, issues, station_repository.station_count, telemetry_repository.reading_count)

    alert_engine = ThresholdAlertPolicyEngine()
    anomaly_detector = TelemetryAnomalyDetector()
    health_aggregator = FleetHealthAggregator(alert_engine=alert_engine)
    insight_service = OperatorInsightService()
    station_detail_service = StationDetailQueryService(
        alert_engine=alert_engine,
        anomaly_detector=anomaly_detector,
        health_aggregator=health_aggregator,
    )
    return DesktopShellContext(
        config=config,
        station_repository=station_repository,
        telemetry_repository=telemetry_repository,
        alert_engine=alert_engine,
        anomaly_detector=anomaly_detector,
        health_aggregator=health_aggregator,
        insight_service=insight_service,
        station_detail_service=station_detail_service,
    )


def _raise_for_bootstrap_issues(
    config: AppConfig,
    issues: list[IngestionIssue],
    station_count: int,
    reading_count: int,
) -> None:
    error_messages = [issue.message for issue in issues if issue.severity == "error"]
    if station_count == 0:
        error_messages.append("No stations were loaded from the demo dataset.")
    if reading_count == 0:
        error_messages.append("No telemetry readings were loaded from the demo dataset.")
    if error_messages:
        formatted = "\n".join(f"- {message}" for message in error_messages)
        raise RuntimeError(
            f"Unable to bootstrap demo data from '{config.paths.demo_data_dir}':\n{formatted}"
        )


def main() -> None:
    config = load_config()
    config.paths.ensure_runtime_directories()
    context = build_desktop_context(config)
    try:
        launch_desktop_shell(context)
    except TclError as exc:
        print(
            build_bootstrap_message(
                config,
                station_count=context.station_repository.station_count,
                reading_count=context.telemetry_repository.reading_count,
            )
        )
        print(f"\nDesktop shell could not open: {exc}")
