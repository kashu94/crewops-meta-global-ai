# CrewOps console

The web console, the ops-room TV board and the ops-room speaker, as one Next.js app exported to
static files. FastAPI serves `web/out` on the same origin as `/api`, so there are no server
routes and no middleware here: every page is a client component that calls the backend.

## Build

```bash
cd web
npm install
npm run build        # writes web/out
npm run typecheck    # tsc --noEmit
npm run lint
```

## Develop

Run the backend, then `next dev`. In development only, `/api/*` is proxied to the backend
named by `CREWOPS_API` (default `http://127.0.0.1:8000`); the production export has no proxy.

```bash
uv run python -m crewops.api --port 8000          # from the repository root
cd web && CREWOPS_API=http://127.0.0.1:8000 npm run dev
```

## Pages

| path | who | what |
|---|---|---|
| `/login/` | everyone | demo identity picker, or Cognito sign-in with the new-password step after a reset |
| `/desk/` | controller (home), approver, auditor | top problem, figures, the desk's disruptions, problems by urgency, desk load, callouts, messages |
| `/disruptions/` | desk roles; reporters and crew see their own reports | reports by state and desk, desk load |
| `/disruptions/view/?id=R-…` | readers and the filer | one report: lifecycle, severity, analysis, seats and the joint plan, plans, callouts, teams to tell, actions from `can`, history |
| `/approvals/` | approver (home) | plans to approve, resolutions to confirm, callouts needing a decision |
| `/cover/?trip=&crew=&report=` | controller | every legal choice with funnel, picks and risk; submit a plan or start a callout, linked to a report |
| `/report/?kind=` | reporter, controller, approver; admins book planned leave | file a report (several crew at once), or read a photo |
| `/operations/` | reporter (home) | the next 24 hours, the reporter's reports, departures, who to call |
| `/gates/` | readers | gate timeline with a closure band, what a closure or a late flight moves |
| `/assistant/` | everyone | questions by text or voice, with how each answer was made |
| `/activity/` | desk roles | changes; refused questions for auditors and admins |
| `/limits/` | desk roles | duty limits; admins tighten, super admins may relax back to the regulator |
| `/evaluation/` | desk roles | the published scorecard |
| `/crew/`, `/messages/` | crew | roster calendar, flights, limits, risk, certificates, offers, reporting unavailable |
| `/admin/` | admin, super admin (home) | accounts, alert addresses, roster upload, revoking reports, duty limits |
| `/board/` | public | the ops-room wall |
| `/speaker/` | public | the ops-room speaker: chime, speech, repeats critical alerts until acknowledged |

Pages refresh themselves: the console polls `/api/version` every 3 seconds and reloads the page
on screen when a number moves. Desktop alerts use the service worker at `public/sw.js`.
