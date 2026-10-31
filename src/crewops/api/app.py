"""The HTTP API, and the web console and TV board it serves.

    uv run python -m crewops.api            # http://localhost:8000

Everything a screen does goes through the same typed tools and role checks the agent uses
(``POST /api/tools/{name}``), so a button can never do what the role could not ask for. The
rest are the things a tool cannot be: asking the agent, speech, photos, the board.

Model-backed requests (asking, speech, photos, the brief) count against a daily allowance,
so a public demo cannot run through the credits.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from crewops.agent.advisor import Advisor, Answer
from crewops.agent.build import build_advisor
from crewops.agent.memory import Conversations
from crewops.agent.tools import Caller, Context, Role, ToolBox
from crewops.api.auth import caller_from
from crewops.engine.clock import IST
from crewops.engine.watch import scan
from crewops.models import Endpoint, ModelClient, ModelError
from crewops.models.media import MediaClient
from crewops.ops import CalloutDesk, StoreOutbox
from crewops.ops.brief import BucketImages, Images, MemoryImages, draw_card, write_brief
from crewops.seed import load_dataset, read_meta
from crewops.settings import ROOT, Settings, settings
from crewops.store import MemoryStore, Store, open_store
from crewops.vision import Kind, ModelReader, read_photo

WEB = ROOT / "web"
SCORECARD = ROOT / "docs" / "scorecard.json"
BRIEF_EVERY_SECONDS = 120
AUDIO_LIMIT = 10 * 1024 * 1024
IMAGE_LIMIT = 8 * 1024 * 1024
LANGUAGES = {"English", "Hindi", "Telugu", "Tamil", "Kannada", "Marathi", "Bengali"}


class Services:
    """Everything a request needs, built once per server."""

    def __init__(self, config: Settings, store: Store | MemoryStore | None = None) -> None:
        self.config = config
        self.store = store or open_store(config)
        if self.store.is_empty():
            self.store.load(load_dataset(config.seed_dir), read_meta(config.seed_dir))
        self.outbox = StoreOutbox(self.store)
        self.desk = CalloutDesk(self.store, self.outbox, docs=self.store)
        self.conversations = Conversations(docs=self.store)
        self.toolbox = ToolBox()
        self.media = MediaClient(config)
        self.reader = ModelReader(ModelClient(Endpoint.meta(config, config.vision_model)))
        self.writer = ModelClient(Endpoint.meta(config, config.wonder_model))
        self.images: Images = MemoryImages()
        if config.bucket:
            import boto3

            self.images = BucketImages(boto3.client("s3"), config.bucket)
        self._advisor: Advisor | None = None
        self._lock = threading.Lock()

    @property
    def advisor(self) -> Advisor:
        with self._lock:
            if self._advisor is None:
                self._advisor = build_advisor(self.config, self.store, self.outbox)
                self._advisor.desk = self.desk
            return self._advisor

    def context(self, caller: Caller) -> Context:
        return Context(self.store, caller, desk=self.desk)

    def spend(self, what: str) -> None:
        """Count one model-backed request against today's allowance."""
        today = datetime.now(UTC).date().isoformat()
        used = self.store.get_doc("usage", today) or {"count": 0}
        if used["count"] >= self.config.daily_asks:
            raise HTTPException(429, "today's demo allowance is used up; please try tomorrow")
        used["count"] += 1
        used[what] = used.get(what, 0) + 1
        self.store.put_doc("usage", today, used)


def answer_json(answer: Answer, conversation_id: str) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "text": answer.text,
        "verified": answer.verified,
        "problems": answer.problems,
        "draft": answer.draft,
        "draft_problems": answer.draft_problems,
        "blocked": answer.blocked,
        "route": (
            {
                "intent": str(answer.route.intent),
                "by": answer.route.by,
                "effort": answer.route.effort,
                "tools": list(answer.route.tools),
            }
            if answer.route
            else None
        ),
        "steps": [
            {"tool": s.tool, "arguments": s.arguments, "result": s.result} for s in answer.steps
        ],
        "tokens": answer.tokens,
        "calls": [
            {
                "model": u.model,
                "purpose": u.purpose,
                "effort": u.effort,
                "prompt": u.prompt_tokens,
                "completion": u.completion_tokens,
                "reasoning": u.reasoning_tokens,
                "cached": u.cached_tokens,
                "seconds": u.seconds,
            }
            for u in answer.usage
        ],
    }


OPEN = ("offered", "needs_decision", "awaiting_approval")


