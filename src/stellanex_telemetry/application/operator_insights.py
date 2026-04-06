from __future__ import annotations

from dataclasses import dataclass

from stellanex_telemetry.application.station_detail import (
    StationAlertSummary,
    StationDetailResult,
    StationMetricSummary,
)
from stellanex_telemetry.domain import AlertCategory, AlertSeverity, StationStatus


@dataclass(frozen=True, slots=True)
class InsightNarrative:
    title: str
    detail: str
    tone: str


@dataclass(frozen=True, slots=True)
class OperatorRecommendation:
    title: str
    detail: str
    priority_label: str
    tone: str


@dataclass(frozen=True, slots=True)
class StationInsightReport:
    station_id: str
    summary_title: str
    summary_body: str
    summary_tone: str
    narratives: tuple[InsightNarrative, ...]
    recommendations: tuple[OperatorRecommendation, ...]


class OperatorInsightService:
    """Generate operator-facing narratives and recommended actions from station detail views."""

    def build_report(self, detail: StationDetailResult) -> StationInsightReport:
        primary_alert = detail.active_alerts[0] if detail.active_alerts else None
        stress_metric = _highest_stress_metric(detail.metric_summaries)
        trend_metrics = _top_trend_metrics(detail.metric_summaries)

        summary_title, summary_body, summary_tone = _summary(detail, primary_alert, stress_metric)
        narratives = (
            _primary_risk_narrative(detail, primary_alert),
            _trend_narrative(detail, trend_metrics, primary_alert),
            _boundary_narrative(detail, stress_metric),
        )
        recommendations = _recommendations(detail, primary_alert, stress_metric)

        return StationInsightReport(
            station_id=detail.station.station_id,
            summary_title=summary_title,
            summary_body=summary_body,
            summary_tone=summary_tone,
            narratives=narratives,
            recommendations=recommendations,
        )


def _summary(
    detail: StationDetailResult,
    primary_alert: StationAlertSummary | None,
    stress_metric: StationMetricSummary | None,
) -> tuple[str, str, str]:
    station = detail.station
    status = detail.health_snapshot.derived_status
    if primary_alert is not None:
        title = "Immediate operator focus"
        body = (
            f"{station.display_name} is currently in {status.value} state because "
            f"{primary_alert.message.lower()}"
        )
        return (title, body, _alert_tone(primary_alert))

    if status is StationStatus.CRITICAL:
        return (
            "Manual critical flag remains active",
            (
                f"{station.display_name} still carries a critical metadata state even though no live threshold or "
                "anomaly alerts are firing at the current reference cut."
            ),
            "critical",
        )

    if status is StationStatus.WARNING:
        return (
            "Operator review still recommended",
            (
                f"{station.display_name} is operating without an active alert, but its metadata state still asks "
                "for operator review."
            ),
            "warning",
        )

    if stress_metric is not None and (stress_metric.utilization_ratio or 0.0) >= 0.75:
        return (
            "Trend watch remains active",
            (
                f"{stress_metric.label} is the closest metric to its configured limit, so this station should remain "
                "on the watchlist even without a formal alert."
            ),
            "warning",
        )

    return (
        "Stable operating posture",
        (
            f"{station.display_name} is operating within its configured envelope and no current signals require "
            "immediate escalation."
        ),
        "signal",
    )


def _primary_risk_narrative(
    detail: StationDetailResult,
    primary_alert: StationAlertSummary | None,
) -> InsightNarrative:
    if primary_alert is None:
        return InsightNarrative(
            title="Primary Risk",
            detail=detail.health_snapshot.status_reason,
            tone=_status_tone(detail.health_snapshot.derived_status),
        )

    detail_text = primary_alert.message
    if primary_alert.observed_value is not None and primary_alert.threshold_value is not None:
        detail_text = (
            f"{detail_text} Observed {primary_alert.observed_value:.3f} against "
            f"{primary_alert.threshold_value:.3f}."
        )
    return InsightNarrative(
        title="Primary Risk",
        detail=detail_text,
        tone=_alert_tone(primary_alert),
    )


