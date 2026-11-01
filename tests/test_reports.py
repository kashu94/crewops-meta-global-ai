import pytest
from conftest import SEED_DIR

from crewops.agent import Caller, Context, Role, ToolBox
from crewops.ops import DESK, CalloutDesk, MemoryOutbox
from crewops.ops.reports import ReportDesk
from crewops.seed import read_meta
from crewops.store import MemoryStore

TRIP = "T-1018"  # flies 5-6 Nov
CAPTAIN, FIRST_OFFICER, CABIN = "C-1111", "C-1191", "C-1460"
IYER = Caller("m.iyer", Role.CONTROLLER)
REDDY = Caller("s.reddy", Role.CONTROLLER)
RAO = Caller("d.rao", Role.CONTROLLER)
NAIR = Caller("a.nair", Role.APPROVER)
STATION = Caller("ops.hyd", Role.REPORTER)
MENON = Caller("k.menon", Role.ADMIN)
ANJALI = Caller("anjali", Role.CREW, "C-1157")


@pytest.fixture
def mem(seed):
    store = MemoryStore()
    store.load(seed, read_meta(SEED_DIR))
    return store


@pytest.fixture
def outbox():
    return MemoryOutbox()


@pytest.fixture
def ctx(mem, outbox):
    desk = CalloutDesk(mem, outbox, docs=mem, four_eyes=True)
    reports = ReportDesk(mem, outbox, SEED_DIR)
    return lambda caller: Context(mem, caller, desk=desk, reports=reports)


@pytest.fixture
def box():
    return ToolBox()


def sick(*crew_ids, **more):
    return {
        "kind": "crew_unavailable",
        "crew_ids": list(crew_ids),
        "first_day": "2026-11-05",
        "last_day": "2026-11-06",
        "reason_kind": "sick",
        **more,
    }


def test_several_sick_crew_in_one_report_are_covered_together(box, ctx, mem, outbox):
    report = box.call("report_disruption", sick(CAPTAIN, FIRST_OFFICER, CABIN), ctx(STATION))
    assert report["status"] == "open" and report["crew_ids"] == [CAPTAIN, FIRST_OFFICER, CABIN]
    assert report["title"].startswith("Sick: 3 crew")
    # Every one of them is now off the roster for those days.
    assert {u.crew_id for u in mem.unavailability()} == {CAPTAIN, FIRST_OFFICER, CABIN}

    analysis = report["analysis"]
    seats = {(s["trip_id"], s["replacing"]) for s in analysis["seats"]}
    assert {(TRIP, CAPTAIN), (TRIP, FIRST_OFFICER), (TRIP, CABIN)} <= seats
    fills = [f for f in analysis["plan"]["fills"] if f.get("crew_id")]
    used = [f["crew_id"] for f in fills]
    assert len(used) == len(set(used)), "nobody is used for two seats"
    assert not {CAPTAIN, FIRST_OFFICER, CABIN} & set(used), "nobody covers for another"
    assert all("risk" in f for f in fills)
    assert analysis["plan"]["total_cost"] == sum(f["cost"] for f in analysis["plan"]["fills"])

    assert report["severity"]["level"] in ("high", "medium", "low")
    assert [t["team"] for t in report["teams"]] == ["station_ops"]
    assert report["teams"][0]["contact"]["name"]
    assert any(n.subject.startswith("New disruption") for n in outbox.sent(DESK))
    assert outbox.sent("team:station_ops")


def test_new_reports_go_to_the_least_busy_desk(box, ctx):
    desks = [
        box.call("report_disruption", sick(crew), ctx(STATION))["desk"]["desk_id"]
        for crew in (CAPTAIN, FIRST_OFFICER, CABIN)
    ]
    assert desks == ["desk-1", "desk-2", "desk-3"]
    load = box.call("desk_load", {}, ctx(NAIR))["desks"]
    assert [d["open"] for d in load] == [1, 1, 1]


