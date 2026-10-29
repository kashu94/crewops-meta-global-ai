import json

import pytest
from conftest import SEED_DIR

from crewops.agent import TOOLS, Caller, Context, Role, ToolBox
from crewops.domain import Rank
from crewops.engine.cover import find_cover
from crewops.seed import read_meta
from crewops.store import MemoryStore

LAPSED = "C-1111"  # medical lapses 2026-11-05; planted in the demo data
TRIP = "T-1018"

CONTROLLER = Caller("m.iyer", Role.CONTROLLER)
VIEWER = Caller("ops.board", Role.VIEWER)


@pytest.fixture
def mem(seed):
    store = MemoryStore()
    store.load(seed, read_meta(SEED_DIR))
    return store


@pytest.fixture
def box():
    return ToolBox()


def call(box, store, name, caller=CONTROLLER, **args):
    result = box.call(name, json.dumps(args), Context(store, caller))
    json.dumps(result)  # every result must be plain JSON
    return result


def test_each_role_sees_only_its_tools(box):
    names = {role: {t.name for t in box.available(Caller("u", role, "C-1111"))} for role in Role}
    assert names[Role.CONTROLLER] == {t.name for t in TOOLS}
    assert names[Role.VIEWER] == names[Role.CONTROLLER] - {"assign_crew"}
    assert names[Role.CREW] == {"find_trips", "trip_details", "crew_profile", "check_legality"}


def test_specs_are_chat_tools_with_object_parameters(box):
    for spec in box.specs(CONTROLLER):
        assert spec["type"] == "function"
        params = spec["function"]["parameters"]
        assert params["type"] == "object" and params["properties"]
        assert '"title"' not in json.dumps(params)


def test_a_crew_member_only_sees_themselves_and_their_trips(box, mem):
    me = Caller("pooja", Role.CREW, LAPSED)
    assert "error" not in call(box, mem, "crew_profile", me, crew_id=LAPSED)
    assert "own record" in call(box, mem, "crew_profile", me, crew_id="C-1157")["error"]

    trips = call(box, mem, "find_trips", me, crew_id="C-1157")["trips"]
    assert {t["trip_id"] for t in trips} == {"T-1018", "T-1009", "T-1010"}

    other = next(t for t in mem.dataset().trips if LAPSED not in {s.crew_id for s in t.crew})
    assert "trips they fly" in call(box, mem, "trip_details", me, trip_id=other.trip_id)["error"]
    assert "cannot use" in call(box, mem, "find_cover", me, trip_id=TRIP, rank="Captain")["error"]


def test_bad_calls_come_back_as_errors_the_model_can_read(box, mem):
    ctx = Context(mem, VIEWER)
    assert "no tool named" in box.call("delete_roster", "{}", ctx)["error"]
    assert "not valid JSON" in box.call("trip_details", "{trip", ctx)["error"]
    assert "trip_id" in box.call("trip_details", '{"trip_id": "1018"}', ctx)["error"]
    assert "T-9999" in box.call("trip_details", '{"trip_id": "T-9999"}', ctx)["error"]
    assert "viewer role cannot use assign_crew" in box.call("assign_crew", "{}", ctx)["error"]


def test_search_finds_crew_by_name_or_id(box, mem):
    by_name = call(box, mem, "search_crew", query="pooja chowdary")["matches"]
    assert [m["crew_id"] for m in by_name] == [LAPSED]
    by_id = call(box, mem, "search_crew", query=LAPSED.lower())["matches"]
    assert [m["name"] for m in by_id] == ["Pooja Chowdary"]
    captains = call(box, mem, "search_crew", query="an", rank="Captain", airline="sy", limit=25)
    assert {m["rank"] for m in captains["matches"]} == {"Captain"}
    assert {m["airline"] for m in captains["matches"]} == {"SY"}
    assert "at least 2" in call(box, mem, "search_crew", query="a")["error"]