def _trend_narrative(
    detail: StationDetailResult,
    trend_metrics: tuple[StationMetricSummary, ...],
    primary_alert: StationAlertSummary | None,
) -> InsightNarrative:
    if not trend_metrics:
        return InsightNarrative(
            title="Recent Trend",
            detail="Not enough telemetry points are available to describe a meaningful short-window trend.",
            tone="neutral",
        )

    fragments = []
    for metric in trend_metrics:
        if metric.delta_from_start is None:
            continue
        if (
            primary_alert is not None
            and primary_alert.category is AlertCategory.ANOMALY
            and primary_alert.metric_name == metric.metric_name
        ):
            direction = "elevated" if primary_alert.observed_value is None or primary_alert.threshold_value is None or primary_alert.observed_value >= primary_alert.threshold_value else "depressed"
            fragments.append(
                f"{metric.label.lower()} shows {'an' if direction[0] in 'aeiou' else 'a'} {direction} recent average versus its prior window"
            )
            continue
        direction = "rose" if metric.delta_from_start > 0 else "eased"
        fragments.append(
            f"{metric.label.lower()} {direction} by {abs(metric.delta_from_start):.3f} {metric.unit}"
        )

    if not fragments:
        body = "The recent telemetry window is available, but directional change is too small to call out."
    else:
        body = "Across the recent telemetry window, " + ", while ".join(fragments) + "."

    return InsightNarrative(
        title="Recent Trend",
        detail=body,
        tone=_trend_tone(detail.metric_summaries),
    )


def _boundary_narrative(
    detail: StationDetailResult,
    stress_metric: StationMetricSummary | None,
) -> InsightNarrative:
    if stress_metric is None or stress_metric.utilization_ratio is None:
        return InsightNarrative(
            title="Limit Proximity",
            detail="No configured limit proximity could be calculated for this station.",
            tone="neutral",
        )

    ratio_percent = stress_metric.utilization_ratio * 100
    detail_text = (
        f"{stress_metric.label} is the closest metric to its configured boundary at {ratio_percent:.1f}% "
        f"utilization. Current reading is {stress_metric.current_value:.3f} {stress_metric.unit}."
    )
    if detail.latest_reading is not None and detail.latest_reading.quality.value != "ok":
        detail_text += f" Telemetry quality is {detail.latest_reading.quality.value}, so operators should verify the signal."

    return InsightNarrative(
        title="Limit Proximity",
        detail=detail_text,
        tone=_metric_tone(stress_metric),
    )


def _recommendations(
    detail: StationDetailResult,
    primary_alert: StationAlertSummary | None,
    stress_metric: StationMetricSummary | None,
) -> tuple[OperatorRecommendation, ...]:
    recommendations: list[OperatorRecommendation] = []

    if primary_alert is not None:
        recommendations.append(_alert_recommendation(primary_alert))

    if detail.health_snapshot.derived_status in {StationStatus.CRITICAL, StationStatus.WARNING} and primary_alert is None:
        recommendations.append(
            OperatorRecommendation(
                title="Reconcile station status",
                detail=(
                    "Compare the manual station status against the latest telemetry and clear or confirm the "
                    "metadata flag so the watchlist reflects the true operating state."
                ),
                priority_label="Next Shift",
                tone=_status_tone(detail.health_snapshot.derived_status),
            )
        )

    if stress_metric is not None and (stress_metric.utilization_ratio or 0.0) >= 0.7:
        recommendations.append(
            OperatorRecommendation(
                title=f"Track {stress_metric.label.lower()} margin",
                detail=(
                    f"Keep {stress_metric.label.lower()} under observation and compare it with neighboring stations "
                    "or upstream assets before the metric approaches its formal alert threshold."
                ),
                priority_label="Monitor",
                tone=_metric_tone(stress_metric),
            )
        )

    if detail.latest_reading is None:
        recommendations.append(
            OperatorRecommendation(
                title="Restore telemetry visibility",
                detail="No current telemetry is available, so communications and sensor health should be verified before any dispatch decision.",
                priority_label="Immediate",
                tone="critical",
            )
        )
    elif detail.latest_reading.quality.value != "ok":
        recommendations.append(
            OperatorRecommendation(
                title="Validate data quality",
                detail=(
                    f"Latest telemetry quality is {detail.latest_reading.quality.value}; compare with field historian or "
                    "backup feeds before making a control-room decision from this signal alone."
                ),
                priority_label="Immediate",
                tone="warning",
            )
        )

    if not recommendations:
        recommendations.append(
            OperatorRecommendation(
                title="Continue routine monitoring",
                detail=(
                    "No corrective action is required right now; keep this station in the normal review cadence and "
                    "use the explorer to compare it with peer substations in the same region."
                ),
                priority_label="Monitor",
                tone="signal",
            )
        )

    deduped: list[OperatorRecommendation] = []
    seen_titles: set[str] = set()
    for recommendation in recommendations:
        key = recommendation.title.casefold()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        deduped.append(recommendation)
        if len(deduped) == 3:
            break
    return tuple(deduped)


