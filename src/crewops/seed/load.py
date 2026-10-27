"""Read an operation from a directory of JSON files."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from crewops.domain import (
    Airline,
    Certificate,
    Crew,
    DutyHistory,
    Leg,
    Rates,
    Rule,
    Standby,
    Trip,
)
from crewops.domain.dataset import Dataset

FILES = {
    "airlines": Airline,
    "crew": Crew,
    "certificates": Certificate,
    "histories": DutyHistory,
    "standby": Standby,
    "legs": Leg,
    "trips": Trip,
    "rules": Rule,
}


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_meta(directory: Path) -> dict[str, Any]:
    return _read(directory / "meta.json")


def load_dataset(directory: Path) -> Dataset:
    parsed = {
        name: TypeAdapter(tuple[model, ...]).validate_python(_read(directory / f"{name}.json"))
        for name, model in FILES.items()
    }
    meta = read_meta(directory)
    return Dataset(
        **parsed,
        rates=Rates.model_validate(_read(directory / "rates.json")),
        as_of=datetime.fromisoformat(meta["as_of"]),
    )
