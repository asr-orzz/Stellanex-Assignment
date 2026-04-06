from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from statistics import fmean, median, pstdev
from typing import Sequence

from stellanex_telemetry.application.contracts import StationQuery, StationRepository, TelemetryQuery, TelemetryRepository
from stellanex_telemetry.domain import (
    Alert,
    AlertCategory,
    AlertSeverity,
    OperatingEnvelope,
    Substation,
    TelemetryQuality,
    TelemetryReading,
)


@dataclass(frozen=True, slots=True)
class MetricAnomalyThreshold:
    spike_warning_ratio: float
    spike_critical_ratio: float
    spike_absolute_floor: float
    drift_warning_ratio: float
    drift_critical_ratio: float
    drift_absolute_floor: float
    detect_drift: bool = True
    drift_min_scale_ratio: float = 0.0


METRIC_THRESHOLDS: dict[str, MetricAnomalyThreshold] = {
    "voltage_kv": MetricAnomalyThreshold(
        spike_warning_ratio=0.025,
        spike_critical_ratio=0.05,
        spike_absolute_floor=0.8,
        drift_warning_ratio=0.015,
        drift_critical_ratio=0.03,
        drift_absolute_floor=0.6,
        detect_drift=False,
    ),
    "load_percent": MetricAnomalyThreshold(
        spike_warning_ratio=0.12,
        spike_critical_ratio=0.22,
        spike_absolute_floor=8.0,
        drift_warning_ratio=0.07,
        drift_critical_ratio=0.13,
        drift_absolute_floor=4.0,
        detect_drift=False,
    ),
    "temperature_c": MetricAnomalyThreshold(
        spike_warning_ratio=0.08,
        spike_critical_ratio=0.14,
        spike_absolute_floor=4.0,
        drift_warning_ratio=0.035,
        drift_critical_ratio=0.07,
        drift_absolute_floor=1.5,
        detect_drift=True,
        drift_min_scale_ratio=0.55,
    ),
}


@dataclass(frozen=True, slots=True)
class TelemetryAnomalyConfig:
    history_limit: int = 24
    spike_baseline_size: int = 8
    drift_window_size: int = 8
    stale_interval_multiplier: float = 4.0
    stale_critical_multiplier: float = 2.0
    default_stale_after: timedelta = timedelta(hours=1)
    minimum_cadence_points: int = 4
    spike_warning_sigma_multiplier: float = 3.0
    spike_critical_sigma_multiplier: float = 4.5
    drift_consistency_ratio: float = 0.6

    def __post_init__(self) -> None:
        if self.history_limit <= 0:
            raise ValueError("history_limit must be greater than zero")
        if self.spike_baseline_size < 2:
            raise ValueError("spike_baseline_size must be at least 2")
        if self.drift_window_size < 2:
            raise ValueError("drift_window_size must be at least 2")
        if self.minimum_cadence_points < 2:
            raise ValueError("minimum_cadence_points must be at least 2")
        for field_name in (
            "stale_interval_multiplier",
            "stale_critical_multiplier",
            "spike_warning_sigma_multiplier",
            "spike_critical_sigma_multiplier",
        ):
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} must be greater than zero")
        if self.default_stale_after <= timedelta(0):
            raise ValueError("default_stale_after must be positive")
        if not 0.0 <= self.drift_consistency_ratio <= 1.0:
            raise ValueError("drift_consistency_ratio must be between 0.0 and 1.0")


