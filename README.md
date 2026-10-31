# CrewOps

[![CI](https://github.com/kashu94/crewops-meta-global-ai/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/kashu94/crewops-meta-global-ai/actions/workflows/ci.yml)

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

| Job | Model | How |
|---|---|---|
| Planning each answer: which engine tools to call, then the reply | **Muse Spark 1.3** | Tool calling, reasoning effort set per kind of question, prompt caching of the rule book |
| Sorting each question (absence, delay, cover, legality, change, lookup) and flagging attacks on the assistant | **Muse Spark Open** (open weights, on Baseten) | Strict JSON-schema structured output; 8 of 8 unseen phrasings routed right where keyword rules got 3 |
| Reading photos: sick notes, roster swaps, certificates, departures boards, aircraft defects | **Muse Spark 1.3 vision** | Each photo fills a fixed form (structured output); code decides what happens |
| Finding the damage in a defect photo | **SAM 3.1** | Streamed segmentation; its box and confidence are one of the signals behind the confidence level |
| Spoken questions, including Hindi, Telugu and mixed speech | **Muse Voice Transcribe** | Push-to-talk WAV recorded in the browser, with a language hint |
| The shift brief on the ops board | **Muse Wonder** | Structured output, then the same evidence check as every answer |
| Optional artwork for the brief (`CREWOPS_BOARD_ART`) | **Muse Image** | One picture per mood per day, no text in it |

No model ever does the arithmetic: every crew id, hour, cost and verdict comes from the rules
engine, and a deterministic check compares each figure in an answer with the tools' results.

## Try it

| Where | What |
|---|---|
| Web console (`/`) | Ask by text or voice, see how each answer was made (route, tool calls, evidence check, tokens), run the desk (issues, callouts, unavailability), find cover with withdrawn crew struck through, check photos, read the scorecard |
| Ops board (`/board`) | The ops-room wall: next 24 hours, shift brief, controller desks, callouts, the watch, departures, standby cover. Read-only, no sign-in |
| Fire TV (`tv/`) | The same board as a Vega OS app, **CrewOps Board (Meta)** |
| MCP server | The tools, with roles, for any MCP client |
| Terminal | `uv run python -m crewops.agent.chat` |

Run it locally (demo data in memory, pick a demo identity at the top right):

```bash
uv run python -m crewops.api        # http://localhost:8000
```

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
| FDTL-08 | Every certificate valid on every date the duty touches (IST); not valid on its expiry date |
| FDTL-09 | Called out from home base, or positioned there on a same-day flight with a free seat |

Limits are parameters in `data/seed/rules.json`, so changing one needs no code change.
Positioning is duty: someone flown in as a passenger is on duty from the report for that
flight, so it counts toward their duty period and the rest before it.

Before anyone is offered as cover, every rule is applied to every day of the trip, together
with: active status and their own airline, not already on the trip or on another duty at the
same time, rest after the trip before their next rostered duty, a standby window that covers
the report, time to get to the airport from home (a late arrival is costed as a delay and the
rules re-run), and no reported unavailability on those dates. A choice that holds the
departure (positioning in, or arriving late) is only offered if everyone else on the trip
stays legal with the later departure, and it lists what the desk must arrange: the
positioning seat to book and the departure to retime.

Not modelled yet: pilot recency (take-offs and landings in the last 90 days), restrictions on
pairing two inexperienced pilots, and cabin crew language or type qualifications.
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

## Watching ahead

The watch (`crewops.engine.watch`) re-judges every rostered crew member on every trip of the
next seven days and reports what nobody has raised yet, most serious first: someone who would
break a rule (with the cheapest legal cover already worked out), high fatigue, and
certificates running out. On the demo data it finds the lapsed medical on T-1018 by itself.
Each issue keeps the same id on every run, so a schedule can alert once and stay quiet.

## Fatigue

The rules say what is allowed; `crewops.engine.fatigue` flags what is allowed but tiring, so
a controller can prefer someone fresher. Flags never block a choice.

| Flag | When | Severity |
|---|---|---|
| Early-start block | 4 early starts (before 07:00 IST) in a row, the longest block the rules allow | caution |
| Tight rest | Rest within an hour of the minimum | caution |
| Night to early | An early report within 36 h of a duty through 02:00-05:00 IST | high |
| Repeated nights | A 3rd duty through 02:00-05:00 IST in 7 days (caution), 4th or more (high) | caution, high |

Cover choices and legality checks show the flags their trip would leave.

## Unavailability

Crew report it themselves, or a controller reports it for them: the dates and a reason. From
that moment they are out of every cover search for those dates, any callout offer waiting on
them moves to the next person at once, and the trips they were rostered on show up in the
watch. A would-be choice who reported unavailable is kept in the cover result as `withdrawn`,
so a screen shows them struck through rather than silently gone. A controller clears the
report when they can fly again.

## Callouts

A callout fills one seat by asking crew in turn, cheapest legal first. A decline, or no answer
within 20 minutes, moves it to the next; cover is worked out again before every offer and on
every acceptance, so nobody gets a seat they stopped being legal for. An acceptance changes
the roster through the same version check as any other change.

When nobody is left to ask, **the callout does not cancel the flight or fly it short**. It
stops, tells the crew desk what options remain and what each costs, and waits. Cancelling or
flying short then needs two controllers: one proposes, a different one approves.

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

The models never touch the data directly. They call fifteen typed tools (`crewops.agent`), each a
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
| `open_issues` | What the watch finds in the coming days |
| `start_callout` | Starts asking crew for a seat, cheapest legal first |
| `callout_status` | Who was asked, who answered what; for crew, offers waiting for them |
| `answer_callout` | Accept or decline (crew, or a controller recording a phone answer) |
| `decide_callout` | Propose or approve cancelling or flying short: two controllers |

Each caller has a role. A `viewer` reads the operation, a `controller` may also change it, and
a `crew` member sees only their own record and trips, and answers their own callouts. Arguments are validated before a tool
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

## The agent

```
question -> screen -> route -> plan with tools -> check every figure -> answer
```

1. **Screen.** Known injection phrasings and over-long input are refused before any model
   reads them.
2. **Route.** Muse Spark Open sorts the question into absence, delay, cover, legality, change,
   lookup or out of scope, from a few worked examples, and flags attempts to steer the
   assistant (new instructions, role play, asking for its rules), which are then refused. The route decides which tools the
   planner sees and how hard it reasons. On phrasings it had not seen ("Shreya's mother is in
   hospital, she can't make the 6am") it routed 8 of 8 correctly; keyword rules, kept as the
   fallback, got 3.
3. **Plan.** Muse Spark calls the tools and writes a short answer for a controller: the
   recommendation, the deciding rule and numbers, up to two alternatives.
4. **Check.** Every crew id, trip id, flight, time, hour figure, count and rupee amount in the
   answer is matched against the tool results, with no model involved. An answer that fails
   gets one rewrite; if it still fails it is shown marked unverified.

Conversations keep their last six turns and the people and trips discussed, so a follow-up
such as "can Anjali do T-1010 as well?" needs no repetition. Try it:

```bash
uv run python -m crewops.agent.chat --user m.iyer
uv run python -m crewops.agent.chat --ask "Pooja Chowdary is unwell from 5 to 8 November"
```

In the chat, `/issues` shows what the watch finds and `/outbox` the messages sent to crew
and the desk.

Set `CREWOPS_USAGE_LOG` to a file path to keep every model call's tokens, reasoning included.

## Database

`CREWOPS_STORE` picks where the operation lives:

* `memory` (the default): the demo operation, loaded at start. Changes last until restart.
  Nothing to set up.
* `dynamodb`: one DynamoDB table (`crewops-meta-<stage>-operation`, region `ap-southeast-2`).

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

## Photos

Every photo passes fixed gates, and code, not the model, decides the outcome: picture quality
measured from the pixels (blur and darkness send it back before any model is asked), then a
fixed form filled by Muse Spark, then the rules. The outcome is `rejected` (not what it should
be), `reshoot` (with the reason), `confirm` (a person or aircraft that does not match) or
`draft`. A draft is a proposal a person confirms with one click; nothing changes because of a
photo.

| Photo | What it becomes |
|---|---|
| Sick note | A proposed unavailability report for the named crew member and dates |
| Departures board or delay notice | Each delayed flight matched to its trip, with a delay-impact check to run |
| Aircraft defect | A draft defect report needing engineer confirmation, with SAM 3.1's box on the damage and a high, medium or low confidence built from picture quality, the model's view, whether SAM found the damage and whether the tail matches |
| Roster swap, certificate | Checked against the roster and the certificates on file |

The aircraft is chosen by the reporter; a tail number in the photo is only a cross-check. A
clear photo of no damage is reported as "no damage identified, inspect in person", never as a
clearance.

## Scorecard

28 scripted crew-desk questions run against the live models and scored by code: routing, the
tools used, what the answer names, the evidence check, refusals and role limits. Each starts
from a fresh copy of the demo operation. See [docs/scorecard.md](docs/scorecard.md), or the
Scorecard tab in the console; rerun it with `uv run python -m crewops.eval.scorecard`.

## Deploying to AWS

One stack, `crewops-meta-<stage>` in ap-southeast-2 (Sydney): DynamoDB, Lambda behind a
function URL (the API, console and board), a second Lambda every 10 minutes (callout
deadlines, watch alerts by email through SNS, the shift brief), S3, and Cognito with the demo
accounts. It is bootstrapped with its own toolkit stack (`CrewOpsMetaToolkit`, qualifier
`crewmeta`), so it shares nothing with other CDK projects in the account. No Docker is needed:
the bundle is built from Linux wheels.

```bash
uv sync --group infra
uv run python scripts/deploy.py --bootstrap   # once per account and region
uv run python scripts/deploy.py               # build and deploy; prints the URLs
```

The script refuses to run unless the AWS profile is `crewops-meta`, the identity is the
`crewops-meta-deployer` user and the region is ap-southeast-2. Model keys come from `.env` and
are never committed. A daily allowance (`CREWOPS_DAILY_ASKS`) protects the model credits on a
public demo.

## Scope and limits

Domestic Indian regional operations under simplified DGCA duty rules; other regulators can be
added as rule files. Not modelled yet: pilot recency, rules on pairing two inexperienced
pilots, cabin crew language qualifications, and recording a positioning flight as its own
duty (the desk is told to book the seat). Video defect reports and a fine-tuned Muse Glimmer
router are next.

## Disclaimer

The duty rules here are a simplified model written for a demo. CrewOps is not certified for
operational use.

## License

MIT
