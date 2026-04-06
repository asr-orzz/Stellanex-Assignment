from __future__ import annotations

from dataclasses import dataclass

from stellanex_telemetry.application.station_detail import (
    StationAlertSummary,
    StationDetailResult,
    StationMetricSummary,
    StationTelemetryPoint,
)
from stellanex_telemetry.domain import AlertSeverity, StationStatus


@dataclass(frozen=True, slots=True)
class KeyValueRowViewModel:
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class StationHeaderViewModel:
    title: str
    subtitle: str
    status_label: str
    status_tone: str
    status_reason: str
    health_score_text: str
    last_updated_text: str


@dataclass(frozen=True, slots=True)
class MetricCardViewModel:
    metric_name: str
    label: str
    current_value_text: str
    average_value_text: str
    range_value_text: str
    delta_value_text: str
    limit_value_text: str
    tone: str


@dataclass(frozen=True, slots=True)
class AlertItemViewModel:
    alert_id: str
    badge_text: str
    tone: str
    headline: str
    detail: str
    timestamp_text: str


@dataclass(frozen=True, slots=True)
class TelemetryPointViewModel:
    timestamp_text: str
    voltage_kv: float
    load_percent: float
    temperature_c: float
    quality_label: str


@dataclass(frozen=True, slots=True)
class StationDetailViewModel:
    header: StationHeaderViewModel
    metadata_rows: tuple[KeyValueRowViewModel, ...]
    metric_cards: tuple[MetricCardViewModel, ...]
    alert_items: tuple[AlertItemViewModel, ...]
    history_points: tuple[TelemetryPointViewModel, ...]


def build_station_detail_view_model(detail: StationDetailResult) -> StationDetailViewModel:
    station = detail.station
    primary_alert = detail.active_alerts[0] if detail.active_alerts else None
    header = StationHeaderViewModel(
        title=station.display_name,
        subtitle=f"{station.region} | {station.capacity_mw:.1f} MW capacity",
        status_label=detail.health_snapshot.derived_status.value.title(),
        status_tone=_status_tone(detail.health_snapshot.derived_status),
        status_reason=primary_alert.message if primary_alert is not None else detail.health_snapshot.status_reason,
        health_score_text=f"{detail.health_snapshot.health_score}/100",
        last_updated_text=(
            detail.latest_reading.recorded_at.strftime("%d %b %Y %H:%M UTC")
            if detail.latest_reading is not None
            else "No telemetry available"
        ),
    )

    metadata_rows = (
        KeyValueRowViewModel(label="Station ID", value=station.station_id),
        KeyValueRowViewModel(label="Nominal Voltage", value=f"{station.nominal_voltage_kv:.1f} kV"),
        KeyValueRowViewModel(
            label="Commissioned",
            value=station.commissioned_on.isoformat() if station.commissioned_on is not None else "Unknown",
        ),
        KeyValueRowViewModel(
            label="Coordinates",
            value=(
                f"{station.location.latitude:.4f}, {station.location.longitude:.4f}"
                if station.location is not None
                else "Not recorded"
            ),
        ),
        KeyValueRowViewModel(
            label="Tags",
            value=", ".join(station.tags) if station.tags else "None",
        ),
        KeyValueRowViewModel(
            label="History Window",
            value=_history_window_text(detail),
        ),
    )

    metric_cards = tuple(_build_metric_card(metric, detail.active_alerts) for metric in detail.metric_summaries)
    alert_items = tuple(_build_alert_item(alert) for alert in detail.active_alerts)
    history_points = tuple(_build_history_point(point) for point in detail.history_points)

    return StationDetailViewModel(
        header=header,
        metadata_rows=metadata_rows,
        metric_cards=metric_cards,
        alert_items=alert_items,
        history_points=history_points,
    )


