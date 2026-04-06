from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import OrderedDict, defaultdict
from datetime import datetime
from heapq import merge
from itertools import islice
from pathlib import Path
from typing import Iterable, Sequence

from stellanex_telemetry.application import IngestionBatch, IngestionIssue, TelemetryQuery, TelemetryRepository
from stellanex_telemetry.domain import TelemetryQuality, TelemetryReading
from stellanex_telemetry.infrastructure.csv_parser import parse_telemetry_readings_csv

QUERY_CACHE_CAPACITY = 128


class IndexedTelemetryRepository(TelemetryRepository):
    """In-memory telemetry store with time-window indexes and query result caching."""

    def __init__(self, readings: Sequence[TelemetryReading] | None = None) -> None:
        self._all_readings: tuple[TelemetryReading, ...] = ()
        self._global_timestamps: tuple[datetime, ...] = ()
        self._ordered_station_ids: tuple[str, ...] = ()
        self._readings_by_station: dict[str, tuple[TelemetryReading, ...]] = {}
        self._timestamps_by_station: dict[str, tuple[datetime, ...]] = {}
        self._latest_by_station: dict[str, TelemetryReading] = {}
        self._query_cache: OrderedDict[TelemetryQuery | None, tuple[TelemetryReading, ...]] = OrderedDict()
        if readings:
            self.append_readings(readings)

    @classmethod
    def from_csv(
        cls,
        source_path: Path,
        *,
        issues: list[IngestionIssue] | None = None,
    ) -> IndexedTelemetryRepository:
        return cls(parse_telemetry_readings_csv(source_path, issues=issues))

    @classmethod
    def from_batch(cls, batch: IngestionBatch) -> IndexedTelemetryRepository:
        return cls(batch.readings)

    @property
    def reading_count(self) -> int:
        return len(self._all_readings)

    @property
    def station_count(self) -> int:
        return len(self._readings_by_station)

    @property
    def station_ids(self) -> tuple[str, ...]:
        return self._ordered_station_ids

    @property
    def time_bounds(self) -> tuple[datetime, datetime] | None:
        if not self._all_readings:
            return None
        return (self._all_readings[0].recorded_at, self._all_readings[-1].recorded_at)

    def list_readings(self, query: TelemetryQuery | None = None) -> Sequence[TelemetryReading]:
        cache_key = query
        if cache_key in self._query_cache:
            self._query_cache.move_to_end(cache_key)
            return self._query_cache[cache_key]

        result = self._execute_query(query)
        self._query_cache[cache_key] = result
        self._query_cache.move_to_end(cache_key)
        if len(self._query_cache) > QUERY_CACHE_CAPACITY:
            self._query_cache.popitem(last=False)
        return result

    def get_latest_reading(self, station_id: str) -> TelemetryReading | None:
        return self._latest_by_station.get(station_id.strip())

    def append_readings(self, readings: Sequence[TelemetryReading]) -> None:
        if not readings:
            return

        incoming = _dedupe_sorted_readings(sorted(readings, key=_reading_sort_key))
        merged = _merge_readings(self._all_readings, incoming)
        self._rebuild_indexes(merged)

    def _execute_query(self, query: TelemetryQuery | None) -> tuple[TelemetryReading, ...]:
        if query is None:
            return self._all_readings

        if not self._all_readings:
            return ()

        if not query.station_ids and not query.qualities:
            return self._query_global_window(query)

        station_ids = self._resolve_station_ids(query)
        if not station_ids:
            return ()

        quality_filter = set(query.qualities)
        station_slices: list[tuple[TelemetryReading, ...]] = []
        for station_id in station_ids:
            candidate_slice = self._slice_station_window(
                station_id,
                start_at=query.start_at,
                end_at=query.end_at,
            )
            if not candidate_slice:
                continue
            if quality_filter:
                candidate_slice = tuple(
                    reading for reading in candidate_slice if reading.quality in quality_filter
                )
                if not candidate_slice:
                    continue
            station_slices.append(candidate_slice)

        if not station_slices:
            return ()

        if len(station_slices) == 1:
            return _finalize_sequence(
                station_slices[0],
                newest_first=query.newest_first,
                limit=query.limit,
            )

        merged_iterable = self._merge_station_slices(
            station_slices,
            newest_first=query.newest_first,
        )
        if query.limit is not None:
            return tuple(islice(merged_iterable, query.limit))
        return tuple(merged_iterable)

    def _query_global_window(self, query: TelemetryQuery) -> tuple[TelemetryReading, ...]:
        left = bisect_left(self._global_timestamps, query.start_at) if query.start_at is not None else 0
        right = bisect_right(self._global_timestamps, query.end_at) if query.end_at is not None else len(self._all_readings)
        window = self._all_readings[left:right]
        return _finalize_sequence(window, newest_first=query.newest_first, limit=query.limit)

    def _resolve_station_ids(self, query: TelemetryQuery) -> tuple[str, ...]:
        if not query.station_ids:
            return self._ordered_station_ids
        seen_station_ids: set[str] = set()
        resolved: list[str] = []
        for station_id in query.station_ids:
            normalized = station_id.strip()
            if normalized in seen_station_ids or normalized not in self._readings_by_station:
                continue
            seen_station_ids.add(normalized)
            resolved.append(normalized)
        return tuple(resolved)

    def _slice_station_window(
        self,
        station_id: str,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> tuple[TelemetryReading, ...]:
        readings = self._readings_by_station.get(station_id, ())
        if not readings:
            return ()

        timestamps = self._timestamps_by_station[station_id]
        left = bisect_left(timestamps, start_at) if start_at is not None else 0
        right = bisect_right(timestamps, end_at) if end_at is not None else len(readings)
        return readings[left:right]

    def _merge_station_slices(
        self,
        slices: Sequence[tuple[TelemetryReading, ...]],
        *,
        newest_first: bool,
    ) -> Iterable[TelemetryReading]:
        if newest_first:
            descending_slices = [reversed(reading_slice) for reading_slice in slices]
            return merge(*descending_slices, key=_reading_sort_key, reverse=True)
        return merge(*slices, key=_reading_sort_key)

    def _rebuild_indexes(self, ordered_readings: Sequence[TelemetryReading]) -> None:
        normalized_readings = tuple(ordered_readings)
        self._all_readings = normalized_readings
        self._global_timestamps = tuple(reading.recorded_at for reading in normalized_readings)

        by_station: dict[str, list[TelemetryReading]] = defaultdict(list)
        for reading in normalized_readings:
            by_station[reading.station_id].append(reading)

        ordered_station_ids = sorted(by_station, key=str.casefold)
        self._ordered_station_ids = tuple(ordered_station_ids)
        self._readings_by_station = {
            station_id: tuple(by_station[station_id])
            for station_id in ordered_station_ids
        }
        self._timestamps_by_station = {
            station_id: tuple(reading.recorded_at for reading in station_readings)
            for station_id, station_readings in self._readings_by_station.items()
        }
        self._latest_by_station = {
            station_id: station_readings[-1]
            for station_id, station_readings in self._readings_by_station.items()
            if station_readings
        }
        self._query_cache.clear()


def _finalize_sequence(
    readings: Sequence[TelemetryReading],
    *,
    newest_first: bool,
    limit: int | None,
) -> tuple[TelemetryReading, ...]:
    if newest_first:
        iterator: Iterable[TelemetryReading] = reversed(readings)
        if limit is not None:
            return tuple(islice(iterator, limit))
        return tuple(iterator)
    if limit is not None:
        return tuple(readings[:limit])
    return tuple(readings)


def _merge_readings(
    existing: Sequence[TelemetryReading],
    incoming: Sequence[TelemetryReading],
) -> tuple[TelemetryReading, ...]:
    if not existing:
        return tuple(incoming)
    if not incoming:
        return tuple(existing)

    merged: list[TelemetryReading] = []
    existing_index = 0
    incoming_index = 0

    while existing_index < len(existing) and incoming_index < len(incoming):
        existing_reading = existing[existing_index]
        incoming_reading = incoming[incoming_index]
        existing_identity = _reading_identity(existing_reading)
        incoming_identity = _reading_identity(incoming_reading)

        if existing_identity == incoming_identity:
            merged.append(incoming_reading)
            existing_index += 1
            incoming_index += 1
            continue

        if _reading_sort_key(existing_reading) <= _reading_sort_key(incoming_reading):
            merged.append(existing_reading)
            existing_index += 1
        else:
            merged.append(incoming_reading)
            incoming_index += 1

    if existing_index < len(existing):
        merged.extend(existing[existing_index:])
    if incoming_index < len(incoming):
        merged.extend(incoming[incoming_index:])

    return tuple(merged)


def _dedupe_sorted_readings(readings: Sequence[TelemetryReading]) -> tuple[TelemetryReading, ...]:
    deduped: list[TelemetryReading] = []
    for reading in readings:
        if deduped and _reading_identity(deduped[-1]) == _reading_identity(reading):
            deduped[-1] = reading
        else:
            deduped.append(reading)
    return tuple(deduped)


def _reading_identity(reading: TelemetryReading) -> tuple[str, datetime]:
    return (reading.station_id, reading.recorded_at)


def _reading_sort_key(reading: TelemetryReading) -> tuple[datetime, str, int]:
    return (
        reading.recorded_at,
        reading.station_id.casefold(),
        reading.sequence_number if reading.sequence_number is not None else -1,
    )
