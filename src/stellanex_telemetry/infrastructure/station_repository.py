from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Sequence

from stellanex_telemetry.application import IngestionBatch, IngestionIssue, StationQuery, StationRepository
from stellanex_telemetry.domain import StationStatus, Substation
from stellanex_telemetry.infrastructure.csv_parser import parse_station_catalog_csv


class IndexedStationRepository(StationRepository):
    """In-memory station catalog with indexes for fast operational queries."""

    def __init__(self, stations: Sequence[Substation] | None = None) -> None:
        self._stations_by_id: dict[str, Substation] = {}
        self._ordered_station_ids: tuple[str, ...] = ()
        self._region_index: dict[str, frozenset[str]] = {}
        self._region_display_names: dict[str, str] = {}
        self._status_index: dict[StationStatus, frozenset[str]] = {}
        self._tag_index: dict[str, frozenset[str]] = {}
        if stations:
            self.upsert_stations(stations)

    @classmethod
    def from_csv(
        cls,
        source_path: Path,
        *,
        issues: list[IngestionIssue] | None = None,
    ) -> IndexedStationRepository:
        return cls(parse_station_catalog_csv(source_path, issues=issues))

    @classmethod
    def from_batch(cls, batch: IngestionBatch) -> IndexedStationRepository:
        return cls(batch.stations)

    @property
    def station_count(self) -> int:
        return len(self._stations_by_id)

    @property
    def region_names(self) -> tuple[str, ...]:
        return tuple(self._region_display_names[key] for key in sorted(self._region_display_names))

    @property
    def station_ids(self) -> tuple[str, ...]:
        return self._ordered_station_ids

    def region_counts(self) -> dict[str, int]:
        return {
            self._region_display_names[region_key]: len(station_ids)
            for region_key, station_ids in sorted(self._region_index.items())
        }

    def status_counts(self) -> dict[StationStatus, int]:
        return {status: len(station_ids) for status, station_ids in sorted(self._status_index.items(), key=_status_sort_key)}

    def list_stations(self, query: StationQuery | None = None) -> Sequence[Substation]:
        ordered_station_ids = self._filter_station_ids(query) if query is not None else self._ordered_station_ids
        stations = [self._stations_by_id[station_id] for station_id in ordered_station_ids]

        if query is not None and query.search_text:
            needle = query.search_text.casefold()
            stations = [station for station in stations if _matches_search(station, needle)]

        if query is not None and query.limit is not None:
            stations = stations[: query.limit]

        return tuple(stations)

    def get_station(self, station_id: str) -> Substation | None:
        return self._stations_by_id.get(station_id.strip())

    def upsert_stations(self, stations: Sequence[Substation]) -> None:
        for station in stations:
            self._stations_by_id[station.station_id] = station
        self._rebuild_indexes()

    def _filter_station_ids(self, query: StationQuery) -> tuple[str, ...]:
        candidate_sets: list[set[str]] = []

        if query.station_ids:
            candidate_sets.append({station_id for station_id in query.station_ids if station_id in self._stations_by_id})

        if query.regions:
            region_hits: set[str] = set()
            for region in query.regions:
                region_hits.update(self._region_index.get(region.casefold(), frozenset()))
            candidate_sets.append(region_hits)

        if query.statuses:
            status_hits: set[str] = set()
            for status in query.statuses:
                status_hits.update(self._status_index.get(status, frozenset()))
            candidate_sets.append(status_hits)

        for tag in query.required_tags:
            candidate_sets.append(set(self._tag_index.get(tag.casefold(), frozenset())))

        if not candidate_sets:
            return self._ordered_station_ids

        matching_ids = set.intersection(*sorted(candidate_sets, key=len))
        if not matching_ids:
            return ()

        return tuple(station_id for station_id in self._ordered_station_ids if station_id in matching_ids)

    def _rebuild_indexes(self) -> None:
        ordered_stations = sorted(self._stations_by_id.values(), key=_station_sort_key)
        self._ordered_station_ids = tuple(station.station_id for station in ordered_stations)

        region_index: dict[str, set[str]] = defaultdict(set)
        region_display_names: dict[str, str] = {}
        status_index: dict[StationStatus, set[str]] = defaultdict(set)
        tag_index: dict[str, set[str]] = defaultdict(set)

        for station in ordered_stations:
            region_key = station.region.casefold()
            region_index[region_key].add(station.station_id)
            region_display_names.setdefault(region_key, station.region)
            status_index[station.status].add(station.station_id)
            for tag in station.tags:
                tag_index[tag.casefold()].add(station.station_id)

        self._region_index = {region: frozenset(station_ids) for region, station_ids in region_index.items()}
        self._region_display_names = region_display_names
        self._status_index = {status: frozenset(station_ids) for status, station_ids in status_index.items()}
        self._tag_index = {tag: frozenset(station_ids) for tag, station_ids in tag_index.items()}


def _matches_search(station: Substation, needle: str) -> bool:
    if needle in station.station_id.casefold():
        return True
    if needle in station.name.casefold():
        return True
    if needle in station.region.casefold():
        return True
    return any(needle in tag.casefold() for tag in station.tags)


def _station_sort_key(station: Substation) -> tuple[str, str, str]:
    return (station.region.casefold(), station.name.casefold(), station.station_id.casefold())


def _status_sort_key(item: tuple[StationStatus, frozenset[str]]) -> tuple[int, str]:
    status, _ = item
    rank = {
        StationStatus.CRITICAL: 1,
        StationStatus.WARNING: 2,
        StationStatus.MAINTENANCE: 3,
        StationStatus.OFFLINE: 4,
        StationStatus.HEALTHY: 5,
        StationStatus.UNKNOWN: 6,
    }[status]
    return (rank, status.value)

