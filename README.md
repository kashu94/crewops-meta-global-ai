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
| Finding the damage in a defect photo, and the flood, fog or closed gate in a photo of the conditions | **SAM 3.1** | Streamed segmentation; its box and confidence are one of the signals behind the confidence level |
| Spoken questions, and crew saying they cannot fly, in English, Hindi, Telugu or mixed speech | **Muse Voice Transcribe** | Push-to-talk WAV recorded in the browser; the absence is then read into the report form by Muse Spark (structured output) for the crew member to check |
| The shift brief on the ops board, the message to passengers on a delayed, held or re-gated flight (English, Hindi, Telugu), and the shift handover | **Muse Wonder** | Structured output, then the same evidence check as every answer; a text that fails it is replaced by a template built from the same facts |
| The faint fog-at-dawn picture behind the report form and the disruption lists | **Muse Image** | Drawn once and kept as a static file (`web/public/art`), shown at 12% opacity, fading out towards the top |
| Optional artwork for the brief (`CREWOPS_BOARD_ART`) | **Muse Image** | One picture per mood per day, no text in it |

No model ever does the arithmetic: every crew id, hour, cost and verdict comes from the rules
engine, and a deterministic check compares each figure in an answer with the tools' results.

## Try it

| Where | What |
|---|---|
| Web console (`/`) | A Next.js app, one page per job and a home page per role. **Controllers**: their desk's disruptions, the problems the watch finds, callouts, find cover, gates, the assistant with its trace panel. **Approvers**: plans, cancellations and resolutions to sign off. **Reporters**: the day's operation and a report form. **Everyone at the desk**: a page per disruption report with its lifecycle. **Admins**: team accounts and password resets, alert addresses, roster upload, revoking reports, duty limits, the logs. **Crew**: their calendar, flights, duty limits, risk, certificates, callout offers and reports. Desktop alerts, and the evaluation |
| Ops board (`/board`) | The ops-room wall: next 24 hours, shift brief, controller desks, callouts, the watch, departures, standby cover. Read-only, no sign-in |
| Speaker (`/speaker`) | The desk's notices read aloud as they happen, critical ones repeated until acknowledged; "what's waiting?" on request; spoken questions answered by the agent |
| Fire TV (`tv/`) | The same board as a Vega OS app, **CrewOps Board (Meta)** |
| MCP server | The tools, with roles, for any MCP client |
| Terminal | `uv run python -m crewops.agent.chat` |

Run it locally (demo data in memory, pick a demo identity at the top right):

