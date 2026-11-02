import io
import time
from datetime import UTC, date, datetime, timedelta

import jwt
import pytest
from conftest import SEED_DIR
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_advisor import FixedRouter, Script
from test_intake import SHARP, Reader, defect, note

import crewops.api.app as api_module
from crewops.agent.advisor import Advisor
from crewops.agent.router import Intent
from crewops.api.app import Services, create_app
from crewops.api.auth import caller_from_claims, verify
from crewops.engine.clock import IST
from crewops.engine.watch import scan
from crewops.models import ModelError
from crewops.models.media import Box, Transcript
from crewops.seed import read_meta
from crewops.settings import load_settings
from crewops.store import MemoryStore

BASE = {
    "MODEL_API_KEY": "",
    "OPEN_MODEL_API_KEY": "",
    "PROMPT_GUARD_URL": "",
    "CREWOPS_SEED_DIR": str(SEED_DIR),
    "CREWOPS_STORE": "memory",
    "CREWOPS_AUTH": "demo",
    "CREWOPS_BUCKET": "",
}
CONTROLLER = {"X-Demo-User": "m.iyer", "X-Demo-Role": "controller"}
VIEWER = {"X-Demo-User": "board", "X-Demo-Role": "auditor"}
ANJALI = {"X-Demo-User": "anjali", "X-Demo-Role": "crew", "X-Demo-Crew-Id": "C-1157"}


class Media:
    def __init__(self):
        self.heard = []

    def transcribe(self, wav, languages=None):
        self.heard.append(languages)
        return Transcript("Pooja kal bimaar hai", 2100)

    def segment(self, image, mime, phrase):
        return [Box(100, 100, 300, 260, 900, 600, 0.9)]


class Writer:
    def parse(self, *args, **kwargs):
        raise ModelError("offline")


@pytest.fixture
def services(seed, monkeypatch):
    monkeypatch.setattr(api_module, "draw_card", lambda *a, **k: None)
    config = load_settings({**BASE, "CREWOPS_DAILY_ASKS": "3"})
    store = MemoryStore()
    store.load(seed, read_meta(SEED_DIR))
    s = Services(config, store)
    s.media = Media()
    s.writer = Writer()
    s._advisor = Advisor(
        store,
        Script("C-1157 is legal for T-1018.", "Second answer."),
        seed.rules,
        router=FixedRouter(Intent.LEGALITY),
        desk=s.desk,
    )
    return s


@pytest.fixture
def client(services):
    return TestClient(create_app(services.config, services))


def test_public_endpoints_and_pages(services, tmp_path, monkeypatch):
    # The console is a static export: a folder per page, each with its index.html.
    (tmp_path / "speaker").mkdir()
    (tmp_path / "index.html").write_text("<title>CrewOps Console</title>")
    (tmp_path / "speaker" / "index.html").write_text("<title>Ops-room speaker</title>")
    monkeypatch.setattr(api_module, "WEB", tmp_path)
    client = TestClient(create_app(services.config, services))
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/config").json()["auth"] == "demo"
    assert "CrewOps Console" in client.get("/").text
    for path in ("/speaker/", "/speaker"):  # with or without the slash, never a redirect
        page = client.get(path, follow_redirects=False)
        assert page.status_code == 200 and "speaker" in page.text
    assert client.get("/../etc/passwd").status_code == 404
    accounts = client.get("/api/accounts/demo").json()["accounts"]
    assert len({a["role"] for a in accounts}) == 8
    assert not any("password" in a for a in accounts)


def test_me_reports_the_identity_role_and_the_operation_clock(client):
    me = client.get("/api/me", headers=ANJALI).json()
    assert (me["user"], me["role"], me["crew_id"]) == ("anjali", "crew", "C-1157")
    assert "assign_crew" not in me["tools"] and me["clock"].endswith("IST")
    assert client.get("/api/me", headers={"X-Demo-Role": "pilot"}).status_code == 400


def test_tools_go_through_the_same_role_checks(client):
    found = client.post("/api/tools/search_crew", json={"query": "chowdary"}, headers=VIEWER)
    assert found.json()["matches"][0]["crew_id"] == "C-1111"
    refused = client.post("/api/tools/assign_crew", json={}, headers=VIEWER).json()
    assert "cannot use" in refused["error"]