def ops_room(s: Services, op: Any, issues: list[Any], callouts: list[Any]) -> dict[str, Any]:
    """What the ops-room wall shows beside the problems: the next day at a glance, each
    controller's load, the departures coming up, standby cover, and the latest messages."""
    horizon = op.now + timedelta(hours=24)
    legs = sorted(
        (leg for leg in op.legs.values() if op.now <= leg.off_block <= horizon),
        key=lambda leg: leg.off_block,
    )
    trip_of = {leg_id: t.trip_id for t in op.trips.values() for leg_id in t.leg_ids}
    troubled = {i.trip_id for i in issues if i.trip_id and i.kind == "illegal"}
    troubled |= {c.trip_id for c in callouts if str(c.status) in OPEN}
    today, tomorrow = op.now.date(), (op.now + timedelta(days=1)).date()
    out_now = {
        u.crew_id
        for u in s.store.unavailability()
        if u.first_day <= tomorrow and u.last_day >= today
    }

    desks: dict[str, dict[str, Any]] = {}
    for c in callouts:
        desk = desks.setdefault(
            c.opened_by, {"controller": c.opened_by, "open": 0, "filled": 0, "to_approve": 0}
        )
        status = str(c.status)
        desk["open"] += status in OPEN
        desk["filled"] += status == "filled"
        if status == "awaiting_approval":
            desk["to_approve"] += 1

    standby: dict[tuple[str, str], int] = {}
    for crew in op.crew.values():
        for rank in ("Captain", "First Officer", "Purser", "Cabin Crew"):
            standby.setdefault((crew.airline, rank), 0)
        on_call = any(
            d in (today, tomorrow) for sb in op.standby.get(crew.crew_id, ()) for d in sb.dates
        )
        if on_call and crew.crew_id not in out_now:
            standby[(crew.airline, str(crew.rank))] += 1

    return {
        "next_24h": {
            "flights": len(legs),
            "passengers": sum(leg.booked for leg in legs),
            "crew_out": len(out_now),
            "open_callouts": sum(1 for c in callouts if str(c.status) in OPEN),
            "illegal": sum(1 for i in issues if i.kind == "illegal"),
            "fatigue": sum(1 for i in issues if i.kind == "fatigue"),
            "certificates": sum(1 for i in issues if i.kind == "certificate"),
        },
        "desks": sorted(desks.values(), key=lambda d: (-d["open"], d["controller"])),
        "departures": [
            {
                "flight": leg.flight_no,
                "route": f"{leg.origin}-{leg.destination}",
                "departs": leg.off_block.astimezone(IST).strftime("%d %b %H:%M"),
                "tail": leg.tail,
                "trip_id": trip_of.get(leg.leg_id),
                "booked": leg.booked,
                "state": "affected" if trip_of.get(leg.leg_id) in troubled else "on plan",
            }
            for leg in legs[:10]
        ],
        "standby": [
            {"airline": airline, "rank": rank, "on_call": n}
            for (airline, rank), n in sorted(standby.items())
        ],
        "latest": [
            {"subject": n.subject, "at": n.at.astimezone(IST).strftime("%d %b %H:%M")}
            for n in s.outbox.sent("crew-desk")[-6:][::-1]
        ],
    }


def refresh_brief(s: Services, force: bool = False) -> bool:
    """Write a new shift brief when the roster or the callouts have moved, at most every two
    minutes. Returns whether one was written."""
    callouts = s.desk.all()
    signature = f"{s.store.roster_version()}:" + ",".join(
        f"{c.callout_id}={c.status}" for c in callouts
    )
    cached = s.store.get_doc("brief", "current")
    now = datetime.now(UTC)
    if cached and not force:
        age = (now - datetime.fromisoformat(cached["at"])).total_seconds()
        if cached["signature"] == signature or age < BRIEF_EVERY_SECONDS:
            return False
    s.spend("brief")
    brief = write_brief(s.store.operation(), callouts, s.writer)
    if s.config.board_art:
        try:
            brief.image_key = draw_card(s.config, s.images, brief.mood)
        except ModelError:
            brief.image_key = None
    s.store.put_doc(
        "brief", "current", {"signature": signature, "at": now.isoformat(), "brief": asdict(brief)}
    )
    return True


