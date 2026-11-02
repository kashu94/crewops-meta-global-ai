from datetime import datetime

import pytest
from conftest import SEED_DIR

from crewops.engine.aircraft import SPARE_COST, aircraft_options
from crewops.engine.clock import IST
from crewops.engine.operation import NotFound, build_operation
from crewops.seed import load_dataset


@pytest.fixture(scope="module")
def op():
    return build_operation(load_dataset(SEED_DIR))


def ist(text):
    return datetime.fromisoformat(text).replace(tzinfo=IST)


def test_a_short_outage_offers_a_free_aircraft_of_the_same_type_first(op):
    flights, options = aircraft_options(
        op, "VT-KFA", ist("2026-11-04T06:00"), ist("2026-11-04T09:00")
    )
    assert flights == ["KF501", "KF502"], "the return flight comes with it, back to its station"
    assert [o.way for o in options] == ["swap", "spare", "hold", "cancel"]
    assert options[0].tail == "VT-KFB" and options[0].cost == 0
    assert options[-1].way == "cancel" and options[-1].cost == op.rates.cancellation_per_leg * 2


def test_when_no_aircraft_is_free_the_spare_comes_out_and_long_holds_are_not_offered(op):
    flights, options = aircraft_options(
        op, "VT-SYB", ist("2026-11-05T06:00"), ist("2026-11-06T18:00")
    )
    assert len(flights) == 6
    ways = [o.way for o in options]
    assert ways == ["spare", "cancel"]
    assert options[0].tail == "VT-SPA" and options[0].cost == SPARE_COST


def test_an_unknown_aircraft_is_refused(op):
    with pytest.raises(NotFound):
        aircraft_options(op, "VT-XXX", ist("2026-11-05T06:00"), ist("2026-11-05T09:00"))
