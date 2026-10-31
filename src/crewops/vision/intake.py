"""Photos into the crew desk: sick notes, roster swaps, certificates, aircraft defects, and
disruption notices (a departures board, a gate screen, an ATC delay message).

Every photo passes the same gates, and the code decides what happens, not the model:

1. **Picture quality**, measured from the pixels: blur and darkness ask for a reshoot before
   any model is called.
2. **What is in it**: Muse Spark reads the photo into a fixed form for its kind. The form has
   no free text the rest of the system acts on.
3. **The decision**, in code:

   ======================  ==============================================================
   ``rejected``            not the kind of thing expected (a selfie as a sick note)
   ``reshoot``             unreadable or unclear, with the reason
   ``confirm``             the person or aircraft it names does not match, or is ambiguous
   ``draft``               a proposal a person must confirm; nothing is changed by a photo
   ======================  ==============================================================

For a defect, SAM 3.1 then locates the damage named by the form, and the confidence level is
built from independent signals (picture quality, the model's view of the photo, whether SAM
found the damage, whether the tail number matches) rather than the model's own score.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Literal, Protocol

from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError
from pydantic import BaseModel

from crewops.engine.clock import IST
from crewops.engine.operation import Operation
from crewops.models.media import Box

MAX_BYTES = 8 * 1024 * 1024
MIN_SHARPNESS = 200.0
"""Variance of the edge image; sharp phone photos measure in the thousands, blur under 100."""
MIN_BRIGHTNESS, MAX_BRIGHTNESS = 40.0, 235.0
MIN_SAM_CONFIDENCE = 0.4
MAX_BOX_SHARE = 0.6
"""A "damage" box covering most of the photo has found the panel, not the damage."""

Clarity = Literal["clear", "partial", "unclear"]


class Kind(StrEnum):
    SICK_NOTE = "sick_note"
    ROSTER_SWAP = "roster_swap"
    CERTIFICATE = "certificate"
    DEFECT = "defect"
    DISRUPTION = "disruption"


class Status(StrEnum):
    REJECTED = "rejected"
    RESHOOT = "reshoot"
    CONFIRM = "confirm"
    DRAFT = "draft"


# -- what the model fills in -----------------------------------------------------------------


class SickNote(BaseModel):
    is_medical_note: bool
    readable: Clarity
    patient_name: str
    unfit_from: str
    """YYYY-MM-DD, or empty if not written."""
    unfit_to: str
    issued_by: str


class RosterSwap(BaseModel):
    is_roster_swap: bool
    readable: Clarity
    crew_names: list[str]
    trip_ids: list[str]
    signed_by_both: bool


class CertificateForm(BaseModel):
    is_certificate: bool
    readable: Clarity
    holder_name: str
    kind: Literal["licence", "medical", "recurrent_training", "safety_equipment", "other"]
    expires: str
    """YYYY-MM-DD, or empty if not visible."""


class Damage(BaseModel):
    part: str
    kind: Literal["dent", "crack", "scratch", "hole", "leak", "burn", "missing", "other"]
    where: str


class DefectForm(BaseModel):
    shows_aircraft: bool
    """An aircraft or a recognisable part of one, inside or out."""
    subject: str
    """What the photo shows, in a few words."""
    area: Literal["exterior", "engine", "cabin", "cockpit", "cargo", "unknown"]
    view: Clarity
    view_problems: list[str]
    tail_number: str
    """The registration if it can be read in the photo, such as VT-SYA; otherwise empty."""
    damage: list[Damage]
    damage_phrase: str
    """Two or three words naming the damage for locating it, such as "dent" or "cracked panel"."""


class FlightStatus(BaseModel):
    flight_no: str
    """Such as SY221, exactly as shown."""
    status: Literal["delayed", "cancelled", "gate_change", "on_time", "other"]
    new_time: str
    """The new departure time as HH:MM if shown, otherwise empty."""
    delay_minutes: int
    """If the delay is stated in minutes or hours, in minutes; otherwise 0."""


class DisruptionNotice(BaseModel):
    is_flight_notice: bool
    """A departures board, gate screen, delay message or printed notice about flights."""
    readable: Clarity
    flights: list[FlightStatus]


PROMPTS: dict[Kind, tuple[type[BaseModel], str]] = {
    Kind.SICK_NOTE: (
        SickNote,
        "This should be a doctor's note that a crew member is unfit to fly. Fill the form only "
        "from what is written; leave a field empty if it is not there. Dates as YYYY-MM-DD.",
    ),
    Kind.ROSTER_SWAP: (
        RosterSwap,
        "This should be a handwritten request by two crew members to swap trips. Fill the form "
        "only from what is written. Trip ids look like T-1018.",
    ),
    Kind.CERTIFICATE: (
        CertificateForm,
        "This should be an aviation certificate: pilot licence, medical, recurrent training or "
        "safety equipment. Fill the form only from what is printed. Dates as YYYY-MM-DD.",
    ),
    Kind.DEFECT: (
        DefectForm,
        "This should be a photo of possible damage on an aircraft, inside or out. Describe only "
        "what is visible. If you cannot see damage, leave damage empty: do not guess. Name the "
        "tail registration only if it is readable in the photo.",
    ),
    Kind.DISRUPTION: (
        DisruptionNotice,
        "This should show flight disruptions: a departures board, a gate screen, an ATC delay "
        "message or a printed notice. List only flights shown with a status; copy flight "
        "numbers and times exactly. Times are local (IST).",
    ),
}


class Reader(Protocol):
    """Fills a form from a photo: Muse Spark vision in production, a fake in tests."""

    def read(self, image: bytes, mime: str, form: type[BaseModel], instructions: str) -> Any: ...


class Locator(Protocol):
    def segment(self, image: bytes, mime: str, phrase: str) -> list[Box]: ...


class ModelReader:
    def __init__(self, client: Any) -> None:
        self.client = client

    def read(self, image: bytes, mime: str, form: type[BaseModel], instructions: str) -> Any:
        data_url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        parsed, _ = self.client.parse(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instructions},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            form,
            purpose="intake",
            effort="low",
            max_tokens=4000,
        )
        return parsed


# -- results ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Quality:
    width: int
    height: int
    sharpness: float
    brightness: float
    problems: tuple[str, ...]


@dataclass
class Intake:
    kind: Kind
    status: Status
    message: str
    quality: Quality | None = None
    form: dict[str, Any] = field(default_factory=dict)
    confidence: str | None = None
    """``high``, ``medium`` or ``low``, for defects."""
    signals: dict[str, Any] = field(default_factory=dict)
    box: Box | None = None
    crew: list[dict[str, str]] = field(default_factory=list)
    proposal: dict[str, Any] | None = None
    """A tool call a person can make with one click; never made by the photo itself."""


def measure(image: bytes) -> Quality:
    try:
        picture = Image.open(io.BytesIO(image))
        picture.load()
    except (UnidentifiedImageError, OSError) as err:
        raise ValueError("not an image this service can read") from err
    width, height = picture.size
    grey = picture.convert("L")
    grey.thumbnail((800, 800))
    sharpness = ImageStat.Stat(grey.filter(ImageFilter.FIND_EDGES)).var[0]
    brightness = ImageStat.Stat(grey).mean[0]
    problems = []
    if brightness < MIN_BRIGHTNESS:
        problems.append("too dark: add light or use the torch")
    elif brightness > MAX_BRIGHTNESS:
        problems.append("washed out: step out of direct glare")
    if sharpness < MIN_SHARPNESS:
        problems.append("blurred: hold the phone still and let it focus")
    if min(width, height) < 300:
        problems.append("too small: send the original photo, not a thumbnail")
    return Quality(width, height, round(sharpness, 1), round(brightness, 1), tuple(problems))


def _crew_named(op: Operation, name: str) -> list[dict[str, str]]:
    words = [w for w in name.lower().replace(".", " ").split() if len(w) > 1]
    if not words:
        return []
    found = [c for c in op.crew.values() if all(w in c.name.lower() for w in words)]
    return [
        {"crew_id": c.crew_id, "name": c.name, "rank": str(c.rank), "airline": c.airline}
        for c in sorted(found, key=lambda c: c.crew_id)
    ]


def _date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _fleet(op: Operation) -> set[str]:
    return {leg.tail for leg in op.legs.values()}


def read_photo(
    op: Operation,
    kind: Kind,
    image: bytes,
    mime: str,
    reader: Reader,
    locator: Locator | None = None,
    tail: str | None = None,
) -> Intake:
    """Run a photo through the gates. ``tail`` is the aircraft the reporter chose."""
    if len(image) > MAX_BYTES:
        return Intake(kind, Status.REJECTED, "That file is too large: send a photo under 8 MB.")
    try:
        quality = measure(image)
    except ValueError:
        return Intake(kind, Status.REJECTED, "That is not a photo this service can read.")
    if quality.problems:
        return Intake(
            kind,
            Status.RESHOOT,
            "Please take the photo again: " + "; ".join(quality.problems) + ".",
            quality,
        )

    form_type, instructions = PROMPTS[kind]
    form = reader.read(image, mime, form_type, instructions)
    result = Intake(kind, Status.DRAFT, "", quality, form.model_dump())
    match kind:
        case Kind.SICK_NOTE:
            return _sick_note(op, form, result)
        case Kind.ROSTER_SWAP:
            return _roster_swap(op, form, result)
        case Kind.CERTIFICATE:
            return _certificate(op, form, result)
        case Kind.DISRUPTION:
            return _disruption(op, form, result)
        case _:
            return _defect(op, form, result, image, mime, locator, tail)


def _unreadable(result: Intake, what: str) -> Intake:
    result.status = Status.RESHOOT
    result.message = f"The {what} cannot be read clearly. Please photograph it flat, in good light."
    return result


def _one_person(op: Operation, name: str, result: Intake, what: str) -> dict[str, str] | None:
    result.crew = _crew_named(op, name) if name else []
    if len(result.crew) == 1:
        return result.crew[0]
    result.status = Status.CONFIRM
    if not result.crew:
        result.message = (
            f"The {what} names {name or 'nobody'}, who is not in the roster. Who is it?"
        )
    else:
        result.message = (
            f"The {what} names {name}, which matches {len(result.crew)} people. Which one?"
        )
    return None


def _sick_note(op: Operation, form: SickNote, result: Intake) -> Intake:
    if not form.is_medical_note:
        result.status = Status.REJECTED
        result.message = "This does not look like a doctor's note."
        return result
    if form.readable == "unclear":
        return _unreadable(result, "note")
    person = _one_person(op, form.patient_name, result, "note")
    if person is None:
        return result
    first, last = _date(form.unfit_from), _date(form.unfit_to)
    if first is None:
        result.status = Status.CONFIRM
        result.message = f"Note for {person['name']}: the dates cannot be read. Which days?"
        return result
    last = last or first
    result.message = (
        f"Note for {person['name']} ({person['crew_id']}), unfit {first:%d %b} to {last:%d %b}. "
        "Confirm to record them as unavailable."
    )
    result.proposal = {
        "tool": "report_unavailable",
        "arguments": {
            "crew_id": person["crew_id"],
            "first_day": first.isoformat(),
            "last_day": last.isoformat(),
            "reason": "sick note" + (f" from {form.issued_by}" if form.issued_by else ""),
        },
    }
    return result


def _roster_swap(op: Operation, form: RosterSwap, result: Intake) -> Intake:
    if not form.is_roster_swap:
        result.status = Status.REJECTED
        result.message = "This does not look like a roster swap request."
        return result
    if form.readable == "unclear":
        return _unreadable(result, "request")
    people = [_crew_named(op, n) for n in form.crew_names]
    result.crew = [p[0] for p in people if len(p) == 1]
    if len(form.crew_names) != 2 or len(result.crew) != 2:
        result.status = Status.CONFIRM
        result.message = "The request should name exactly two crew members on the roster."
        return result
    missing = [t for t in form.trip_ids if t not in op.trips]
    if missing or not form.trip_ids:
        result.status = Status.CONFIRM
        result.message = "Check the trip ids: " + (", ".join(missing) or "none were written") + "."
        return result
    names = " and ".join(p["name"] for p in result.crew)
    signed = "" if form.signed_by_both else " It is not signed by both."
    result.message = (
        f"Swap request from {names} for {', '.join(form.trip_ids)}. Each swap is checked "
        f"against the rules before it is made.{signed}"
    )
    return result


def _certificate(op: Operation, form: CertificateForm, result: Intake) -> Intake:
    if not form.is_certificate:
        result.status = Status.REJECTED
        result.message = "This does not look like an aviation certificate."
        return result
    if form.readable == "unclear":
        return _unreadable(result, "certificate")
    person = _one_person(op, form.holder_name, result, "certificate")
    if person is None:
        return result
    expires = _date(form.expires)
    on_file = (
        dict(op.state(person["crew_id"]).certs).get(form.kind) if form.kind != "other" else None
    )
    result.message = (
        f"{form.kind.replace('_', ' ').capitalize()} for {person['name']}"
        + (f", expiring {expires:%d %b %Y}" if expires else ", expiry not readable")
        + (f"; on file: {on_file:%d %b %Y}" if on_file else "")
        + ". A person updates the record after checking the original."
    )
    return result


def _defect(
    op: Operation,
    form: DefectForm,
    result: Intake,
    image: bytes,
    mime: str,
    locator: Locator | None,
    tail: str | None,
) -> Intake:
    if not form.shows_aircraft:
        result.status = Status.REJECTED
        result.message = (
            f"This shows {form.subject or 'something else'}, not an aircraft. "
            "Please photograph the affected area."
        )
        return result
    if form.view == "unclear":
        result.status = Status.RESHOOT
        reasons = "; ".join(form.view_problems) or "the damage area is not clear"
        result.message = f"Please take the photo again: {reasons}. Get closer and hold steady."
        return result

    seen = form.tail_number.strip().upper()
    fleet = _fleet(op)
    tail_ok: bool | None = None
    if seen:
        tail_ok = seen == (tail or "").upper()
        if seen not in fleet or (tail and not tail_ok):
            result.status = Status.CONFIRM
            chosen = f", not {tail}" if tail else ""
            where = "" if seen in fleet else " That registration is not in our fleet."
            result.message = f"This looks like {seen}{chosen}.{where} Please confirm the aircraft."
            return result

    box = None
    if form.damage and locator is not None:
        tried = dict.fromkeys(p for p in (form.damage_phrase, "damage", form.damage[0].kind) if p)
        boxes = [b for phrase in tried for b in locator.segment(image, mime, phrase)]
        usable = [
            b for b in boxes if b.confidence >= MIN_SAM_CONFIDENCE and b.share <= MAX_BOX_SHARE
        ]
        box = max(usable, key=lambda b: b.confidence, default=None)
    result.box = box

    result.signals = {
        "picture_quality": "good",
        "model_view": form.view,
        "damage_described": bool(form.damage),
        "damage_located": box is not None,
        "located_confidence": round(box.confidence, 2) if box else None,
        "tail_matches": tail_ok,
    }
    if not form.damage:
        result.confidence = "low"
        result.message = (
            "No damage identified in this photo. That is not a clearance: inspect in person."
        )
        return result
    if form.view == "clear" and box is not None and tail_ok is not False:
        result.confidence = "high"
    elif box is not None or form.view == "clear":
        result.confidence = "medium"
    else:
        result.confidence = "low"
    first = form.damage[0]
    on = tail or seen or "the aircraft"
    result.message = (
        f"Draft defect report for {on}: {first.kind} on the {first.part} ({first.where}). "
        f"Confidence {result.confidence}. Needs engineer confirmation before anything changes."
    )
    if result.confidence == "low":
        result.message += (
            " The damage could not be located in the photo: a closer photo would help."
        )
    return result


def _next_leg(op: Operation, flight_no: str):
    legs = [
        leg
        for leg in op.legs.values()
        if leg.flight_no == flight_no.upper().replace(" ", "") and leg.off_block > op.now
    ]
    return min(legs, key=lambda leg: leg.off_block, default=None)


def _disruption(op: Operation, form: DisruptionNotice, result: Intake) -> Intake:
    if not form.is_flight_notice:
        result.status = Status.REJECTED
        result.message = "This does not look like a flight board or disruption notice."
        return result
    if form.readable == "unclear":
        return _unreadable(result, "notice")
    trip_of = {leg_id: t.trip_id for t in op.trips.values() for leg_id in t.leg_ids}
    found, unknown, checks = [], [], []
    for f in form.flights:
        leg = _next_leg(op, f.flight_no)
        if leg is None:
            unknown.append(f.flight_no)
            continue
        trip_id = trip_of.get(leg.leg_id)
        minutes = f.delay_minutes
        if not minutes and f.new_time:
            try:
                hh, mm = (int(x) for x in f.new_time.split(":"))
                scheduled = leg.off_block.astimezone(IST)
                minutes = (hh * 60 + mm) - (scheduled.hour * 60 + scheduled.minute)
                minutes += 24 * 60 if minutes < -12 * 60 else 0
            except ValueError:
                minutes = 0
        entry = {
            "flight_no": leg.flight_no,
            "status": f.status,
            "trip_id": trip_id,
            "scheduled": leg.off_block.astimezone(IST).strftime("%d %b %H:%M IST"),
        }
        if f.status == "delayed" and minutes > 0 and trip_id:
            entry["delay_minutes"] = minutes
            checks.append(
                {
                    "tool": "delay_impact",
                    "arguments": {
                        "trip_id": trip_id,
                        "hours": round(minutes / 60, 2),
                        "day": leg.day.isoformat(),
                    },
                }
            )
        found.append(entry)
    result.form["matched"] = found
    if not found:
        result.status = Status.CONFIRM
        result.message = (
            "None of the flights shown are ours in the coming days: "
            + (", ".join(unknown) or "no flights could be read")
            + "."
        )
        return result
    delayed = [f for f in found if "delay_minutes" in f]
    parts = [f"{f['flight_no']} ({f['trip_id']}) delayed {f['delay_minutes']} min" for f in delayed]
    parts += [
        f"{f['flight_no']} cancelled: the desk decides" for f in found if f["status"] == "cancelled"
    ]
    parts += [
        f"{f['flight_no']} gate change: no crew impact"
        for f in found
        if f["status"] == "gate_change"
    ]
    result.message = ("; ".join(parts) or "No delays or cancellations shown") + "."
    if unknown:
        result.message += f" Not ours: {', '.join(unknown)}."
    if checks:
        result.message += " Check what each delay does to the crew before acting."
        result.proposal = checks[0] if len(checks) == 1 else {"tool": "several", "calls": checks}
    return result