```bash
cd web && npm install && npm run build && cd ..    # the console, exported to web/out
uv run python -m crewops.api                       # http://localhost:8000
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
certificates running out. On the demo data it finds the lapsed medical on T-1018 by itself,
and one other certificate running out the week after.
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

## Severity

Every problem the watch raises is graded high, medium or low with its reasons, from what the
engine knows (`crewops.engine.severity`): how soon the trip reports, how many passengers are
booked, and whether anyone can still fill the seat. Someone rostered illegally is never low.
The desk lists problems in that order.

## Disruption reports

Whatever goes wrong is filed as one report (`crewops.ops.reports`): crew out (sick, fatigue,
personal), **several crew out at once** (food poisoning after a crew meal, a road accident on
the way in), planned leave, a certificate lapse, a flight delay, an aircraft fault, a station
closed, gates closed or a gate change. Filing it records the absences, grades its severity,
assigns it to a desk, tells the crew desk and the teams the kind of problem needs, and comes
back with the engine's analysis: for absences, every seat left empty and the cheapest way to
fill **all of them together**, never using one person twice and never one absent crew member
for another's seat.

The station files reports (crew file their own sickness, admins book planned leave); crew
control works them and approvers decide. Crew out on the same flight are one disruption,
covered together; crew on different flights become separate disruptions, each sent to the
least busy desk. A seat is offered only to its own rank first: a right-seat qualified captain
for a first officer's seat, or a command-qualified first officer for a captain's, is offered
only when fewer than three of the seat's own rank are legal, and after them.

The same thing is never filed twice: someone already reported out for those days, or a trip,
aircraft, station or gate with an open report, is refused with the report to follow instead.
A sick note or certificate photo must name a person on the report. When crew withdraw their
own report, any callout for their seat stands down, a waiting plan for it is withdrawn, the
desk and the ops-room speaker hear "Back on duty", and a disruption with nobody left out is
closed.

Each seat shows its ranked choices, each one a plan to submit for approval after a
confirmation; while a callout or a plan is in hand for a seat, nothing else can be started for
it, and a rejected plan frees it again. An aircraft fault (`crewops.engine.aircraft`) offers,
in order: another aircraft of the same type that is free for the whole run of flights, out and
back to where it started; one of the spares kept at Hyderabad (an A320 and an ATR); holding
the flights, for short outages only; and cancelling them. A gate closure offers a free gate for
each flight it moves. The chosen option goes to an approver as the resolution.

    OPEN --plan or callout--> IN_PROGRESS --controller closes--> RESOLVED --approver--> CLOSED
                                    ^                                |
                                    '-------- approver returns ------'
    any state but CLOSED --admin--> REVOKED   (filed in error; its absences are withdrawn)

Station duty managers, controllers and approvers file any kind; crew report only themselves;
planned leave is booked by an admin, the way rostering would. Each report has its own page.

## Desks

Three controllers share the operation, one desk each (`crewops.ops.desks`). A new report goes
to the desk with the fewest open ones, then the fewest overall, so the load evens out and
nobody picks. Only the owning desk's controller plans and closes it; an approver or an admin
can move it to another desk. Cover is still checked across desks, because two reports on
different desks can want the same standby.

## Risk

Legal is yes or no; risk is a matter of degree (`crewops.engine.risk`). A score from 0 to 100
adds points for a fatigue pattern ahead, duty or block hours near a limit, absences reported in
the operation, a certificate running out and a long drive to the airport, and says which
drivers did it. It is shown beside every cover choice and on the crew record, and **never ranks
cover or rules anyone out**: the rules engine alone decides who is legal, and cost alone orders
the legal choices.

## Teams

A disruption rarely stops at the crew desk (`crewops.ops.teams`). Gate and stand control, the
station duty manager, flight information, operations monitoring, maintenance control, crew
records and customer care each have a fixed job; the kind of report decides which are told,
with who is on duty at that station or at the operations centre (`data/seed/contacts.json`).

## Unavailability

Crew report it themselves, or a controller reports it for them: the dates and a reason. From
that moment they are out of every cover search for those dates, any callout offer waiting on
them moves to the next person at once, and the trips they were rostered on show up in the
watch. A would-be choice who reported unavailable is kept in the cover result as `withdrawn`,
so a screen shows them struck through rather than silently gone. A controller clears the
report when they can fly again, and crew can withdraw their own. A report carries its kind
(sick, fatigue, personal, other) and, for someone taken ill part-way through a day, the time:
duties that end before then are still theirs to fly.

## Callouts

A callout fills one seat by asking crew in turn, cheapest legal first. A decline, or no answer
within 20 minutes, moves it to the next; cover is worked out again before every offer and on
every acceptance, so nobody gets a seat they stopped being legal for. An acceptance becomes a plan for
an approver to decide (see below).

When nobody is left to ask, **the callout does not cancel the flight or fly it short**. It
stops, tells the crew desk what options remain and what each costs, and waits. Cancelling or
flying short then needs two people: a controller proposes, an approver decides.

## Four eyes on every change

Nothing changes a trip's crew on one person's word (`crewops.ops.plans`). A controller submits
a plan, or a callout submits one in the name of the controller who opened it when crew accept.
An approver approves, rejects with a reason, or sends it back with a note; the submitter may
withdraw it. At approval the plan is judged again as the roster stands: if the
trip changed since, or the crew member is no longer legal, it goes **stale** and nothing
changes. Every plan keeps its history.

## Escalation

Every ten minutes, what the desk has left untouched for ten minutes goes to the duty
supervisor by email (`crewops.ops.escalation`): a plan nobody approved, a callout with nobody
left to ask, a high-severity problem with no callout and no plan on its seat, a high-severity
report its desk has not started. Each escalates once.

## Alerts

Notices go out three ways. Every notice is kept and shown on the screens and the speaker.
**Email**: an admin subscribes addresses to a group (the crew desk, the duty supervisor or one
of the teams); each message names its group, so the topic delivers it only to that group's
addresses (`crewops.ops.alerts`). **Desktop alerts**: a browser that allows notifications gets
the desk's notices by Web Push even with the tab closed, encrypted for that browser (RFC 8291)
and signed with the server's VAPID key (`crewops.ops.push`).

## Gates, stations and aircraft

Each departure holds a gate from 45 minutes before off-block (`crewops.engine.gates`); the demo
data holds five contact gates, two remote stands and an emergency gate at Hyderabad, where the
morning wave sends five departures out within an hour. When gates close, or a late flight is
still at its gate, each displaced departure goes to the first free gate, then the emergency
gate, then a remote stand by bus, which adds 15 minutes, and that delay is judged against
crew duty. A gate change is checked for a clash with whoever holds the gate.

A station closure holds every departure and arrival inside the window, and an aircraft out of
service holds its flights that day (`crewops.engine.disruption`). Both are judged like a
reported delay, and only breaches the delay causes are counted against it: someone illegal
even on time is shown apart.

## Governance

Every change made through a tool is logged with who, their role and when; every refused
question is logged for the admins and auditors (`crewops.ops.governance`). An admin may make a
duty limit stricter than the regulator's (a shorter duty, longer rest); relaxing it again, back
towards the regulator's figure and never past it, needs a super admin. Each change needs a
reason, and the engine applies it at once.

Admins look after the team's accounts (`crewops.ops.accounts`): add people, change roles,
switch accounts off and reset passwords to a temporary one that must be changed at sign-in.
Only a super admin manages admins, and nobody changes their own account.

**Roster upload.** Rostering publishes in bulk: an admin uploads crew, certificates, standby or
trips as JSON in the demo data's shapes (`crewops.ops.roster_upload`). The whole merged roster
is checked before anything is written (a trip naming someone who does not exist, a leg nobody
flies), and the engine lists every rule problem the upload would add. A dry run stops there;
otherwise new trips are added and changed crew lists are applied as roster changes by the
uploader, at each trip's current version.

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

The models never touch the data directly. They call fifty-two typed tools (`crewops.agent`),
each a thin wrapper over the rules engine or the database:

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
| `assign_crew` | Submits a change for an approver, only for legal cover at the current version |
| `plan_status` | Changes waiting for approval, or one plan and what was decided |
| `review_plan` | Approve (rules checked again), reject or send back; the submitter may withdraw |
| `open_issues` | What the watch finds in the coming days |
| `start_callout` | Starts asking crew for a seat, cheapest legal first |
| `callout_status` | Who was asked, who answered what; for crew, offers waiting for them |
| `answer_callout` | Accept or decline, with a remark (crew, or a controller recording a phone answer) |
| `decide_callout` | A controller proposes cancelling or flying short; an approver decides |
| `report_unavailable`, `clear_unavailable` | Record who cannot fly (kind, dates, from what time), or withdraw it |
| `gate_status` | Gates and stands at a station, and who holds which on a day |
| `gate_closure`, `late_at_gate`, `gate_change` | Where displaced departures board, and any crew impact |
| `station_closure`, `aircraft_out_of_service` | Flights held, and who the delay pushes over a limit |
| `rule_limits`, `set_rule_limit` | Duty limits against the regulator's; admins tighten, super admins may relax back |
| `report_disruption` | Files a report of any kind, one or several crew; returns it with its analysis |
| `disruptions`, `my_reports`, `show_disruption` | Reports by state and desk, the caller's own, or one with its lifecycle |
| `submit_report_plan` | Submits a report's cheapest joint cover as plans, one per seat |
| `close_disruption`, `confirm_resolution`, `return_resolution` | A controller resolves; an approver signs off or returns it |
| `reassign_disruption`, `revoke_report` | Move a report to another desk; revoke one filed in error |
| `desk_load` | Each desk's reports by state, and how new ones are assigned |
| `crew_risk` | Crew most at risk of dropping out, with what drives each score |
| `contacts` | The operational teams, their jobs and who is on duty where |
| `my_queue` | What is waiting for the caller now |
| `about_me` | Who the caller is, what their role does and may not do, and what waits for them |
| `operations` | A week of flights for the station: who flies each and who is out (when, never why) |
| `catalog` | Every trip, flight, aircraft, station and gate from today, for forms to pick from |
| `team_accounts`, `create_account`, `set_account`, `reset_password` | Team accounts and passwords (admins) |
| `alert_addresses`, `add_alert_address`, `remove_alert_address` | Who hears which group's alerts by email (admins) |
| `upload_roster` | Roster records from a file, checked whole first; dry run or apply (admins) |

Each caller has one of eight roles:

| Role | Does |
|---|---|
| `crew` | Sees only their own record and trips, answers their own callouts, reports themselves unavailable |
| `reporter` | A station duty manager: sees the flights and gates, files disruption reports, follows their own |
| `controller` | Owns a desk: works its reports, finds cover, runs callouts, submits changes, closes reports |
| `approver` | Approves, rejects or sends back changes; decides cancellations; signs off resolutions |
| `auditor` | Reads everything, the activity and security logs included; changes nothing |
| `admin` | Accounts, passwords, alert addresses, roster uploads, planned leave, revoking reports, tightening limits |
| `super_admin` | What an admin does, plus managing admins and relaxing a limit back towards the regulator's |
| `speaker` | The ops-room speaker, a device: hears what is waiting and nothing else |

Arguments are validated before a tool runs, and every problem comes back as a readable error
for the model to recover from.

## MCP server

The same tools, with the same roles, for any MCP client:

```bash
uv run python -m crewops.mcp_server                                    # read-only
uv run python -m crewops.mcp_server --role controller --user ananya.iyer
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
uv run python -m crewops.agent.chat --user ananya.iyer
uv run python -m crewops.agent.chat --ask "A. Nair is unwell from 5 to 8 November"
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

