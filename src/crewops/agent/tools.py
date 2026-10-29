"""The tools a model may call, and who may call each.

Every tool is a thin, typed wrapper over the rules engine or the store. The model picks a tool
and its arguments; the tool validates them, checks the caller may use it, and returns plain
JSON built from the engine's results. No tool asks a model anything, so every crew id, hour
and rupee in an answer can be traced back to a tool result.

Roles:

* ``viewer`` reads the operation: an ops board, a duty manager.
* ``controller`` also changes the roster, and only to crew the engine offers as legal cover.
* ``crew`` reads their own record and the trips they fly, nothing about anyone else.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from crewops.domain import Rank, Seat, Trip
from crewops.engine import Finding, NotFound, Operation, assess
from crewops.engine.clock import IST, window
from crewops.engine.cover import Choice, TripStarted, find_cover
from crewops.engine.impact import absence_gaps, delay_impact, joint_cover, with_unavailable
from crewops.store.roster import RosterChange, StaleTrip

CREW_ID = r"^C-\d{4}$"
TRIP_ID = r"^T-\d{4}$"


class Role(StrEnum):
    VIEWER = "viewer"
    CONTROLLER = "controller"
    CREW = "crew"


@dataclass(frozen=True, slots=True)
class Caller:
    user: str
    role: Role
    crew_id: str | None = None
    """For the crew role: whose record this caller is."""

    def __post_init__(self) -> None:
        if self.role is Role.CREW and not self.crew_id:
            raise ValueError("a crew caller needs their crew id")


class Roster(Protocol):
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
    def changes(self, trip_id: str | None = None) -> list[RosterChange]: ...


@dataclass(frozen=True, slots=True)
class Context:
    store: Roster
    caller: Caller
    now: datetime | None = None
    """The operation's clock; ``None`` uses the time the demo data was taken."""

    def operation(self) -> Operation:
        return self.store.operation(self.now)

    def own(self, crew_id: str) -> None:
        """Crew callers may only ask about themselves."""
        if self.caller.role is Role.CREW and crew_id != self.caller.crew_id:
            raise Forbidden("crew members can only look up their own record")

    def on_trip(self, trip: Trip) -> None:
        if self.caller.role is Role.CREW and self.caller.crew_id not in _on_board(trip):
            raise Forbidden("crew members can only look up trips they fly")


class ToolError(Exception):
    """A problem the model should read and recover from, not a crash."""


class Forbidden(ToolError):
    pass


# -- shaping results -------------------------------------------------------------------------


def _on_board(trip: Trip) -> set[str]:
    return {s.crew_id for s in trip.crew}


def _when(moment: datetime) -> str:
    return moment.astimezone(IST).strftime("%Y-%m-%d %H:%M IST")


def _finding(f: Finding) -> dict[str, Any]:
    out: dict[str, Any] = {"rule": f.rule_id, "outcome": str(f.outcome), "detail": f.detail}
    if f.day is not None:
        out["day"] = f.day.isoformat()
    if f.margin is not None:
        out["margin_hours"] = round(f.margin, 2)
    return out


def _choice(c: Choice) -> dict[str, Any]:
    out: dict[str, Any] = {
        "position": c.position,
        "way": c.way.label,
        "summary": c.summary,
        "cost_inr": c.cost,
        "cost_breakdown": c.breakdown,
    }
    for key in ("crew_id", "name", "base", "positioning_leg", "minutes_to_airport", "note"):
        value = getattr(c, key)
        if value is not None:
            out[key] = value
    if c.rank is not None:
        out["rank"] = str(c.rank)
    if c.slip_hours:
        out["departure_late_hours"] = c.slip_hours
    return out


def _trip_summary(op: Operation, trip: Trip) -> dict[str, Any]:
    days = op.days_of(trip.trip_id)
    return {
        "trip_id": trip.trip_id,
        "airline": trip.airline,
        "tail": trip.tail,
        "days": [d.day.isoformat() for d in days],
        "report": _when(days[0].report),
        "release": _when(days[-1].release),
        "route": " ".join(
            [op.legs[trip.days[0].legs[0]].origin]
            + [op.legs[leg].destination for leg in trip.leg_ids]
        ),
        "started": op.started(trip.trip_id),
    }


