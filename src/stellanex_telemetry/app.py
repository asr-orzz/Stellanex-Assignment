from __future__ import annotations

from tkinter import TclError

from stellanex_telemetry.application import (
    DatasetRuntime,
    FleetHealthAggregator,
    IngestionIssue,
    OperatorInsightService,
    StationDetailQueryService,
    ThresholdAlertPolicyEngine,
    TelemetryAnomalyDetector,
)
from stellanex_telemetry.config import AppConfig, load_config
from stellanex_telemetry.infrastructure import RuntimeDatasetWorkspace
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
    dataset_workspace = RuntimeDatasetWorkspace(
        demo_data_dir=config.paths.demo_data_dir,
        imports_dir=config.paths.imports_dir,
        runtime_dir=config.paths.runtime_dir,
    )
    dataset_runtime = _load_initial_dataset(config, dataset_workspace.load_dataset("demo"))

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
        dataset_workspace=dataset_workspace,
        active_dataset_key=dataset_runtime.descriptor.dataset_key,
        station_repository=dataset_runtime.station_repository,
        telemetry_repository=dataset_runtime.telemetry_repository,
        alert_engine=alert_engine,
        anomaly_detector=anomaly_detector,
        health_aggregator=health_aggregator,
        insight_service=insight_service,
        station_detail_service=station_detail_service,
    )


def _load_initial_dataset(config: AppConfig, dataset_runtime: DatasetRuntime) -> DatasetRuntime:
    _raise_for_bootstrap_issues(
        config,
        list(dataset_runtime.issues),
        _station_count(dataset_runtime.station_repository),
        _reading_count(dataset_runtime.telemetry_repository),
    )
    return dataset_runtime


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
                station_count=_station_count(context.station_repository),
                reading_count=_reading_count(context.telemetry_repository),
            )
        )
        print(f"\nDesktop shell could not open: {exc}")


def _station_count(repository: object) -> int:
    station_count = getattr(repository, "station_count", None)
    if isinstance(station_count, int):
        return station_count
    if hasattr(repository, "list_stations"):
        return len(repository.list_stations())
    raise TypeError("station repository does not expose a station count")


def _reading_count(repository: object) -> int:
    reading_count = getattr(repository, "reading_count", None)
    if isinstance(reading_count, int):
        return reading_count
    if hasattr(repository, "list_readings"):
        return len(repository.list_readings())
    raise TypeError("telemetry repository does not expose a reading count")