def test_legality_reports_the_lapsed_medical(box, mem):
    result = call(box, mem, "check_legality", crew_id=LAPSED, trip_id=TRIP)
    assert result["legal"] is False
    assert [(b["rule"], b["day"]) for b in result["blockers"]] == [("FDTL-08", "2026-11-06")]
    assert len({f["rule"] for f in result["findings"]}) == 9


def test_cover_lists_cheapest_first_and_always_ends_with_cancelling(box, mem):
    op = mem.operation()
    excluded = find_cover(op, TRIP, Rank.CAPTAIN, LAPSED).excluded[0]
    result = call(
        box,
        mem,
        "find_cover",
        trip_id=TRIP,
        rank="Captain",
        vacated_by=LAPSED,
        explain=[excluded.crew_id],
        limit=2,
    )
    costs = [c["cost_inr"] for c in result["choices"]]
    assert costs == sorted(costs) and len(costs) == 3
    assert result["choices"][-1]["way"] == "Cancel the trip"
    assert result["why_not"][excluded.crew_id]["reasons"] == list(excluded.reasons)


def test_an_absence_is_covered_without_using_anyone_twice(box, mem):
    result = call(
        box, mem, "absence_impact", crew_id=LAPSED, first_day="2026-11-05", last_day="2026-11-08"
    )
    assert [g["trip_id"] for g in result["seats_left_empty"]] == ["T-1018", "T-1009", "T-1010"]
    crew = [p["crew_id"] for p in result["plan"]]
    assert len(set(crew)) == len(crew) == 3 and LAPSED not in crew
    assert result["total_cost_inr"] == sum(p["cost_inr"] for p in result["plan"])
    assert (
        "before"
        in call(
            box,
            mem,
            "absence_impact",
            crew_id=LAPSED,
            first_day="2026-11-08",
            last_day="2026-11-05",
        )["error"]
    )


def test_assigning_cover_changes_the_roster_once(box, mem):
    best = call(box, mem, "find_cover", trip_id=TRIP, rank="Captain", vacated_by=LAPSED)
    pick = best["choices"][0]["crew_id"]
    args = dict(
        trip_id=TRIP,
        replace_crew_id=LAPSED,
        with_crew_id=pick,
        expected_version=1,
        reason="medical lapses 5 Nov",
    )

    done = call(box, mem, "assign_crew", **args)
    assert (done["version"], done["assigned"]["crew_id"]) == (2, pick)
    crew = {c["crew_id"] for c in call(box, mem, "trip_details", trip_id=TRIP)["crew"]}
    assert pick in crew and LAPSED not in crew
    [change] = call(box, mem, "roster_changes", trip_id=TRIP)["changes"]
    assert (change["by"], change["added"], change["removed"]) == ("m.iyer", [pick], [LAPSED])

    again = call(
        box, mem, "assign_crew", **{**args, "replace_crew_id": pick, "with_crew_id": LAPSED}
    )
    assert "not legal cover" in again["error"]
    stale = dict(args, replace_crew_id=pick, with_crew_id=best["choices"][1]["crew_id"])
    assert "trip_details" in call(box, mem, "assign_crew", **stale)["error"]
    assert mem.roster_version() == 2


def test_assigning_someone_the_engine_rules_out_is_refused(box, mem):
    excluded = find_cover(mem.operation(), TRIP, Rank.CAPTAIN, LAPSED).excluded[0]
    result = call(
        box,
        mem,
        "assign_crew",
        trip_id=TRIP,
        replace_crew_id=LAPSED,
        with_crew_id=excluded.crew_id,
        expected_version=1,
        reason="test",
    )
    assert "not legal cover" in result["error"]
    assert mem.changes() == []


def test_a_delay_names_who_it_pushes_over_a_limit(box, mem):
    result = call(box, mem, "delay_impact", trip_id=TRIP, hours=3)
    assert [b["crew_id"] for b in result["crew_over_a_limit"]] == [LAPSED]
    assert result["delay_cost_inr"] > 0
