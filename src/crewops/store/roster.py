"""Reading and changing the operation in DynamoDB.

``Store.operation()`` is how the rest of the system gets the operation: built from the table
once and kept in memory until the roster changes. Every change to a trip's crew goes through
``change_crew``, which only succeeds against the version of the trip the caller last saw. If
someone else changed it in between, the caller gets ``StaleTrip`` and must look again, so two
controllers can never quietly overwrite each other.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, TypeAdapter

from crewops.domain import (
    Airline,
    Certificate,
    Crew,
    DutyHistory,
    Leg,
    Rates,
    Rule,
    Seat,
    Standby,
    Trip,
)
from crewops.domain.dataset import Dataset
from crewops.engine import NotFound, Operation, build_operation
from crewops.settings import Settings
from crewops.store import schema

TRIP = "TRIP"
CHANGE = "CHANGE"
META = "META"
ROSTER_VERSION = "roster_version"
BATCH_SIZE = 25


class StaleTrip(RuntimeError):
    """The trip changed since the caller read it."""

    def __init__(self, trip_id: str, expected: int, actual: int) -> None:
        super().__init__(f"{trip_id} is at version {actual}, not {expected}: read it again")
        self.trip_id = trip_id
        self.expected = expected
        self.actual = actual


def _key(kind: str, record: BaseModel) -> str:
    match kind:
        case "airlines":
            return record.code
        case "crew" | "histories":
            return record.crew_id
        case "certificates":
            return f"{record.crew_id}:{record.kind}"
        case "standby":
            return f"{record.crew_id}:{record.dates[0].isoformat()}"
        case "legs":
            return record.leg_id
        case "rules":
            return record.rule_id
    raise ValueError(f"unknown record kind {kind!r}")


KINDS: dict[str, type[BaseModel]] = {
    "airlines": Airline,
    "crew": Crew,
    "certificates": Certificate,
    "histories": DutyHistory,
    "standby": Standby,
    "legs": Leg,
    "rules": Rule,
}


@dataclass(frozen=True, slots=True)
class RosterChange:
    change_id: str
    trip_id: str
    version: int
    at: datetime
    actor: str
    reason: str
    before: tuple[Seat, ...]
    after: tuple[Seat, ...]

    @property
    def added(self) -> tuple[str, ...]:
        old = {s.crew_id for s in self.before}
        return tuple(s.crew_id for s in self.after if s.crew_id not in old)

    @property
    def removed(self) -> tuple[str, ...]:
        new = {s.crew_id for s in self.after}
        return tuple(s.crew_id for s in self.before if s.crew_id not in new)


_seats = TypeAdapter(tuple[Seat, ...])


def _s(value: str) -> dict[str, str]:
    return {"S": value}


def _n(value: int) -> dict[str, str]:
    return {"N": str(value)}


def _json(value: Any) -> dict[str, str]:
    return _s(json.dumps(value, separators=(",", ":")))


def _item(pk: str, sk: str, **attrs: dict[str, str]) -> dict[str, dict[str, str]]:
    return {"pk": _s(pk), "sk": _s(sk), **attrs}


class OperationCache:
    """Builds the operation from a store's records, again only when the roster version moves."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cached: tuple[int, Operation] | None = None

    def roster_version(self) -> int:
        raise NotImplementedError

    def dataset(self) -> Dataset:
        raise NotImplementedError

    def operation(self, now: datetime | None = None) -> Operation:
        """The operation at ``now``, rebuilt only when the roster has changed since last time."""
        version = self.roster_version()
        with self._lock:
            if self._cached is None or self._cached[0] != version:
                self._cached = (version, build_operation(self.dataset()))
            op = self._cached[1]
        if now is not None and now > op.now:
            op = replace(op, now=now)
        return op


