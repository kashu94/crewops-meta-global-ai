# CrewOps

Crew control for regional airlines, built on Meta's Muse models.

At 04:10 a first officer sends a photo of a doctor's note to the crew desk. Their trip leaves
at 06:30. Today a controller digs through the roster, duty-hour sheets and licence records to
find someone who is rested, rated, current and close enough to the airport, and works out by
hand whether the cover breaks a duty limit later in the week. CrewOps does that in seconds,
and shows its working.

> The model reads, listens, plans and explains. It never does the arithmetic.

Every crew id, duty hour, verdict and rupee in an answer comes from a deterministic rules
engine. The models decide what to look up and how to say it, and a verifier checks the final
wording against the engine's results before anyone sees it.

## Status

Under active development for the Meta Global AI Developer Hackathon (October 26 to
November 4, 2026). This README grows with the code.

## How Meta's models are used

| Job | Model |
|---|---|
| Choosing which engine tools to call, drafting the answer | Muse Spark 1.3 (Meta Model API) |
| Reading photos of sick notes, handwritten roster swaps and defect slips | Muse Spark 1.3 vision |
| Spoken questions from the crew desk | Muse Voice Transcribe |
| Marking the damaged area on an aircraft defect photo | SAM 3.1 |
| Fast triage and plain-language rewrites | Muse Spark Open (open weights, partner inference) |

## Running the tests

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check .
```

Copy `.env.example` to `.env` and fill in `MODEL_API_KEY` to use the hosted models.

## Disclaimer

The duty rules here are a simplified model written for a demo. CrewOps is not certified for
operational use.

## License

MIT
