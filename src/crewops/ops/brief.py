"""The shift brief on the ops board: what the desk needs to know, in three lines and a picture.

Muse Wonder writes the brief from the facts the watch and the callout desk hold, and the same
evidence check every answer gets makes sure each id and figure in it came from those facts.
A brief that fails the check is replaced by one built from the facts by a template, so the
board never shows a figure nobody computed.

Muse Image draws the card's artwork: a calm, busy or critical scene with no text in it (image
models are poor at lettering), so the words always come from the brief. One picture per mood
per day is enough; it is kept and reused.
"""

from __future__ import annotations

import base64
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel

from crewops.agent.advisor import Step
from crewops.agent.verify import EvidenceVerifier
from crewops.engine.clock import IST
from crewops.engine.operation import Operation
from crewops.engine.watch import Issue, scan
from crewops.models.client import ModelClient, ModelError
from crewops.ops.callout import Callout, Status
from crewops.settings import Settings

Mood = Literal["calm", "busy", "critical"]

SCENES: dict[str, str] = {
    "calm": "a quiet regional airport apron at dawn, two turboprop aircraft parked, soft "
    "golden light, crew walking to the aircraft",
    "busy": "a busy regional airport apron at dusk, ground crew around an A320, baggage carts "
    "and lit terminal windows",
    "critical": "an airline operations control room at night, controllers at screens showing "
    "flight maps, a single aircraft waiting on a rain-wet apron outside the window",
}
ART_STYLE = (
    "Wide editorial illustration, muted navy and amber palette, clean shapes. No text, no "
    "letters, no numbers, no logos, no airline names anywhere in the image."
)


class BriefText(BaseModel):
    headline: str
    lines: list[str]


@dataclass
class Brief:
    mood: Mood
    headline: str
    lines: list[str]
    written_by: str
    """``muse-wonder`` or ``template``."""
    verified: bool
    facts: dict[str, Any] = field(default_factory=dict)
    image_key: str | None = None


def facts(op: Operation, callouts: list[Callout]) -> dict[str, Any]:
    issues = scan(op)
    open_callouts = [c for c in callouts if c.status not in (Status.FILLED, Status.CLOSED)]

    def issue(i: Issue) -> dict[str, Any]:
        out = {"kind": i.kind, "crew_id": i.crew_id, "name": i.name, "detail": i.detail}
        if i.trip_id:
            out["trip_id"] = i.trip_id
        if i.suggestion:
            out["suggested_cover"] = i.suggestion
            out["cost_inr"] = i.suggestion_cost
        return out

    return {
        "clock": op.now.astimezone(IST).strftime("%d %b %H:%M IST"),
        "illegal": [issue(i) for i in issues if i.kind == "illegal"],
        "fatigue": [issue(i) for i in issues if i.kind == "fatigue"],
        "certificates": [issue(i) for i in issues if i.kind == "certificate"],
        "callouts_waiting_on_crew": [
            {"trip_id": c.trip_id, "seat": str(c.rank), "asking": c.current.crew_id}
            for c in open_callouts
            if c.current is not None
        ],
        "callouts_needing_a_decision": [
            {"trip_id": c.trip_id, "seat": str(c.rank)}
            for c in open_callouts
            if c.status in (Status.NEEDS_DECISION, Status.AWAITING_APPROVAL)
        ],
    }


def mood_of(f: dict[str, Any]) -> Mood:
    if f["illegal"] or f["callouts_needing_a_decision"]:
        return "critical"
    if f["fatigue"] or f["callouts_waiting_on_crew"]:
        return "busy"
    return "calm"


def template(f: dict[str, Any]) -> list[str]:
    lines = []
    for i in f["illegal"][:2]:
        cover = f", cover {i['suggested_cover']}" if i.get("suggested_cover") else ""
        lines.append(f"{i['trip_id']}: {i['name']} ({i['crew_id']}) {i['detail']}{cover}.")
    if f["callouts_needing_a_decision"]:
        trips = ", ".join(c["trip_id"] for c in f["callouts_needing_a_decision"])
        lines.append(f"Decision needed: nobody accepted the callout for {trips}.")
    if f["fatigue"]:
        lines.append(f"{len(f['fatigue'])} crew at high fatigue in the next 7 days.")
    if f["certificates"]:
        lines.append(f"{len(f['certificates'])} certificates run out in the next 14 days.")
    return lines[:3] or ["No open problems in the next 7 days."]


def write_brief(op: Operation, callouts: list[Callout], writer: ModelClient | None) -> Brief:
    f = facts(op, callouts)
    mood = mood_of(f)
    headline = {"calm": "All quiet", "busy": "Busy shift", "critical": "Action needed"}[mood]
    if writer is not None:
        try:
            text, _ = writer.parse(
                [
                    {
                        "role": "system",
                        "content": "Write the crew-desk shift brief for the ops board: a headline "
                        "of at most 6 words and at most 3 lines of at most 18 words each, most "
                        "urgent first. Use only the facts given; copy ids, names and figures "
                        "exactly; never calculate. Write plain sentences: amounts as INR 31160, "
                        "never field names such as cost_inr or suggested_cover.",
                    },
                    {"role": "user", "content": str(f)},
                ],
                BriefText,
                purpose="brief",
                effort="low",
                max_tokens=3000,
            )
            evidence = [Step("facts", {}, f)]
            said = " ".join([text.headline, *text.lines])
            if text.lines and not EvidenceVerifier().problems(said, "", evidence):
                return Brief(mood, text.headline, text.lines[:3], "muse-wonder", True, f)
        except ModelError:
            pass
    return Brief(mood, headline, template(f), "template", True, f)


# -- pictures --------------------------------------------------------------------------------


class Images(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def put(self, key: str, data: bytes) -> None: ...


class MemoryImages:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._images: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self._images.get(key)

    def put(self, key: str, data: bytes) -> None:
        with self._lock:
            self._images[key] = data


class BucketImages:
    def __init__(self, s3: Any, bucket: str) -> None:
        self.s3, self.bucket = s3, bucket

    def get(self, key: str) -> bytes | None:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None

    def put(self, key: str, data: bytes) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType="image/jpeg")


def card_key(mood: Mood, day: date | None = None) -> str:
    return f"cards/{(day or datetime.now(UTC).date()).isoformat()}-{mood}.jpg"


def draw_card(
    config: Settings, images: Images, mood: Mood, http: httpx.Client | None = None
) -> str:
    """The card artwork for ``mood`` today, drawn by Muse Image once and then reused."""
    key = card_key(mood)
    if images.get(key) is not None:
        return key
    client = http or httpx.Client(timeout=180)
    try:
        response = client.post(
            f"{config.meta_base_url}/images/generations",
            headers={"Authorization": f"Bearer {config.model_api_key}"},
            json={
                "model": config.image_model,
                "prompt": f"{SCENES[mood]}. {ART_STYLE}",
                "n": 1,
                "size": "1792x1024",
                "output_format": "jpeg",
            },
        )
    except httpx.HTTPError as err:
        raise ModelError(f"image generation unreachable: {err}") from err
    finally:
        if http is None:
            client.close()
    if response.is_error:
        raise ModelError(
            f"image generation returned {response.status_code}",
            status=response.status_code,
            body=response.text[:2000],
        )
    images.put(key, base64.b64decode(response.json()["data"][0]["b64_json"]))
    return key
