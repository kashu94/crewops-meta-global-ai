"""Calling out replacement crew, one at a time, until someone accepts.

A callout fills one empty seat. It offers the seat to the cheapest legal crew member first;
if they decline, or do not answer in time, it offers it to the next. Before every offer, and
again when someone accepts, the cover is worked out afresh, so nobody is offered or given a
seat they stopped being legal for in the meantime.

**A callout never cancels a flight or flies it short on its own.** When nobody is left to
ask, it stops and hands the decision to the crew desk with the remaining options and their
costs. Cancelling or flying one short then needs two controllers: one proposes, a different
one approves. Until then the trip stays as it is.

    OFFERED --accept--> FILLED
       |  decline / no answer: next legal crew member
       v
    NEEDS_DECISION --propose (controller A)--> AWAITING_APPROVAL --approve (controller B)--> CLOSED
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from crewops.domain import Rank, Seat, Trip
from crewops.engine.cover import Choice, TripStarted, arrangements, find_cover
from crewops.engine.operation import NotFound, Operation
from crewops.ops.notify import DESK, Notice, Outbox
from crewops.store.roster import StaleTrip

RESPOND_WITHIN = timedelta(minutes=20)
NO_CREW_WAYS = ("one_short", "cancel")


class Status(StrEnum):
    OFFERED = "offered"
    FILLED = "filled"
    NEEDS_DECISION = "needs_decision"
    AWAITING_APPROVAL = "awaiting_approval"
    CLOSED = "closed"


class CalloutError(ValueError):
    """A request the callout cannot take in its current state."""


@dataclass
class Offer:
    crew_id: str
    name: str
    way: str
    cost: int
    offered_at: datetime
    expires_at: datetime
    answer: str | None = None
    """``accepted``, ``declined``, ``no answer``, ``unavailable`` or ``no longer legal``."""
    answered_at: datetime | None = None


@dataclass
class Proposal:
    way: str
    """``one_short`` or ``cancel``."""
    summary: str
    cost: int
    proposed_by: str
    proposed_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None


@dataclass
class Callout:
    callout_id: str
    trip_id: str
    rank: Rank
    vacated_by: str
    opened_by: str
    opened_at: datetime
    status: Status = Status.OFFERED
    offers: list[Offer] = field(default_factory=list)
    options: list[dict] = field(default_factory=list)
    """What the desk can still do once nobody is left to ask: never applied automatically."""
    reason: str = ""
    proposal: Proposal | None = None
    filled_by: str | None = None
    version: int | None = None
    """The trip's version after the seat was filled."""
    to_arrange: tuple[str, ...] = ()
    """What the desk must still book or retime for the person who accepted."""

    @property
    def current(self) -> Offer | None:
        if self.status is Status.OFFERED and self.offers and self.offers[-1].answer is None:
            return self.offers[-1]
        return None


class Roster(Protocol):
    """What the desk needs from the store."""

    def operation(self, now: datetime | None = None) -> Operation: ...
    def trip(self, trip_id: str) -> tuple[Trip, int]: ...
    def change_crew(
        self,
        trip_id: str,
        crew: list[Seat],
        expected_version: int,
        actor: str,
        reason: str,
        at: datetime | None = None,
    ) -> int: ...