# -- the tools -------------------------------------------------------------------------------


class SearchCrew(BaseModel):
    query: str = Field(min_length=2, description="Part of a name, or a crew id such as C-1111")
    airline: str | None = Field(None, description="Airline code: SY, KF or GL")
    rank: Rank | None = None
    limit: int = Field(10, ge=1, le=25)


def search_crew(ctx: Context, args: SearchCrew) -> dict[str, Any]:
    op = ctx.operation()
    words = args.query.lower().split()
    found = [
        c
        for c in op.crew.values()
        if (args.airline is None or c.airline == args.airline.upper())
        and (args.rank is None or c.rank is args.rank)
        and (c.crew_id.lower() == args.query.lower() or all(w in c.name.lower() for w in words))
    ]
    found.sort(key=lambda c: c.crew_id)
    return {
        "matches": [
            {
                "crew_id": c.crew_id,
                "name": c.name,
                "rank": str(c.rank),
                "airline": c.airline,
                "base": c.base,
                "status": str(c.status),
            }
            for c in found[: args.limit]
        ],
        "total": len(found),
    }


class FindTrips(BaseModel):
    day: date | None = Field(None, description="Trips flying on this date")
    airline: str | None = Field(None, description="Airline code: SY, KF or GL")
    crew_id: str | None = Field(None, pattern=CREW_ID, description="Trips this person flies")
    flight_no: str | None = Field(None, description="A flight number such as SY101")
    limit: int = Field(20, ge=1, le=50)


def find_trips(ctx: Context, args: FindTrips) -> dict[str, Any]:
    crew_id = args.crew_id
    if ctx.caller.role is Role.CREW:
        crew_id = ctx.caller.crew_id
    op = ctx.operation()
    found = [
        t
        for t in op.trips.values()
        if (args.day is None or any(d.day == args.day for d in t.days))
        and (args.airline is None or t.airline == args.airline.upper())
        and (crew_id is None or crew_id in _on_board(t))
        and (
            args.flight_no is None
            or any(op.legs[leg].flight_no == args.flight_no.upper() for leg in t.leg_ids)
        )
    ]
    found.sort(key=lambda t: (op.days_of(t.trip_id)[0].report, t.trip_id))
    return {
        "trips": [_trip_summary(op, t) for t in found[: args.limit]],
        "total": len(found),
    }


class TripDetails(BaseModel):
    trip_id: str = Field(pattern=TRIP_ID)


def trip_details(ctx: Context, args: TripDetails) -> dict[str, Any]:
    trip, version = ctx.store.trip(args.trip_id)
    ctx.on_trip(trip)
    op = ctx.operation()
    legs = [op.legs[leg] for leg in trip.leg_ids]
    return {
        **_trip_summary(op, trip),
        "version": version,
        "legs": [
            {
                "flight": leg.flight_no,
                "from": leg.origin,
                "to": leg.destination,
                "departs": _when(leg.off_block),
                "arrives": _when(leg.on_block),
                "aircraft": str(leg.aircraft_type),
                "booked": leg.booked,
                "seats": leg.seats,
            }
            for leg in legs
        ],
        "crew": [
            {"crew_id": s.crew_id, "name": op.state(s.crew_id).name, "seat": str(s.rank)}
            for s in trip.crew
        ],
    }


class CrewProfile(BaseModel):
    crew_id: str = Field(pattern=CREW_ID)


def crew_profile(ctx: Context, args: CrewProfile) -> dict[str, Any]:
    ctx.own(args.crew_id)
    op = ctx.operation()
    crew = op.state(args.crew_id)
    today = op.now.date()
    book = op.book
    duty_from, duty_to = window(today, book.duty_days)
    block_from, block_to = window(today, book.block_days)
    return {
        "crew_id": crew.crew_id,
        "name": crew.name,
        "rank": str(crew.rank),
        "airline": crew.airline,
        "base": crew.base,
        "ratings": [str(r) for r in crew.ratings],
        "status": str(crew.status),
        "minutes_to_airport": op.minutes_to_airport.get(crew.crew_id),
        "certificates": [
            {"kind": str(kind), "expires": expires.isoformat(), "days_left": (expires - today).days}
            for kind, expires in crew.certs
        ],
        "duty_hours_last_7_days": round(crew.duty_between(duty_from, duty_to), 2),
        "duty_limit_7_days": book.duty_hours,
        "block_hours_last_28_days": round(crew.block_between(block_from, block_to), 2),
        "block_limit_28_days": book.block_hours,
        "rest_until": _when(crew.rest_until) if crew.rest_until else None,
        "upcoming_duties": [
            {"trip_id": d.trip_id, "day": d.day.isoformat(), "report": _when(d.report)}
            for d in crew.rostered()
            if d.release > op.now
        ][:10],
        "standby_days": sorted(
            {day.isoformat() for s in op.standby.get(crew.crew_id, ()) for day in s.dates}
        ),
    }