A disruption report carries its photo with it. The report form asks for the one that backs up
its kind, checks it the moment it is added and keeps it, so the desk sees what the reporter saw
and how far it was checked:

| Report | Photo | Needed |
|---|---|---|
| Crew can't fly | Sick note or medical report | optional; checked against the person and the dates reported |
| Certificate lapse | The certificate | optional; checked against the holder and the date on file |
| Delay, gate change | Departures board or gate screen | optional |
| Aircraft fault | The fault | required in the console; the agent can file without one, marked for maintenance to confirm |
| Station closure, gate closure | The conditions: fog, flooding, snow, a closed gate | optional |

A photo never changes how severe a report is: severity comes from what the disruption does to
the flights and crew. A photo says how far the report is confirmed, shown as a badge on every
list (photo, with its confidence, or no photo).

| Photo | What it becomes |
|---|---|
| Sick note | A proposed unavailability report for the named crew member and dates |
| Conditions at the airport | What the photo shows (fog, flooding, a closed gate), or that nothing visible is wrong |
| Departures board or delay notice | Each delayed flight matched to its trip, with a delay-impact check to run |
| Aircraft defect | A draft defect report needing engineer confirmation, with SAM 3.1's box on the damage and a high, medium or low confidence built from picture quality, the model's view, whether SAM found the damage and whether the tail matches |
| Roster swap, certificate | Checked against the roster and the certificates on file |

