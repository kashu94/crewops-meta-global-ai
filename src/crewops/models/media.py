"""Meta's media models: Muse Voice Transcribe for speech, SAM 3.1 for finding things in images.

Both sit on the same key and base URL as Muse Spark, but speak their own formats:

* transcription takes a multipart upload (a JSON ``request`` part and a WAV ``audio`` part)
  and returns the transcript;
* SAM 3.1 runs on the Responses API, streams its results, and writes each match as special
  tokens, ``<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..;c=..|>`` followed by a mask. Only the boxes
  and their confidence are used here.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from crewops.models.client import ModelError, ModelUnavailable
from crewops.settings import Settings

BOX = re.compile(r"<\|box;([^|]*)\|>")


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class Box:
    x1: int
    y1: int
    x2: int
    y2: int
    width: int
    """Of the whole image, in pixels."""
    height: int
    confidence: float

    @property
    def share(self) -> float:
        """How much of the image the box covers, 0 to 1."""
        return (self.x2 - self.x1) * (self.y2 - self.y1) / max(1, self.width * self.height)


def parse_boxes(text: str) -> list[Box]:
    boxes = []
    for raw in BOX.findall(text):
        fields = dict(part.split("=", 1) for part in raw.split(";") if "=" in part)
        try:
            boxes.append(
                Box(
                    int(fields["x1"]),
                    int(fields["y1"]),
                    int(fields["x2"]),
                    int(fields["y2"]),
                    int(fields["w"]),
                    int(fields["h"]),
                    float(fields.get("c", 0)),
                )
            )
        except (KeyError, ValueError):
            continue
    return boxes


class MediaClient:
    def __init__(
        self,
        config: Settings,
        http: httpx.Client | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = config.meta_base_url
        self.api_key = config.model_api_key
        self.transcribe_model = config.transcribe_model
        self.segment_model = config.segment_model
        self.http = http
        self.timeout = timeout

    def _client(self) -> httpx.Client:
        if not self.api_key:
            raise ModelUnavailable("no API key configured for the meta models")
        return self.http or httpx.Client(timeout=self.timeout)

    def _done(self, http: httpx.Client) -> None:
        if self.http is None:
            http.close()

    def transcribe(self, wav: bytes, languages: list[str] | None = None) -> Transcript:
        """Speech to text. ``languages`` steers recognition (say ``["Hindi", "English"]``)."""
        request: dict[str, Any] = {
            "model": self.transcribe_model,
            "audioEncoding": "WAV",
            "mode": "PUSH_TO_TALK",
        }
        if languages:
            request["languageBias"] = languages
        http = self._client()
        try:
            response = http.post(
                f"{self.base_url}/asr/transcribe",
                headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                files={
                    "request": (None, json.dumps(request), "application/json"),
                    "audio": ("speech.wav", wav, "audio/wav"),
                },
            )
        except httpx.HTTPError as err:
            raise ModelError(f"transcription unreachable: {err}") from err
        finally:
            self._done(http)
        if response.is_error:
            raise ModelError(
                f"transcription returned {response.status_code}",
                status=response.status_code,
                body=response.text[:2000],
            )
        body = response.json()
        return Transcript(body.get("transcript", "").strip(), int(body.get("audioDurationMs", 0)))

    def segment(self, image: bytes, mime: str, phrase: str) -> list[Box]:
        """Every match for ``phrase`` in the image, with SAM 3.1's confidence."""
        data_url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        payload = {
            "model": self.segment_model,
            "stream": True,
            "metadata": {"include_confidence": "true"},
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": phrase},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "text/event-stream"}
        http = self._client()
        text = []
        try:
            with http.stream(
                "POST", f"{self.base_url}/responses", json=payload, headers=headers
            ) as response:
                if response.is_error:
                    response.read()
                    raise ModelError(
                        f"segmentation returned {response.status_code}",
                        status=response.status_code,
                        body=response.text[:2000],
                    )
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:])
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "response.output_text.delta":
                        text.append(event.get("delta", ""))
                    elif event.get("type") in ("error", "response.failed"):
                        raise ModelError(f"segmentation failed: {event}")
        except httpx.HTTPError as err:
            raise ModelError(f"segmentation unreachable: {err}") from err
        finally:
            self._done(http)
        return parse_boxes("".join(text))
