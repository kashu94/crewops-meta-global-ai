"""Messages to crew and to the crew desk.

Callouts and escalations write ``Notice`` records to an outbox. The outbox decides how they
travel: kept in memory here and in tests, sent by email or SMS when deployed. The wording is
fixed templates filled from the engine's figures, so a notice never says anything a tool did
not compute.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

DESK = "crew-desk"
"""Address of the controllers on duty."""


@dataclass(frozen=True, slots=True)
class Notice:
    to: str
    """A crew id, or ``DESK``."""
    subject: str
    body: str
    at: datetime
    ref: str
    """What it is about, such as a callout id."""


class Outbox(Protocol):
    def send(self, notice: Notice) -> None: ...


class MemoryOutbox:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sent: list[Notice] = []

    def send(self, notice: Notice) -> None:
        with self._lock:
            self._sent.append(notice)

    def sent(self, to: str | None = None) -> list[Notice]:
        with self._lock:
            return [n for n in self._sent if to is None or n.to == to]