The aircraft is chosen by the reporter; a tail number in the photo is only a cross-check. A
clear photo of no damage is reported as "no damage identified, inspect in person", never as a
clearance.

## Scorecard

The router is also measured on its own, on 64 held-out crew-desk questions in English,
Hinglish, Hindi and Telugu whose phrasings never appear in the training set
(`scripts/router_dataset.py`, `scripts/router_eval.py`, [docs/router_eval.md](docs/router_eval.md)):

| Setup | Right | Attacks caught | False alarms | Median | Tokens per question |
|---|---|---|---|---|---|
| Muse Spark Open on Baseten (live) | 60 of 64 | 3 of 3 | 0 | 1.9 s | 1,060 |
| Muse Spark Open on Fireworks (backup) | 61 of 64 | 3 of 3 | 0 | 4.5 s | 1,082 |
| Baseten, tuned with 28 more examples | 61 of 64 | 3 of 3 | 0 | 2.0 s | 1,654 |

Tuning by examples fixed one question for 56% more tokens on every question, so the live router
keeps its prompt. Fireworks routes as well as Baseten, a little slower, and is the router's
backup. A fine-tuned Muse Glimmer was planned on the same training file; dataset uploads on
Fireworks were switched off for every account during the hackathon, so it is not measured.


36 scripted crew-desk questions run against the live models and scored by code: routing, the
tools used, what the answer names, the evidence check, refusals and role limits. Each starts
from a fresh copy of the demo operation. The last run (2 November): 35 of 36 passed; routing
33 of 33; every figure checked in 33 of 33 answers; 3 of 3 attacks refused; 12,984 tokens and
12.2 s per question on average. The one miss, D3, asked about an aircraft not ready before 11
and expected the delay tool; the assistant used the aircraft-out-of-service tool instead and
gave the right new times, which the scorecard still counts as a miss. It covers several crew
sick in one report, the risk score and desk load.
See
[docs/scorecard.md](docs/scorecard.md), or the Evaluation page in the console (median and p95
seconds per answer, crew privacy); rerun it with `uv run python -m crewops.eval.scorecard`.

