from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from stellanex_telemetry.app import main as launch_desktop_app
from stellanex_telemetry.application import (
    DatasetDescriptor,
    DatasetRuntime,
    FleetHealthAggregator,
    FleetOperationalReport,
    FleetReportingService,
    IngestionIssue,
    OperatorInsightService,
    StationDetailQueryService,
    ThresholdAlertPolicyEngine,
    TelemetryAnomalyDetector,
)
from stellanex_telemetry.config import AppConfig, load_config
from stellanex_telemetry.infrastructure import (
    CsvTelemetryBatchParser,
    IndexedStationRepository,
    IndexedTelemetryRepository,
    RuntimeDatasetWorkspace,
)


@dataclass(frozen=True, slots=True)
class DatasetValidationReport:
    label: str
    source_path: str
    station_count: int
    reading_count: int
    warning_count: int
    error_count: int
    issues: tuple[IngestionIssue, ...]

    @property
    def is_valid(self) -> bool:
        return self.error_count == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "source_path": self.source_path,
            "station_count": self.station_count,
            "reading_count": self.reading_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "is_valid": self.is_valid,
            "issues": [
                {
                    "severity": issue.severity,
                    "message": issue.message,
                    "row_number": issue.row_number,
                    "field_name": issue.field_name,
                }
                for issue in self.issues
            ],
        }


@dataclass(frozen=True, slots=True)
class CliServiceBundle:
    reporting_service: FleetReportingService


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = args.command or "desktop"

    try:
        if command == "desktop":
            launch_desktop_app()
            return 0

        config = load_config()
        config.paths.ensure_runtime_directories()

        if command == "validate":
            return _run_validate(args, config)
        if command == "report":
            return _run_report(args, config)
    except (LookupError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    parser.error(f"Unsupported command '{command}'.")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stellanex-console",
        description="Desktop and headless tooling for the Stellanex telemetry assessment.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("desktop", help="Launch the desktop operator console.")

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a dataset source path or a catalog dataset without opening the desktop shell.",
    )
    _add_dataset_selection_arguments(validate_parser)
    validate_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Validation output format.",
    )
    validate_parser.add_argument(
        "--output",
        type=Path,
        help="Optional file path to write the validation result.",
    )

    report_parser = subparsers.add_parser(
        "report",
        help="Generate a headless fleet report for a dataset source or catalog entry.",
    )
    _add_dataset_selection_arguments(report_parser)
    report_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Report output format.",
    )
    report_parser.add_argument(
        "--output",
        type=Path,
        help="Optional file path to write the generated report.",
    )
    report_parser.add_argument(
        "--top-stations",
        type=int,
        default=5,
        help="Number of priority stations to include in the report.",
    )
    report_parser.add_argument(
        "--signal-limit",
        type=int,
        default=5,
        help="Number of threshold and anomaly signal previews to include.",
    )

    return parser


def _add_dataset_selection_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dataset",
        default="demo",
        help="Dataset key from the runtime catalog. Defaults to 'demo'.",
    )
    group.add_argument(
        "--source",
        type=Path,
        help="Filesystem path to a dataset directory, manifest, or CSV export to analyze directly.",
    )


def _run_validate(args: argparse.Namespace, config: AppConfig) -> int:
    report = _build_validation_report(args, config)
    content = (
        json.dumps(report.to_dict(), indent=2)
        if args.format == "json"
        else _render_validation_text(report)
    )
    _emit_output(content, args.output)
    return 0 if report.is_valid else 1


def _run_report(args: argparse.Namespace, config: AppConfig) -> int:
    dataset_runtime = _resolve_dataset_runtime(args, config)
    services = _build_cli_services()
    report = services.reporting_service.build_report(
        dataset_runtime,
        priority_station_limit=args.top_stations,
        signal_preview_limit=args.signal_limit,
    )
    content = (
        json.dumps(report.to_dict(), indent=2)
        if args.format == "json"
        else _render_report_text(report)
    )
    _emit_output(content, args.output)
    return 0


