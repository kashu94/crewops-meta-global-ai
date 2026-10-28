"""Runtime settings.

Read from the environment, with a `.env` file in the repository root filling any gaps. A value
exported in the shell always wins over the file, so a one-off override needs no edit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


@dataclass(frozen=True, slots=True)
class Settings:
    model_api_key: str
    meta_base_url: str
    advisor_model: str
    vision_model: str
    transcribe_model: str
    segment_model: str
    open_model_api_key: str
    open_model_base_url: str
    open_model: str
    stage: str
    aws_profile: str
    aws_region: str
    table_name: str
    dynamodb_endpoint: str
    seed_dir: Path

    @property
    def has_meta_api(self) -> bool:
        return bool(self.model_api_key)

    @property
    def has_open_model(self) -> bool:
        return bool(self.open_model_api_key)


def load_settings(env: dict[str, str] | None = None) -> Settings:
    merged = {**_read_dotenv(ROOT / ".env"), **(env if env is not None else os.environ)}

    def get(key: str, default: str = "") -> str:
        return merged.get(key) or default

    stage = get("CREWOPS_STAGE", "dev")
    return Settings(
        model_api_key=get("MODEL_API_KEY"),
        meta_base_url=get("META_BASE_URL", "https://api.meta.ai/v1").rstrip("/"),
        advisor_model=get("CREWOPS_ADVISOR_MODEL", "muse-spark-1.3"),
        vision_model=get("CREWOPS_VISION_MODEL", "muse-spark-1.3"),
        transcribe_model=get("CREWOPS_TRANSCRIBE_MODEL", "muse-voice-transcribe-1.0"),
        segment_model=get("CREWOPS_SEGMENT_MODEL", "sam-3.1"),
        open_model_api_key=get("OPEN_MODEL_API_KEY"),
        open_model_base_url=get("OPEN_MODEL_BASE_URL", "https://inference.baseten.co/v1").rstrip(
            "/"
        ),
        open_model=get("CREWOPS_OPEN_MODEL", "meta-models/muse-spark-open-1026"),
        stage=stage,
        aws_profile=get("AWS_PROFILE"),
        aws_region=get("AWS_REGION", "ap-south-1"),
        table_name=get("CREWOPS_TABLE", f"crewops-meta-{stage}-operation"),
        dynamodb_endpoint=get("CREWOPS_DYNAMODB_ENDPOINT"),
        seed_dir=Path(get("CREWOPS_SEED_DIR", str(ROOT / "data" / "seed"))),
    )


@lru_cache(maxsize=1)
def settings() -> Settings:
    return load_settings()
