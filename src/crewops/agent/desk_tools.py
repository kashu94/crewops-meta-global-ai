"""Tools for disruption reports, desks, risk, teams and the admins' jobs.

Same rules as ``crewops.agent.tools``: typed arguments, a role check before anything runs,
plain JSON from the engine's own results, and no model asked anything.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from crewops.agent.tools import (
    ADMINS,
    CREW_ID,
    EVERYONE,
    OPS,
    READERS,
    TOOLS,
    TRIP_ID,
    AircraftOut,
    Context,
    DelayImpactArgs,
    Forbidden,
    GateChange,
    GateClosure,
    LateAtGate,
    Role,
    StationClosure,
    Tool,
    ToolError,
    _callout,
    _choice,
    _plan,
    _when,
    aircraft_out_tool,
    delay_impact_tool,
    gate_change,
    gate_closure_tool,
    late_at_gate,
    station_closure_tool,
)
from crewops.engine import NotFound, Operation
from crewops.engine.clock import IST
from crewops.engine.cover import Way
from crewops.engine.impact import absence_gaps, joint_cover
from crewops.engine.risk import crew_risk, risk_json
from crewops.engine.severity import Level, for_trip
from crewops.ops.accounts import AccountError, check_may_manage, current_role
from crewops.ops.alerts import AlertError
from crewops.ops.callout import Status
from crewops.ops.desks import DESKS
from crewops.ops.plans import PlanError, PlanStatus
from crewops.ops.reports import (
    ABSENCES,
    ACTIVE,
    LABELS,
    WORKING,
    Kind,
    Report,
    ReportError,
    ReportStatus,
    summary,
)
from crewops.ops.roster_upload import upload
from crewops.ops.teams import ALERT_GROUPS, TEAMS, Team, contacts
from crewops.settings import ROOT

MAX_ABSENCE_DAYS = 14
OPERATIONAL_FILERS = frozenset({Role.REPORTER, Role.CONTROLLER, Role.APPROVER})
APPROVE_ROLES = frozenset({Role.APPROVER})


def _reports(ctx: Context):
    if ctx.reports is None:
        raise ToolError("disruption reports are not available here")
    return ctx.reports


def _fail(err: Exception) -> ToolError:
    return ToolError(str(err))


# -- filing -----------------------------------------------------------------------------------


class FileReport(BaseModel):
    kind: Kind
    crew_ids: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="Crew out, 1 to 12; several crew out together go in one report",
    )
    first_day: date | None = None
    last_day: date | None = None
    reason_kind: Literal["sick", "fatigue", "personal", "other"] = "sick"
    since: str | None = Field(
        None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="IST time they fell ill"
    )
    leave: Literal["annual_leave", "medical", "training", "personal"] | None = None
    cert: str | None = Field(None, max_length=40, description="Which certificate lapses")
    trip_id: str | None = Field(None, pattern=TRIP_ID)
    hours: float | None = Field(None, gt=0, le=24)
    day: date | None = None
    tail: str | None = Field(None, pattern=r"^VT-[A-Z]{3}$")
    start: datetime | None = None
    end: datetime | None = None
    station: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    gates: list[str] = Field(default_factory=list, max_length=6)
    leg_id: str | None = None
    gate: str | None = Field(None, max_length=8)
    note: str = Field("", max_length=500)

    @model_validator(mode="after")
    def _needs(self) -> FileReport:
        need = {
            Kind.CREW_UNAVAILABLE: ("first_day",),
            Kind.PLANNED_LEAVE: ("first_day", "last_day", "leave"),
            Kind.CERTIFICATION_LAPSE: ("first_day", "cert"),
            Kind.FLIGHT_DELAY: ("trip_id", "hours"),
            Kind.AIRCRAFT_TECHNICAL: ("tail", "start", "end"),
            Kind.STATION_DISRUPTION: ("station", "start", "end"),
            Kind.GATE_CLOSURE: ("station", "gates", "start", "end"),
            Kind.GATE_CHANGE: ("leg_id", "gate"),
        }[self.kind]
        missing = [f for f in need if not getattr(self, f)]
        if missing:
            raise ValueError(f"a {self.kind} report needs {', '.join(missing)}")
        for crew_id in self.crew_ids:
            if not crew_id.startswith("C-") or len(crew_id) != 6:
                raise ValueError(f"{crew_id!r} is not a crew id")
        if len(set(self.crew_ids)) != len(self.crew_ids):
            raise ValueError("a crew member is listed twice")
        return self


def _who_may_file(ctx: Context, args: FileReport) -> list[str]:
    """Check the caller may file this report; returns the crew it is about."""
    role = ctx.caller.role
    if role is Role.CREW:
        if args.kind is not Kind.CREW_UNAVAILABLE:
            raise Forbidden("crew can only report themselves unavailable")
        if args.crew_ids not in ([], [ctx.caller.crew_id]):
            raise Forbidden("crew can only report themselves unavailable")
        return [ctx.caller.crew_id or ""]
    if args.kind is Kind.PLANNED_LEAVE:
        if role not in ADMINS:
            raise Forbidden("planned leave is booked by an admin, the way rostering would")
    elif role not in OPERATIONAL_FILERS:
        raise Forbidden(f"the {role} role cannot file {args.kind} reports")
    if args.kind in ABSENCES:
        if not args.crew_ids:
            raise ToolError("say who is out with crew_ids")
        if args.kind is not Kind.CREW_UNAVAILABLE and len(args.crew_ids) > 1:
            raise ToolError(f"one {LABELS[args.kind].lower()} report per crew member")
    return args.crew_ids


def _span(op: Operation, args: FileReport) -> tuple[date, date]:
    first = args.first_day
    assert first is not None
    end_of_roster = max(leg.day for leg in op.legs.values())
    last = args.last_day or (end_of_roster if args.kind is Kind.CERTIFICATION_LAPSE else first)
    if args.kind is Kind.CERTIFICATION_LAPSE:
        last = min(last, first + timedelta(days=MAX_ABSENCE_DAYS - 1))
    if last < first:
        raise ToolError("last_day is before first_day")
    if (last - first).days >= MAX_ABSENCE_DAYS:
        raise ToolError(f"report at most {MAX_ABSENCE_DAYS} days at a time")
    return first, last


def _names(op: Operation, crew_ids: list[str]) -> str:
    names = [op.state(c).name for c in crew_ids]
    if len(names) <= 2:
        return " and ".join(names)
    return f"{len(names)} crew ({', '.join(names[:3])}{', ...' if len(names) > 3 else ''})"


def _days(first: date, last: date) -> str:
    if first == last:
        return first.strftime("%d %b")
    return f"{first.strftime('%d')}-{last.strftime('%d %b')}"


def _absence_analysis(ctx: Context, report: Report) -> tuple[dict[str, Any], Any, list]:
    """The seats the absent crew leave, and the cheapest way to fill all of them together."""
    op = ctx.operation()
    first = date.fromisoformat(report.details["first_day"])
    last = date.fromisoformat(report.details["last_day"])
    since = report.details.get("since_utc")
    since_at = datetime.fromisoformat(since) if since else None
    gaps = []
    for crew_id in report.crew_ids:
        for gap in absence_gaps(op, crew_id, first, last):
            if since_at is not None and all(d.release <= since_at for d in op.days_of(gap.trip_id)):
                continue  # finished before they fell ill
            gaps.append(gap)
    plan = joint_cover(op, gaps)
    in_hand: dict[tuple[str, str], str] = {}
    if ctx.desk is not None:
        for c in ctx.desk.all():
            if str(c.status) in ("offered", "accepted", "needs_decision", "awaiting_approval"):
                in_hand[(c.trip_id, c.vacated_by)] = c.callout_id
        if ctx.desk.plans is not None:
            for p in ctx.desk.plans.waiting():
                in_hand[(p.trip_id, p.replacing)] = p.plan_id
    reports = ctx.store.unavailability()
    fills = []
    for f in plan.fills:
        row = {
            "trip_id": f.gap.trip_id,
            "rank": str(f.gap.rank),
            "replacing": f.gap.vacated_by,
            **_choice(f.choice),
            "cost": f.choice.cost,
        }
        if f.choice.crew_id:
            row["risk"] = risk_json(crew_risk(op, f.choice.crew_id, reports))
        if (f.gap.trip_id, f.gap.vacated_by) in in_hand:
            row["in_hand"] = in_hand[(f.gap.trip_id, f.gap.vacated_by)]
        fills.append(row)
    seats = [
        {
            "trip_id": g.trip_id,
            "day": g.days[0].isoformat(),
            "days": [d.isoformat() for d in g.days],
            "rank": str(g.rank),
            "replacing": g.vacated_by,
            "name": op.state(g.vacated_by).name,
            "reports_at": _when(op.days_of(g.trip_id)[0].report),
            "passengers": g.passengers,
            "started": g.started,
        }
        for g in gaps
    ]
    return (
        {
            "crew": [
                {"crew_id": c, "name": op.state(c).name, "rank": str(op.state(c).rank)}
                for c in report.crew_ids
            ],
            "seats": seats,
            "plan": {
                "fills": fills,
                "unfilled": [
                    {
                        "trip_id": g.trip_id,
                        "rank": str(g.rank),
                        "replacing": g.vacated_by,
                        "why": "the trip has already reported",
                    }
                    for g in plan.skipped
                ],
                "total_cost": plan.total_cost,
                "every_combination_compared": plan.searched,
            },
            "seats_open": sum(
                1 for g in gaps if not g.started and (g.trip_id, g.vacated_by) not in in_hand
            ),
        },
        plan,
        gaps,
    )


def _ops_analysis(ctx: Context, kind: Kind, d: dict[str, Any]) -> dict[str, Any]:
    """Rerun the engine for an operational report: the same answer as its own tool."""
    match kind:
        case Kind.FLIGHT_DELAY:
            out = delay_impact_tool(
                ctx, DelayImpactArgs(trip_id=d["trip_id"], hours=d["hours"], day=d.get("day"))
            )
            op = ctx.operation()
            day = date.fromisoformat(out["day"])
            first_leg = next(
                (td.legs[0] for td in op.trip(d["trip_id"]).days if td.day == day), None
            )
            if first_leg and op.legs[first_leg].gate:
                minutes = max(1, round(d["hours"] * 60))
                out["gates"] = late_at_gate(ctx, LateAtGate(leg_id=first_leg, minutes=minutes))
            return out
        case Kind.AIRCRAFT_TECHNICAL:
            return aircraft_out_tool(
                ctx, AircraftOut(tail=d["tail"], start=d["start"], back=d["end"])
            )
        case Kind.STATION_DISRUPTION:
            return station_closure_tool(
                ctx, StationClosure(station=d["station"], start=d["start"], end=d["end"])
            )
        case Kind.GATE_CLOSURE:
            return gate_closure_tool(
                ctx,
                GateClosure(station=d["station"], gates=d["gates"], start=d["start"], end=d["end"]),
            )
        case _:
            return gate_change(ctx, GateChange(leg_id=d["leg_id"], gate=d["gate"]))


def crew_over(a: dict[str, Any]) -> int:
    """How many crew an operational analysis pushes over a limit, whatever its shape."""
    over = a.get("crew_over_a_limit")
    count = over if isinstance(over, int) else len(over or [])
    count += sum(len(i.get("crew_over_a_limit", [])) for i in a.get("crew_impact", []))
    if "gates" in a:
        count += crew_over(a["gates"])
    return count


def _ops_severity(ctx: Context, kind: Kind, a: dict[str, Any]) -> tuple[str, list[str]]:
    if kind is Kind.GATE_CHANGE:
        if a.get("free"):
            return "low", [f"gate {a['wanted_gate']} is free for boarding"]
        return "medium", [f"gate {a['wanted_gate']} is held by {', '.join(a.get('held_by', []))}"]
    op = ctx.operation()
    over = crew_over(a)
    trips = [a["trip_id"]] if a.get("trip_id") else [t["trip_id"] for t in a.get("trips", [])]
    trips += [m["trip_id"] for m in a.get("moves", []) if m.get("trip_id")]
    passengers = a.get("passengers") or a.get("passengers_moved") or 0
    soon = False
    for trip_id in set(trips):
        try:
            if for_trip(op, trip_id).level is Level.HIGH:
                soon = True
        except (NotFound, IndexError):
            continue
    reasons = [f"{passengers} passengers affected"]
    if over:
        reasons.insert(0, f"{over} crew pushed over a duty limit")
    if over and soon:
        return "high", reasons + ["a trip reports within hours"]
    if over or passengers >= 300:
        return "medium", reasons
    return "low", reasons


def _absence_severity(op: Operation, plan, gaps) -> tuple[str, list[str]]:
    live = list(plan.fills)
    if not live:
        return "low", ["no rostered duty left to cover in those days"]
    worst = None
    for f in live:
        grade = for_trip(op, f.gap.trip_id, no_crew_left=f.choice.way is Way.CANCEL)
        if worst is None or grade.level.rank < worst.level.rank:
            worst = grade
    assert worst is not None
    return str(worst.level), [
        f"{len(live)} seat{'s' if len(live) != 1 else ''} to fill",
        *worst.reasons,
    ]


def report_disruption(ctx: Context, args: FileReport) -> dict[str, Any]:
    desk = _reports(ctx)
    crew_ids = _who_may_file(ctx, args)
    op = ctx.operation()
    by = ctx.caller.user
    details: dict[str, Any] = {"note": args.note} if args.note else {}
    unavailability: list[str] = []
    stations: list[str] = []

    if args.kind in ABSENCES:
        for crew_id in crew_ids:
            op.state(crew_id)
        first, last = _span(op, args)
        since = None
        if args.since:
            hour, minute = map(int, args.since.split(":"))
            since = datetime.combine(first, time(hour, minute), IST).astimezone(UTC)
        kind, reason = {
            Kind.CREW_UNAVAILABLE: (args.reason_kind, args.note or args.reason_kind),
            Kind.PLANNED_LEAVE: ("leave", (args.leave or "leave").replace("_", " ")),
            Kind.CERTIFICATION_LAPSE: ("certificate", f"{args.cert} lapsed"),
        }[args.kind]
        details |= {
            "crew_ids": crew_ids,
            "first_day": first.isoformat(),
            "last_day": last.isoformat(),
            "reason": reason,
            **({"reason_kind": args.reason_kind} if args.kind is Kind.CREW_UNAVAILABLE else {}),
            **({"leave": args.leave} if args.leave else {}),
            **({"cert": args.cert} if args.cert else {}),
            **({"since": args.since, "since_utc": since.isoformat()} if since else {}),
        }
        recorded = ctx.store.unavailability()
        for crew_id in crew_ids:
            # Already recorded for these days (report_unavailable first): keep that record.
            u = next(
                (
                    u
                    for u in recorded
                    if u.crew_id == crew_id and u.first_day <= first and u.last_day >= last
                ),
                None,
            ) or ctx.store.mark_unavailable(
                crew_id, first, last, reason[:200], by, kind=kind, since=since
            )
            unavailability.append(u.report_id)
            if ctx.desk is not None:
                ctx.desk.withdraw(crew_id)
        stations = [ctx.operation().state(c).base for c in crew_ids]
        word = {
            Kind.CREW_UNAVAILABLE: args.reason_kind.capitalize(),
            Kind.PLANNED_LEAVE: "Leave",
            Kind.CERTIFICATION_LAPSE: f"{args.cert} lapsed",
        }[args.kind]
        title = f"{word}: {_names(op, crew_ids)}, {_days(first, last)}"
        draft = Report(
            report_id="R-000000",
            kind=args.kind,
            title=title,
            details=details,
            filed_by=by,
            filed_role=str(ctx.caller.role),
            filed_at=datetime.now(UTC),
            desk_id="desk-1",
            severity="low",
            severity_reasons=[],
            stations=stations,
            crew_ids=crew_ids,
        )
        _, plan, gaps = _absence_analysis(ctx, draft)
        severity = _absence_severity(ctx.operation(), plan, gaps)
    else:
        raw = args.model_dump(
            mode="json",
            include={
                "trip_id",
                "hours",
                "day",
                "tail",
                "start",
                "end",
                "station",
                "gates",
                "leg_id",
                "gate",
            },
            exclude_none=True,
        )
        if args.kind is Kind.GATE_CLOSURE:
            raw["gates"] = [g.strip().upper() for g in args.gates if g.strip()]
        try:
            analysis = _ops_analysis(ctx, args.kind, raw)
        except (NotFound, ValueError, KeyError) as err:
            raise ToolError(f"cannot analyse this report: {err}") from err
        details |= raw
        severity = _ops_severity(ctx, args.kind, analysis)
        stations, title = _ops_where(op, args, analysis)

    report = desk.file(
        args.kind,
        title,
        details,
        by,
        str(ctx.caller.role),
        severity,
        stations,
        crew_ids=crew_ids,
        unavailability_ids=unavailability,
    )
    return _report_json(ctx, report)


def _ops_where(op: Operation, args: FileReport, a: dict[str, Any]) -> tuple[list[str], str]:
    match args.kind:
        case Kind.FLIGHT_DELAY:
            legs = op.trip(args.trip_id or "").leg_ids
            origin = op.legs[legs[0]].origin
            return [origin], f"{args.trip_id} {args.hours:g} h late"
        case Kind.AIRCRAFT_TECHNICAL:
            held = a.get("flights_held", [])
            stations = sorted({f["route"].split("-")[0] for f in held})
            return stations, f"{args.tail} out of service, {len(held)} flights held"
        case Kind.STATION_DISRUPTION:
            held = a.get("flights_held", [])
            return [args.station or ""], f"{args.station} closed, {len(held)} flights held"
        case Kind.GATE_CLOSURE:
            return [args.station or ""], (
                f"{args.station} gate{'s' if len(args.gates) > 1 else ''} "
                f"{', '.join(args.gates)} closed"
            )
        case _:
            return [a.get("station", "")], f"{a.get('flight')} to gate {a.get('wanted_gate')}"


# -- reading ----------------------------------------------------------------------------------


def _can(ctx: Context, report: Report) -> dict[str, bool]:
    role, user = ctx.caller.role, ctx.caller.user
    owner = next(d for d in DESKS if d.desk_id == report.desk_id)
    working = report.status in WORKING
    mine = role is Role.CONTROLLER and owner.controller == user
    return {
        "plan": mine and working,
        "close": mine and working,
        "confirm": role in APPROVE_ROLES and report.status is ReportStatus.RESOLVED,
        "return": role in APPROVE_ROLES and report.status is ReportStatus.RESOLVED,
        "revoke": role in ADMINS
        and report.status not in (ReportStatus.CLOSED, ReportStatus.REVOKED),
        "reassign": role in APPROVE_ROLES | ADMINS and report.status in ACTIVE,
    }


def _report_json(ctx: Context, report: Report) -> dict[str, Any]:
    desk = _reports(ctx)
    out = summary(report)
    out["filed_at"] = _when(report.filed_at)
    out["details"] = report.details
    if report.status is ReportStatus.REVOKED:
        out["analysis"] = {"note": "revoked: filed in error"}
        out["summary"] = "Revoked; its absences were withdrawn."
    elif report.kind in ABSENCES:
        analysis, _, _ = _absence_analysis(ctx, report)
        out["analysis"] = analysis
        out["seats_open"] = analysis["seats_open"]
        out["summary"] = (
            f"{len(analysis['seats'])} seat{'s' if len(analysis['seats']) != 1 else ''} left "
            f"empty; {analysis['seats_open']} still to fill. The cheapest way to fill them "
            f"together costs INR {analysis['plan']['total_cost']:,}."
        )
    else:
        try:
            out["analysis"] = _ops_analysis(ctx, report.kind, report.details)
        except (NotFound, ValueError, ToolError) as err:
            out["analysis"] = {"note": f"cannot analyse it any more: {err}"}
        over = crew_over(out["analysis"])
        out["summary"] = (
            f"{over} crew pushed over a duty limit." if over else "No crew over a limit."
        )
    out["teams"] = desk.teams(report)
    plans = []
    if ctx.desk is not None and ctx.desk.plans is not None:
        for plan_id in report.plan_ids:
            try:
                plans.append(_plan(ctx.desk.plans.get(plan_id)))
            except NotFound:
                continue
    out["plans"] = plans
    callouts = []
    if ctx.desk is not None:
        for callout_id in report.callout_ids:
            try:
                callouts.append(_callout(ctx.desk.get(callout_id)))
            except (NotFound, Exception):
                continue
    out["callouts"] = callouts
    out["plans_waiting"] = sum(p["status"] == "submitted" for p in plans)
    out["history"] = [{**h, "at": _when(datetime.fromisoformat(h["at"]))} for h in report.history]
    out["resolution_note"] = report.resolution_note
    out["can"] = _can(ctx, report)
    return out


class Disruptions(BaseModel):
    status: str = Field(
        "active", description="active (open, in progress or resolved), all, or one status"
    )
    desk_id: str | None = Field(None, pattern=r"^desk-\d$")
    limit: int = Field(30, ge=1, le=100)


def disruptions(ctx: Context, args: Disruptions) -> dict[str, Any]:
    found = _reports(ctx).all()
    counts = {str(s): sum(r.status is s for r in found) for s in ReportStatus}
    if args.status == "active":
        found = [r for r in found if r.status in ACTIVE]
    elif args.status != "all":
        found = [r for r in found if str(r.status) == args.status]
    if args.desk_id:
        found = [r for r in found if r.desk_id == args.desk_id]
    order = {"high": 0, "medium": 1, "low": 2}
    found.sort(key=lambda r: (r.status not in WORKING, order.get(r.severity, 3)))
    return {
        "disruptions": [_listed(ctx, r) for r in found[: args.limit]],
        "counts": counts,
    }


def _listed(ctx: Context, report: Report) -> dict[str, Any]:
    out = summary(report)
    out["filed_at"] = _when(report.filed_at)
    out["plans_waiting"] = 0
    if ctx.desk is not None and ctx.desk.plans is not None:
        waiting = {p.plan_id for p in ctx.desk.plans.waiting()}
        out["plans_waiting"] = sum(p in waiting for p in report.plan_ids)
    return out


class MyReports(BaseModel):
    active_only: bool = Field(False, description="Only reports not yet closed or revoked")


def my_reports(ctx: Context, args: MyReports) -> dict[str, Any]:
    crew_id = ctx.caller.crew_id if ctx.caller.role is Role.CREW else None
    mine = [
        r
        for r in _reports(ctx).all()
        if r.filed_by == ctx.caller.user or (crew_id is not None and crew_id in r.crew_ids)
    ]
    if args.active_only:
        mine = [r for r in mine if r.status in ACTIVE]
    return {"disruptions": [_listed(ctx, r) for r in mine]}


class ReportId(BaseModel):
    report_id: str = Field(pattern=r"^R-[0-9a-f]{6}$")


def show_disruption(ctx: Context, args: ReportId) -> dict[str, Any]:
    report = _get(ctx, args.report_id)
    about_me = ctx.caller.role is Role.CREW and ctx.caller.crew_id in report.crew_ids
    if ctx.caller.role not in READERS and report.filed_by != ctx.caller.user and not about_me:
        raise Forbidden("you can see the reports you filed or that are about you, not others")
    return _report_json(ctx, report)


def _get(ctx: Context, report_id: str) -> Report:
    return _reports(ctx).get(report_id)


# -- working a report -------------------------------------------------------------------------


class SubmitReportPlan(BaseModel):
    report_id: str = Field(pattern=r"^R-[0-9a-f]{6}$")
    note: str = Field("", max_length=300)


def submit_report_plan(ctx: Context, args: SubmitReportPlan) -> dict[str, Any]:
    """Submit the joint plan: one plan per seat the cheapest combination fills with crew."""
    desk = _reports(ctx)
    try:
        report = desk.check_mine(args.report_id, ctx.caller.user)
    except ReportError as err:
        raise _fail(err) from err
    if report.kind not in ABSENCES:
        raise ToolError("only reports that leave seats empty have a crew plan to submit")
    plans = ctx.plans()
    analysis, joint, _ = _absence_analysis(ctx, report)
    submitted, skipped = [], []
    for fill, row in zip(joint.fills, analysis["plan"]["fills"], strict=True):
        seat = f"{fill.gap.rank} on {fill.gap.trip_id}"
        if "in_hand" in row:
            skipped.append({"seat": seat, "why": f"already in hand ({row['in_hand']})"})
            continue
        if not fill.choice.crew_id:
            skipped.append(
                {
                    "seat": seat,
                    "why": f"{fill.choice.summary}: needs a callout and an approver's decision",
                }
            )
            continue
        try:
            plan = plans.submit(
                fill.gap.trip_id,
                fill.gap.vacated_by,
                fill.choice.crew_id,
                ctx.caller.user,
                args.note or f"{report.report_id}: {report.title}",
                source=report.report_id,
            )
        except PlanError as err:
            skipped.append({"seat": seat, "why": str(err)})
            continue
        desk.link(report.report_id, ctx.caller.user, plan_id=plan.plan_id)
        submitted.append(_plan(plan))
    return {
        "report": _report_json(ctx, desk.get(report.report_id)),
        "plans": submitted,
        "skipped": skipped,
    }


class CloseReport(BaseModel):
    report_id: str = Field(pattern=r"^R-[0-9a-f]{6}$")
    note: str = Field(min_length=3, max_length=500, description="How it was resolved")


def close_disruption(ctx: Context, args: CloseReport) -> dict[str, Any]:
    try:
        report = _reports(ctx).close(args.report_id, ctx.caller.user, args.note)
    except ReportError as err:
        raise _fail(err) from err
    return _report_json(ctx, report)


def confirm_resolution(ctx: Context, args: ReportId) -> dict[str, Any]:
    try:
        report = _reports(ctx).confirm(args.report_id, ctx.caller.user)
    except ReportError as err:
        raise _fail(err) from err
    return _report_json(ctx, report)


def return_resolution(ctx: Context, args: CloseReport) -> dict[str, Any]:
    try:
        report = _reports(ctx).give_back(args.report_id, ctx.caller.user, args.note)
    except ReportError as err:
        raise _fail(err) from err
    return _report_json(ctx, report)


class Reassign(BaseModel):
    report_id: str = Field(pattern=r"^R-[0-9a-f]{6}$")
    desk_id: str = Field(pattern=r"^desk-\d$")
    note: str = Field("", max_length=300)


def reassign_disruption(ctx: Context, args: Reassign) -> dict[str, Any]:
    try:
        report = _reports(ctx).reassign(args.report_id, args.desk_id, ctx.caller.user, args.note)
    except ReportError as err:
        raise _fail(err) from err
    return _report_json(ctx, report)


class Revoke(BaseModel):
    report_id: str = Field(pattern=r"^R-[0-9a-f]{6}$")
    reason: str = Field(min_length=3, max_length=300)


def revoke_report(ctx: Context, args: Revoke) -> dict[str, Any]:
    desk = _reports(ctx)
    try:
        report = desk.revoke(args.report_id, ctx.caller.user, args.reason)
    except ReportError as err:
        raise _fail(err) from err
    for report_id in report.unavailability_ids:
        try:
            ctx.store.clear_unavailable(report_id)
        except NotFound:
            continue  # already withdrawn
    return _report_json(ctx, report)


class DeskLoad(BaseModel):
    desk_id: str | None = Field(None, pattern=r"^desk-\d$", description="Only this desk")


def desk_load(ctx: Context, args: DeskLoad) -> dict[str, Any]:
    return {
        "desks": [d for d in _reports(ctx).load() if args.desk_id in (None, d["desk_id"])],
        "rule": "a new disruption goes to the desk with the fewest open ones, then the fewest "
        "overall",
    }


# -- risk, teams, the queue -------------------------------------------------------------------


class CrewRisk(BaseModel):
    crew_id: str | None = Field(None, pattern=CREW_ID)
    limit: int = Field(10, ge=1, le=50)


def crew_risk_tool(ctx: Context, args: CrewRisk) -> dict[str, Any]:
    op = ctx.operation()
    reports = ctx.store.unavailability()
    if ctx.caller.role is Role.CREW:
        args = CrewRisk(crew_id=ctx.caller.crew_id, limit=1)
    ids = [args.crew_id] if args.crew_id else list(op.crew)
    rows = []
    for crew_id in ids:
        crew = op.state(crew_id)
        risk = crew_risk(op, crew_id, reports)
        rows.append(
            {
                "crew_id": crew_id,
                "name": crew.name,
                "rank": str(crew.rank),
                "airline": crew.airline,
                **risk_json(risk),
            }
        )
    rows.sort(key=lambda r: -r["score"])
    return {
        "crew": rows[: args.limit],
        "note": "Shown for judgement, never used to rank cover or rule anyone out.",
    }


class Contacts(BaseModel):
    station: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    team: Team | None = None


def contacts_tool(ctx: Context, args: Contacts) -> dict[str, Any]:
    seed = ctx.reports.seed_dir if ctx.reports is not None else ROOT / "data" / "seed"
    everyone = contacts(seed)
    teams = []
    for team, info in TEAMS.items():
        if args.team is not None and team is not args.team:
            continue
        rows = [
            {"station": c.station, "name": c.name, "phone": c.phone}
            for c in everyone
            if c.team is team and (args.station is None or c.station in (args.station, "NETWORK"))
        ]
        teams.append(
            {
                "team": str(team),
                "title": info.title,
                "job": info.job,
                "per_station": info.per_station,
                "contacts": rows,
            }
        )
    return {"teams": teams}


class MyQueue(BaseModel):
    limit: int = Field(20, ge=1, le=50)


def my_queue(ctx: Context, args: MyQueue) -> dict[str, Any]:
    """What is waiting for the caller, most urgent first."""
    role, user = ctx.caller.role, ctx.caller.user
    items: list[dict[str, Any]] = []

    def add(kind: str, ref: str, title: str, detail: str, link: str, tone: str) -> None:
        items.append(
            {"kind": kind, "ref": ref, "title": title, "detail": detail, "link": link, "tone": tone}
        )

    reports = ctx.reports.all() if ctx.reports is not None else []
    callouts = ctx.desk.all() if ctx.desk is not None else []
    plans = ctx.desk.plans.all() if ctx.desk is not None and ctx.desk.plans else []
    view = "/disruptions/view/?id="
    if role is Role.CREW:
        for c in ctx.desk.offers_for(ctx.caller.crew_id or "") if ctx.desk else []:
            add(
                "offer",
                c.callout_id,
                f"Callout offer: {c.rank} on {c.trip_id}",
                f"answer by {_when(c.current.expires_at)}" if c.current else "",
                "/crew/",
                "critical",
            )
    if role is Role.CONTROLLER:
        mine = next((d.desk_id for d in DESKS if d.controller == user), None)
        for r in reports:
            if r.desk_id == mine and r.status in WORKING:
                add(
                    "disruption",
                    r.report_id,
                    r.title,
                    f"{r.status}, severity {r.severity}",
                    view + r.report_id,
                    "critical" if r.severity == "high" else "pending",
                )
        for c in callouts:
            if c.opened_by == user and c.status is Status.NEEDS_DECISION:
                add(
                    "callout",
                    c.callout_id,
                    f"Nobody accepted {c.rank} on {c.trip_id}",
                    "propose cancelling or flying one short",
                    "/desk/",
                    "critical",
                )
        for p in plans:
            if p.submitted_by == user and p.status is PlanStatus.SENT_BACK:
                add(
                    "plan",
                    p.plan_id,
                    f"Sent back: {p.rank} on {p.trip_id}",
                    p.decision_note,
                    "/approvals/",
                    "pending",
                )
    if role in (Role.APPROVER, Role.AUDITOR, Role.SPEAKER, Role.ADMIN, Role.SUPER_ADMIN):
        for p in plans:
            if p.status is PlanStatus.SUBMITTED:
                add(
                    "plan",
                    p.plan_id,
                    f"Approve: {p.summary} on {p.trip_id}",
                    f"by {p.submitted_by}, INR {p.cost:,}",
                    "/approvals/",
                    "pending",
                )
        for c in callouts:
            if c.status is Status.AWAITING_APPROVAL and c.proposal is not None:
                add(
                    "callout",
                    c.callout_id,
                    f"Decide: {c.proposal.summary}",
                    f"proposed by {c.proposal.proposed_by}",
                    "/approvals/",
                    "critical",
                )
        for r in reports:
            if r.status is ReportStatus.RESOLVED:
                add(
                    "disruption",
                    r.report_id,
                    f"Confirm resolution: {r.title}",
                    r.resolution_note,
                    view + r.report_id,
                    "pending",
                )
        if role is not Role.APPROVER:
            for r in reports:
                if r.status in WORKING and r.severity == "high":
                    add(
                        "disruption",
                        r.report_id,
                        r.title,
                        f"{r.status} on {r.desk_id}",
                        view + r.report_id,
                        "critical",
                    )
    if role is Role.REPORTER:
        for r in reports:
            if r.filed_by == user and r.status in ACTIVE:
                add("disruption", r.report_id, r.title, str(r.status), view + r.report_id, "info")
    order = {"critical": 0, "pending": 1, "info": 2}
    items.sort(key=lambda i: order[i["tone"]])
    return {"items": items[: args.limit], "count": len(items)}


# -- accounts, alerts, roster ----------------------------------------------------------------


def _accounts(ctx: Context):
    if ctx.accounts is None:
        raise ToolError("team accounts are not available here")
    return ctx.accounts


class TeamAccounts(BaseModel):
    role: Role | None = Field(None, description="Only accounts with this role")


def team_accounts(ctx: Context, args: TeamAccounts) -> dict[str, Any]:
    return {
        "accounts": [
            {
                "username": a.username,
                "role": a.role,
                "crew_id": a.crew_id,
                "enabled": a.enabled,
                "status": a.status,
                "created": a.created,
            }
            for a in _accounts(ctx).list()
            if args.role is None or a.role == str(args.role)
        ]
    }


class CreateAccount(BaseModel):
    username: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,31}$")
    role: Role
    crew_id: str | None = Field(None, pattern=CREW_ID)
    email: str | None = Field(None, max_length=200)


def create_account(ctx: Context, args: CreateAccount) -> dict[str, Any]:
    accounts = _accounts(ctx)
    try:
        check_may_manage(ctx.caller.role, ctx.caller.user, args.username, args.role, None)
        if args.role is Role.CREW:
            if not args.crew_id:
                raise AccountError("a crew account needs the crew id it belongs to")
            ctx.operation().state(args.crew_id)
        password = accounts.create(args.username, args.role, args.crew_id, args.email)
    except (AccountError, NotFound) as err:
        raise _fail(err) from err
    return {
        "username": args.username,
        "role": str(args.role),
        "temporary_password": password,
        "note": "Shown once. They choose their own password when they first sign in.",
    }


class SetAccount(BaseModel):
    username: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,31}$")
    role: Role | None = None
    enabled: bool | None = None


def set_account(ctx: Context, args: SetAccount) -> dict[str, Any]:
    accounts = _accounts(ctx)
    try:
        current = current_role(accounts, args.username)
        if current is None:
            raise AccountError(f"no account {args.username}")
        check_may_manage(ctx.caller.role, ctx.caller.user, args.username, args.role, current)
        if args.role is not None:
            accounts.set_role(args.username, args.role)
        if args.enabled is not None:
            accounts.set_enabled(args.username, args.enabled)
    except AccountError as err:
        raise _fail(err) from err
    found = next(a for a in accounts.list() if a.username == args.username)
    return {
        "username": found.username,
        "role": found.role,
        "enabled": found.enabled,
        "status": found.status,
    }


class Username(BaseModel):
    username: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,31}$")


def reset_password(ctx: Context, args: Username) -> dict[str, Any]:
    accounts = _accounts(ctx)
    try:
        current = current_role(accounts, args.username)
        if current is None:
            raise AccountError(f"no account {args.username}")
        check_may_manage(ctx.caller.role, ctx.caller.user, args.username, None, current)
        password = accounts.reset_password(args.username)
    except AccountError as err:
        raise _fail(err) from err
    return {
        "username": args.username,
        "temporary_password": password,
        "note": "Shown once. They must choose a new password when they next sign in.",
    }


def _alerts(ctx: Context):
    if ctx.alerts is None:
        raise ToolError("alert addresses are not available here")
    return ctx.alerts


class AlertList(BaseModel):
    team: str | None = Field(None, description="Only this group, such as desk or gate_control")


def alert_addresses(ctx: Context, args: AlertList) -> dict[str, Any]:
    return {
        "addresses": [a for a in _alerts(ctx).list() if args.team in (None, a["team"])],
        "teams": [{"team": k, "title": v} for k, v in ALERT_GROUPS.items()],
    }


class AlertAddress(BaseModel):
    address: str = Field(min_length=5, max_length=254)
    team: str = Field(description="desk, supervisor, or a team such as gate_control")


def add_alert_address(ctx: Context, args: AlertAddress) -> dict[str, Any]:
    try:
        return _alerts(ctx).add(args.address, args.team, ctx.caller.user)
    except AlertError as err:
        raise _fail(err) from err


def remove_alert_address(ctx: Context, args: AlertAddress) -> dict[str, Any]:
    try:
        _alerts(ctx).remove(args.address, args.team)
    except AlertError as err:
        raise _fail(err) from err
    return {"removed": True, "address": args.address, "team": args.team}


class UploadRoster(BaseModel):
    content: dict[str, Any] = Field(
        description="Collections in the demo data's shapes: crew, certificates, standby, trips"
    )
    dry_run: bool = True


def upload_roster(ctx: Context, args: UploadRoster) -> dict[str, Any]:
    return upload(ctx.store, args.content, ctx.caller.user, args.dry_run, ctx.now)


DESK_ROLES = READERS
MORE_TOOLS = (
    Tool(
        "report_disruption",
        "File a disruption report: one or several crew out (sick, fatigue...), planned leave, a "
        "certificate lapse, a flight delay, an aircraft fault, a station closed, gates closed or "
        "a gate change. It goes to the least busy desk, the right teams are told, and the "
        "engine's analysis comes back with it.",
        FileReport,
        report_disruption,
        OPERATIONAL_FILERS | ADMINS | {Role.CREW},
        writes=True,
    ),
    Tool(
        "disruptions",
        "Disruption reports by state and desk, the busiest first, with counts per state.",
        Disruptions,
        disruptions,
        DESK_ROLES,
    ),
    Tool(
        "my_reports",
        "The disruption reports the caller filed, or for crew that are about them, and where "
        "each one stands.",
        MyReports,
        my_reports,
        EVERYONE,
    ),
    Tool(
        "show_disruption",
        "One disruption report: its desk, severity, the engine's analysis (seats to fill and "
        "the cheapest way to fill them together, or the delays), teams to tell, plans, "
        "callouts and history.",
        ReportId,
        show_disruption,
        EVERYONE,
    ),
    Tool(
        "submit_report_plan",
        "Submit the cheapest joint cover for a report as plans, one per seat, for an approver. "
        "Only the report's desk controller.",
        SubmitReportPlan,
        submit_report_plan,
        frozenset({Role.CONTROLLER}),
        writes=True,
    ),
    Tool(
        "close_disruption",
        "Mark a report resolved, saying how; an approver then confirms it or returns it.",
        CloseReport,
        close_disruption,
        frozenset({Role.CONTROLLER}),
        writes=True,
    ),
    Tool(
        "confirm_resolution",
        "Confirm a controller's resolution and close the report (approvers).",
        ReportId,
        confirm_resolution,
        APPROVE_ROLES,
        writes=True,
    ),
    Tool(
        "return_resolution",
        "Return a resolved report to its desk with what is still missing (approvers).",
        CloseReport,
        return_resolution,
        APPROVE_ROLES,
        writes=True,
    ),
    Tool(
        "reassign_disruption",
        "Move a report to another desk.",
        Reassign,
        reassign_disruption,
        APPROVE_ROLES | ADMINS,
        writes=True,
    ),
    Tool(
        "revoke_report",
        "Revoke a report filed in error; any absences it recorded are withdrawn (admins).",
        Revoke,
        revoke_report,
        ADMINS,
        writes=True,
    ),
    Tool(
        "desk_load",
        "Each controller desk's disruptions by state, and how new ones are assigned.",
        DeskLoad,
        desk_load,
        DESK_ROLES,
    ),
    Tool(
        "crew_risk",
        "Crew most at risk of dropping out of the roster, with what drives each score "
        "(fatigue, hours near a limit, absences, certificates, distance). Never ranks cover.",
        CrewRisk,
        crew_risk_tool,
        DESK_ROLES | {Role.CREW},
    ),
    Tool(
        "contacts",
        "The operational teams (gate control, station duty managers, maintenance control...), "
        "their jobs and who is on duty, per station or for the network.",
        Contacts,
        contacts_tool,
        OPS,
    ),
    Tool(
        "my_queue",
        "What is waiting for the caller now: offers, plans to approve, disruptions to work, "
        "resolutions to confirm.",
        MyQueue,
        my_queue,
        frozenset(Role),
    ),
    Tool(
        "team_accounts",
        "Every account that can sign in, with its role and status (admins).",
        TeamAccounts,
        team_accounts,
        ADMINS,
    ),
    Tool(
        "create_account",
        "Add an account with a role; returns a temporary password, shown once. Only a super "
        "admin creates admins.",
        CreateAccount,
        create_account,
        ADMINS,
        writes=True,
    ),
    Tool(
        "set_account",
        "Change an account's role or switch it on or off. Only a super admin changes admins.",
        SetAccount,
        set_account,
        ADMINS,
        writes=True,
    ),
    Tool(
        "reset_password",
        "Reset someone's password to a temporary one they must change at sign-in (admins).",
        Username,
        reset_password,
        ADMINS,
        writes=True,
    ),
    Tool(
        "alert_addresses",
        "Email addresses subscribed to alerts, per group: the desk, the supervisor and each "
        "team (admins).",
        AlertList,
        alert_addresses,
        ADMINS,
    ),
    Tool(
        "add_alert_address",
        "Subscribe an email address to one group's alerts (admins). The owner confirms by email.",
        AlertAddress,
        add_alert_address,
        ADMINS,
        writes=True,
    ),
    Tool(
        "remove_alert_address",
        "Stop an email address hearing one group's alerts (admins).",
        AlertAddress,
        remove_alert_address,
        ADMINS,
        writes=True,
    ),
    Tool(
        "upload_roster",
        "Upload roster records (crew, certificates, standby, trips). Checks the whole merged "
        "roster first and lists every rule problem it would add; dry_run to only check.",
        UploadRoster,
        upload_roster,
        ADMINS,
        writes=True,
    ),
)

ALL_TOOLS = TOOLS + MORE_TOOLS
