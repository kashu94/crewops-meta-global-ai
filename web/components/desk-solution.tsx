"use client";

import { ArrowRight, CheckCheck, Clock, ListChecks, Radio, Send, UserPlus, XCircle } from "lucide-react";
import Link from "next/link";

import { tool } from "@/lib/api";
import { inr, plural, short } from "@/lib/format";
import type { Callout, CrewAnalysis, Plan, Report } from "@/lib/types";
import { useAction } from "@/lib/use-load";

import { RiskBadge } from "./ops";
import { useSession } from "./session";
import { Button, cx, Mono, Notice, Pill, SeverityBadge, StatusPill } from "./ui";

const LIVE_CALLOUT = ["offered", "accepted", "needs_decision", "awaiting_approval"];
const LIVE_PLAN = ["submitted", "approved"];

/** Where one seat stands: the callout and the plan for it, in words a controller acts on. */
function seatState(callouts: Callout[], plans: Plan[], trip: string, replacing: string) {
  const callout = [...callouts].reverse().find((c) => c.trip_id === trip && c.replacing === replacing);
  const plan = [...plans].reverse().find((p) => p.trip_id === trip && p.replacing === replacing);
  return { callout, plan, busy: Boolean((callout && LIVE_CALLOUT.includes(callout.status)) || (plan && LIVE_PLAN.includes(plan.status))) };
}

function CalloutLine({ c }: { c: Callout }) {
  const declined = c.asked.filter((o) => ["declined", "no answer", "unavailable", "not approved"].includes(o.answer));
  const waiting = c.waiting_for ? c.asked.find((o) => o.crew_id === c.waiting_for) : null;
  const accepted = c.asked.find((o) => o.answer === "accepted");
  return (
    <div className="flex flex-col gap-1 text-xs">
      {declined.map((o) => (
        <span key={o.crew_id} className="flex items-start gap-1.5 text-muted">
          <XCircle size={12} className="mt-px shrink-0 text-critical" />
          <span>
            {o.name} {o.answer === "no answer" ? "did not answer in time" : o.answer === "unavailable" ? "reported they cannot fly" : o.answer === "not approved" ? "accepted, not approved" : "declined"}
            {(o as { remark?: string }).remark ? <i>: “{(o as { remark?: string }).remark}”</i> : null}
          </span>
        </span>
      ))}
      {waiting && (
        <span className="flex items-center gap-1.5 text-pending-ink">
          <Clock size={12} /> Offered to {waiting.name}
          {c.answer_by ? `, answer by ${short(c.answer_by).slice(-5)}` : ""}
        </span>
      )}
      {accepted && c.status === "accepted" && (
        <span className="flex items-center gap-1.5 text-ok-ink">
          <CheckCheck size={12} /> {accepted.name} accepted: waits for an approver
        </span>
      )}
      {c.status === "needs_decision" && <span className="font-medium text-critical-ink">Nobody left to ask: propose cancelling or flying short on the full report.</span>}
      {c.status === "awaiting_approval" && <span className="text-pending-ink">A cancellation or flying short waits for an approver.</span>}
    </div>
  );
}

/** The selected disruption's solution on the desk: every seat with its cover and where it
 * stands, and only the actions this controller can take now. */
