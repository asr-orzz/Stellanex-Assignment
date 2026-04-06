from __future__ import annotations

import csv
import json
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from stellanex_telemetry.config import load_config
from stellanex_telemetry.domain import (
    GeoCoordinate,
    OperatingEnvelope,
    StationStatus,
    Substation,
    TelemetryQuality,
    TelemetryReading,
)


@dataclass(frozen=True, slots=True)
class RegionBlueprint:
    region: str
    prefix: str
    nominal_voltage_kv: float
    base_latitude: float
    base_longitude: float
    place_names: tuple[str, ...]


REGION_BLUEPRINTS: tuple[RegionBlueprint, ...] = (
    RegionBlueprint(
        region="North Grid",
        prefix="NG",
        nominal_voltage_kv=132.0,
        base_latitude=28.6139,
        base_longitude=77.2090,
        place_names=(
            "Yamuna Exchange",
            "Noida Corridor",
            "Rohini Peak",
            "Ghaziabad Ring",
            "Sonepat Yard",
            "Panipat Industrial",
        ),
    ),
    RegionBlueprint(
        region="West Grid",
        prefix="WG",
        nominal_voltage_kv=220.0,
        base_latitude=19.0760,
        base_longitude=72.8777,
        place_names=(
            "Harbor Link",
            "Mira Junction",
            "Thane Core",
            "Navi Gateway",
            "Turbhe Switchyard",
            "Kalyan Spur",
        ),
    ),
    RegionBlueprint(
        region="South Grid",
        prefix="SG",
        nominal_voltage_kv=110.0,
        base_latitude=12.9716,
        base_longitude=77.5946,
        place_names=(
            "Whitefield Spine",
            "Electronic City",
            "Peenya Works",
            "Hosur Road",
            "Mysore Link",
            "Tumakuru Edge",
        ),
    ),
    RegionBlueprint(
        region="East Grid",
        prefix="EG",
        nominal_voltage_kv=66.0,
        base_latitude=22.5726,
        base_longitude=88.3639,
        place_names=(
            "Howrah North",
            "Salt Lake Central",
            "Dum Dum Feed",
            "Kalyani Spur",
            "Haldia Port",
            "Durgapur Metal Park",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class DemoDatasetSpec:
    seed: int = 20260406
    station_count: int = 24
    interval_minutes: int = 15
    periods: int = 192
    start_at: datetime = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    dataset_name: str = "municipal-grid-demo"

    def __post_init__(self) -> None:
        if self.station_count <= 0:
            raise ValueError("station_count must be greater than zero")
        if self.interval_minutes <= 0:
            raise ValueError("interval_minutes must be greater than zero")
        if self.periods <= 0:
            raise ValueError("periods must be greater than zero")
        if self.station_count % len(REGION_BLUEPRINTS) != 0:
            raise ValueError("station_count must be evenly divisible by the number of regions")
        if self.start_at.tzinfo is None or self.start_at.utcoffset() is None:
            raise ValueError("start_at must be timezone-aware")

    @property
    def periods_per_day(self) -> int:
        return (24 * 60) // self.interval_minutes

    @property
    def cadence(self) -> timedelta:
        return timedelta(minutes=self.interval_minutes)


@dataclass(frozen=True, slots=True)
class DemoDataset:
    spec: DemoDatasetSpec
    stations: tuple[Substation, ...]
    readings: tuple[TelemetryReading, ...]
    incidents: tuple[str, ...] = field(default_factory=tuple)


def build_demo_dataset(spec: DemoDatasetSpec | None = None) -> DemoDataset:
    resolved_spec = spec or DemoDatasetSpec()
    stations = build_demo_stations(resolved_spec)
    readings = build_demo_readings(stations, resolved_spec)
    incidents = (
        "NG-003 experiences a midday overload spike and elevated temperatures.",
        "WG-002 emits degraded-quality telemetry during a communications disturbance.",
        "SG-005 shows gradual thermal drift over the second day of the dataset.",
        "EG-004 suffers a short voltage sag event with recovery.",
        "NG-006 stops reporting during the final two hours to simulate stale telemetry.",
    )
    return DemoDataset(spec=resolved_spec, stations=stations, readings=readings, incidents=incidents)


def build_demo_stations(spec: DemoDatasetSpec) -> tuple[Substation, ...]:
    stations_per_region = spec.station_count // len(REGION_BLUEPRINTS)
    stations: list[Substation] = []

    for region_index, blueprint in enumerate(REGION_BLUEPRINTS):
        for local_index in range(stations_per_region):
            station_id = f"{blueprint.prefix}-{local_index + 1:03d}"
            nominal_voltage_kv = blueprint.nominal_voltage_kv
            envelope = OperatingEnvelope(
                nominal_voltage_kv=nominal_voltage_kv,
                min_voltage_kv=round(nominal_voltage_kv * 0.94, 1),
                max_voltage_kv=round(nominal_voltage_kv * 1.06, 1),
                max_load_percent=92.0 + (local_index % 3) * 2.0,
                max_temperature_c=84.0 + region_index,
            )
            tags = _build_station_tags(blueprint, local_index)
            stations.append(
                Substation(
                    station_id=station_id,
                    name=blueprint.place_names[local_index],
                    region=blueprint.region,
                    capacity_mw=90.0 + (local_index * 18.0) + (region_index * 12.0),
                    status=_station_status(station_id),
                    nominal_voltage_kv=nominal_voltage_kv,
                    envelope=envelope,
                    location=GeoCoordinate(
                        latitude=blueprint.base_latitude + (local_index * 0.18),
                        longitude=blueprint.base_longitude + (local_index * 0.16),
                    ),
                    commissioned_on=date(2011 + local_index, (region_index % 12) + 1, min(local_index + 3, 28)),
                    tags=tags,
                )
            )
    return tuple(stations)


def build_demo_readings(
    stations: tuple[Substation, ...],
    spec: DemoDatasetSpec,
) -> tuple[TelemetryReading, ...]:
    readings: list[TelemetryReading] = []

    for station_index, station in enumerate(stations):
        rng = random.Random(spec.seed + (station_index + 1) * 7919)
        base_load_percent = 48.0 + (station_index % 6) * 4.8 + rng.uniform(-3.0, 3.0)
        region_heat_offset = (station_index // (spec.station_count // len(REGION_BLUEPRINTS))) * 1.8
        phase = rng.uniform(0.0, math.pi)

        for step in range(spec.periods):
            if station.station_id == "NG-006" and step >= spec.periods - 8:
                continue

            recorded_at = spec.start_at + (step * spec.cadence)
            daily_position = step % spec.periods_per_day
            daily_angle = (daily_position / spec.periods_per_day) * math.tau

            load_percent = (
                base_load_percent
                + 12.0 * math.sin(daily_angle - phase)
                + 5.5 * math.cos((daily_angle * 2.0) + phase / 2.0)
                + rng.uniform(-1.8, 1.8)
            )
            temperature_c = (
                25.0
                + region_heat_offset
                + 7.2 * math.sin(daily_angle - 0.8)
                + (load_percent * 0.31)
                + rng.uniform(-1.1, 1.1)
            )
            voltage_kv = (
                station.nominal_voltage_kv
                * (1.0 + 0.008 * math.sin(daily_angle + phase / 3.0) - 0.00075 * (load_percent - 65.0))
                + rng.uniform(-0.35, 0.35)
            )
            quality = TelemetryQuality.OK

            if station.station_id == "NG-003" and 44 <= step < 58:
                load_percent += 19.0
                temperature_c += 7.5
            elif station.station_id == "WG-002" and 70 <= step < 92:
                quality = TelemetryQuality.DEGRADED
                voltage_kv += rng.uniform(-1.2, 1.2)
            elif station.station_id == "SG-005" and step >= 96:
                drift = (step - 96) * 0.14
                load_percent += min(8.0, drift * 0.35)
                temperature_c += drift
                if step % 6 == 0:
                    quality = TelemetryQuality.ESTIMATED
            elif station.station_id == "EG-004" and 128 <= step < 136:
                voltage_kv *= 0.91
                load_percent += 4.5

            readings.append(
                TelemetryReading(
                    station_id=station.station_id,
                    recorded_at=recorded_at,
                    voltage_kv=round(max(0.0, voltage_kv), 3),
                    load_percent=round(min(max(load_percent, 0.0), 100.0), 3),
                    temperature_c=round(temperature_c, 3),
                    quality=quality,
                    source="demo-generator",
                    sequence_number=step + 1,
                )
            )

    readings.sort(key=lambda reading: (reading.station_id, reading.recorded_at))
    return tuple(readings)


def write_demo_dataset(dataset: DemoDataset, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    _write_station_catalog(dataset.stations, destination_dir / "stations.csv")
    _write_telemetry_readings(dataset.readings, destination_dir / "telemetry_readings.csv")
    _write_manifest(dataset, destination_dir / "manifest.json")


def _build_station_tags(blueprint: RegionBlueprint, local_index: int) -> tuple[str, ...]:
    tags = [blueprint.prefix.lower(), "municipal"]
    tags.append("industrial" if local_index in {2, 5} else "urban")
    if local_index in {1, 4}:
        tags.append("renewable-feed")
    if local_index == 5 and blueprint.prefix == "SG":
        tags.append("maintenance-window")
    return tuple(tags)


def _station_status(station_id: str) -> StationStatus:
    if station_id == "NG-003":
        return StationStatus.CRITICAL
    if station_id in {"WG-002", "SG-005", "EG-004", "NG-006"}:
        return StationStatus.WARNING
    if station_id == "SG-006":
        return StationStatus.MAINTENANCE
    return StationStatus.HEALTHY


def _write_station_catalog(stations: tuple[Substation, ...], destination: Path) -> None:
    with destination.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(
            file_obj,
            fieldnames=[
                "station_id",
                "name",
                "region",
                "status",
                "capacity_mw",
                "nominal_voltage_kv",
                "min_voltage_kv",
                "max_voltage_kv",
                "max_load_percent",
                "max_temperature_c",
                "latitude",
                "longitude",
                "commissioned_on",
                "tags",
            ],
        )
        writer.writeheader()
        for station in stations:
            envelope = station.envelope
            writer.writerow(
                {
                    "station_id": station.station_id,
                    "name": station.name,
                    "region": station.region,
                    "status": station.status.value,
                    "capacity_mw": f"{station.capacity_mw:.1f}",
                    "nominal_voltage_kv": f"{station.nominal_voltage_kv:.1f}",
                    "min_voltage_kv": f"{envelope.min_voltage_kv:.1f}" if envelope else "",
                    "max_voltage_kv": f"{envelope.max_voltage_kv:.1f}" if envelope else "",
                    "max_load_percent": f"{envelope.max_load_percent:.1f}" if envelope else "",
                    "max_temperature_c": f"{envelope.max_temperature_c:.1f}" if envelope else "",
                    "latitude": f"{station.location.latitude:.4f}" if station.location else "",
                    "longitude": f"{station.location.longitude:.4f}" if station.location else "",
                    "commissioned_on": station.commissioned_on.isoformat() if station.commissioned_on else "",
                    "tags": "|".join(station.tags),
                }
            )


def _write_telemetry_readings(readings: tuple[TelemetryReading, ...], destination: Path) -> None:
    with destination.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(
            file_obj,
            fieldnames=[
                "station_id",
                "recorded_at",
                "voltage_kv",
                "load_percent",
                "temperature_c",
                "quality",
                "source",
                "sequence_number",
            ],
        )
        writer.writeheader()
        for reading in readings:
            writer.writerow(
                {
                    "station_id": reading.station_id,
                    "recorded_at": reading.recorded_at.isoformat().replace("+00:00", "Z"),
                    "voltage_kv": f"{reading.voltage_kv:.3f}",
                    "load_percent": f"{reading.load_percent:.3f}",
                    "temperature_c": f"{reading.temperature_c:.3f}",
                    "quality": reading.quality.value,
                    "source": reading.source,
                    "sequence_number": reading.sequence_number or "",
                }
            )


def _write_manifest(dataset: DemoDataset, destination: Path) -> None:
    payload = {
        "dataset_name": dataset.spec.dataset_name,
        "seed": dataset.spec.seed,
        "station_count": len(dataset.stations),
        "reading_count": len(dataset.readings),
        "interval_minutes": dataset.spec.interval_minutes,
        "periods": dataset.spec.periods,
        "start_at": dataset.spec.start_at.isoformat().replace("+00:00", "Z"),
        "end_at": (dataset.spec.start_at + ((dataset.spec.periods - 1) * dataset.spec.cadence)).isoformat().replace(
            "+00:00",
            "Z",
        ),
        "files": {
            "stations": "stations.csv",
            "telemetry": "telemetry_readings.csv",
        },
        "incident_notes": list(dataset.incidents),
    }
    with destination.open("w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, indent=2)
        file_obj.write("\n")


def main() -> None:
    config = load_config()
    dataset = build_demo_dataset()
    write_demo_dataset(dataset, config.paths.demo_data_dir)
    print(
        f"Wrote demo dataset '{dataset.spec.dataset_name}' "
        f"with {len(dataset.stations)} stations and {len(dataset.readings)} readings "
        f"to {config.paths.demo_data_dir}"
    )


if __name__ == "__main__":
    main()