def create_app(config: Settings | None = None, services: Services | None = None) -> FastAPI:
    config = config or settings()
    app = FastAPI(title="CrewOps", docs_url="/api/docs", openapi_url="/api/openapi.json")
    state: dict[str, Services] = {}
    if services is not None:
        state["services"] = services

    def svc() -> Services:
        if "services" not in state:
            state["services"] = Services(config)
        return state["services"]

    def caller(request: Request) -> Caller:
        return caller_from(request, config)

    @app.exception_handler(ModelError)
    async def model_down(_request: Request, err: ModelError) -> JSONResponse:
        return JSONResponse({"detail": f"a model is unavailable: {err}"}, status_code=503)

    # -- public ---------------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config")
    def public_config() -> dict[str, Any]:
        return {
            "auth": config.auth,
            "region": config.aws_region,
            "client_id": config.cognito_client_id,
            "stage": config.stage,
        }

    # -- reading --------------------------------------------------------------------------

    @app.get("/api/me")
    def me(who: Caller = Depends(caller)) -> dict[str, Any]:
        s = svc()
        op = s.store.operation()
        return {
            "user": who.user,
            "role": str(who.role),
            "crew_id": who.crew_id,
            "clock": op.now.astimezone(IST).strftime("%a %d %b %Y, %H:%M IST"),
            "tools": [t.name for t in s.toolbox.available(who)],
        }

    @app.get("/api/version")
    def version(_who: Caller = Depends(caller)) -> dict[str, Any]:
        """Cheap to call every couple of seconds: screens refresh when a number moves."""
        s = svc()
        callouts = s.store.docs("callout")
        return {
            "roster": s.store.roster_version(),
            "callouts": hash(json.dumps(callouts, sort_keys=True)) % 10**9,
            "notices": len(s.store.docs("notice")),
        }

    @app.post("/api/tools/{name}")
    def tool(
        name: str, arguments: dict[str, Any] = Body(default={}), who: Caller = Depends(caller)
    ) -> dict[str, Any]:
        s = svc()
        return s.toolbox.call(name, arguments, s.context(who))

    @app.get("/api/notices")
    def notices(limit: int = 30, who: Caller = Depends(caller)) -> dict[str, Any]:
        s = svc()
        mine = {"crew-desk"} if who.role is not Role.CREW else {who.crew_id}
        found = [n for n in s.outbox.sent() if n.to in mine]
        return {
            "notices": [
                {**asdict(n), "at": n.at.astimezone(IST).strftime("%d %b %H:%M IST")}
                for n in found[-limit:][::-1]
            ]
        }

    # -- the agent ------------------------------------------------------------------------

    @app.post("/api/ask")
    def ask(
        question: str = Body(..., embed=True, min_length=2, max_length=2000),
        conversation_id: str | None = Body(None, embed=True),
        who: Caller = Depends(caller),
    ) -> dict[str, Any]:
        s = svc()
        s.spend("ask")
        conversation, answer = s.conversations.ask(s.advisor, question, who, conversation_id)
        return answer_json(answer, conversation.id)

    @app.post("/api/voice")
    async def voice(
        audio: UploadFile = File(...),
        languages: str = Form("English"),
        _who: Caller = Depends(caller),
    ) -> dict[str, Any]:
        data = await audio.read()
        if len(data) > AUDIO_LIMIT:
            raise HTTPException(413, "keep recordings under a minute")
        hints = [x.strip() for x in languages.split(",") if x.strip() in LANGUAGES]
        s = svc()
        s.spend("voice")
        transcript = s.media.transcribe(data, hints or None)
        return {"text": transcript.text, "seconds": round(transcript.duration_ms / 1000, 1)}

    @app.post("/api/intake")
    async def intake(
        image: UploadFile = File(...),
        kind: Kind = Form(...),
        tail: str | None = Form(None),
        _who: Caller = Depends(caller),
    ) -> dict[str, Any]:
        data = await image.read()
        if len(data) > IMAGE_LIMIT:
            raise HTTPException(413, "send a photo under 8 MB")
        mime = image.content_type or "image/jpeg"
        if mime not in ("image/jpeg", "image/png", "image/webp"):
            raise HTTPException(415, "send a JPEG, PNG or WebP photo")
        s = svc()
        s.spend("intake")
        result = read_photo(
            s.store.operation(), kind, data, mime, s.reader, s.media, (tail or None)
        )
        out = asdict(result)
        out["kind"], out["status"] = str(result.kind), str(result.status)
        return out

    # -- the board ------------------------------------------------------------------------

    @app.get("/api/board")
    def board(request: Request) -> dict[str, Any]:
        """Read-only, so a TV on the wall needs no sign-in. Only a signed-in desk user (or the
        schedule) can trigger a fresh brief, so an open screen never spends model credits."""
        s = svc()
        try:
            who: Caller | None = caller_from(request, config)
        except HTTPException:
            who = None
        if who is not None and who.role is not Role.CREW:
            refresh_brief(s)
        op = s.store.operation()
        cached = s.store.get_doc("brief", "current")
        ctx = s.context(Caller("board", Role.VIEWER))
        issues = scan(op)
        callouts = s.desk.all()
        return {
            "clock": op.now.astimezone(IST).strftime("%a %d %b, %H:%M IST"),
            "brief": cached["brief"] if cached else None,
            "issues": [{**asdict(i), "day": i.day.isoformat()} for i in issues[:12]],
            "callouts": s.toolbox.call("callout_status", {}, ctx).get("callouts", []),
            "changes": s.toolbox.call("roster_changes", {"limit": 5}, ctx).get("changes", []),
            **ops_room(s, op, issues, callouts),
        }

    @app.get("/api/card/{key:path}")
    def card(key: str) -> Response:
        if not key.startswith("cards/") or ".." in key:
            raise HTTPException(404)
        data = svc().images.get(key)
        if data is None:
            raise HTTPException(404)
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})

    @app.get("/api/scorecard")
    def scorecard() -> Any:
        if not SCORECARD.is_file():
            raise HTTPException(404, "no scorecard yet")
        return json.loads(SCORECARD.read_text(encoding="utf-8"))

    # -- the pages ------------------------------------------------------------------------

    if WEB.is_dir():
        app.mount("/static", StaticFiles(directory=WEB), name="static")

        @app.get("/")
        def console() -> FileResponse:
            return FileResponse(WEB / "index.html")

        @app.get("/board")
        def board_page() -> FileResponse:
            return FileResponse(WEB / "board.html")

    return app


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Run the CrewOps API and web console.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