def _alert_recommendation(alert: StationAlertSummary) -> OperatorRecommendation:
    if alert.category is AlertCategory.CONNECTIVITY:
        return OperatorRecommendation(
            title="Verify telemetry heartbeat",
            detail=(
                "Check the RTU or gateway heartbeat, confirm recent packet arrival, and compare the stale station "
                "with a neighboring site before trusting any older reading."
            ),
            priority_label="Immediate",
            tone=_alert_tone(alert),
        )
    if alert.metric_name == "temperature_c":
        return OperatorRecommendation(
            title="Inspect thermal loading",
            detail=(
                "Review recent load transfers, cooling performance, and ambient conditions to confirm whether the "
                "temperature trend is a reversible operating drift or an equipment issue."
            ),
            priority_label="Immediate",
            tone=_alert_tone(alert),
        )
    if alert.category is AlertCategory.LOAD:
        return OperatorRecommendation(
            title="Prepare load balancing options",
            detail=(
                "Compare feeder margin and reserve transfer paths so operators can shed or redistribute load "
                "quickly if the trend continues toward the configured limit."
            ),
            priority_label="Immediate",
            tone=_alert_tone(alert),
        )
    if alert.category is AlertCategory.VOLTAGE:
        return OperatorRecommendation(
            title="Review voltage support",
            detail=(
                "Check transformer tap positions, reactive support, and nearby bus conditions to determine whether "
                "the voltage event is local or system-driven."
            ),
            priority_label="Immediate",
            tone=_alert_tone(alert),
        )
    return OperatorRecommendation(
        title="Review active station signal",
        detail=(
            "Use the alert context and recent chart history to confirm whether the event is isolated, persistent, "
            "or part of a broader regional pattern before escalating."
        ),
        priority_label="Immediate",
        tone=_alert_tone(alert),
    )


def _highest_stress_metric(metrics: tuple[StationMetricSummary, ...]) -> StationMetricSummary | None:
    candidates = [metric for metric in metrics if metric.utilization_ratio is not None]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda metric: (metric.utilization_ratio or 0.0, metric.label.casefold()),
    )


def _top_trend_metrics(metrics: tuple[StationMetricSummary, ...]) -> tuple[StationMetricSummary, ...]:
    candidates = [metric for metric in metrics if metric.delta_from_start is not None]
    if not candidates:
        return ()
    ordered = sorted(
        candidates,
        key=lambda metric: (abs(metric.delta_from_start or 0.0), metric.label.casefold()),
        reverse=True,
    )
    return tuple(ordered[:2])


def _metric_tone(metric: StationMetricSummary) -> str:
    ratio = metric.utilization_ratio
    if ratio is None:
        return "neutral"
    if ratio >= 1.0:
        return "critical"
    if ratio >= 0.85:
        return "warning"
    return "signal"


def _trend_tone(metrics: tuple[StationMetricSummary, ...]) -> str:
    if any((metric.utilization_ratio or 0.0) >= 0.85 for metric in metrics):
        return "warning"
    return "accent"


def _alert_tone(alert: StationAlertSummary) -> str:
    if alert.severity is AlertSeverity.CRITICAL:
        return "critical"
    if alert.severity is AlertSeverity.WARNING:
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