class CheckLegality(BaseModel):
    crew_id: str = Field(pattern=CREW_ID)
    trip_id: str = Field(pattern=TRIP_ID)
    delay_hours: float = Field(0, ge=0, le=24, description="Judge with the trip departing late")


def check_legality(ctx: Context, args: CheckLegality) -> dict[str, Any]:
    ctx.own(args.crew_id)
    op = ctx.operation()
    result = assess(op, args.crew_id, args.trip_id, delay_hours=args.delay_hours)
    out: dict[str, Any] = {
        "crew_id": result.crew_id,
        "trip_id": result.trip_id,
        "legal": result.legal,
        "blockers": [_finding(f) for f in result.blockers],
        "findings": [_finding(f) for f in result.findings],
        "on_standby": result.on_standby,
    }
    if result.positioning is not None:
        out["positioning"] = {
            "leg_id": result.positioning.leg_id,
            "from": result.positioning.origin,
            "lands": _when(result.positioning.lands),
        }
    if result.slip_hours:
        out["departure_late_hours"] = result.slip_hours
    return out


class FindCover(BaseModel):
    trip_id: str = Field(pattern=TRIP_ID)
    rank: Rank = Field(description="The seat to fill")
    vacated_by: str | None = Field(None, pattern=CREW_ID, description="Who left the seat")
    explain: list[str] = Field(
        default_factory=list, max_length=5, description="Crew ids to explain the rejection of"
    )
    limit: int = Field(5, ge=1, le=10, description="How many choices to return")


def find_cover_tool(ctx: Context, args: FindCover) -> dict[str, Any]:
    op = ctx.operation()
    try:
        cover = find_cover(op, args.trip_id, args.rank, args.vacated_by)
    except TripStarted as err:
        raise ToolError(str(err)) from err
    choices = list(cover.choices[: args.limit])
    if cover.choices[-1] not in choices:
        choices.append(cover.choices[-1])
    explained = {}
    for crew_id in args.explain:
        excluded = cover.why_not(crew_id)
        explained[crew_id] = (
            {
                "stage": excluded.stage,
                "rules": list(excluded.rule_ids),
                "reasons": list(excluded.reasons),
            }
            if excluded
            else "not excluded: offered as a choice, or not someone who could take this seat"
        )
    return {
        "trip_id": cover.trip_id,
        "seat": str(cover.seat),
        "choices": [_choice(c) for c in choices],
        "more_choices": len(cover.choices) - len(choices),
        "considered": cover.considered,
        "funnel": [
            {"stage": s.stage, "left": s.left, "dropped": s.dropped, "reason": s.reason}
            for s in cover.funnel
        ],
        "facts": cover.facts,
        **({"why_not": explained} if explained else {}),
    }


class AbsenceImpact(BaseModel):
    crew_id: str = Field(pattern=CREW_ID, description="Who is absent")
    first_day: date
    last_day: date


