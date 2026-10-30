"""Screening what people type before any model reads it.

Two layers, cheapest first; the first to block wins:

1. ``PatternGuard``: length limit and well-known injection phrasings, in microseconds.
2. ``PromptGuard``: Meta's Llama Prompt Guard 2 classifier, served behind a small HTTP
   endpoint (``POST {"text": ...}`` returning ``{"label": ..., "score": ...}``).

What a screened question can still do is bounded anyway: tools check the caller's role, and
roster changes need legal cover and the trip's current version. The guard keeps abuse away
from the models and out of the logs. If the classifier is unreachable the pattern layer still
applies and the answer is marked with what screened it, rather than refusing every question.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import httpx

from crewops.agent.advisor import Guard, Screening

MAX_CHARS = 2000

INJECTION = re.compile(
    r"\b(ignore|disregard|forget|override)\b.{0,40}\b(instructions?|rules|prompt|guidelines)\b"
    r"|\b(system|developer)\s+(prompt|message|instructions?)\b"
    r"|\byou are now\b|\bdeveloper mode\b|\bjailbreak\w*\b|\bDAN\b"
    r"|\b(reveal|print|show|repeat)\b.{0,30}\b(your|the)\s+(prompt|instructions|rules)\b",
    re.IGNORECASE | re.DOTALL,
)


class PatternGuard:
    def screen(self, text: str) -> Screening:
        if len(text) > MAX_CHARS:
            return Screening(False, f"longer than {MAX_CHARS} characters", "patterns")
        if INJECTION.search(text):
            return Screening(False, "prompt injection", "patterns")
        return Screening(True, by="patterns")


class PromptGuard:
    BLOCK_LABELS = frozenset({"MALICIOUS", "INJECTION", "JAILBREAK", "LABEL_1"})

    def __init__(
        self,
        url: str,
        token: str = "",
        threshold: float = 0.8,
        http: httpx.Client | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.url = url
        self.token = token
        self.threshold = threshold
        self.http = http
        self.timeout = timeout

    def screen(self, text: str) -> Screening:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        http = self.http or httpx.Client(timeout=self.timeout)
        try:
            response = http.post(self.url, json={"text": text}, headers=headers)
            response.raise_for_status()
            body = response.json()
            label, score = str(body["label"]).upper(), float(body["score"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return Screening(True, "classifier unavailable", "prompt-guard-unavailable")
        finally:
            if self.http is None:
                http.close()
        if label in self.BLOCK_LABELS and score >= self.threshold:
            return Screening(False, f"prompt injection ({score:.2f})", "prompt-guard")
        return Screening(True, by="prompt-guard")


class GuardChain:
    def __init__(self, guards: Sequence[Guard]) -> None:
        self.guards = tuple(guards)

    def screen(self, text: str) -> Screening:
        last = Screening(True)
        for guard in self.guards:
            last = guard.screen(text)
            if not last.allowed:
                return last
        return last
