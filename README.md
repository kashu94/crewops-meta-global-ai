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

## Calling the models

`crewops.models.ModelClient` speaks the OpenAI-compatible chat protocol to both Muse Spark
(Meta Model API) and Muse Spark Open (partner inference). Every call names its purpose and
reasoning effort, sends only parameters the APIs accept, retries rate limits with backoff,
and records prompt, completion, reasoning and cached tokens in a ledger, so the cost of each
step of an answer is known. Check your keys with:

```bash
uv run python -m crewops.models.check
```

## Tools and roles

The models never touch the data directly. They call ten typed tools (`crewops.agent`), each a
thin wrapper over the rules engine or the database:

| Tool | Returns |
|---|---|
| `search_crew` | Crew ids for a name |
| `find_trips` | Trips by date, airline, crew member or flight |
| `trip_details` | Legs with IST times and bookings, crew, and the trip's version |
| `crew_profile` | Certificates, hours against the limits, rest and upcoming duties |
| `check_legality` | All nine rules for one person on one trip, with the numbers |
| `find_cover` | Legal replacements cheapest first, and why others were ruled out |
| `absence_impact` | Every seat an absence empties, and the cheapest joint cover |
| `delay_impact` | Who a late departure pushes over a limit, and its cost |
| `roster_changes` | Who changed which trip, when and why |
| `assign_crew` | Makes the change, only for legal cover and the current version |

Each caller has a role. A `viewer` reads the operation, a `controller` may also change it, and
a `crew` member sees only their own record and trips. Arguments are validated before a tool
runs, and every problem comes back as a readable error for the model to recover from.

## MCP server

The same tools, with the same roles, for any MCP client:

```bash
uv run python -m crewops.mcp_server                                    # read-only
uv run python -m crewops.mcp_server --role controller --user m.iyer
```

For a desktop client, add it to the client's MCP configuration:

```json
{
  "mcpServers": {
    "crewops": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/crewops-meta-global-ai",
               "python", "-m", "crewops.mcp_server"]
    }
  }
}
```

## Database

`CREWOPS_STORE` picks where the operation lives:

* `memory` (the default): the demo operation, loaded at start. Changes last until restart.
  Nothing to set up.
* `dynamodb`: one DynamoDB table (`crewops-meta-<stage>-operation`, region `ap-south-1`).

The tests run against both, with DynamoDB simulated, so they need no AWS account. Load the
demo operation into the deployed table with:

```bash
uv run python -m crewops.store.init           # only if the table is empty
uv run python -m crewops.store.init --reset   # wipe and reload
```

`AWS_PROFILE` in `.env` picks the AWS credentials; keys never go in `.env`. To work against
DynamoDB without AWS, run DynamoDB Local, set `CREWOPS_DYNAMODB_ENDPOINT=http://localhost:8000`
and add `--create-table` to the first load.

Every change to a trip's crew is checked against the version of the trip the caller last
read, in the same transaction that records the change, so two controllers can never overwrite
each other's change, and each change is kept with who made it and why.

## Disclaimer

The duty rules here are a simplified model written for a demo. CrewOps is not certified for
operational use.

## License

MIT