class Store(OperationCache):
    """The operation in DynamoDB."""

    def __init__(self, dynamodb: Any, table: str) -> None:
        super().__init__()
        self.dynamodb = dynamodb
        self.table = table

    @classmethod
    def connect(cls, config: Settings) -> Store:
        return cls(schema.client(config), config.table_name)

    # -- low level --------------------------------------------------------------------------

    def _query(self, pk: str) -> Iterator[dict[str, Any]]:
        pages = self.dynamodb.get_paginator("query").paginate(
            TableName=self.table,
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": _s(pk)},
            ConsistentRead=True,
        )
        for page in pages:
            yield from page["Items"]

    def _get(self, pk: str, sk: str) -> dict[str, Any] | None:
        reply = self.dynamodb.get_item(TableName=self.table, Key=_item(pk, sk), ConsistentRead=True)
        return reply.get("Item")

    def _write(self, requests: list[dict[str, Any]]) -> None:
        for start in range(0, len(requests), BATCH_SIZE):
            pending = {self.table: requests[start : start + BATCH_SIZE]}
            while pending:
                reply = self.dynamodb.batch_write_item(RequestItems=pending)
                pending = reply.get("UnprocessedItems") or {}

    # -- loading ----------------------------------------------------------------------------

    def is_empty(self) -> bool:
        reply = self.dynamodb.query(
            TableName=self.table,
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": _s(TRIP)},
            Limit=1,
        )
        return not reply["Items"]

    def load(self, data: Dataset, meta: dict[str, Any]) -> None:
        """Replace everything with ``data``. Used to seed a fresh table.

        Not atomic: DynamoDB cannot write a whole operation in one transaction. The roster
        version is written last, so a reader never builds an operation from half a load.
        """
        keys = [
            {"pk": item["pk"], "sk": item["sk"]}
            for page in self.dynamodb.get_paginator("scan").paginate(
                TableName=self.table, ProjectionExpression="pk, sk"
            )
            for item in page["Items"]
        ]
        self._write([{"DeleteRequest": {"Key": k}} for k in keys])

        items = [
            _item(f"REC#{kind}", _key(kind, r), body=_json(r.model_dump(mode="json")))
            for kind in KINDS
            for r in getattr(data, kind)
        ]
        items.append(_item("REC#rates", "rates", body=_json(data.rates.model_dump(mode="json"))))
        items.append(
            _item("REC#meta", "meta", body=_json({**meta, "as_of": data.as_of.isoformat()}))
        )
        items += [
            _item(TRIP, t.trip_id, version=_n(1), body=_json(t.model_dump(mode="json")))
            for t in data.trips
        ]
        self._write([{"PutRequest": {"Item": item}} for item in items])
        self.dynamodb.put_item(TableName=self.table, Item=_item(META, ROSTER_VERSION, value=_n(1)))
        self._cached = None

    # -- reading ----------------------------------------------------------------------------

    def _bodies(self, kind: str) -> list[Any]:
        return [json.loads(item["body"]["S"]) for item in self._query(f"REC#{kind}")]

    def meta(self) -> dict[str, Any]:
        [body] = self._bodies("meta")
        return body

    def roster_version(self) -> int:
        item = self._get(META, ROSTER_VERSION)
        return int(item["value"]["N"]) if item else 0

    def dataset(self) -> Dataset:
        parsed = {
            kind: TypeAdapter(tuple[model, ...]).validate_python(self._bodies(kind))
            for kind, model in KINDS.items()
        }
        [rates] = self._bodies("rates")
        [meta] = self._bodies("meta")
        roster = TypeAdapter(tuple[Trip, ...]).validate_python(
            [json.loads(item["body"]["S"]) for item in self._query(TRIP)]
        )
        return Dataset(
            **parsed,
            trips=roster,
            rates=Rates.model_validate(rates),
            as_of=datetime.fromisoformat(meta["as_of"]),
        )

    def trip(self, trip_id: str) -> tuple[Trip, int]:
        """The trip and the version to pass back when changing it."""
        item = self._get(TRIP, trip_id)
        if item is None:
            raise NotFound("trip", trip_id)
        return Trip.model_validate_json(item["body"]["S"]), int(item["version"]["N"])

    # -- changing ---------------------------------------------------------------------------

    def change_crew(
        self,
        trip_id: str,
        crew: Iterable[Seat],
        expected_version: int,
        actor: str,
        reason: str,
        at: datetime | None = None,
    ) -> int:
        """Set the crew of ``trip_id``, if it is still at ``expected_version``.

        Returns the new version. The trip update, the change record and the roster version move
        together in one transaction, or not at all.
        """
        at = (at or datetime.now(UTC)).astimezone(UTC)
        seats = _seats.validate_python(list(crew))
        before, current = self.trip(trip_id)
        if current != expected_version:
            raise StaleTrip(trip_id, expected_version, current)
        after = before.model_copy(update={"crew": seats})
        version = expected_version + 1
        change = _item(
            CHANGE,
            f"{at.isoformat()}#{trip_id}#{version:06d}",
            trip_id=_s(trip_id),
            version=_n(version),
            at=_s(at.isoformat()),
            actor=_s(actor),
            reason=_s(reason),
            before=_json(_seats.dump_python(before.crew, mode="json")),
            after=_json(_seats.dump_python(seats, mode="json")),
        )
        try:
            self.dynamodb.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self.table,
                            "Key": _item(TRIP, trip_id),
                            "UpdateExpression": "SET #version = :new, #body = :body",
                            "ConditionExpression": "#version = :expected",
                            "ExpressionAttributeNames": {"#version": "version", "#body": "body"},
                            "ExpressionAttributeValues": {
                                ":new": _n(version),
                                ":expected": _n(expected_version),
                                ":body": _json(after.model_dump(mode="json")),
                            },
                        }
                    },
                    {"Put": {"TableName": self.table, "Item": change}},
                    {
                        "Update": {
                            "TableName": self.table,
                            "Key": _item(META, ROSTER_VERSION),
                            "UpdateExpression": "ADD #value :one",
                            "ExpressionAttributeNames": {"#value": "value"},
                            "ExpressionAttributeValues": {":one": _n(1)},
                        }
                    },
                ]
            )
        except self.dynamodb.exceptions.TransactionCanceledException:
            _, actual = self.trip(trip_id)
            if actual == expected_version:
                raise
            raise StaleTrip(trip_id, expected_version, actual) from None
        return version

    def changes(self, trip_id: str | None = None) -> list[RosterChange]:
        """Every change to the roster, oldest first, optionally for one trip."""
        found = [
            RosterChange(
                change_id=item["sk"]["S"],
                trip_id=item["trip_id"]["S"],
                version=int(item["version"]["N"]),
                at=datetime.fromisoformat(item["at"]["S"]),
                actor=item["actor"]["S"],
                reason=item["reason"]["S"],
                before=_seats.validate_json(item["before"]["S"]),
                after=_seats.validate_json(item["after"]["S"]),
            )
            for item in self._query(CHANGE)
        ]
        return [c for c in found if trip_id is None or c.trip_id == trip_id]
