"""Check the model keys in ``.env`` work: one tiny call to each configured endpoint.

uv run python -m crewops.models.check
"""

from __future__ import annotations

from crewops.models.client import Endpoint, ModelClient, ModelError
from crewops.settings import settings


def main() -> int:
    config = settings()
    failed = 0
    for endpoint in (Endpoint.meta(config), Endpoint.open_weights(config)):
        client = ModelClient(endpoint)
        try:
            reply = client.chat(
                [{"role": "user", "content": "Reply with the single word: ready"}],
                purpose="check",
                effort="minimal",
                max_tokens=400,
            )
        except ModelError as err:
            failed += 1
            print(f"{endpoint.name:5} {endpoint.model}: FAILED, {err}")
            continue
        u = reply.usage
        print(
            f"{endpoint.name:5} {u.model}: {reply.content.strip()!r} "
            f"({u.prompt_tokens} in, {u.completion_tokens} out, {u.reasoning_tokens} reasoning, "
            f"{u.seconds:.1f}s)"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
