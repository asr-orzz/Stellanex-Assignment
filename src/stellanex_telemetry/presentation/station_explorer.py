from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from stellanex_telemetry.application import FleetHealthSnapshot, StationHealthSnapshot
from stellanex_telemetry.domain import Alert, AlertSeverity, StationStatus


@dataclass(frozen=True, slots=True)
class StationExplorerRowViewModel:
    station_id: str
    station_name: str
    title: str
    subtitle: str
    region: str
    status_label: str
    status_tone: str
    health_score: int
    health_score_text: str
    latest_timestamp: datetime | None
    last_updated_text: str
    load_percent: float | None
    load_text: str
    temperature_c: float | None
    temperature_text: str
    voltage_kv: float | None
    voltage_text: str
    signal_count: int
    signal_text: str
    quality_label: str
    tags_text: str
    focus_text: str
    priority_rank: int
    is_priority: bool
    search_blob: str


@dataclass(frozen=True, slots=True)
class StationExplorerViewModel:
    rows: tuple[StationExplorerRowViewModel, ...]
    region_options: tuple[str, ...]
    status_options: tuple[str, ...]
    summary_text: str


def build_station_explorer_view_model(
    snapshot: FleetHealthSnapshot,
    *,
    anomaly_alerts: Sequence[Alert] = (),
) -> StationExplorerViewModel:
    ordered_anomaly_alerts = tuple(sorted(anomaly_alerts, key=_alert_sort_key))
    anomaly_lookup = _group_alerts_by_station(ordered_anomaly_alerts)

    rows: list[StationExplorerRowViewModel] = []
    for priority_rank, station_snapshot in enumerate(snapshot.station_snapshots, start=1):
        rows.append(
            _build_station_explorer_row(
                station_snapshot,
                anomaly_lookup.get(station_snapshot.station.station_id, ()),
                priority_rank=priority_rank,
            )
        )

    ordered_rows = tuple(rows)
    region_options = tuple(sorted({row.region for row in ordered_rows}, key=str.casefold))
    status_options = tuple(
        status_label
        for status_label in _ordered_status_labels()
        if any(row.status_label == status_label for row in ordered_rows)
    )
    priority_count = sum(1 for row in ordered_rows if row.is_priority)
    anomaly_count = len(ordered_anomaly_alerts)

    return StationExplorerViewModel(
        rows=ordered_rows,
        region_options=region_options,
        status_options=status_options,
        summary_text=(
            f"{len(ordered_rows)} stations indexed | "
            f"{priority_count} priority sites | "
            f"{anomaly_count} telemetry watch signals"
        ),
    )


def filter_station_explorer_rows(
    rows: Sequence[StationExplorerRowViewModel],
    *,
    search_text: str | None = None,
    region: str | None = None,
    status_label: str | None = None,
    priority_only: bool = False,
) -> tuple[StationExplorerRowViewModel, ...]:
    filtered_rows = tuple(rows)

    if search_text:
        needle = search_text.strip().casefold()
        if needle:
            filtered_rows = tuple(row for row in filtered_rows if needle in row.search_blob)

    if region and region.strip() and region.casefold() != "all regions":
        normalized_region = region.casefold()
        filtered_rows = tuple(row for row in filtered_rows if row.region.casefold() == normalized_region)

    if status_label and status_label.strip() and status_label.casefold() != "all statuses":
        normalized_status = status_label.casefold()
        filtered_rows = tuple(row for row in filtered_rows if row.status_label.casefold() == normalized_status)

    if priority_only:
        filtered_rows = tuple(row for row in filtered_rows if row.is_priority)

    return filtered_rows