def test_a_change_moves_the_version_screens_poll(client):
    before = client.get("/api/version", headers=VIEWER).json()
    opened = client.post(
        "/api/tools/start_callout",
        json={"trip_id": "T-1018", "replace_crew_id": "C-1111"},
        headers=CONTROLLER,
    )
    assert opened.json()["waiting_for"] == "C-1157"
    after = client.get("/api/version", headers=VIEWER).json()
    assert after["callouts"] != before["callouts"] and after["notices"] > before["notices"]
    mine = client.get("/api/notices", headers=ANJALI).json()["notices"]
    assert mine[0]["subject"] == "Callout: Captain on T-1018"


def test_asking_returns_the_answer_with_its_trace_and_counts_against_the_allowance(client):
    first = client.post(
        "/api/ask", json={"question": "Is C-1157 legal for T-1018?"}, headers=CONTROLLER
    ).json()
    assert first["text"] == "C-1157 is legal for T-1018." and first["route"]["intent"] == "legality"
    assert first["conversation_id"] and isinstance(first["calls"], list)
    again = client.post(
        "/api/ask",
        json={"question": "And T-1010?", "conversation_id": first["conversation_id"]},
        headers=CONTROLLER,
    ).json()
    assert again["conversation_id"] == first["conversation_id"]
    client.post("/api/voice", files={"audio": ("a.wav", b"RIFF", "audio/wav")}, headers=CONTROLLER)
    over = client.post("/api/ask", json={"question": "One more?"}, headers=CONTROLLER)
    assert over.status_code == 429


def test_voice_passes_only_known_language_hints(client, services):
    r = client.post(
        "/api/voice",
        files={"audio": ("a.wav", b"RIFF", "audio/wav")},
        data={"languages": "Hindi,Klingon,English"},
        headers=CONTROLLER,
    )
    assert r.json() == {"text": "Pooja kal bimaar hai", "seconds": 2.1}
    assert services.media.heard == [["Hindi", "English"]]


def test_photos_come_back_with_status_box_and_proposal(client, services):
    services.reader = Reader(defect())
    r = client.post(
        "/api/intake",
        files={"image": ("d.jpg", SHARP, "image/jpeg")},
        data={"kind": "defect", "tail": "VT-SYA"},
        headers=CONTROLLER,
    ).json()
    assert (r["status"], r["confidence"], r["box"]["confidence"]) == ("draft", "high", 0.9)
    services.reader = Reader(note())
    r = client.post(
        "/api/intake",
        files={"image": ("n.jpg", SHARP, "image/jpeg")},
        data={"kind": "sick_note"},
        headers=CONTROLLER,
    ).json()
    assert r["proposal"]["tool"] == "report_unavailable"
    bad = client.post(
        "/api/intake",
        files={"image": ("x.gif", io.BytesIO(b"GIF89a"), "image/gif")},
        data={"kind": "defect"},
        headers=CONTROLLER,
    )
    assert bad.status_code == 415


def test_the_board_shows_brief_issues_and_callouts(client):
    client.post(
        "/api/tools/start_callout",
        json={"trip_id": "T-1018", "replace_crew_id": "C-1111"},
        headers=CONTROLLER,
    )
    b = client.get("/api/board", headers=VIEWER).json()
    assert b["brief"]["written_by"] == "template"
    assert b["brief"]["mood"] == "critical"
    assert b["issues"][0]["crew_id"] == "C-1111"
    assert b["callouts"][0]["trip_id"] == "T-1018"
    assert b["next_24h"]["open_callouts"] == 1 and b["next_24h"]["illegal"] == 1
    assert len(b["departures"]) == min(10, b["next_24h"]["flights"])
    assert b["desks"] == [{"controller": "m.iyer", "open": 1, "filled": 0, "to_approve": 0}]
    sy_captains = [x for x in b["standby"] if (x["airline"], x["rank"]) == ("SY", "Captain")]
    assert len(sy_captains) == 1 and sy_captains[0]["on_call"] >= 1
    assert b["latest"] == []  # the callout messaged the crew member, not the desk
    assert client.get("/api/card/../etc/passwd").status_code == 404


