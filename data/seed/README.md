# Demo operation

Two weeks (30 October to 12 November 2026) of three fictional regional airlines flying out of
Hyderabad:

| Airline | Code | Fleet |
|---|---|---|
| Sahyadri Air | SY | 2 × A320 (one flies two-day trips with a Delhi night-stop), 1 × ATR 72 |
| Kaveri Flyers | KF | 2 × A320 (one flies a late-evening Delhi return) |
| Godavari Link | GL | 2 × ATR 72 |

The files are written by `uv run python -m crewops.seed.generate`, which is deterministic;
`tests/test_seed.py` fails if they drift from it. Edit the generator, not the JSON.

| File | Contents |
|---|---|
| `airlines.json` | Airlines and their fleets |
| `crew.json` | 104 crew: captains, first officers, pursers and cabin crew, mostly Hyderabad-based, a few in Mumbai |
| `certificates.json` | Licence, medical, recurrent training and safety equipment expiry dates |
| `histories.json` | Duty and block hours for the 28 days before the roster starts |
| `standby.json` | Who is on standby each day, and their callout window (UTC) |
| `legs.json` | Every flight, UTC times, with its departure gate |
| `gates.json` | The gates and stands the operation holds at each station: at Hyderabad five contact gates (21-25), two remote stands and an emergency gate; two gates, a stand and an emergency gate elsewhere |
| `contacts.json` | Who is on duty in each operational team: gate and stand control and the station duty manager at each station, and flight information, operations monitoring, maintenance control, crew records and customer care at the operations centre. Made-up names and numbers |
| `trips.json` | Crew trips: duty days, legs, and who is rostered |
| `rules.json` | The nine duty rules and their limits |
| `rates.json` | What each way of covering a seat costs, in rupees |
| `meta.json` | When the histories were taken, the date range, problems planted on purpose, and the data version (a deployed store reloads when it changes) |

Every rostered seat is legal except the ones listed under `known_issues` in `meta.json`.
All names, flight numbers and registrations are made up.