class CalloutDesk:
    def __init__(
        self,
        store: Roster,
        outbox: Outbox,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        respond_within: timedelta = RESPOND_WITHIN,
        operation_clock: Callable[[], datetime | None] = lambda: None,
    ) -> None:
        self.store = store
        self.outbox = outbox
        self.clock = clock
        self.respond_within = respond_within
        self.operation_clock = operation_clock
        """The time the roster is judged at; ``None`` uses the operation's own clock."""
        self._lock = threading.RLock()
        self._callouts: dict[str, Callout] = {}

    # -- reading ----------------------------------------------------------------------------

    def get(self, callout_id: str) -> Callout:
        try:
            return self._callouts[callout_id]
        except KeyError:
            raise NotFound("callout", callout_id) from None

    def all(self) -> list[Callout]:
        return sorted(self._callouts.values(), key=lambda c: c.opened_at)

    def offers_for(self, crew_id: str) -> list[Callout]:
        return [c for c in self.all() if c.current and c.current.crew_id == crew_id]

    # -- opening and offering ---------------------------------------------------------------

    def open(self, trip_id: str, rank: Rank, vacated_by: str, by: str) -> Callout:
        """Start filling the seat ``vacated_by`` leaves on ``trip_id``.

        Opening the same seat twice returns the callout already running.
        """
        with self._lock:
            for c in self._callouts.values():
                if (c.trip_id, c.rank, c.vacated_by) == (
                    trip_id,
                    rank,
                    vacated_by,
                ) and c.status in (
                    Status.OFFERED,
                    Status.NEEDS_DECISION,
                    Status.AWAITING_APPROVAL,
                ):
                    return c
            trip, _ = self.store.trip(trip_id)
            if vacated_by not in {s.crew_id for s in trip.crew}:
                raise CalloutError(f"{vacated_by} is not on {trip_id}")
            callout = Callout(
                callout_id=f"CO-{uuid.uuid4().hex[:8]}",
                trip_id=trip_id,
                rank=rank,
                vacated_by=vacated_by,
                opened_by=by,
                opened_at=self.clock(),
            )
            self._callouts[callout.callout_id] = callout
            self._offer_next(callout)
            return callout

    def _cover(self, callout: Callout):
        op = self.store.operation(self.operation_clock())
        return find_cover(op, callout.trip_id, callout.rank, callout.vacated_by)

    def _offer_next(self, callout: Callout) -> None:
        now = self.clock()
        try:
            cover = self._cover(callout)
        except TripStarted:
            self._needs_decision(callout, [], "the trip has already reported")
            return
        asked = {o.crew_id for o in callout.offers}
        crewed = [c for c in cover.choices if c.crew_id and c.crew_id not in asked]
        if not crewed:
            options = [c for c in cover.choices if c.way.value in NO_CREW_WAYS]
            why = "every legal crew member has been asked" if asked else "no legal crew"
            self._needs_decision(callout, options, why)
            return
        choice = crewed[0]
        offer = Offer(
            crew_id=choice.crew_id,
            name=choice.name or choice.crew_id,
            way=choice.way.label,
            cost=choice.cost,
            offered_at=now,
            expires_at=now + self.respond_within,
        )
        callout.offers.append(offer)
        callout.status = Status.OFFERED
        minutes = int(self.respond_within.total_seconds() // 60)
        self.outbox.send(
            Notice(
                to=choice.crew_id,
                subject=f"Callout: {callout.rank} on {callout.trip_id}",
                body=(
                    f"{offer.name}, you are asked to fly {callout.trip_id} as {callout.rank} "
                    f"({choice.way.label.lower()}). Please accept or decline within "
                    f"{minutes} minutes."
                ),
                at=now,
                ref=callout.callout_id,
            )
        )

    def _needs_decision(self, callout: Callout, options: list[Choice], why: str) -> None:
        callout.status = Status.NEEDS_DECISION
        callout.reason = why
        callout.options = [
            {"way": c.way.value, "summary": c.summary, "cost_inr": c.cost} for c in options
        ]
        listed = "; ".join(f"{o['summary']} (INR {o['cost_inr']:,})" for o in callout.options)
        self.outbox.send(
            Notice(
                to=DESK,
                subject=f"Decision needed: {callout.rank} on {callout.trip_id}",
                body=(
                    f"Nobody is left to call out for {callout.trip_id} ({why}). Nothing has been "
                    "cancelled. A controller must decide"
                    + (f": {listed}." if listed else ".")
                    + " A cancellation or flying short needs a second controller to approve."
                ),
                at=self.clock(),
                ref=callout.callout_id,
            )
        )

    # -- answers ----------------------------------------------------------------------------

    def respond(self, callout_id: str, crew_id: str, accept: bool) -> Callout:
        with self._lock:
            callout = self.get(callout_id)
            offer = callout.current
            if offer is None or offer.crew_id != crew_id:
                raise CalloutError(f"there is no open offer for {crew_id} on {callout_id}")
            now = self.clock()
            if now > offer.expires_at:
                self._answer(offer, "no answer", offer.expires_at)
                self._offer_next(callout)
                raise CalloutError("the offer expired and has gone to the next crew member")
            if not accept:
                self._answer(offer, "declined", now)
                self._offer_next(callout)
                return callout
            self._fill(callout, offer, now)
            return callout

    def _answer(self, offer: Offer, answer: str, at: datetime) -> None:
        offer.answer = answer
        offer.answered_at = at

    def _fill(self, callout: Callout, offer: Offer, now: datetime) -> None:
        for _ in range(2):
            try:
                cover = self._cover(callout)
            except TripStarted:
                self._answer(offer, "no longer legal", now)
                self._needs_decision(callout, [], "the trip has already reported")
                return
            choice = next((c for c in cover.choices if c.crew_id == offer.crew_id), None)
            if choice is None:
                self._answer(offer, "no longer legal", now)
                self._offer_next(callout)
                return
            notes = arrangements(
                self.store.operation(self.operation_clock()), callout.trip_id, choice
            )
            trip, version = self.store.trip(callout.trip_id)
            if callout.vacated_by not in {s.crew_id for s in trip.crew}:
                self._answer(offer, "no longer needed", now)
                callout.status = Status.CLOSED
                callout.reason = f"{callout.vacated_by} is no longer on {callout.trip_id}"
                return
            crew = [
                Seat(crew_id=offer.crew_id, rank=s.rank) if s.crew_id == callout.vacated_by else s
                for s in trip.crew
            ]
            try:
                callout.version = self.store.change_crew(
                    callout.trip_id,
                    crew,
                    version,
                    actor=f"callout {callout.callout_id} ({callout.opened_by})",
                    reason=f"{offer.name} accepted the callout for {callout.vacated_by}"
                    + "".join(f"; {n}" for n in notes),
                    at=now,
                )
            except StaleTrip:
                continue  # someone changed the trip meanwhile: judge again with the new roster
            self._answer(offer, "accepted", now)
            callout.status = Status.FILLED
            callout.filled_by = offer.crew_id
            callout.to_arrange = notes
            todo = "".join(f" To do: {n}." for n in notes)
            self.outbox.send(
                Notice(
                    to=DESK,
                    subject=f"Filled: {callout.rank} on {callout.trip_id}",
                    body=f"{offer.name} ({offer.crew_id}) accepted {callout.trip_id}.{todo}",
                    at=now,
                    ref=callout.callout_id,
                )
            )
            return
        self._answer(offer, "no longer legal", now)
        self._offer_next(callout)

    def withdraw(self, crew_id: str) -> list[Callout]:
        """Pull open offers from someone who just reported they cannot fly that trip.

        Called the moment they report it, so the next person is asked straight away instead of
        after the answer window runs out. An offer stays if the dates they gave miss the trip.
        """
        moved = []
        with self._lock:
            for callout in self._callouts.values():
                offer = callout.current
                if offer is None or offer.crew_id != crew_id:
                    continue
                try:
                    still = any(c.crew_id == crew_id for c in self._cover(callout).choices)
                except TripStarted:
                    still = False
                if still:
                    continue
                self._answer(offer, "unavailable", self.clock())
                self.outbox.send(
                    Notice(
                        to=DESK,
                        subject=f"Offer withdrawn: {callout.rank} on {callout.trip_id}",
                        body=f"{offer.name} ({crew_id}) reported they cannot fly. The offer has "
                        "moved to the next legal crew member.",
                        at=self.clock(),
                        ref=callout.callout_id,
                    )
                )
                self._offer_next(callout)
                moved.append(callout)
        return moved

    def tick(self) -> list[Callout]:
        """Move every offer that ran out of time to the next crew member. Run on a schedule."""
        moved = []
        with self._lock:
            now = self.clock()
            for callout in self._callouts.values():
                offer = callout.current
                if offer is not None and now > offer.expires_at:
                    self._answer(offer, "no answer", offer.expires_at)
                    self._offer_next(callout)
                    moved.append(callout)
        return moved

    # -- the desk's decision ----------------------------------------------------------------

    def propose(self, callout_id: str, way: str, by: str) -> Callout:
        with self._lock:
            callout = self.get(callout_id)
            if callout.status is not Status.NEEDS_DECISION:
                raise CalloutError(f"{callout_id} is {callout.status}, not waiting for a decision")
            option = next((o for o in callout.options if o["way"] == way), None)
            if option is None:
                ways = ", ".join(o["way"] for o in callout.options) or "none"
                raise CalloutError(f"{way!r} is not an option here (options: {ways})")
            callout.proposal = Proposal(
                way, option["summary"], option["cost_inr"], by, self.clock()
            )
            callout.status = Status.AWAITING_APPROVAL
            self.outbox.send(
                Notice(
                    to=DESK,
                    subject=f"Approval needed: {option['summary']}",
                    body=f"{by} proposes: {option['summary']} for {callout.trip_id}. "
                    "A second controller must approve before anything happens.",
                    at=self.clock(),
                    ref=callout.callout_id,
                )
            )
            return callout

    def approve(self, callout_id: str, by: str) -> Callout:
        with self._lock:
            callout = self.get(callout_id)
            proposal = callout.proposal
            if callout.status is not Status.AWAITING_APPROVAL or proposal is None:
                raise CalloutError(f"{callout_id} has nothing waiting for approval")
            if by == proposal.proposed_by:
                raise CalloutError("a proposal must be approved by a different controller")
            proposal.approved_by = by
            proposal.approved_at = self.clock()
            callout.status = Status.CLOSED
            callout.reason = f"{proposal.summary}: approved by {by}"
            self.outbox.send(
                Notice(
                    to=DESK,
                    subject=f"Approved: {proposal.summary}",
                    body=f"{proposal.summary} for {callout.trip_id}, proposed by "
                    f"{proposal.proposed_by} and approved by {by}. Operations to action.",
                    at=proposal.approved_at,
                    ref=callout.callout_id,
                )
            )
            return callout

    def reject(self, callout_id: str, by: str) -> Callout:
        """Send a proposal back; the callout waits for a decision again."""
        with self._lock:
            callout = self.get(callout_id)
            if callout.status is not Status.AWAITING_APPROVAL:
                raise CalloutError(f"{callout_id} has nothing waiting for approval")
            callout.proposal = None
            callout.status = Status.NEEDS_DECISION
            return callout
