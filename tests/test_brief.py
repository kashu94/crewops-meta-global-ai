import base64

import httpx
import pytest

from crewops.engine import build_operation
from crewops.models import ModelError
from crewops.ops.brief import (
    BriefText,
    MemoryImages,
    card_key,
    draw_card,
    facts,
    mood_of,
    write_brief,
)
from crewops.seed import load_dataset
from crewops.settings import ROOT, load_settings


@pytest.fixture(scope="module")
def op():
    return build_operation(load_dataset(ROOT / "data" / "seed"))


class Writer:
    def __init__(self, reply):
        self.reply = reply

    def parse(self, messages, schema, **kwargs):
        if isinstance(self.reply, Exception):
            raise self.reply
        assert schema is BriefText
        return self.reply, None


def test_the_facts_lead_with_what_breaks_a_rule(op):
    f = facts(op, [])
    assert [i["crew_id"] for i in f["illegal"]] == ["C-1111"]
    assert f["illegal"][0]["cost_inr"] == 20840
    assert mood_of(f) == "critical"
    assert mood_of({**f, "illegal": [], "fatigue": []}) == "calm"


def test_a_brief_from_muse_wonder_is_kept_when_every_figure_checks_out(op):
    good = BriefText(
        headline="Cover T-1018 now",
        lines=["Pooja Chowdary (C-1111) cannot fly T-1018; cover C-1157 for INR 20840."],
    )
    brief = write_brief(op, [], Writer(good))
    assert (brief.written_by, brief.verified, brief.lines) == ("muse-wonder", True, good.lines)


def test_a_brief_with_an_invented_figure_falls_back_to_the_template(op):
    bad = BriefText(headline="Cover T-1018", lines=["Cover C-1157 for INR 19000."])
    brief = write_brief(op, [], Writer(bad))
    assert brief.written_by == "template"
    assert brief.lines[0].startswith("T-1018: Pooja Chowdary (C-1111)")
    assert write_brief(op, [], Writer(ModelError("down"))).written_by == "template"
    assert write_brief(op, [], None).headline == "Action needed"


def test_the_card_is_drawn_once_per_mood_per_day_with_no_text_in_it():
    sent = []
    jpeg = base64.b64encode(b"\xff\xd8 card").decode()

    def handle(request):
        sent.append(request)
        return httpx.Response(200, json={"data": [{"b64_json": jpeg}]})

    config = load_settings({"MODEL_API_KEY": "k", "META_BASE_URL": "https://models.test/v1"})
    images = MemoryImages()
    client = httpx.Client(transport=httpx.MockTransport(handle))
    key = draw_card(config, images, "critical", http=client)
    assert key == card_key("critical") and images.get(key) == b"\xff\xd8 card"
    assert draw_card(config, images, "critical", http=client) == key
    assert len(sent) == 1
    body = sent[0].read().decode()
    assert '"model":"muse-image-1.0"' in body.replace(" ", "") and "No text" in body