def sort_station_explorer_rows(
    rows: Sequence[StationExplorerRowViewModel],
    *,
    sort_key: str = "priority",
    descending: bool = False,
) -> tuple[StationExplorerRowViewModel, ...]:
    normalized_key = sort_key.strip().lower()

    if normalized_key == "station":
        return tuple(sorted(rows, key=lambda row: (row.station_name.casefold(), row.station_id.casefold()), reverse=descending))
    if normalized_key == "region":
        return tuple(
            sorted(
                rows,
                key=lambda row: (row.region.casefold(), row.station_name.casefold(), row.station_id.casefold()),
                reverse=descending,
            )
        )
    if normalized_key == "status":
        return tuple(sorted(rows, key=lambda row: (_status_rank(row.status_label), row.station_id.casefold()), reverse=descending))
    if normalized_key == "health":
        return tuple(sorted(rows, key=lambda row: (row.health_score, row.station_id.casefold()), reverse=descending))
    if normalized_key == "updated":
        return tuple(sorted(rows, key=lambda row: (_directional_optional_number_key(_timestamp_value(row.latest_timestamp), descending), row.station_id.casefold())))
    if normalized_key == "load":
        return tuple(sorted(rows, key=lambda row: (_directional_optional_number_key(row.load_percent, descending), row.station_id.casefold())))
    if normalized_key == "temperature":
        return tuple(sorted(rows, key=lambda row: (_directional_optional_number_key(row.temperature_c, descending), row.station_id.casefold())))
    if normalized_key == "signals":
        return tuple(sorted(rows, key=lambda row: (row.signal_count, row.station_id.casefold()), reverse=descending))
    return tuple(sorted(rows, key=lambda row: (row.priority_rank, row.station_id.casefold()), reverse=descending))


def _build_station_explorer_row(
    station_snapshot: StationHealthSnapshot,
    anomaly_alerts: Sequence[Alert],
    *,
    priority_rank: int,
) -> StationExplorerRowViewModel:
    station = station_snapshot.station
    latest_reading = station_snapshot.latest_reading
    status_label = station_snapshot.derived_status.value.title()
    status_tone = _status_tone(station_snapshot.derived_status)
    threshold_signal_count = station_snapshot.alert_count
    anomaly_signal_count = len(anomaly_alerts)
    signal_count = threshold_signal_count + anomaly_signal_count

    if anomaly_alerts:
        primary_signal = anomaly_alerts[0]
        focus_text = primary_signal.message
    elif station_snapshot.primary_alert is not None:
        primary_signal = station_snapshot.primary_alert
        focus_text = primary_signal.message
    else:
        focus_text = station_snapshot.status_reason

    search_blob = " ".join(
        fragment.casefold()
        for fragment in (
            station.station_id,
            station.name,
            station.region,
            station_snapshot.derived_status.value,
            " ".join(station.tags),
            focus_text,
        )
        if fragment
    )

    return StationExplorerRowViewModel(
        station_id=station.station_id,
        station_name=station.name,
        title=station.display_name,
        subtitle=f"{station.region} | {station.capacity_mw:.1f} MW capacity",
        region=station.region,
        status_label=status_label,
        status_tone=status_tone,
        health_score=station_snapshot.health_score,
        health_score_text=f"{station_snapshot.health_score}/100",
        latest_timestamp=latest_reading.recorded_at if latest_reading is not None else None,
        last_updated_text=(
            latest_reading.recorded_at.strftime("%d %b %H:%M UTC")
            if latest_reading is not None
            else "No telemetry"
        ),
        load_percent=latest_reading.load_percent if latest_reading is not None else None,
        load_text=f"{latest_reading.load_percent:.1f}%" if latest_reading is not None else "N/A",
        temperature_c=latest_reading.temperature_c if latest_reading is not None else None,
        temperature_text=f"{latest_reading.temperature_c:.1f} C" if latest_reading is not None else "N/A",
        voltage_kv=latest_reading.voltage_kv if latest_reading is not None else None,
        voltage_text=f"{latest_reading.voltage_kv:.1f} kV" if latest_reading is not None else "N/A",
        signal_count=signal_count,
        signal_text=_signal_text(station_snapshot, anomaly_alerts),
        quality_label=latest_reading.quality.value.title() if latest_reading is not None else "No data",
        tags_text=", ".join(station.tags) if station.tags else "No tags",
        focus_text=focus_text,
        priority_rank=priority_rank,
        is_priority=_is_priority_station(station_snapshot, signal_count),
        search_blob=search_blob,
    )


