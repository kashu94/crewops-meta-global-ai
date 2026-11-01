"use client";

import { BadgeCheck, CalendarDays, Gauge, Inbox, ListChecks, Plane, Timer, UserX } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Modal } from "@/components/modal";
import { NoticeList, ReportRows, RiskDetail } from "@/components/ops";
import { Part } from "@/components/part";
import { useSession } from "@/components/session";
import { Button, Chips, cx, Empty, Input, Loading, Meter, Mono, Notice, PageHeader, Panel, Pill, Spinner, Table } from "@/components/ui";
import { api, message, missing, tool } from "@/lib/api";
import { addDays, opDay, workDay } from "@/lib/clock";
import { plural, short, words } from "@/lib/format";
import { settle } from "@/lib/settle";
import type { Callout, Notice as NoticeT, Profile, Report, ReportSummary, Trip } from "@/lib/types";
import { useAction, useLoad } from "@/lib/use-load";

const START = "2026-10-30";
const DAYS = 14;

function Calendar({ trips, p, today }: { trips: Trip[]; p: Profile; today: string }) {
  const duty = new Map<string, string>();
  for (const t of trips) for (const d of t.days) duty.set(d, t.trip_id);
  const standby = new Set(p.standby_days ?? []);
  const out = new Set<string>();
  for (const u of p.unavailable ?? []) for (let d = u.from; d <= u.to; d = addDays(d, 1)) out.add(d);
  const lead = (new Date(`${START}T00:00:00Z`).getUTCDay() + 6) % 7;
  const cells = Array.from({ length: DAYS }, (_, i) => addDays(START, i));
  return (
    <div>
      <div className="grid grid-cols-7 gap-1 sm:gap-1.5">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
          <div key={d} className="pb-1 text-center text-[11px] font-medium text-faint">
            {d}
          </div>
        ))}
        {Array.from({ length: lead }, (_, i) => (
          <div key={`l${i}`} />
        ))}
        {cells.map((iso) => {
          const trip = duty.get(iso);
          const away = out.has(iso);
          const sb = standby.has(iso);
          const d = new Date(`${iso}T00:00:00Z`);
          return (
            <div
              key={iso}
              className={cx(
                "flex min-h-16 flex-col gap-0.5 rounded-md p-1.5 text-[11px] sm:p-2",
                away ? "hatch-out border border-[#f3c4c0]" : trip ? "bg-accent text-white" : sb ? "bg-accent-soft text-accent-ink" : "bg-sunken",
                iso === today && "outline-2 -outline-offset-2 outline-foreground",
              )}
            >
              <span className={cx("font-mono", trip && !away ? "text-white/80" : "text-muted")}>
                {d.getUTCDate()} {d.toLocaleString("en", { month: "short", timeZone: "UTC" })}
              </span>
              {trip && <span className={cx("font-mono font-semibold", away && "text-critical-ink line-through")}>{trip}</span>}
              {!trip && sb && <span>standby</span>}
              {away && <span className="font-medium text-critical-ink">can&apos;t fly</span>}
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex flex-wrap gap-4 text-xs text-muted">
        <span className="flex items-center gap-1.5"><i className="h-3 w-3 rounded-sm bg-accent" />flying</span>
        <span className="flex items-center gap-1.5"><i className="h-3 w-3 rounded-sm bg-accent-soft" />standby</span>
        <span className="flex items-center gap-1.5"><i className="hatch-out h-3 w-3 rounded-sm border border-[#f3c4c0]" />can&apos;t fly</span>
        <span className="flex items-center gap-1.5"><i className="h-3 w-3 rounded-sm outline-2 -outline-offset-2 outline-foreground" />today</span>
      </div>
    </div>
  );
}

function Unavailable({ crewId, today, onDone }: { crewId: string; today: string; onDone: (text: string) => void }) {
  const [kind, setKind] = useState("sick");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>;
    setBusy(true);
    setError(null);
    try {
      try {
        const r = await tool<Report>("report_disruption", {
          kind: "crew_unavailable",
          crew_ids: [crewId],
          first_day: f.first_day,
          last_day: f.last_day,
          reason_kind: kind,
          ...(f.since ? { since: f.since } : {}),
          ...(f.note ? { note: f.note } : {}),
        });
        onDone(`Crew control has been told (${r.report_id}, ${r.desk?.name ?? "a desk"}).`);
      } catch (err) {
        if (!missing(err)) throw err;
        const r = await tool<{ own_trips_now_short: string[] }>("report_unavailable", { first_day: f.first_day, last_day: f.last_day, reason: f.note || kind, kind, ...(f.since ? { since: f.since } : {}) });
        onDone(`Crew control has been told.${r.own_trips_now_short.length ? ` Your trips ${r.own_trips_now_short.join(", ")} need cover.` : ""}`);
      }
    } catch (err) {
      setError(message(err));
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3">
        <Input label="From" type="date" name="first_day" defaultValue={today} required />
        <Input label="Until" type="date" name="last_day" defaultValue={addDays(today, 1)} required />
      </div>
      <Chips
        label="Reason"
        value={kind}
        onChange={setKind}
        options={[
          { value: "sick", label: "Sick" },
          { value: "fatigue", label: "Fatigue" },
          { value: "personal", label: "Personal" },
          { value: "other", label: "Other" },
        ]}
      />
      <Input label="Taken ill at (optional, India time)" type="time" name="since" />
      <Input label="Anything crew control should know" name="note" defaultValue="unwell" maxLength={200} />
      <p className="text-xs text-faint">Any callout offer to you for those dates moves to the next person at once.</p>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="flex gap-2">
        <Button tone="danger" type="submit" disabled={busy}>
          {busy ? <Spinner /> : <UserX size={15} />} Tell crew control
        </Button>
      </div>
    </form>
  );
}

export default function CrewPage() {
  const { me, flash, bump } = useSession();
  const { busy, run } = useAction();
  const [dialog, setDialog] = useState(false);
  const id = me.crew_id ?? "";
  const today = opDay(me.clock);
  const { data, error } = useLoad(async () => {
    const [p, trips, offers, inbox, reports] = await Promise.all([
      tool<Profile>("crew_profile", { crew_id: id }),
      settle(tool<{ trips: Trip[] }>("find_trips", { crew_id: id, limit: 30 })),
      settle(tool<{ offers_to_me: Callout[] }>("callout_status", {})),
      settle(api<{ notices: NoticeT[] }>("/api/notices?limit=10")),
      settle(tool<{ disruptions: ReportSummary[] }>("my_reports")),
    ]);
    return { p, trips, offers, inbox, reports };
  }, id);

  if (!id) return <Notice tone="error">This account has no crew id.</Notice>;
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!data) return <Loading />;
  const { p } = data;
  const trips = data.trips.ok ? data.trips.value.trips ?? [] : [];
  const offers = data.offers.ok ? data.offers.value.offers_to_me ?? [] : [];

  return (
    <div className="animate-rise">
      <PageHeader
        eyebrow={
          <>
            {p.rank} · {p.airline} · based {p.base} · <Mono>{p.crew_id}</Mono>
          </>
        }
        title={`Good to see you, ${p.name.split(" ")[0]}`}
        lede={p.rest_until ? <>Resting until {short(p.rest_until)}.</> : "Your roster, your limits and anything crew control has sent you."}
        actions={
          <Button tone="danger-quiet" onClick={() => setDialog(true)}>
            <UserX size={15} /> I can&apos;t fly
          </Button>
        }
      />

      {offers.length > 0 && (
        <div className="mb-5 flex flex-col gap-2">
          {offers.map((c) => (
            <Notice key={c.callout_id} tone="pending" icon={<Plane size={15} />}>
              <div className="flex flex-wrap items-center gap-3">
                <span className="min-w-0 flex-1 basis-64">
                  <b>Callout offer:</b> <Mono>{c.trip_id}</Mono> as {c.seat}
                  {c.answer_by ? `, answer by ${short(c.answer_by)}` : ""}.
                </span>
                <Button
                  size="sm"
                  disabled={busy !== null}
                  onClick={() => run(c.callout_id, () => tool("answer_callout", { callout_id: c.callout_id, accept: true }), () => "Accepted. The desk confirms once an approver approves.")}
                >
                  Accept
                </Button>
                <Button
                  size="sm"
                  tone="secondary"
                  disabled={busy !== null}
                  onClick={() => run(c.callout_id, () => tool("answer_callout", { callout_id: c.callout_id, accept: false }), () => "Declined. The next crew member is being asked.")}
                >
                  Decline
                </Button>
              </div>
            </Notice>
          ))}
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="flex min-w-0 flex-col gap-5">
          <Panel title="My calendar" icon={<CalendarDays size={15} />} action="30 Oct – 12 Nov">
            <Calendar trips={trips} p={p} today={today} />
          </Panel>
          <Panel flush title="My flights" icon={<Plane size={15} />} action={plural(trips.length, "trip")}>
            <Part of={data.trips}>
              {() =>
                trips.length ? (
                  <ul className="divide-y divide-rule">
                    {trips.map((t) => (
                      <li key={t.trip_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 sm:px-5">
                        <Mono className="font-semibold">{t.trip_id}</Mono>
                        <span className="text-sm">{t.route}</span>
                        <span className="text-xs text-muted">
                          <Mono>{t.tail}</Mono> · release {short(t.release)}
                        </span>
                        <span className="ml-auto font-mono text-xs text-faint">reports {short(t.report)}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <Empty>No trips rostered.</Empty>
                )
              }
            </Part>
          </Panel>
          <Panel flush title="My reports" icon={<ListChecks size={15} />}>
            {(p.unavailable ?? []).length > 0 && (
              <ul className="divide-y divide-rule border-b border-rule">
                {p.unavailable.map((u) => (
                  <li key={u.report_id} className="flex flex-wrap items-center gap-2 px-4 py-3 sm:px-5">
                    <Pill tone="critical">{u.kind || "unavailable"}</Pill>
                    <span className="text-sm">
                      {short(u.from)} to {short(u.to)}
                    </span>
                    <span className="text-xs text-muted">
                      {u.reason}
                      {u.since ? ` · from ${u.since.slice(11, 16)}` : ""}
                    </span>
                    <Button
                      size="sm"
                      tone="secondary"
                      className="ml-auto"
                      disabled={busy !== null}
                      onClick={() => run(u.report_id, () => tool("clear_unavailable", { report_id: u.report_id }), () => "Withdrawn. You are back in the roster for those dates.")}
                    >
                      Withdraw, I can fly
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <Part of={data.reports}>
              {(v) =>
                (v.disruptions ?? []).length || !(p.unavailable ?? []).length ? <ReportRows reports={v.disruptions ?? []} empty="You have not reported anything." /> : null
              }
            </Part>
          </Panel>
        </div>
        <div className="flex min-w-0 flex-col gap-5">
          <Panel title="Duty limits" icon={<Timer size={15} />}>
            <div className="flex flex-col gap-4">
              <Meter label="Duty, last 7 days" value={p.duty_hours_last_7_days} max={p.duty_limit_7_days} />
              <Meter label="Flying, last 28 days" value={p.block_hours_last_28_days} max={p.block_limit_28_days} />
            </div>
          </Panel>
          <Panel title="My risk score" icon={<Gauge size={15} />}>
            <RiskDetail risk={p.risk} />
          </Panel>
          <Panel flush title="Certificates" icon={<BadgeCheck size={15} />}>
            <Table>
              <tbody>
                {p.certificates.map((c) => (
                  <tr key={c.kind}>
                    <td className="capitalize">{words(c.kind)}</td>
                    <td className="font-mono text-xs">{short(c.expires)}</td>
                    <td className="text-right">
                      <Pill tone={c.days_left < 15 ? "critical" : c.days_left < 60 ? "pending" : "ok"}>{c.days_left} days</Pill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Panel>
          <Panel flush title="Messages" icon={<Inbox size={15} />}>
            <Part of={data.inbox}>{(v) => <NoticeList notices={(v.notices ?? []).slice(0, 5)} />}</Part>
          </Panel>
        </div>
      </div>

      <Modal open={dialog} onClose={() => setDialog(false)} title="Report that you cannot fly">
        <Unavailable
          crewId={id}
          today={workDay(me.clock)}
          onDone={(text) => {
            setDialog(false);
            flash(text);
            bump();
          }}
        />
      </Modal>
    </div>
  );
}