def absence_impact(ctx: Context, args: AbsenceImpact) -> dict[str, Any]:
    if args.last_day < args.first_day:
        raise ToolError("last_day is before first_day")
    if (args.last_day - args.first_day).days > 13:
        raise ToolError("an absence can cover at most 14 days at a time")
    op = ctx.operation()
    gaps = absence_gaps(op, args.crew_id, args.first_day, args.last_day)
    span = (args.last_day - args.first_day).days + 1
    days = [date.fromordinal(args.first_day.toordinal() + i) for i in range(span)]
    plan = joint_cover(with_unavailable(op, args.crew_id, days, "absence"), gaps)
    return {
        "crew_id": args.crew_id,
        "name": op.state(args.crew_id).name,
        "seats_left_empty": [
            {
                "trip_id": g.trip_id,
                "seat": str(g.rank),
                "days": [d.isoformat() for d in g.days],
                "legs": g.legs,
                "passengers": g.passengers,
                "started": g.started,
            }
            for g in gaps
        ],
        "plan": [{"trip_id": f.gap.trip_id, **_choice(f.choice)} for f in plan.fills],
        "already_started": [g.trip_id for g in plan.skipped],
        "total_cost_inr": plan.total_cost,
        "every_combination_compared": plan.searched,
    }


class DelayImpactArgs(BaseModel):
    trip_id: str = Field(pattern=TRIP_ID)
    hours: float = Field(gt=0, le=24, description="How late the trip departs")
    day: date | None = Field(None, description="Which day of a multi-day trip; default the first")


def delay_impact_tool(ctx: Context, args: DelayImpactArgs) -> dict[str, Any]:
    op = ctx.operation()
    impact = delay_impact(op, args.trip_id, args.hours, args.day)
    return {
        "trip_id": impact.trip_id,
        "delay_hours": impact.hours,
        "day": impact.day.isoformat(),
        "crew_over_a_limit": [
            {
                "crew_id": b.crew_id,
                "name": b.name,
                "rank": str(b.rank),
                "rules": list(b.rule_ids),
                "details": list(b.details),
            }
            for b in impact.breaches
        ],
        "crew_still_legal": list(impact.still_legal),
        "passengers": impact.passengers,
        "delay_cost_inr": impact.delay_cost,
    }


class RosterChanges(BaseModel):
    trip_id: str | None = Field(None, pattern=TRIP_ID)
    limit: int = Field(20, ge=1, le=100)


def roster_changes(ctx: Context, args: RosterChanges) -> dict[str, Any]:
    changes = ctx.store.changes(args.trip_id)
    return {
        "changes": [
            {
                "trip_id": c.trip_id,
                "version": c.version,
                "at": _when(c.at),
                "by": c.actor,
                "reason": c.reason,
                "added": list(c.added),
                "removed": list(c.removed),
            }
            for c in changes[-args.limit :]
        ],
        "total": len(changes),
    }


class AssignCrew(BaseModel):
    trip_id: str = Field(pattern=TRIP_ID)
    replace_crew_id: str = Field(pattern=CREW_ID, description="Who leaves the trip")
    with_crew_id: str = Field(pattern=CREW_ID, description="Who takes the seat")
    expected_version: int = Field(ge=1, description="The trip version from trip_details")
    reason: str = Field(min_length=3, max_length=200)


