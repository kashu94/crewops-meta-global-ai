import json

import httpx
import pytest
from pydantic import BaseModel

from crewops.models import Endpoint, Ledger, ModelClient, ModelError, ModelUnavailable
from crewops.models.client import response_format

ENDPOINT = Endpoint("meta", "https://models.test/v1", "key-1", "muse-spark-1.3")


def reply(content="ok", tool_calls=None, reasoning=None, usage=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    if reasoning:
        message["reasoning_content"] = reasoning
    return {
        "model": "muse-spark-1.3",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": usage
        or {
            "prompt_tokens": 17,
            "completion_tokens": 61,
            "completion_tokens_details": {"reasoning_tokens": 46},
            "prompt_tokens_details": {"cached_tokens": 8},
        },
    }


def client_for(*responses, ledger=None):
    """A client whose server answers with ``responses`` in turn and keeps every request."""
    sent = []
    queue = list(responses)

    def handle(request):
        sent.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body, headers = item if isinstance(item, tuple) else (200, item, {})
        return httpx.Response(status, json=body, headers=headers)

    client = ModelClient(
        ENDPOINT,
        ledger=ledger or Ledger(),
        http=httpx.Client(transport=httpx.MockTransport(handle)),
        sleep=lambda s: sent.append(("slept", s)),
    )
    return client, sent


class Intent(BaseModel):
    intent: str
    crew_ids: list[str]


def test_a_call_sends_only_supported_parameters_and_records_usage():
    client, sent = client_for(reply("ready"))
    result = client.chat([{"role": "user", "content": "hi"}], purpose="check", effort="minimal")

    [request] = sent
    body = json.loads(request.content)
    assert request.url == "https://models.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer key-1"
    assert body == {
        "model": "muse-spark-1.3",
        "messages": [{"role": "user", "content": "hi"}],
        "reasoning_effort": "minimal",
    }
    assert result.content == "ready"
    assert (result.usage.reasoning_tokens, result.usage.cached_tokens) == (46, 8)
    assert client.ledger.totals() == {
        "muse-spark-1.3": {
            "calls": 1,
            "prompt": 17,
            "completion": 61,
            "reasoning": 46,
            "cached": 8,
        }
    }


def test_tool_calls_come_back_and_round_trip_as_the_assistant_turn():
    call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "check_legality", "arguments": '{"crew_id":"C-1111"}'},
    }
    client, sent = client_for(reply("Checking.", tool_calls=[call]))
    tools = [{"type": "function", "function": {"name": "check_legality", "parameters": {}}}]
    result = client.chat([], purpose="plan", tools=tools, tool_choice="auto")

    body = json.loads(sent[0].content)
    assert body["tools"] == tools and body["tool_choice"] == "auto"
    [tc] = result.tool_calls
    assert (tc.name, tc.arguments) == ("check_legality", '{"crew_id":"C-1111"}')
    assert result.message() == {"role": "assistant", "content": "Checking.", "tool_calls": [call]}


def test_structured_replies_are_validated_against_the_schema():
    client, sent = client_for(reply('{"intent": "absence", "crew_ids": ["C-1111"]}'))
    parsed, _ = client.parse([], Intent, purpose="route", effort="minimal")
    assert parsed == Intent(intent="absence", crew_ids=["C-1111"])
    assert json.loads(sent[0].content)["response_format"] == response_format(Intent)

    client, _ = client_for(reply('{"intent": "absence"}'))
    with pytest.raises(ModelError, match="did not match Intent"):
        client.parse([], Intent, purpose="route")


def test_the_schema_is_strict():
    schema = response_format(Intent)["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["additionalProperties"] is False
    assert schema["schema"]["required"] == ["intent", "crew_ids"]


def test_rate_limits_and_dropped_connections_are_retried():
    client, sent = client_for(
        (429, {"error": "slow down"}, {"retry-after": "2"}),
        httpx.ConnectError("reset"),
        reply("ok"),
    )
    result = client.chat([], purpose="check")
    assert result.usage.attempts == 3
    assert [s for s in sent if isinstance(s, tuple)] == [("slept", 2.0), ("slept", 2.0)]


def test_client_errors_are_not_retried():
    client, sent = client_for((400, {"error": "bad parameter"}, {}))
    with pytest.raises(ModelError) as err:
        client.chat([], purpose="check")
    assert err.value.status == 400 and "bad parameter" in err.value.body
    assert len(sent) == 1


def test_retries_give_up_with_the_last_error():
    client, _ = client_for(*[(503, {"error": "busy"}, {})] * 4)
    with pytest.raises(ModelError) as err:
        client.chat([], purpose="check")
    assert err.value.status == 503


def test_open_weight_reasoning_text_is_kept():
    client, _ = client_for(reply("ready", reasoning="User wants one word."))
    assert client.chat([], purpose="check").reasoning == "User wants one word."


def test_a_missing_key_or_unknown_effort_fails_before_any_call():
    client, sent = client_for()
    client.endpoint = Endpoint("open", "https://x/v1", "", "m")
    with pytest.raises(ModelUnavailable):
        client.chat([], purpose="check")
    client.endpoint = ENDPOINT
    with pytest.raises(ValueError, match="effort"):
        client.chat([], purpose="check", effort="max")
    assert sent == []


def test_the_ledger_appends_to_a_file(tmp_path):
    path = tmp_path / "usage.jsonl"
    client, _ = client_for(reply(), reply(), ledger=Ledger(path))
    client.chat([], purpose="route", effort="minimal")
    client.chat([], purpose="plan", effort="high")
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [(r["purpose"], r["effort"]) for r in lines] == [("route", "minimal"), ("plan", "high")]
