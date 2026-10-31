"""Entry points on AWS Lambda.

``handler`` serves the API, the console and the board through a function URL. ``scheduled``
runs every few minutes: it moves offers nobody answered to the next crew member, emails the
crew desk once about each new problem the watch finds, and keeps the board's brief fresh.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import boto3
from mangum import Mangum

from crewops.api.app import Services, create_app, refresh_brief
from crewops.engine.watch import scan
from crewops.ops import DESK, Notice
from crewops.ops.notify import EmailingOutbox
from crewops.settings import settings


def services() -> Services:
    config = settings()
    s = Services(config)
    if config.alert_topic_arn:
        s.outbox = EmailingOutbox(s.outbox, boto3.client("sns"), config.alert_topic_arn)
        s.desk.outbox = s.outbox
    return s


_services = services()
handler = Mangum(create_app(_services.config, _services), lifespan="off")


def scheduled(_event: dict[str, Any] | None = None, _context: Any = None) -> dict[str, int]:
    s = _services
    moved = s.desk.tick()
    raised = {d["issue_id"] for d in s.store.docs("alerted")}
    new = [i for i in scan(s.store.operation()) if i.kind != "certificate"]
    new = [i for i in new if i.issue_id not in raised]
    now = datetime.now(UTC)
    for issue in new:
        cover = f" Cheapest legal cover: {issue.suggestion}." if issue.suggestion else ""
        where = f" on {issue.trip_id}" if issue.trip_id else ""
        s.outbox.send(
            Notice(
                to=DESK,
                subject=f"Watch: {issue.name}{where}",
                body=f"{issue.name} ({issue.crew_id}){where}: {issue.detail}.{cover}",
                at=now,
                ref=issue.issue_id,
            )
        )
        s.store.put_doc("alerted", issue.issue_id, {"issue_id": issue.issue_id})
    try:
        briefed = refresh_brief(s)
    except Exception:  # a model outage must not stop the alerts above
        briefed = False
    return {"offers_moved": len(moved), "alerts": len(new), "brief": int(briefed)}