export function DeskSolution({ report }: { report: Report }) {
  const { me } = useSession();
  const { busy, run } = useAction();
  const mine = me.desk?.desk_id === report.desk?.desk_id && me.role === "controller";
  const a = report.analysis as unknown as CrewAnalysis | null;
  const seats = a?.seats ?? [];
  const fills = a?.plan?.fills ?? [];
  const link = `/disruptions/view/?id=${encodeURIComponent(report.report_id)}`;
  const anyFree = seats.some((s) => !seatState(report.callouts, report.plans, s.trip_id, s.replacing).busy);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-muted">
            <Mono>{report.report_id}</Mono> · {report.label ?? report.kind} · filed by {report.filed_by}
          </p>
          <h2 className="mt-0.5 text-lg font-semibold leading-snug">{report.title}</h2>
        </div>
        <SeverityBadge severity={report.severity} />
        <StatusPill value={report.status} />
      </div>
      <p className="text-sm text-muted">{report.summary}</p>
      {!mine && report.desk && (
        <Notice tone="pending">
          With {report.desk.name} ({report.desk.controller}). You can read it; planning it is theirs.
        </Notice>
      )}

      {seats.length > 0 ? (
        <ul className="flex flex-col gap-2.5">
          {seats.map((s) => {
            const fill = fills.find((f) => f.trip_id === s.trip_id && f.replacing === s.replacing);
            const state = seatState(report.callouts, report.plans, s.trip_id, s.replacing);
            const plan = state.plan;
            return (
              <li key={`${s.trip_id}-${s.replacing}`} className={cx("rounded-xl border p-3.5", state.busy ? "border-line bg-sunken/50" : "border-line bg-surface")}>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Mono className="font-semibold">{s.trip_id}</Mono>
                  <span className="font-medium">{s.rank}</span>
                  <span className="text-muted">
                    for {s.name} <Mono className="text-faint">{s.replacing}</Mono>
                  </span>
                  <span className="ml-auto font-mono text-xs text-faint">reports {short(s.reports_at)}</span>
                </div>
                {plan && LIVE_PLAN.includes(plan.status) ? (
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-muted">{plan.status === "approved" ? "Covered by:" : "Proposed:"}</span>
                    <b className="font-medium">{plan.name}</b>
                    <Mono className="text-faint">{plan.crew_id}</Mono>
                    <span className="ml-auto font-mono font-semibold">{inr(plan.cost_inr)}</span>
                  </div>
                ) : fill?.crew_id ? (
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-muted">Cheapest cover:</span>
                    <b className="font-medium">{fill.name}</b>
                    <Mono className="text-faint">{fill.crew_id}</Mono>
                    {fill.risk && <RiskBadge risk={fill.risk} compact />}
                    <span className="ml-auto font-mono font-semibold">{inr(fill.cost)}</span>
                  </div>
                ) : (
                  <p className="mt-2 text-sm text-critical-ink">No legal crew for this seat: see every choice on the full report.</p>
                )}
                <div className="mt-2 flex flex-col gap-1.5">
                  {state.callout && <CalloutLine c={state.callout} />}
                  {plan && (
                    <span className="flex flex-wrap items-center gap-1.5 text-xs">
                      <StatusPill value={plan.status} />
                      <span className="text-muted">
                        Plan <Mono>{plan.plan_id}</Mono>: {plan.name}
                        {plan.status === "submitted" ? ", waits for an approver" : plan.decision_note ? `: ${plan.decision_note}` : ""}
                      </span>
                    </span>
                  )}
                </div>
                {mine && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      disabled={busy !== null || state.busy}
                      title={state.busy ? "A callout or plan is already in hand for this seat" : "Offer the seat to legal crew, cheapest first"}
                      onClick={() =>
                        run(`co-${s.trip_id}-${s.replacing}`, () => tool("start_callout", { trip_id: s.trip_id, replace_crew_id: s.replacing, report_id: report.report_id }), () => `Callout started for ${s.trip_id}.`)
                      }
                    >
                      <Radio size={13} />{" "}
                      {plan?.status === "approved"
                        ? "Covered"
                        : plan?.status === "submitted"
                          ? "With an approver"
                          : state.callout && LIVE_CALLOUT.includes(state.callout.status)
                            ? "Callout running"
                            : "Start callout"}
                    </Button>
                    <Link href={`/cover/?trip=${s.trip_id}&crew=${s.replacing}&report=${encodeURIComponent(report.report_id)}`}>
                      <Button size="sm" tone="secondary">
                        <UserPlus size={13} /> Every choice
                      </Button>
                    </Link>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-sm text-muted">{report.summary}</p>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-rule pt-3">
        {mine && report.can?.plan && anyFree && (
          <Button
            disabled={busy !== null}
            onClick={() =>
              run(
                "plan",
                () => tool<{ plans: unknown[] }>("submit_report_plan", { report_id: report.report_id }),
                (r) => `${plural(r.plans?.length ?? 0, "plan")} sent to an approver.`,
              )
            }
          >
            <Send size={14} /> Submit the joint plan
          </Button>
        )}
        {report.plans.length > 0 && (
          <Pill tone="pending">
            <ListChecks size={11} /> {plural(report.plans.filter((p) => p.status === "submitted").length, "plan")} with an approver
          </Pill>
        )}
        <Link href={link} className="ml-auto inline-flex items-center gap-1 text-sm text-accent hover:underline">
          Full report <ArrowRight size={13} />
        </Link>
      </div>
    </div>
  );
}