class TelemetryAnomalyDetector:
    """Detect spikes, drift, and stale telemetry from recent per-station history."""

    def __init__(self, config: TelemetryAnomalyConfig | None = None) -> None:
        self._config = config or TelemetryAnomalyConfig()

    @property
    def config(self) -> TelemetryAnomalyConfig:
        return self._config

    def evaluate_station(
        self,
        station: Substation,
        readings: Sequence[TelemetryReading],
        *,
        reference_time: datetime | None = None,
    ) -> tuple[Alert, ...]:
        ordered_readings = tuple(sorted(
            (reading for reading in readings if reading.station_id == station.station_id),
            key=lambda reading: reading.recorded_at,
        ))
        if reference_time is not None and (reference_time.tzinfo is None or reference_time.utcoffset() is None):
            raise ValueError("reference_time must be timezone-aware")

        latest_reading = ordered_readings[-1] if ordered_readings else None
        effective_reference_time = reference_time or (latest_reading.recorded_at if latest_reading else datetime.now(timezone.utc))

        alerts: list[Alert] = []
        stale_alert = self._detect_stale_telemetry(
            station=station,
            readings=ordered_readings,
            reference_time=effective_reference_time,
        )
        if stale_alert is not None:
            alerts.append(stale_alert)

        if latest_reading is None:
            alerts.sort(key=_alert_sort_key)
            return tuple(alerts)

        if latest_reading.quality is not TelemetryQuality.MISSING:
            alerts.extend(self._detect_spikes(station=station, readings=ordered_readings))
            alerts.extend(self._detect_drift(station=station, readings=ordered_readings))

        alerts.sort(key=_alert_sort_key)
        return tuple(alerts)

    def evaluate_latest(
        self,
        station_repository: StationRepository,
        telemetry_repository: TelemetryRepository,
        *,
        station_query: StationQuery | None = None,
        generated_at: datetime | None = None,
    ) -> tuple[Alert, ...]:
        if generated_at is not None and (generated_at.tzinfo is None or generated_at.utcoffset() is None):
            raise ValueError("generated_at must be timezone-aware")

        stations = tuple(station_repository.list_stations(query=station_query))
        latest_candidates = tuple(
            reading
            for station in stations
            if (reading := telemetry_repository.get_latest_reading(station.station_id)) is not None
        )
        reference_time = generated_at or _latest_reference_time(latest_candidates)

        alerts: list[Alert] = []
        for station in stations:
            history = tuple(
                reversed(
                    telemetry_repository.list_readings(
                        TelemetryQuery(
                            station_ids=(station.station_id,),
                            end_at=reference_time,
                            newest_first=True,
                            limit=self._config.history_limit,
                        )
                    )
                )
            )
            alerts.extend(self.evaluate_station(station, history, reference_time=reference_time))

        alerts.sort(key=_alert_sort_key)
        return tuple(alerts)

    def _detect_stale_telemetry(
        self,
        *,
        station: Substation,
        readings: Sequence[TelemetryReading],
        reference_time: datetime,
    ) -> Alert | None:
        if not readings:
            return self._build_alert(
                station=station,
                reading=None,
                triggered_at=reference_time,
                severity=AlertSeverity.CRITICAL,
                category=AlertCategory.CONNECTIVITY,
                metric_name="telemetry_gap_minutes",
                message="No telemetry history is available for anomaly analysis.",
            )

        latest_reading = readings[-1]
        expected_interval = _estimate_expected_interval(readings, minimum_points=self._config.minimum_cadence_points)
        tolerance = max(
            self._config.default_stale_after,
            expected_interval * self._config.stale_interval_multiplier,
        )
        age = reference_time - latest_reading.recorded_at
        if age < timedelta(0):
            return None
        if age <= tolerance:
            return None

        severity = (
            AlertSeverity.CRITICAL
            if age >= (tolerance * self._config.stale_critical_multiplier)
            else AlertSeverity.WARNING
        )
        return self._build_alert(
            station=station,
            reading=latest_reading,
            triggered_at=reference_time,
            severity=severity,
            category=AlertCategory.CONNECTIVITY,
            metric_name="telemetry_gap_minutes",
            observed_value=round(age.total_seconds() / 60, 3),
            threshold_value=round(tolerance.total_seconds() / 60, 3),
            message=(
                f"Telemetry is stale by {age}, which exceeds the expected cadence tolerance of {tolerance}."
            ),
        )

    def _detect_spikes(
        self,
        *,
        station: Substation,
        readings: Sequence[TelemetryReading],
    ) -> list[Alert]:
        if len(readings) < self._config.spike_baseline_size + 1:
            return []

        latest = readings[-1]
        baseline = readings[-(self._config.spike_baseline_size + 1):-1]
        alerts: list[Alert] = []
        for metric_name, threshold in METRIC_THRESHOLDS.items():
            latest_value = getattr(latest, metric_name)
            baseline_values = [getattr(reading, metric_name) for reading in baseline]
            baseline_mean = fmean(baseline_values)
            baseline_stddev = pstdev(baseline_values) if len(baseline_values) > 1 else 0.0
            delta = abs(latest_value - baseline_mean)
            scale = _metric_scale(metric_name, station)
            warning_threshold = max(
                threshold.spike_absolute_floor,
                scale * threshold.spike_warning_ratio,
                baseline_stddev * self._config.spike_warning_sigma_multiplier,
            )
            critical_threshold = max(
                threshold.spike_absolute_floor * 1.5,
                scale * threshold.spike_critical_ratio,
                baseline_stddev * self._config.spike_critical_sigma_multiplier,
            )

            if delta < warning_threshold:
                continue

            severity = AlertSeverity.CRITICAL if delta >= critical_threshold else AlertSeverity.WARNING
            direction = "upward" if latest_value > baseline_mean else "downward"
            alerts.append(
                self._build_alert(
                    station=station,
                    reading=latest,
                    triggered_at=latest.recorded_at,
                    severity=severity,
                    category=AlertCategory.ANOMALY,
                    metric_name=metric_name,
                    observed_value=latest_value,
                    threshold_value=round(baseline_mean, 3),
                    message=(
                        f"Detected a sudden {direction} spike in {metric_name} "
                        f"({latest_value:.3f} vs recent baseline {baseline_mean:.3f})."
                    ),
                )
            )
        return alerts

    def _detect_drift(
        self,
        *,
        station: Substation,
        readings: Sequence[TelemetryReading],
    ) -> list[Alert]:
        window_size = self._config.drift_window_size
        if len(readings) < window_size * 2:
            return []

        baseline_window = readings[-(window_size * 2):-window_size]
        recent_window = readings[-window_size:]
        alerts: list[Alert] = []

        for metric_name, threshold in METRIC_THRESHOLDS.items():
            if not threshold.detect_drift:
                continue
            baseline_values = [getattr(reading, metric_name) for reading in baseline_window]
            recent_values = [getattr(reading, metric_name) for reading in recent_window]
            baseline_mean = fmean(baseline_values)
            recent_mean = fmean(recent_values)
            delta = recent_mean - baseline_mean
            absolute_delta = abs(delta)
            scale = _metric_scale(metric_name, station)
            if scale and threshold.drift_min_scale_ratio and (recent_mean / scale) < threshold.drift_min_scale_ratio:
                continue

            warning_threshold = max(
                threshold.drift_absolute_floor,
                scale * threshold.drift_warning_ratio,
            )
            critical_threshold = max(
                threshold.drift_absolute_floor * 1.75,
                scale * threshold.drift_critical_ratio,
            )
            if absolute_delta < warning_threshold:
                continue

            consistency = _trend_consistency(recent_values, positive=delta >= 0)
            if consistency < self._config.drift_consistency_ratio:
                continue

            severity = AlertSeverity.CRITICAL if absolute_delta >= critical_threshold else AlertSeverity.WARNING
            direction = "upward" if delta >= 0 else "downward"
            latest = recent_window[-1]
            alerts.append(
                self._build_alert(
                    station=station,
                    reading=latest,
                    triggered_at=latest.recorded_at,
                    severity=severity,
                    category=AlertCategory.ANOMALY,
                    metric_name=metric_name,
                    observed_value=round(recent_mean, 3),
                    threshold_value=round(baseline_mean, 3),
                    message=(
                        f"Detected sustained {direction} drift in {metric_name} "
                        f"(recent mean {recent_mean:.3f} vs prior mean {baseline_mean:.3f})."
                    ),
                )
            )
        return alerts

    def _build_alert(
        self,
        *,
        station: Substation,
        triggered_at: datetime,
        severity: AlertSeverity,
        category: AlertCategory,
        message: str,
        reading: TelemetryReading | None,
        metric_name: str | None = None,
        observed_value: float | None = None,
        threshold_value: float | None = None,
    ) -> Alert:
        fingerprint = sha1(
            "|".join(
                (
                    station.station_id,
                    category.value,
                    metric_name or "",
                    severity.value,
                    triggered_at.isoformat(),
                    message,
                )
            ).encode("utf-8")
        ).hexdigest()[:12]
        return Alert(
            alert_id=f"ANM-{station.station_id}-{fingerprint}",
            station_id=station.station_id,
            severity=severity,
            category=category,
            message=message,
            triggered_at=triggered_at,
            metric_name=metric_name,
            observed_value=observed_value,
            threshold_value=threshold_value,
            reading=reading,
        )