def _build_metric_card(
    metric: StationMetricSummary,
    active_alerts: tuple[StationAlertSummary, ...],
) -> MetricCardViewModel:
    tone = _metric_tone(metric, active_alerts)
    current_value_text = _format_metric_value(metric.current_value, metric.unit)
    average_value_text = _format_metric_value(metric.average_value, metric.unit)
    range_value_text = _format_range(metric.minimum_value, metric.maximum_value, metric.unit)
    delta_value_text = _format_delta(metric.delta_from_start, metric.unit)
    limit_value_text = _format_limits(metric)
    return MetricCardViewModel(
        metric_name=metric.metric_name,
        label=metric.label,
        current_value_text=current_value_text,
        average_value_text=average_value_text,
        range_value_text=range_value_text,
        delta_value_text=delta_value_text,
        limit_value_text=limit_value_text,
        tone=tone,
    )


def _build_alert_item(alert: StationAlertSummary) -> AlertItemViewModel:
    headline = f"{alert.category.value.title()} | {alert.metric_name or 'system'}"
    detail = alert.message
    if alert.observed_value is not None and alert.threshold_value is not None:
        detail = f"{detail} Observed {alert.observed_value:.3f}; threshold {alert.threshold_value:.3f}."
    return AlertItemViewModel(
        alert_id=alert.alert_id,
        badge_text=f"{alert.severity.value.upper()} | {alert.source.upper()}",
        tone=_severity_tone(alert.severity),
        headline=headline,
        detail=detail,
        timestamp_text=alert.triggered_at.strftime("%d %b %Y %H:%M UTC"),
    )


def _build_history_point(point: StationTelemetryPoint) -> TelemetryPointViewModel:
    return TelemetryPointViewModel(
        timestamp_text=point.recorded_at.strftime("%d %b %H:%M"),
        voltage_kv=point.voltage_kv,
        load_percent=point.load_percent,
        temperature_c=point.temperature_c,
        quality_label=point.quality.value.title(),
    )


def _history_window_text(detail: StationDetailResult) -> str:
    if detail.history_start_at is None or detail.history_end_at is None:
        return "No telemetry history"
    return (
        f"{detail.history_start_at.strftime('%d %b %H:%M UTC')} -> "
        f"{detail.history_end_at.strftime('%d %b %H:%M UTC')} "
        f"({detail.history_point_count} points)"
    )


def _format_metric_value(value: float | None, unit: str) -> str:
    if value is None:
        return "N/A"
    return f"{value:.3f} {unit}"


def _format_range(minimum_value: float | None, maximum_value: float | None, unit: str) -> str:
    if minimum_value is None or maximum_value is None:
        return "N/A"
    return f"{minimum_value:.3f} -> {maximum_value:.3f} {unit}"


def _format_delta(delta: float | None, unit: str) -> str:
    if delta is None:
        return "N/A"
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.3f} {unit}"


def _format_limits(metric: StationMetricSummary) -> str:
    if metric.lower_bound is None and metric.upper_bound is None:
        return "No configured bound"
    if metric.lower_bound is None:
        return f"Upper limit {metric.upper_bound:.3f} {metric.unit}"
    if metric.upper_bound is None:
        return f"Lower limit {metric.lower_bound:.3f} {metric.unit}"
    return f"{metric.lower_bound:.3f} -> {metric.upper_bound:.3f} {metric.unit}"


def _metric_tone(
    metric: StationMetricSummary,
    active_alerts: tuple[StationAlertSummary, ...],
) -> str:
    for alert in active_alerts:
        if alert.metric_name != metric.metric_name:
            continue
        return _severity_tone(alert.severity)

    ratio = metric.utilization_ratio
    if ratio is None:
        return "neutral"
    if ratio >= 1.0:
        return "critical"
    if ratio >= 0.9:
        return "warning"
    return "normal"


def _severity_tone(severity: AlertSeverity) -> str:
    if severity is AlertSeverity.CRITICAL:
        return "critical"
    if severity is AlertSeverity.WARNING:
        return "warning"
    return "info"


def _status_tone(status: StationStatus) -> str:
    tones = {
        StationStatus.HEALTHY: "normal",
        StationStatus.WARNING: "warning",
        StationStatus.CRITICAL: "critical",
        StationStatus.MAINTENANCE: "info",
        StationStatus.OFFLINE: "critical",
        StationStatus.UNKNOWN: "neutral",
    }
    return tones[status]
