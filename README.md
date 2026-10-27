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

## The rules

Nine rules, modelled on Indian flight duty time limitations and simplified for a demo. Each
returns the numbers behind its verdict ("1h45m over the 12h limit for 4 sectors"), not a bare
pass or fail.

| Rule | Check |
|---|---|
| FDTL-01 | Flight duty period at most 13 h, 30 min less for each sector beyond the second |
| FDTL-02 | A duty touching 00:00-06:00 IST: at most 10 h and two night landings |
| FDTL-03 | At most 60 duty hours in any 7 calendar days |
| FDTL-04 | At most 100 block hours in any 28 calendar days |
| FDTL-05 | Rest of at least 12 h, and at least as long as the duty before it |
| FDTL-06 | Two clear days in a row in every 7 |
| FDTL-07 | Active, rated on the type, flying for their own airline |
| FDTL-08 | Every certificate valid on every duty date |
| FDTL-09 | Called out from home base, or positioned there on a same-day flight |

Limits are parameters in `data/seed/rules.json`, so changing one needs no code change.
Windows are checked up to every later rostered day the new duty affects, so a cover that
looks legal today cannot break a limit on a trip already planned for Thursday.

## Demo data

Two weeks of three fictional Hyderabad airlines, generated deterministically. See
[data/seed/README.md](data/seed/README.md).

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