def _latest_reference_time(readings: Sequence[TelemetryReading]) -> datetime:
    if not readings:
        return datetime.now(timezone.utc)
    return max(reading.recorded_at for reading in readings)


def _estimate_expected_interval(
    readings: Sequence[TelemetryReading],
    *,
    minimum_points: int,
) -> timedelta:
    if len(readings) < minimum_points:
        return timedelta(0)

    deltas = [
        (current.recorded_at - previous.recorded_at).total_seconds()
        for previous, current in zip(readings[:-1], readings[1:])
        if current.recorded_at > previous.recorded_at
    ]
    if not deltas:
        return timedelta(0)
    return timedelta(seconds=median(deltas))


def _metric_scale(metric_name: str, station: Substation) -> float:
    envelope = station.envelope
    if metric_name == "voltage_kv":
        if envelope is not None:
            return max(envelope.nominal_voltage_kv, 1.0)
        return max(station.nominal_voltage_kv, 1.0)
    if metric_name == "load_percent":
        if envelope is not None:
            return max(envelope.max_load_percent, 1.0)
        return 100.0
    if metric_name == "temperature_c":
        if envelope is not None:
            return max(envelope.max_temperature_c, 1.0)
        return 100.0
    return 1.0


def _trend_consistency(values: Sequence[float], *, positive: bool) -> float:
    if len(values) < 2:
        return 0.0
    aligned_steps = 0
    total_steps = 0
    for previous_value, current_value in zip(values[:-1], values[1:]):
        delta = current_value - previous_value
        if delta == 0:
            continue
        total_steps += 1
        if (delta > 0) is positive:
            aligned_steps += 1
    if total_steps == 0:
        return 0.0
    return aligned_steps / total_steps


def _alert_sort_key(alert: Alert) -> tuple[int, float, str, str]:
    return (
        -alert.severity.rank,
        -alert.triggered_at.timestamp(),
        alert.station_id.casefold(),
        alert.alert_id,
    )
