"""The operation held in memory, with the same behaviour as the DynamoDB store.

Used by tests and to run the tools and the MCP server on a laptop without AWS
(``CREWOPS_STORE=memory``). Changes last as long as the process.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from crewops.domain import Seat, Trip
from crewops.domain.dataset import Dataset
from crewops.engine import NotFound
from crewops.store.roster import OperationCache, RosterChange, StaleTrip, _seats


class MemoryStore(OperationCache):
    def __init__(self) -> None:
        super().__init__()
        self._write_lock = threading.Lock()
        self._data: Dataset | None = None
        self._meta: dict[str, Any] = {}
        self._trips: dict[str, tuple[Trip, int]] = {}
        self._changes: list[RosterChange] = []
        self._version = 0

    def is_empty(self) -> bool:
        return not self._trips

    def load(self, data: Dataset, meta: dict[str, Any]) -> None:
        with self._write_lock:
            self._data = data
            self._meta = {**copy.deepcopy(meta), "as_of": data.as_of.isoformat()}
            self._trips = {t.trip_id: (t, 1) for t in data.trips}
            self._changes = []
            self._version = 1

    def meta(self) -> dict[str, Any]:
        return copy.deepcopy(self._meta)

    def roster_version(self) -> int:
        return self._version

    def dataset(self) -> Dataset:
        if self._data is None:
            raise NotFound("operation", "nothing loaded")
        trips = tuple(t for t, _ in sorted(self._trips.values(), key=lambda tv: tv[0].trip_id))
        return replace(self._data, trips=trips)

    def trip(self, trip_id: str) -> tuple[Trip, int]:
        if trip_id not in self._trips:
            raise NotFound("trip", trip_id)
        return self._trips[trip_id]

    def change_crew(
        self,
        trip_id: str,
        crew: Iterable[Seat],
        expected_version: int,
        actor: str,
        reason: str,
        at: datetime | None = None,
    ) -> int:
        at = (at or datetime.now(UTC)).astimezone(UTC)
        seats = _seats.validate_python(list(crew))
        with self._write_lock:
            before, current = self.trip(trip_id)
            if current != expected_version:
                raise StaleTrip(trip_id, expected_version, current)
            version = current + 1
            self._trips[trip_id] = (before.model_copy(update={"crew": seats}), version)
            self._changes.append(
                RosterChange(
                    change_id=f"{at.isoformat()}#{trip_id}#{version:06d}",
                    trip_id=trip_id,
                    version=version,
                    at=at,
                    actor=actor,
                    reason=reason,
                    before=before.crew,
                    after=seats,
                )
            )
            self._version += 1
        return version

    def changes(self, trip_id: str | None = None) -> list[RosterChange]:
        found = sorted(self._changes, key=lambda c: c.change_id)
        return [c for c in found if trip_id is None or c.trip_id == trip_id]