def test_cognito_mode_requires_a_valid_signed_token(seed, monkeypatch):
    config = load_settings(
        {
            **BASE,
            "CREWOPS_AUTH": "cognito",
            "COGNITO_POOL_ID": "ap-south-1_x",
            "COGNITO_CLIENT_ID": "client",
        }
    )
    store = MemoryStore()
    store.load(seed, read_meta(SEED_DIR))
    client = TestClient(create_app(config, Services(config, store)))
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    board = client.get("/api/board")  # a TV with no sign-in: read-only, never runs a model
    assert board.status_code == 200 and board.json()["brief"] is None
    assert board.json()["issues"][0]["crew_id"] == "C-1111"


def test_tokens_are_checked_for_signature_audience_and_issuer():
    config = load_settings(
        {
            **BASE,
            "CREWOPS_AUTH": "cognito",
            "COGNITO_POOL_ID": "ap-south-1_x",
            "COGNITO_CLIENT_ID": "client",
            "AWS_REGION": "ap-south-1",
        }
    )
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": private.public_key()})()

    claims = {
        "sub": "u1",
        "aud": "client",
        "token_use": "id",
        "exp": int(time.time()) + 600,
        "iss": "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_x",
        "cognito:username": "s.reddy",
        "cognito:groups": ["controller"],
    }
    good = jwt.encode(claims, private, algorithm="RS256")
    assert verify(good, config, Keys())["cognito:username"] == "s.reddy"
    with pytest.raises(HTTPException):
        verify(jwt.encode({**claims, "aud": "other"}, private, algorithm="RS256"), config, Keys())
    with pytest.raises(HTTPException):
        verify(jwt.encode({**claims, "exp": 1}, private, algorithm="RS256"), config, Keys())

    assert caller_from_claims(claims).role.value == "controller"
    crew = caller_from_claims({**claims, "cognito:groups": ["crew"], "custom:crew_id": "C-1157"})
    assert crew.crew_id == "C-1157"
    with pytest.raises(HTTPException):
        caller_from_claims({**claims, "cognito:groups": []})


def test_the_speaker_feed_is_public_and_says_how_each_notice_sounds(client):
    client.post(
        "/api/tools/start_callout",
        json={"trip_id": "T-1018", "replace_crew_id": "C-1111"},
        headers=CONTROLLER,
    )
    feed = client.get("/api/speaker").json()
    assert feed["waiting"] == {
        "plans": 0,
        "decisions": 0,
        "proposals": 0,
        "resolutions": 0,
        "disruptions": 0,
    }
    illegal, running = feed["summary"]
    assert illegal.startswith("1 rostered crew member is not legal: Pooja Chowdary on T-1018")
    assert running.startswith("Callout running for Captain on T-1018: waiting for Anjali Goud")


def test_an_approval_needs_an_approver_through_the_api(client):
    trip = client.post("/api/tools/trip_details", json={"trip_id": "T-1018"}, headers=CONTROLLER)
    version = trip.json()["version"]
    plan = client.post(
        "/api/tools/assign_crew",
        json={
            "trip_id": "T-1018",
            "replace_crew_id": "C-1111",
            "with_crew_id": "C-1157",
            "expected_version": version,
            "reason": "medical lapses",
        },
        headers=CONTROLLER,
    ).json()
    assert plan["status"] == "submitted"
    feed = client.get("/api/speaker").json()
    assert feed["waiting"]["plans"] == 1
    assert feed["items"][0]["tone"] == "pending"
    reddy = {"X-Demo-User": "s.reddy", "X-Demo-Role": "controller"}
    review = {"plan_id": plan["plan_id"], "action": "approve"}
    refused = client.post("/api/tools/review_plan", json=review, headers=reddy).json()
    assert "only an approver" in refused["error"]
    nair = {"X-Demo-User": "a.nair", "X-Demo-Role": "approver"}
    done = client.post("/api/tools/review_plan", json=review, headers=nair).json()
    assert done["status"] == "approved"
    log = client.get("/api/log/activity", headers=CONTROLLER).json()["entries"]
    assert [e["action"] for e in log[:2]] == ["review_plan", "assign_crew"]


