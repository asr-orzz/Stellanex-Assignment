from __future__ import annotations

from dataclasses import dataclass

from stellanex_telemetry.application.station_detail import (
    StationAlertSummary,
    StationDetailResult,
    StationMetricSummary,
)
from stellanex_telemetry.domain import AlertSeverity, StationStatus


@dataclass(frozen=True, slots=True)
class HistoryChartPointViewModel:
    timestamp_text: str
    value: float
    quality_label: str


@dataclass(frozen=True, slots=True)
class MetricHistoryChartViewModel:
    metric_name: str
    label: str
    unit: str
    tone: str
    current_value_text: str
    average_value_text: str
    range_value_text: str
    delta_value_text: str
    limit_text: str
    window_text: str
    axis_min: float
    axis_max: float
    lower_bound: float | None
    upper_bound: float | None
    points: tuple[HistoryChartPointViewModel, ...]


@dataclass(frozen=True, slots=True)
class StationHistoryDashboardViewModel:
    station_id: str
    title: str
    subtitle: str
    status_label: str
    status_tone: str
    status_reason: str
    health_score_text: str
    last_updated_text: str
    history_window_text: str
    active_signal_text: str
    charts: tuple[MetricHistoryChartViewModel, ...]


def build_station_history_dashboard_view_model(detail: StationDetailResult) -> StationHistoryDashboardViewModel:
    station = detail.station
    primary_alert = detail.active_alerts[0] if detail.active_alerts else None

    return StationHistoryDashboardViewModel(
        station_id=station.station_id,
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
        history_window_text=_history_window_text(detail),
        active_signal_text=_active_signal_text(detail),
        charts=tuple(
            _build_metric_history_chart_view_model(metric, detail)
            for metric in detail.metric_summaries
        ),
    )


def _build_metric_history_chart_view_model(
    metric: StationMetricSummary,
    detail: StationDetailResult,
) -> MetricHistoryChartViewModel:
    points = tuple(
        HistoryChartPointViewModel(
            timestamp_text=point.recorded_at.strftime("%d %b %H:%M"),
            value=getattr(point, metric.metric_name),
            quality_label=point.quality.value.title(),
        )
        for point in detail.history_points
    )
    axis_min, axis_max = _resolve_axis_bounds(points, metric)
    return MetricHistoryChartViewModel(
        metric_name=metric.metric_name,
        label=metric.label,
        unit=metric.unit,
        tone=_metric_tone(metric, detail.active_alerts),
        current_value_text=_format_metric_value(metric.current_value, metric.unit),
        average_value_text=_format_metric_value(metric.average_value, metric.unit),
        range_value_text=_format_range(metric.minimum_value, metric.maximum_value, metric.unit),
        delta_value_text=_format_delta(metric.delta_from_start, metric.unit),
        limit_text=_format_limits(metric),
        window_text=_chart_window_text(points),
        axis_min=axis_min,
        axis_max=axis_max,
        lower_bound=metric.lower_bound,
        upper_bound=metric.upper_bound,
        points=points,
    )


def _resolve_axis_bounds(
    points: tuple[HistoryChartPointViewModel, ...],
    metric: StationMetricSummary,
) -> tuple[float, float]:
    values = [point.value for point in points]
    if metric.lower_bound is not None:
        values.append(metric.lower_bound)
    if metric.upper_bound is not None:
        values.append(metric.upper_bound)

    if not values:
        return (0.0, 1.0)

    minimum_value = min(values)
    maximum_value = max(values)
    spread = maximum_value - minimum_value
    padding = spread * 0.12
    if padding == 0:
        padding = max(abs(maximum_value) * 0.08, 1.0)
    return (minimum_value - padding, maximum_value + padding)


def _chart_window_text(points: tuple[HistoryChartPointViewModel, ...]) -> str:
    if not points:
        return "No history loaded"
    if len(points) == 1:
        return f"1 point | {points[0].timestamp_text}"
    return f"{len(points)} points | {points[0].timestamp_text} -> {points[-1].timestamp_text}"


def _history_window_text(detail: StationDetailResult) -> str:
    if detail.history_start_at is None or detail.history_end_at is None:
        return "No telemetry history"
    return (
        f"{detail.history_start_at.strftime('%d %b %H:%M UTC')} -> "
        f"{detail.history_end_at.strftime('%d %b %H:%M UTC')} "
        f"({detail.history_point_count} points)"
    )


def _active_signal_text(detail: StationDetailResult) -> str:
    if not detail.active_alerts:
        return "Clear"

    threshold_count = len(detail.threshold_alerts)
    anomaly_count = len(detail.anomaly_alerts)
    fragments: list[str] = []
    if threshold_count:
        fragments.append(f"{threshold_count} {_pluralize(threshold_count, 'threshold')}")
    if anomaly_count:
        fragments.append(f"{anomaly_count} {_pluralize(anomaly_count, 'anomaly', 'anomalies')}")
    return " | ".join(fragments)


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
    return "signal"


def _severity_tone(severity: AlertSeverity) -> str:
    if severity is AlertSeverity.CRITICAL:
        return "critical"
    if severity is AlertSeverity.WARNING:
        return "warning"
    return "accent"


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


def _pluralize(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return singular
    return plural or f"{singular}s"