def assign_crew(ctx: Context, args: AssignCrew) -> dict[str, Any]:
    trip, _ = ctx.store.trip(args.trip_id)
    seat = next((s for s in trip.crew if s.crew_id == args.replace_crew_id), None)
    if seat is None:
        raise ToolError(f"{args.replace_crew_id} is not on {args.trip_id}")
    if args.with_crew_id in _on_board(trip):
        raise ToolError(f"{args.with_crew_id} is already on {args.trip_id}")
    op = ctx.operation()
    try:
        cover = find_cover(op, args.trip_id, seat.rank, args.replace_crew_id)
    except TripStarted as err:
        raise ToolError(str(err)) from err
    choice = next((c for c in cover.choices if c.crew_id == args.with_crew_id), None)
    if choice is None:
        excluded = cover.why_not(args.with_crew_id)
        why = "; ".join(excluded.reasons) if excluded else "not someone who can take this seat"
        raise ToolError(f"{args.with_crew_id} is not legal cover for this seat: {why}")
    crew = [
        Seat(crew_id=args.with_crew_id, rank=s.rank) if s.crew_id == args.replace_crew_id else s
        for s in trip.crew
    ]
    try:
        version = ctx.store.change_crew(
            args.trip_id, crew, args.expected_version, ctx.caller.user, args.reason
        )
    except StaleTrip as err:
        raise ToolError(
            f"{err}. Someone changed the trip; call trip_details and decide again."
        ) from err
    return {"trip_id": args.trip_id, "version": version, "assigned": _choice(choice)}


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    run: Callable[[Context, Any], dict[str, Any]]
    roles: frozenset[Role]
    writes: bool = False

    def parameters(self) -> dict[str, Any]:
        return _untitled(self.args.model_json_schema())

    def spec(self) -> dict[str, Any]:
        """The tool in the chat-completions ``tools`` format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters(),
            },
        }


def _untitled(node: Any) -> Any:
    if isinstance(node, list):
        return [_untitled(n) for n in node]
    if isinstance(node, dict):
        return {k: _untitled(v) for k, v in node.items() if k != "title"}
    return node


READERS = frozenset({Role.VIEWER, Role.CONTROLLER})
EVERYONE = frozenset(Role)

TOOLS = (
    Tool(
        "search_crew",
        "Find crew by part of their name or by crew id. Use it to turn a name into a crew id.",
        SearchCrew,
        search_crew,
        READERS,
    ),
    Tool(
        "find_trips",
        "List trips by date, airline, crew member or flight number, earliest first.",
        FindTrips,
        find_trips,
        EVERYONE,
    ),
    Tool(
        "trip_details",
        "One trip: its legs with IST times and bookings, its crew, and its current version.",
        TripDetails,
        trip_details,
        EVERYONE,
    ),
    Tool(
        "crew_profile",
        "One crew member: rank, base, ratings, certificates, recent hours against the limits, "
        "rest and upcoming duties.",
        CrewProfile,
        crew_profile,
        EVERYONE,
    ),
    Tool(
        "check_legality",
        "Judge one crew member on one trip against all nine duty rules, optionally with a "
        "late departure. Returns every rule's verdict and the numbers behind it.",
        CheckLegality,
        check_legality,
        EVERYONE,
    ),
    Tool(
        "find_cover",
        "Legal replacements for an empty seat, cheapest first, ending with cancelling the trip. "
        "Includes how many crew were ruled out at each stage, and why named crew were.",
        FindCover,
        find_cover_tool,
        READERS,
    ),
    Tool(
        "absence_impact",
        "Every seat an absent crew member leaves empty between two dates, and the cheapest legal "
        "way to fill all of them together without using anyone twice.",
        AbsenceImpact,
        absence_impact,
        READERS,
    ),
    Tool(
        "delay_impact",
        "Who on a trip a late departure pushes over a duty limit, and what the delay costs.",
        DelayImpactArgs,
        delay_impact_tool,
        READERS,
    ),
    Tool(
        "roster_changes",
        "Recent changes to the roster: who changed which trip, when and why.",
        RosterChanges,
        roster_changes,
        READERS,
    ),
    Tool(
        "assign_crew",
        "Replace one crew member on a trip. Only succeeds for someone find_cover offers as "
        "legal, and only if the trip is still at expected_version.",
        AssignCrew,
        assign_crew,
        frozenset({Role.CONTROLLER}),
        writes=True,
    ),
)


class ToolBox:
    def __init__(self, tools: tuple[Tool, ...] = TOOLS) -> None:
        self.tools = {t.name: t for t in tools}

    def available(self, caller: Caller) -> list[Tool]:
        return [t for t in self.tools.values() if caller.role in t.roles]

    def specs(self, caller: Caller) -> list[dict[str, Any]]:
        return [t.spec() for t in self.available(caller)]

    def call(self, name: str, arguments: str | dict[str, Any], ctx: Context) -> dict[str, Any]:
        """Run a tool for the model. Problems come back as ``{"error": ...}`` for it to read."""
        tool = self.tools.get(name)
        if tool is None:
            return {"error": f"no tool named {name!r}"}
        if ctx.caller.role not in tool.roles:
            return {"error": f"the {ctx.caller.role} role cannot use {name}"}
        try:
            raw = json.loads(arguments or "{}") if isinstance(arguments, str) else arguments
            args = tool.args.model_validate(raw)
        except json.JSONDecodeError as err:
            return {"error": f"arguments are not valid JSON: {err}"}
        except ValidationError as err:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in err.errors()
            )
            return {"error": f"invalid arguments: {problems}"}
        try:
            return tool.run(ctx, args)
        except NotFound as err:
            return {"error": str(err)}
        except ToolError as err:
            return {"error": str(err)}