def test_a_report_runs_from_plan_to_sign_off(box, ctx, mem):
    report = box.call("report_disruption", sick(CAPTAIN), ctx(STATION))
    rid = report["report_id"]
    assert report["desk"]["controller"] == "m.iyer"
    assert box.call("show_disruption", {"report_id": rid}, ctx(IYER))["can"]["plan"]

    # Only the owning desk works it.
    other = box.call("submit_report_plan", {"report_id": rid}, ctx(REDDY))
    assert "only its controller" in other["error"]

    done = box.call("submit_report_plan", {"report_id": rid}, ctx(IYER))
    assert done["report"]["status"] == "in_progress"
    assert all(p["report_id"] == rid for p in done["plans"])
    assert [p["status"] for p in done["plans"]] and all(
        p["status"] == "submitted" for p in done["plans"]
    )
    # Seats with a plan are in hand: submitting again adds nothing.
    again = box.call("submit_report_plan", {"report_id": rid}, ctx(IYER))
    assert again["plans"] == [] and all("in hand" in s["why"] for s in again["skipped"])

    for plan in done["plans"]:
        review = {"plan_id": plan["plan_id"], "action": "approve"}
        assert box.call("review_plan", review, ctx(NAIR))["status"] == "approved"
    after = box.call("show_disruption", {"report_id": rid}, ctx(IYER))
    assert after["seats_open"] == 0

    closed = box.call("close_disruption", {"report_id": rid, "note": "covered"}, ctx(IYER))
    assert closed["status"] == "resolved" and closed["can"]["close"] is False
    assert "error" in box.call("confirm_resolution", {"report_id": rid}, ctx(IYER))
    back = {"report_id": rid, "note": "add the hotel booking"}
    assert box.call("return_resolution", back, ctx(NAIR))["status"] == "in_progress"
    box.call("close_disruption", {"report_id": rid, "note": "hotel booked"}, ctx(IYER))
    final = box.call("confirm_resolution", {"report_id": rid}, ctx(NAIR))
    assert final["status"] == "closed"
    assert [h["what"] for h in final["history"]] == [
        "reported",
        "assigned",
        "plan submitted",
        "resolved",
        "returned",
        "resolved",
        "closed",
    ]


def test_who_may_file_what(box, ctx, mem):
    mine = box.call("report_disruption", sick(), ctx(ANJALI))
    assert mine["crew_ids"] == ["C-1157"]
    someone = box.call("report_disruption", sick(CAPTAIN), ctx(ANJALI))
    assert "only report themselves" in someone["error"]
    delay = {"kind": "flight_delay", "trip_id": TRIP, "hours": 2}
    assert "only report themselves" in box.call("report_disruption", delay, ctx(ANJALI))["error"]
    leave = {
        "kind": "planned_leave",
        "crew_ids": [CABIN],
        "first_day": "2026-11-07",
        "last_day": "2026-11-09",
        "leave": "annual_leave",
    }
    assert "booked by an admin" in box.call("report_disruption", leave, ctx(STATION))["error"]
    booked = box.call("report_disruption", leave, ctx(MENON))
    assert booked["teams"][0]["team"] == "crew_records"
    # Crew see their own report, and only theirs.
    assert box.call("show_disruption", {"report_id": mine["report_id"]}, ctx(ANJALI))["title"]
    theirs = box.call("show_disruption", {"report_id": booked["report_id"]}, ctx(ANJALI))
    assert "reports you filed" in theirs["error"]
    # A report about her, filed by the station, is hers to see too.
    about = box.call("report_disruption", sick("C-1157", CAPTAIN), ctx(STATION))
    assert box.call("show_disruption", {"report_id": about["report_id"]}, ctx(ANJALI))["title"]
    ids = [r["report_id"] for r in box.call("my_reports", {}, ctx(ANJALI))["disruptions"]]
    assert about["report_id"] in ids and mine["report_id"] in ids