def _build_validation_report(args: argparse.Namespace, config: AppConfig) -> DatasetValidationReport:
    parser = CsvTelemetryBatchParser()
    if args.source is not None:
        label = args.source.name
        source_path = args.source.resolve()
        batch = parser.parse(source_path)
    else:
        descriptor = _resolve_catalog_descriptor(config, args.dataset)
        label = descriptor.label
        source_path = descriptor.source_path
        batch = parser.parse(source_path)

    issues = list(batch.issues)
    if not batch.stations:
        issues.append(
            IngestionIssue(
                message="Dataset validation requires a station catalog.",
                severity="error",
            )
        )
    if not batch.readings:
        issues.append(
            IngestionIssue(
                message="Dataset validation requires at least one telemetry reading.",
                severity="error",
            )
        )

    return DatasetValidationReport(
        label=label,
        source_path=str(source_path),
        station_count=len(batch.stations),
        reading_count=len(batch.readings),
        warning_count=sum(1 for issue in issues if issue.severity == "warning"),
        error_count=sum(1 for issue in issues if issue.severity == "error"),
        issues=tuple(issues),
    )


def _resolve_dataset_runtime(args: argparse.Namespace, config: AppConfig) -> DatasetRuntime:
    if args.source is not None:
        return _load_runtime_from_source(args.source)

    workspace = _build_dataset_workspace(config)
    return workspace.load_dataset(args.dataset)


def _resolve_catalog_descriptor(config: AppConfig, dataset_key: str) -> DatasetDescriptor:
    workspace = _build_dataset_workspace(config)
    for descriptor in workspace.list_datasets():
        if descriptor.dataset_key == dataset_key:
            return descriptor
    raise LookupError(f"Dataset '{dataset_key}' is not present in the runtime catalog.")


def _load_runtime_from_source(source_path: Path) -> DatasetRuntime:
    parser = CsvTelemetryBatchParser()
    resolved_path = source_path.resolve()
    batch = parser.parse(resolved_path)
    issues = list(batch.issues)
    if not batch.stations:
        issues.append(
            IngestionIssue(
                message="Fleet reports require a station catalog.",
                severity="error",
            )
        )
    if not batch.readings:
        issues.append(
            IngestionIssue(
                message="Fleet reports require telemetry readings.",
                severity="error",
            )
        )
    error_messages = [issue.message for issue in issues if issue.severity == "error"]
    if error_messages:
        formatted = "\n".join(f"- {message}" for message in error_messages)
        raise RuntimeError(f"Unable to build a report from '{resolved_path.name}':\n{formatted}")

    label = resolved_path.stem.replace("-", " ").replace("_", " ").title() if resolved_path.is_file() else resolved_path.name.replace("-", " ").replace("_", " ").title()
    descriptor = DatasetDescriptor(
        dataset_key=f"source:{resolved_path.stem.casefold()}",
        label=label or "Direct Source Dataset",
        source_path=resolved_path,
        origin="source",
        description="Loaded directly from a CLI source path",
        station_count=len(batch.stations),
        reading_count=len(batch.readings),
        updated_at=batch.imported_at,
    )
    return DatasetRuntime(
        descriptor=descriptor,
        station_repository=IndexedStationRepository.from_batch(batch),
        telemetry_repository=IndexedTelemetryRepository.from_batch(batch),
        issues=tuple(issues),
    )


def _build_dataset_workspace(config: AppConfig) -> RuntimeDatasetWorkspace:
    return RuntimeDatasetWorkspace(
        demo_data_dir=config.paths.demo_data_dir,
        imports_dir=config.paths.imports_dir,
        runtime_dir=config.paths.runtime_dir,
    )


def _build_cli_services() -> CliServiceBundle:
    alert_engine = ThresholdAlertPolicyEngine()
    anomaly_detector = TelemetryAnomalyDetector()
    health_aggregator = FleetHealthAggregator(alert_engine=alert_engine)
    insight_service = OperatorInsightService()
    station_detail_service = StationDetailQueryService(
        alert_engine=alert_engine,
        anomaly_detector=anomaly_detector,
        health_aggregator=health_aggregator,
    )
    reporting_service = FleetReportingService(
        health_aggregator=health_aggregator,
        anomaly_detector=anomaly_detector,
        station_detail_service=station_detail_service,
        insight_service=insight_service,
    )
    return CliServiceBundle(reporting_service=reporting_service)