def _signal_text(
    station_snapshot: StationHealthSnapshot,
    anomaly_alerts: Sequence[Alert],
) -> str:
    threshold_signal_count = station_snapshot.alert_count
    anomaly_signal_count = len(anomaly_alerts)
    if anomaly_signal_count and threshold_signal_count:
        return f"{anomaly_signal_count + threshold_signal_count} live signals"
    if anomaly_signal_count:
        suffix = "anomaly" if anomaly_signal_count == 1 else "anomalies"
        return f"{anomaly_signal_count} {suffix}"
    if threshold_signal_count:
        suffix = "alert" if threshold_signal_count == 1 else "alerts"
        return f"{threshold_signal_count} {suffix}"
    if station_snapshot.derived_status is StationStatus.CRITICAL:
        return "Critical state"
    if station_snapshot.derived_status is StationStatus.WARNING:
        return "Review status"
    if station_snapshot.derived_status is StationStatus.MAINTENANCE:
        return "Maintenance"
    if station_snapshot.derived_status is StationStatus.OFFLINE:
        return "Offline"
    return "Clear"


def _is_priority_station(station_snapshot: StationHealthSnapshot, signal_count: int) -> bool:
    if signal_count > 0:
        return True
    return station_snapshot.derived_status in {
        StationStatus.CRITICAL,
        StationStatus.WARNING,
        StationStatus.OFFLINE,
    }


def _group_alerts_by_station(alerts: Sequence[Alert]) -> dict[str, tuple[Alert, ...]]:
    grouped: dict[str, list[Alert]] = defaultdict(list)
    for alert in alerts:
        grouped[alert.station_id].append(alert)
    return {
        station_id: tuple(sorted(station_alerts, key=_alert_sort_key))
        for station_id, station_alerts in grouped.items()
    }


def _status_tone(status: StationStatus) -> str:
    tones = {
        StationStatus.HEALTHY: "signal",
        StationStatus.WARNING: "warning",
        StationStatus.CRITICAL: "critical",
        StationStatus.MAINTENANCE: "accent",
        StationStatus.OFFLINE: "critical",
        StationStatus.UNKNOWN: "neutral",
    }
    return tones[status]


def _ordered_status_labels() -> tuple[str, ...]:
    return tuple(
        status.value.title()
        for status in (
            StationStatus.CRITICAL,
            StationStatus.WARNING,
            StationStatus.MAINTENANCE,
            StationStatus.OFFLINE,
            StationStatus.HEALTHY,
            StationStatus.UNKNOWN,
        )
    )


def _status_rank(status_label: str) -> int:
    return {
        "Critical": 0,
        "Warning": 1,
        "Maintenance": 2,
        "Offline": 3,
        "Healthy": 4,
        "Unknown": 5,
    }[status_label]


def _directional_optional_number_key(value: float | None, descending: bool) -> tuple[int, float]:
    if value is None:
        return (1, 0.0)
    return (0, -value if descending else value)


def _timestamp_value(value: datetime | None) -> float | None:
    if value is None:
        return None
    return value.timestamp()


def _alert_sort_key(alert: Alert) -> tuple[int, float, str]:
    return (
        -_severity_rank(alert.severity),
        -alert.triggered_at.timestamp(),
        alert.alert_id,
    )


def _severity_rank(severity: AlertSeverity) -> int:
    return {
        AlertSeverity.CRITICAL: 3,
        AlertSeverity.WARNING: 2,
        AlertSeverity.INFO: 1,
    }[severity]
