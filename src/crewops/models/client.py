"""Calls to Meta's models.

Muse Spark on the Meta Model API and Muse Spark Open on a partner endpoint speak the same
OpenAI-compatible chat protocol, so one client serves both. Every call:

* names its purpose and reasoning effort. Muse Spark reasons before it answers and bills for
  it, so routing a question gets ``minimal`` effort and only planning gets more;
* sends only parameters the APIs accept (no ``n``, ``stop`` or ``logprobs``);
* retries rate limits and server errors with backoff, honouring ``Retry-After``;
* records its token use, reasoning tokens included, in a ``Ledger``.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from crewops.settings import Settings

EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
MAX_RETRY_WAIT = 20.0


class ModelError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class ModelUnavailable(ModelError):
    """No API key is configured for the endpoint."""


@dataclass(frozen=True, slots=True)
class Endpoint:
    name: str
    base_url: str
    api_key: str
    model: str

    @classmethod
    def meta(cls, config: Settings, model: str | None = None) -> Endpoint:
        return cls(
            "meta", config.meta_base_url, config.model_api_key, model or config.advisor_model
        )

    @classmethod
    def open_weights(cls, config: Settings) -> Endpoint:
        return cls("open", config.open_model_base_url, config.open_model_api_key, config.open_model)


@dataclass(frozen=True, slots=True)
class Usage:
    endpoint: str
    model: str
    purpose: str
    effort: str
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    cached_tokens: int
    seconds: float
    attempts: int

    @classmethod
    def from_reply(cls, body: dict[str, Any], **fields: Any) -> Usage:
        usage = body.get("usage") or {}
        completion = usage.get("completion_tokens_details") or {}
        prompt = usage.get("prompt_tokens_details") or {}
        return cls(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            reasoning_tokens=completion.get("reasoning_tokens") or 0,
            cached_tokens=prompt.get("cached_tokens") or 0,
            **fields,
        )


class Ledger:
    """Every call's token use, kept in memory and optionally appended to a JSON-lines file."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._entries: list[Usage] = []

    def record(self, usage: Usage) -> None:
        with self._lock:
            self._entries.append(usage)
            if self.path is not None:
                with self.path.open("a", encoding="utf-8") as out:
                    out.write(json.dumps(asdict(usage)) + "\n")

    @property
    def entries(self) -> tuple[Usage, ...]:
        with self._lock:
            return tuple(self._entries)

    def totals(self) -> dict[str, dict[str, int]]:
        """Calls and tokens per model."""
        totals: dict[str, dict[str, int]] = {}
        for u in self.entries:
            t = totals.setdefault(
                u.model, {"calls": 0, "prompt": 0, "completion": 0, "reasoning": 0, "cached": 0}
            )
            t["calls"] += 1
            t["prompt"] += u.prompt_tokens
            t["completion"] += u.completion_tokens
            t["reasoning"] += u.reasoning_tokens
            t["cached"] += u.cached_tokens
        return totals


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: str
    """The model's arguments as sent: JSON text, not yet trusted."""


@dataclass(frozen=True, slots=True)
class Reply:
    content: str
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str
    usage: Usage
    reasoning: str | None = None
    """The model's reasoning text, where the endpoint returns it (Muse Spark Open does)."""

    def message(self) -> dict[str, Any]:
        """This reply as the assistant turn to send back with the tool results."""
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.arguments},
                }
                for c in self.tool_calls
            ]
        return message


def _strict(node: Any) -> Any:
    """A JSON schema tightened for structured output: no extra keys, every key required."""
    if isinstance(node, list):
        return [_strict(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {k: _strict(v) for k, v in node.items() if k not in ("default", "title")}
    if "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out["properties"])
    return out


def response_format(schema: type[BaseModel]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema.__name__,
            "strict": True,
            "schema": _strict(schema.model_json_schema()),
        },
    }


@dataclass
class ModelClient:
    endpoint: Endpoint
    ledger: Ledger = field(default_factory=Ledger)
    http: httpx.Client | None = None
    timeout: float = 120.0
    retries: int = 3
    backoff: float = 1.0
    sleep: Callable[[float], None] = time.sleep

    def chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        purpose: str,
        effort: str = "low",
        tools: Sequence[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        schema: type[BaseModel] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Reply:
        if not self.endpoint.api_key:
            raise ModelUnavailable(f"no API key configured for the {self.endpoint.name} models")
        if effort not in EFFORTS:
            raise ValueError(f"effort must be one of {', '.join(EFFORTS)}, not {effort!r}")
        payload: dict[str, Any] = {
            "model": self.endpoint.model,
            "messages": list(messages),
            "reasoning_effort": effort,
        }
        if tools:
            payload["tools"] = list(tools)
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        if schema is not None:
            payload["response_format"] = response_format(schema)
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature

        started = time.monotonic()
        body, attempts = self._post("/chat/completions", payload)
        usage = Usage.from_reply(
            body,
            endpoint=self.endpoint.name,
            model=body.get("model") or self.endpoint.model,
            purpose=purpose,
            effort=effort,
            seconds=round(time.monotonic() - started, 3),
            attempts=attempts,
        )
        self.ledger.record(usage)
        try:
            [choice] = body["choices"][:1]
            message = choice["message"]
        except (KeyError, ValueError) as err:
            raise ModelError("reply had no message", body=json.dumps(body)[:2000]) from err
        return Reply(
            content=message.get("content") or "",
            tool_calls=tuple(
                ToolCall(
                    id=c["id"], name=c["function"]["name"], arguments=c["function"]["arguments"]
                )
                for c in message.get("tool_calls") or ()
            ),
            finish_reason=choice.get("finish_reason") or "",
            usage=usage,
            reasoning=message.get("reasoning_content"),
        )

    def parse[M: BaseModel](
        self,
        messages: Sequence[dict[str, Any]],
        schema: type[M],
        *,
        purpose: str,
        effort: str = "low",
        max_tokens: int | None = None,
    ) -> tuple[M, Reply]:
        """A reply that must fit ``schema``, validated before it is returned."""
        reply = self.chat(
            messages, purpose=purpose, effort=effort, schema=schema, max_tokens=max_tokens
        )
        try:
            return schema.model_validate_json(reply.content), reply
        except ValidationError as err:
            raise ModelError(
                f"reply did not match {schema.__name__}", body=reply.content[:2000]
            ) from err

    # -- transport --------------------------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        http = self.http or httpx.Client(timeout=self.timeout)
        url = self.endpoint.base_url + path
        headers = {"Authorization": f"Bearer {self.endpoint.api_key}"}
        try:
            for attempt in range(1, self.retries + 2):
                last = attempt > self.retries
                try:
                    response = http.post(url, json=payload, headers=headers)
                except httpx.TransportError as err:
                    if last:
                        raise ModelError(f"{self.endpoint.name} models unreachable: {err}") from err
                    self.sleep(self._wait(attempt, None))
                    continue
                if response.status_code in RETRY_STATUSES and not last:
                    self.sleep(self._wait(attempt, response.headers.get("retry-after")))
                    continue
                if response.is_error:
                    raise ModelError(
                        f"{self.endpoint.name} models returned {response.status_code}",
                        status=response.status_code,
                        body=response.text[:2000],
                    )
                return response.json(), attempt
        finally:
            if self.http is None:
                http.close()
        raise AssertionError("unreachable")

    def _wait(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), MAX_RETRY_WAIT)
            except ValueError:
                pass
        return min(self.backoff * 2 ** (attempt - 1), MAX_RETRY_WAIT)
