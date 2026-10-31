"""Runtime settings.

Read from the environment, with a `.env` file in the repository root filling any gaps. A value
exported in the shell always wins over the file, so a one-off override needs no edit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(os.environ.get("CREWOPS_ROOT") or Path(__file__).resolve().parents[2])
"""The repository root, or where the deployed bundle unpacks (``CREWOPS_ROOT``)."""
STORES = ("memory", "dynamodb")
AUTH_MODES = ("demo", "cognito")


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    # utf-8-sig: Windows editors may start the file with a byte-order mark
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
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
    store: str
    aws_profile: str
    aws_region: str
    table_name: str
    dynamodb_endpoint: str
    prompt_guard_url: str
    prompt_guard_token: str
    usage_log: Path | None
    wonder_model: str
    image_model: str
    auth: str
    """``demo``: callers pick a demo identity (local use). ``cognito``: signed-in users only."""
    cognito_pool_id: str
    cognito_client_id: str
    bucket: str
    """Where generated images are kept when deployed; empty keeps them in memory."""
    alert_topic_arn: str
    daily_asks: int
    """Model-backed requests allowed per day across all users, to protect the credits."""
    board_art: bool
    """Draw artwork for the shift brief with Muse Image (off: the board shows text only)."""
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
    store = get("CREWOPS_STORE", "memory")
    if store not in STORES:
        raise ValueError(f"CREWOPS_STORE must be one of {', '.join(STORES)}, not {store!r}")
    auth = get("CREWOPS_AUTH", "demo")
    if auth not in AUTH_MODES:
        raise ValueError(f"CREWOPS_AUTH must be one of {', '.join(AUTH_MODES)}, not {auth!r}")
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
        store=store,
        aws_profile=get("AWS_PROFILE"),
        aws_region=get("AWS_REGION", "ap-southeast-2"),
        table_name=get("CREWOPS_TABLE", f"crewops-meta-{stage}-operation"),
        dynamodb_endpoint=get("CREWOPS_DYNAMODB_ENDPOINT"),
        prompt_guard_url=get("PROMPT_GUARD_URL"),
        prompt_guard_token=get("PROMPT_GUARD_TOKEN"),
        usage_log=Path(get("CREWOPS_USAGE_LOG")) if get("CREWOPS_USAGE_LOG") else None,
        wonder_model=get("CREWOPS_WONDER_MODEL", "muse-wonder-1.0"),
        image_model=get("CREWOPS_IMAGE_MODEL", "muse-image-1.0"),
        auth=auth,
        cognito_pool_id=get("COGNITO_POOL_ID"),
        cognito_client_id=get("COGNITO_CLIENT_ID"),
        bucket=get("CREWOPS_BUCKET"),
        alert_topic_arn=get("CREWOPS_ALERT_TOPIC_ARN"),
        daily_asks=int(get("CREWOPS_DAILY_ASKS", "300")),
        board_art=get("CREWOPS_BOARD_ART", "false").lower() in ("1", "true", "yes"),
        seed_dir=Path(get("CREWOPS_SEED_DIR", str(ROOT / "data" / "seed"))),
    )


@lru_cache(maxsize=1)
def settings() -> Settings:
    return load_settings()
