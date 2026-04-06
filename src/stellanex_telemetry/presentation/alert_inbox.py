from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from stellanex_telemetry.application import FleetHealthSnapshot, StationHealthSnapshot
from stellanex_telemetry.domain import Alert, AlertSeverity


@dataclass(frozen=True, slots=True)
class AlertInboxSummaryViewModel:
    label: str
    value_text: str
    detail_text: str
    tone: str


@dataclass(frozen=True, slots=True)
class AlertInboxItemViewModel:
    alert_id: str
    station_id: str
    station_title: str
    station_subtitle: str
    badge_text: str
    badge_tone: str
    source_text: str
    timestamp_text: str
    metric_text: str
    observed_text: str
    reading_text: str
    context_text: str
    health_score_text: str
    status_text: str


@dataclass(frozen=True, slots=True)
class AlertInboxViewModel:
    summary_text: str
    summary_cards: tuple[AlertInboxSummaryViewModel, ...]
    items: tuple[AlertInboxItemViewModel, ...]
    empty_title: str
    empty_body: str


def build_alert_inbox_view_model(
    snapshot: FleetHealthSnapshot,
    *,
    anomaly_alerts: Sequence[Alert] = (),
    item_limit: int = 6,
) -> AlertInboxViewModel:
    if item_limit <= 0:
        raise ValueError("item_limit must be greater than zero")

    station_lookup = {
        station_snapshot.station.station_id: station_snapshot
        for station_snapshot in snapshot.station_snapshots
    }
    threshold_items = tuple(
        _AlertEnvelope(alert=alert, source="threshold", station_snapshot=station_lookup.get(alert.station_id))
        for alert in snapshot.active_alerts
    )
    anomaly_items = tuple(
        _AlertEnvelope(alert=alert, source="anomaly", station_snapshot=station_lookup.get(alert.station_id))
        for alert in anomaly_alerts
    )

    ordered_items = tuple(
        sorted(
            (*threshold_items, *anomaly_items),
            key=_alert_envelope_sort_key,
        )
    )
    critical_count = sum(1 for item in ordered_items if item.alert.severity is AlertSeverity.CRITICAL)
    warning_count = sum(1 for item in ordered_items if item.alert.severity is AlertSeverity.WARNING)
    threshold_count = len(threshold_items)
    anomaly_count = len(anomaly_items)
    affected_stations = len({item.alert.station_id for item in ordered_items})

    summary_cards = (
        AlertInboxSummaryViewModel(
            label="Active Signals",
            value_text=str(len(ordered_items)),
            detail_text=f"{affected_stations} stations in scope",
            tone="critical" if critical_count else ("warning" if ordered_items else "signal"),
        ),
        AlertInboxSummaryViewModel(
            label="Severity Mix",
            value_text=f"{critical_count} critical",
            detail_text=f"{warning_count} warning",
            tone="critical" if critical_count else ("warning" if warning_count else "signal"),
        ),
        AlertInboxSummaryViewModel(
            label="Source Mix",
            value_text=f"{anomaly_count} anomaly",
            detail_text=f"{threshold_count} threshold",
            tone="accent" if anomaly_count else ("warning" if threshold_count else "signal"),
        ),
    )

    return AlertInboxViewModel(
        summary_text=_summary_text(
            signal_count=len(ordered_items),
            critical_count=critical_count,
            warning_count=warning_count,
            affected_stations=affected_stations,
        ),
        summary_cards=summary_cards,
        items=tuple(
            _build_alert_item_view_model(item)
            for item in ordered_items[:item_limit]
        ),
        empty_title="Alert Inbox Clear",
        empty_body=(
            "No live threshold or anomaly signals are active at the current reference cut. "
            "Operators can use the explorer and trend deck to review priority stations proactively."
        ),
    )


@dataclass(frozen=True, slots=True)
class _AlertEnvelope:
    alert: Alert
    source: str
    station_snapshot: StationHealthSnapshot | None


def _build_alert_item_view_model(item: _AlertEnvelope) -> AlertInboxItemViewModel:
    alert = item.alert
    station_snapshot = item.station_snapshot
    station = station_snapshot.station if station_snapshot is not None else None
    latest_reading = station_snapshot.latest_reading if station_snapshot is not None else None

    station_title = station.display_name if station is not None else alert.station_id
    station_subtitle = (
        f"{station.region} | {station.capacity_mw:.1f} MW capacity"
        if station is not None
        else "Station metadata unavailable"
    )
    metric_text = _metric_text(alert)
    observed_text = _observed_text(alert)
    reading_text = (
        f"{latest_reading.voltage_kv:.1f} kV | {latest_reading.load_percent:.1f}% load | {latest_reading.temperature_c:.1f} C"
        if latest_reading is not None
        else "No current telemetry"
    )

    return AlertInboxItemViewModel(
        alert_id=alert.alert_id,
        station_id=alert.station_id,
        station_title=station_title,
        station_subtitle=station_subtitle,
        badge_text=f"{alert.severity.value.upper()} | {item.source.upper()}",
        badge_tone=_severity_tone(alert.severity),
        source_text=_source_text(alert, item.source),
        timestamp_text=alert.triggered_at.strftime("%d %b %Y %H:%M UTC"),
        metric_text=metric_text,
        observed_text=observed_text,
        reading_text=reading_text,
        context_text=alert.message,
        health_score_text=(
            f"Score {station_snapshot.health_score}/100"
            if station_snapshot is not None
            else "Score unavailable"
        ),
        status_text=(
            station_snapshot.derived_status.value.title()
            if station_snapshot is not None
            else "Unknown"
        ),
    )


def _summary_text(
    *,
    signal_count: int,
    critical_count: int,
    warning_count: int,
    affected_stations: int,
) -> str:
    if signal_count == 0:
        return "The inbox is clear at the current fleet reference time."
    return (
        f"{signal_count} live signals are active across {affected_stations} stations, including "
        f"{critical_count} critical and {warning_count} warning events."
    )


def _metric_text(alert: Alert) -> str:
    metric_name = alert.metric_name or "system"
    return f"{alert.category.value.title()} | {metric_name}"


def _observed_text(alert: Alert) -> str:
    if alert.observed_value is None and alert.threshold_value is None:
        return "Observed delta not available"
    if alert.observed_value is None:
        return f"Threshold {alert.threshold_value:.3f}"
    if alert.threshold_value is None:
        return f"Observed {alert.observed_value:.3f}"
    return f"Observed {alert.observed_value:.3f} | Threshold {alert.threshold_value:.3f}"


def _source_text(alert: Alert, source: str) -> str:
    if source == "threshold":
        return "Threshold policy"
    if alert.category.value == "connectivity":
        return "Connectivity watch"
    return "Trend watch"


def _severity_tone(severity: AlertSeverity) -> str:
    if severity is AlertSeverity.CRITICAL:
        return "critical"
    if severity is AlertSeverity.WARNING:
        return "warning"
    return "accent"


def _alert_envelope_sort_key(item: _AlertEnvelope) -> tuple[int, float, str, str]:
    return (
        -item.alert.severity.rank,
        -item.alert.triggered_at.timestamp(),
        item.alert.station_id.casefold(),
        item.alert.alert_id,
    )