def test_operational_reports_carry_the_engines_analysis(box, ctx):
    delay = box.call(
        "report_disruption", {"kind": "flight_delay", "trip_id": TRIP, "hours": 3}, ctx(STATION)
    )
    assert delay["analysis"]["delay_hours"] == 3 and "crew_over_a_limit" in delay["analysis"]
    assert {t["team"] for t in delay["teams"]} >= {"customer_care", "flight_info"}

    gates = {
        "kind": "gate_closure",
        "station": "HYD",
        "gates": ["21", "22"],
        "start": "2026-10-30T05:00",
        "end": "2026-10-30T10:00",
    }
    closed = box.call("report_disruption", gates, ctx(STATION))
    assert closed["analysis"]["moves"] and closed["title"] == "HYD gates 21, 22 closed"
    assert {t["team"] for t in closed["teams"]} == {"gate_control", "station_ops", "flight_info"}

    bad = box.call("report_disruption", {"kind": "flight_delay", "hours": 3}, ctx(STATION))
    assert "needs trip_id" in bad["error"]


def test_an_admin_revokes_a_report_filed_in_error(box, ctx, mem):
    report = box.call("report_disruption", sick(CAPTAIN, FIRST_OFFICER), ctx(STATION))
    assert len(mem.unavailability()) == 2
    refused = box.call(
        "revoke_report", {"report_id": report["report_id"], "reason": "x"}, ctx(IYER)
    )
    assert "cannot use" in refused["error"]
    done = box.call(
        "revoke_report", {"report_id": report["report_id"], "reason": "wrong crew"}, ctx(MENON)
    )
    assert done["status"] == "revoked" and mem.unavailability() == []


def test_reassigning_moves_the_work(box, ctx):
    report = box.call("report_disruption", sick(CAPTAIN), ctx(STATION))
    rid = report["report_id"]
    moved = box.call("reassign_disruption", {"report_id": rid, "desk_id": "desk-3"}, ctx(NAIR))
    assert moved["desk"]["controller"] == "d.rao"
    assert (
        "only its controller"
        in box.call("submit_report_plan", {"report_id": rid}, ctx(IYER))["error"]
    )
    assert box.call("submit_report_plan", {"report_id": rid}, ctx(RAO))["plans"]


def test_the_queue_says_what_waits_for_each_role(box, ctx):
    report = box.call("report_disruption", sick(CAPTAIN), ctx(STATION))
    queue = box.call("my_queue", {}, ctx(IYER))["items"]
    assert [i["ref"] for i in queue] == [report["report_id"]]
    box.call("submit_report_plan", {"report_id": report["report_id"]}, ctx(IYER))
    waiting = box.call("my_queue", {}, ctx(NAIR))["items"]
    assert waiting and all(i["kind"] == "plan" for i in waiting)
    assert box.call("my_queue", {}, ctx(STATION))["items"][0]["ref"] == report["report_id"]


def test_station_and_aircraft_reports_are_graded_from_the_engine(box, ctx):
    station = {
        "kind": "station_disruption",
        "station": "HYD",
        "start": "2026-11-05T06:00",
        "end": "2026-11-05T11:00",
        "note": "fog",
    }
    shut = box.call("report_disruption", station, ctx(STATION))
    assert shut["analysis"]["flights_held"] and shut["title"].startswith("HYD closed")
    assert "maintenance_control" not in {t["team"] for t in shut["teams"]}
    assert shut["summary"].endswith("duty limit.") or shut["summary"] == "No crew over a limit."

    aog = {
        "kind": "aircraft_technical",
        "tail": "VT-KFA",
        "start": "2026-11-05T05:00",
        "end": "2026-11-05T13:00",
    }
    fault = box.call("report_disruption", aog, ctx(IYER))
    assert fault["teams"][0]["team"] == "maintenance_control"
    assert fault["severity"]["level"] in ("high", "medium", "low")
    assert fault["severity"]["reasons"][-1].endswith("passengers affected") or fault["severity"][
        "reasons"
    ][-1].startswith("a trip")


def test_an_absence_already_recorded_is_not_recorded_twice(box, ctx, mem):
    args = {"first_day": "2026-11-05", "last_day": "2026-11-06", "reason": "food poisoning"}
    box.call("report_unavailable", {**args, "crew_id": CAPTAIN}, ctx(IYER))
    report = box.call("report_disruption", sick(CAPTAIN, CABIN), ctx(IYER))
    assert sorted(u.crew_id for u in mem.unavailability()) == sorted([CAPTAIN, CABIN])
    assert report["crew_ids"] == [CAPTAIN, CABIN]