## Deploying to AWS

One stack, `crewops-meta-<stage>` in ap-southeast-2 (Sydney): the web console on Amplify
Hosting (app `crewops-meta-<stage>-console`, a static Next.js export built and uploaded by the
deploy script), DynamoDB, Lambda behind a function URL (the API, answering browsers from the
console's address only), a second Lambda every 10 minutes (callout
deadlines, watch alerts and escalations by email through SNS, the shift brief), S3, and
Cognito with a group per role and the demo accounts: `ananya.iyer`, `rohit.malhotra` and
`divya.rao` (controllers, desks 1 to 3), `meera.bhatt`, `karan.mehta` and `farah.qureshi`
(approvers), `imran.sheikh` and `lakshmi.hegde` (station reporters), `nikhil.agarwal`
(auditor), `priya.desai` (admin), `vikram.saxena` (super admin), `ops.speaker` (speaker), and
`c1111.nair`, `c1157.reddy`, `c1167.iyer`, `c1191.nair` and `c1460.krishnan`, and the crew the
seats on T-1018 are offered to (`c1123.verma`, `c1177.rao`, `c1211.bose`, `c1242.iyer`,
`c1184.chandra`, `c1247.reddy`, `c1341.chandra`, `c1357.gupta`, `c1530.malhotra`,
`c1542.krishnan`)
(crew). A store seeded from older demo data is reseeded when the data version changes, and on
the wall clock it is moved to start today, and again a week later. Photos kept with reports go
to the same S3 bucket and are served only to the desk roles and whoever took them. It is
bootstrapped with its own toolkit stack (`CrewOpsMetaToolkit`, qualifier
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
duty (the desk is told to book the seat). Video defect reports are next.

## Disclaimer

The duty rules here are a simplified model written for a demo. CrewOps is not certified for
operational use.

## License

MIT