def test_only_an_admin_reads_the_security_log(client):
    assert client.get("/api/log/security", headers=CONTROLLER).status_code == 403
    crew = {"X-Demo-User": "anjali", "X-Demo-Role": "crew", "X-Demo-Crew-Id": "C-1157"}
    assert client.get("/api/log/activity", headers=crew).status_code == 403
    admin = {"X-Demo-User": "k.menon", "X-Demo-Role": "admin"}
    assert client.get("/api/log/security", headers=admin).json() == {"entries": []}


def test_on_the_wall_clock_the_demo_starts_today(monkeypatch):
    monkeypatch.setattr(api_module, "draw_card", lambda *a, **k: None)
    s = Services(load_settings({**BASE, "CREWOPS_LIVE_CLOCK": "true"}), MemoryStore())
    today = datetime.now(IST).date()
    assert s.days["first"] == today.isoformat()
    op = s.store.operation()
    assert abs((op.now - datetime.now(UTC)).total_seconds()) < 60
    [illegal] = [i for i in scan(op) if i.kind == "illegal"]
    assert (illegal.crew_id, illegal.trip_id) == ("C-1111", "T-1018")
    assert illegal.day == today + timedelta(days=6), "the same problem, the same days ahead"
    assert s.store.meta()["shifted_days"] == (today - date(2026, 10, 30)).days


def test_a_checked_photo_is_kept_with_the_report_it_backs(client, services):
    services.reader = Reader(defect())
    photo = {"image": ("d.jpg", SHARP, "image/jpeg")}
    kept = client.post(
        "/api/intake",
        files=photo,
        data={"kind": "defect", "tail": "VT-SYA", "keep": "true"},
        headers=CONTROLLER,
    ).json()
    fault = {
        "kind": "aircraft_technical",
        "tail": "VT-SYA",
        "start": "2026-11-05T05:00",
        "end": "2026-11-05T09:00",
    }
    reddy = {"X-Demo-User": "s.reddy", "X-Demo-Role": "controller"}
    theirs = {**fault, "evidence_ids": [kept["evidence_id"]]}
    assert (
        "no photo"
        in client.post("/api/tools/report_disruption", json=theirs, headers=reddy).json()["error"]
    )
    report = client.post("/api/tools/report_disruption", json=theirs, headers=CONTROLLER).json()
    assert report["evidence"] == {
        "level": "high",
        "label": "Photo checked, high confidence",
        "photos": 1,
    }
    assert report["details"]["evidence"][0]["message"].startswith("Draft defect report")
    assert client.get(f"/api/evidence/{kept['evidence_id']}", headers=CONTROLLER).content == SHARP
    assert client.get(f"/api/evidence/{kept['evidence_id']}", headers=ANJALI).status_code == 403
    bare = client.post("/api/tools/report_disruption", json=fault, headers=CONTROLLER).json()
    assert bare["evidence"]["label"] == "No photo"
    assert "maintenance confirms" in bare["details"]["evidence_note"]


def test_a_note_that_does_not_match_the_report_is_flagged(client, services):
    services.reader = Reader(note())
    kept = client.post(
        "/api/intake",
        files={"image": ("n.jpg", SHARP, "image/jpeg")},
        data={"kind": "sick_note", "keep": "true"},
        headers=CONTROLLER,
    ).json()
    form = services.store.get_doc("evidence", kept["evidence_id"])
    [crew_id] = form["crew_ids"]
    first, last = form["days"]

    def sick(crew, day_one, day_two):
        return client.post(
            "/api/tools/report_disruption",
            json={
                "kind": "crew_unavailable",
                "crew_ids": [crew],
                "first_day": day_one,
                "last_day": day_two,
                "evidence_ids": [kept["evidence_id"]],
            },
            headers=CONTROLLER,
        ).json()["details"]["evidence"][0]

    same = sick(crew_id, first, last)
    assert same["check"] == "The photo matches the person and the dates reported."
    assert "Confirm to record" not in same["message"]
    other = sick("C-1157", first, last)
    assert other["check"].startswith(f"The photo names {crew_id}")