def _emit_output(content: str, output_path: Path | None) -> None:
    if output_path is None:
        print(content)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content + "\n", encoding="utf-8")
    print(f"Wrote output to {output_path}")


def _render_validation_text(report: DatasetValidationReport) -> str:
    lines = [
        "Dataset Validation",
        f"Label: {report.label}",
        f"Source: {report.source_path}",
        f"Stations: {report.station_count}",
        f"Readings: {report.reading_count}",
        f"Warnings: {report.warning_count}",
        f"Errors: {report.error_count}",
        f"Status: {'VALID' if report.is_valid else 'INVALID'}",
    ]
    if report.issues:
        lines.append("")
        lines.append("Issues")
        for issue in report.issues[:10]:
            location = _issue_location_text(issue)
            lines.append(f"- {issue.severity.upper()}{location}: {issue.message}")
        if len(report.issues) > 10:
            lines.append(f"- ... {len(report.issues) - 10} more issue(s)")
    return "\n".join(lines)


def _render_report_text(report: FleetOperationalReport) -> str:
    lines = [
        "Fleet Report",
        f"Dataset: {report.dataset_label} ({report.dataset_key})",
        f"Origin: {report.dataset_origin}",
        f"Source: {report.source_path}",
        f"Generated At: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"Reference Time: {report.reference_time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "",
        "Fleet Summary",
        f"Stations: {report.station_count}",
        f"Readings: {report.reading_count}",
        f"Fleet Score: {report.fleet_health_score:.2f}",
        (
            "Status Mix: "
            f"healthy {report.healthy_stations} | warning {report.warning_stations} | "
            f"critical {report.critical_stations} | maintenance {report.maintenance_stations} | "
            f"offline {report.offline_stations}"
        ),
        f"Signals: threshold {report.threshold_alert_count} | anomaly {report.anomaly_alert_count}",
        f"Ingestion Issues: warnings {report.issue_warning_count} | errors {report.issue_error_count}",
        "",
        "Regions",
    ]
    for region in report.region_summaries:
        lines.append(
            f"- {region.region}: score {region.average_health_score:.2f} | stations {region.station_count} | "
            f"warning {region.warning_stations} | critical {region.critical_stations} | alerts {region.active_alert_count}"
        )

    lines.append("")
    lines.append("Priority Stations")
    for index, station in enumerate(report.priority_stations, start=1):
        reading_text = (
            station.latest_reading_at.strftime("%Y-%m-%d %H:%M:%S %Z")
            if station.latest_reading_at is not None
            else "no telemetry"
        )
        lines.append(
            f"{index}. {station.station_name} ({station.station_id}) | {station.region} | "
            f"{station.derived_status.value.upper()} | score {station.health_score} | "
            f"signals {station.active_signal_count} | latest {reading_text}"
        )
        lines.append(f"   Summary: {station.operator_summary}")
        lines.append(f"   Reason: {station.status_reason}")
        if station.next_action is not None:
            lines.append(f"   Next Action: {station.next_action}")

    if report.threshold_signal_previews:
        lines.append("")
        lines.append("Threshold Signals")
        for signal in report.threshold_signal_previews:
            lines.append(
                f"- {signal.severity.value.upper()} | {signal.station_name} ({signal.station_id}) | "
                f"{signal.category.value}: {signal.message}"
            )

    if report.anomaly_signal_previews:
        lines.append("")
        lines.append("Anomaly Signals")
        for signal in report.anomaly_signal_previews:
            lines.append(
                f"- {signal.severity.value.upper()} | {signal.station_name} ({signal.station_id}) | "
                f"{signal.category.value}: {signal.message}"
            )

    return "\n".join(lines)


def _issue_location_text(issue: IngestionIssue) -> str:
    fragments: list[str] = []
    if issue.row_number is not None:
        fragments.append(f"row {issue.row_number}")
    if issue.field_name is not None:
        fragments.append(f"field {issue.field_name}")
    return f" ({', '.join(fragments)})" if fragments else ""


if __name__ == "__main__":
    raise SystemExit(main())
