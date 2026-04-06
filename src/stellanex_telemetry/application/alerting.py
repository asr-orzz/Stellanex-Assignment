from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import Sequence

from stellanex_telemetry.application.contracts import StationQuery, StationRepository, TelemetryRepository
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
class ThresholdAlertPolicyConfig:
    voltage_warning_band_ratio: float = 0.015
    minimum_voltage_warning_band_kv: float = 0.5
    load_warning_ratio: float = 0.92
    temperature_warning_ratio: float = 0.9

    def __post_init__(self) -> None:
        for field_name in (
            "voltage_warning_band_ratio",
            "minimum_voltage_warning_band_kv",
            "load_warning_ratio",
            "temperature_warning_ratio",
        ):
            value = getattr(self, field_name)
            if value <= 0:
                raise ValueError(f"{field_name} must be greater than zero")
        if self.load_warning_ratio >= 1.0:
            raise ValueError("load_warning_ratio must be less than 1.0")
        if self.temperature_warning_ratio >= 1.0:
            raise ValueError("temperature_warning_ratio must be less than 1.0")


class ThresholdAlertPolicyEngine:
    """Evaluate transparent operating-threshold alerts from station envelopes and telemetry."""

    def __init__(self, config: ThresholdAlertPolicyConfig | None = None) -> None:
        self._config = config or ThresholdAlertPolicyConfig()

    @property
    def config(self) -> ThresholdAlertPolicyConfig:
        return self._config

    def evaluate_station(self, station: Substation, reading: TelemetryReading | None) -> tuple[Alert, ...]:
        if reading is None:
            return ()
        if reading.station_id != station.station_id:
            raise ValueError("reading.station_id must match station.station_id")

        alerts: list[Alert] = []
        alerts.extend(self._evaluate_quality(station, reading))

        if station.envelope is not None:
            alerts.extend(self._evaluate_voltage(station, reading, station.envelope))
            alerts.extend(self._evaluate_load(station, reading, station.envelope))
            alerts.extend(self._evaluate_temperature(station, reading, station.envelope))

        alerts.sort(key=_alert_sort_key)
        return tuple(alerts)

    def evaluate_readings(
        self,
        stations: Sequence[Substation],
        readings: Sequence[TelemetryReading],
    ) -> tuple[Alert, ...]:
        stations_by_id = {station.station_id: station for station in stations}
        alerts: list[Alert] = []
        for reading in readings:
            station = stations_by_id.get(reading.station_id)
            if station is None:
                continue
            alerts.extend(self.evaluate_station(station, reading))
        alerts.sort(key=_alert_sort_key)
        return tuple(alerts)

    def evaluate_latest(
        self,
        station_repository: StationRepository,
        telemetry_repository: TelemetryRepository,
        *,
        station_query: StationQuery | None = None,
    ) -> tuple[Alert, ...]:
        stations = tuple(station_repository.list_stations(query=station_query))
        latest_readings = tuple(
            reading
            for station in stations
            if (reading := telemetry_repository.get_latest_reading(station.station_id)) is not None
        )
        return self.evaluate_readings(stations, latest_readings)

    def _evaluate_quality(self, station: Substation, reading: TelemetryReading) -> list[Alert]:
        if reading.quality is TelemetryQuality.OK:
            return []

        if reading.quality is TelemetryQuality.ESTIMATED:
            severity = AlertSeverity.INFO
            message = "Telemetry values are estimated and should be confirmed against the raw device feed."
        elif reading.quality is TelemetryQuality.DEGRADED:
            severity = AlertSeverity.WARNING
            message = "Telemetry feed is degraded and may not reflect full sensor fidelity."
        else:
            severity = AlertSeverity.CRITICAL
            message = "Telemetry feed reported missing data from the device."

        return [
            self._build_alert(
                station=station,
                reading=reading,
                severity=severity,
                category=AlertCategory.CONNECTIVITY,
                metric_name="quality",
                message=message,
            )
        ]

    def _evaluate_voltage(
        self,
        station: Substation,
        reading: TelemetryReading,
        envelope: OperatingEnvelope,
    ) -> list[Alert]:
        warning_band = max(
            self._config.minimum_voltage_warning_band_kv,
            envelope.nominal_voltage_kv * self._config.voltage_warning_band_ratio,
        )
        low_warning_threshold = envelope.min_voltage_kv + warning_band
        high_warning_threshold = envelope.max_voltage_kv - warning_band

        if reading.voltage_kv < envelope.min_voltage_kv:
            return [
                self._build_alert(
                    station=station,
                    reading=reading,
                    severity=AlertSeverity.CRITICAL,
                    category=AlertCategory.VOLTAGE,
                    metric_name="voltage_kv",
                    observed_value=reading.voltage_kv,
                    threshold_value=envelope.min_voltage_kv,
                    message=(
                        f"Voltage dropped below the operating floor "
                        f"({reading.voltage_kv:.3f} kV vs {envelope.min_voltage_kv:.3f} kV)."
                    ),
                )
            ]

        if reading.voltage_kv > envelope.max_voltage_kv:
            return [
                self._build_alert(
                    station=station,
                    reading=reading,
                    severity=AlertSeverity.CRITICAL,
                    category=AlertCategory.VOLTAGE,
                    metric_name="voltage_kv",
                    observed_value=reading.voltage_kv,
                    threshold_value=envelope.max_voltage_kv,
                    message=(
                        f"Voltage exceeded the operating ceiling "
                        f"({reading.voltage_kv:.3f} kV vs {envelope.max_voltage_kv:.3f} kV)."
                    ),
                )
            ]

        if reading.voltage_kv <= low_warning_threshold:
            return [
                self._build_alert(
                    station=station,
                    reading=reading,
                    severity=AlertSeverity.WARNING,
                    category=AlertCategory.VOLTAGE,
                    metric_name="voltage_kv",
                    observed_value=reading.voltage_kv,
                    threshold_value=envelope.min_voltage_kv,
                    message=(
                        f"Voltage is approaching the low operating boundary "
                        f"({reading.voltage_kv:.3f} kV vs {envelope.min_voltage_kv:.3f} kV minimum)."
                    ),
                )
            ]

        if reading.voltage_kv >= high_warning_threshold:
            return [
                self._build_alert(
                    station=station,
                    reading=reading,
                    severity=AlertSeverity.WARNING,
                    category=AlertCategory.VOLTAGE,
                    metric_name="voltage_kv",
                    observed_value=reading.voltage_kv,
                    threshold_value=envelope.max_voltage_kv,
                    message=(
                        f"Voltage is approaching the high operating boundary "
                        f"({reading.voltage_kv:.3f} kV vs {envelope.max_voltage_kv:.3f} kV maximum)."
                    ),
                )
            ]

        return []

    def _evaluate_load(
        self,
        station: Substation,
        reading: TelemetryReading,
        envelope: OperatingEnvelope,
    ) -> list[Alert]:
        warning_threshold = envelope.max_load_percent * self._config.load_warning_ratio

        if reading.load_percent > envelope.max_load_percent:
            severity = AlertSeverity.CRITICAL
            message = (
                f"Load exceeded the operating limit "
                f"({reading.load_percent:.3f}% vs {envelope.max_load_percent:.3f}%)."
            )
        elif reading.load_percent >= warning_threshold:
            severity = AlertSeverity.WARNING
            message = (
                f"Load is approaching the operating limit "
                f"({reading.load_percent:.3f}% vs {envelope.max_load_percent:.3f}%)."
            )
        else:
            return []

        return [
            self._build_alert(
                station=station,
                reading=reading,
                severity=severity,
                category=AlertCategory.LOAD,
                metric_name="load_percent",
                observed_value=reading.load_percent,
                threshold_value=envelope.max_load_percent,
                message=message,
            )
        ]

    def _evaluate_temperature(
        self,
        station: Substation,
        reading: TelemetryReading,
        envelope: OperatingEnvelope,
    ) -> list[Alert]:
        warning_threshold = envelope.max_temperature_c * self._config.temperature_warning_ratio

        if reading.temperature_c > envelope.max_temperature_c:
            severity = AlertSeverity.CRITICAL
            message = (
                f"Temperature exceeded the operating limit "
                f"({reading.temperature_c:.3f} C vs {envelope.max_temperature_c:.3f} C)."
            )
        elif reading.temperature_c >= warning_threshold:
            severity = AlertSeverity.WARNING
            message = (
                f"Temperature is approaching the operating limit "
                f"({reading.temperature_c:.3f} C vs {envelope.max_temperature_c:.3f} C)."
            )
        else:
            return []

        return [
            self._build_alert(
                station=station,
                reading=reading,
                severity=severity,
                category=AlertCategory.TEMPERATURE,
                metric_name="temperature_c",
                observed_value=reading.temperature_c,
                threshold_value=envelope.max_temperature_c,
                message=message,
            )
        ]

    def _build_alert(
        self,
        *,
        station: Substation,
        reading: TelemetryReading,
        severity: AlertSeverity,
        category: AlertCategory,
        message: str,
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
                    reading.recorded_at.isoformat(),
                    message,
                )
            ).encode("utf-8")
        ).hexdigest()[:12]
        return Alert(
            alert_id=f"ALT-{station.station_id}-{fingerprint}",
            station_id=station.station_id,
            severity=severity,
            category=category,
            message=message,
            triggered_at=reading.recorded_at,
            metric_name=metric_name,
            observed_value=observed_value,
            threshold_value=threshold_value,
            reading=reading,
        )


def _alert_sort_key(alert: Alert) -> tuple[int, str, str, str]:
    return (
        -alert.severity.rank,
        -alert.triggered_at.timestamp(),
        alert.station_id.casefold(),
        alert.category.value,
        alert.alert_id,
    )
