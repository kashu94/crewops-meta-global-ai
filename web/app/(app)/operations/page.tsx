"use client";

import { BookUser, CalendarClock, Clock, CloudLightning, DoorClosed, ListChecks, Phone, Plane, TriangleAlert, Users, UserX, Wrench } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ReportRows } from "@/components/ops";
import { Part } from "@/components/part";
import { useSession } from "@/components/session";
import { Button, control, Empty, Kpi, Kpis, Loading, Mono, Notice, PageHeader, Panel, Pill } from "@/components/ui";
import { api, tool } from "@/lib/api";
import { settle } from "@/lib/settle";
import type { Board, ReportSummary } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

type Directory = { teams: { team: string; title: string; job: string; per_station: boolean; contacts: { station: string; name: string; phone: string }[] }[] };

const QUICK = [
  ["crew_unavailable", "Crew can't fly", UserX],
  ["flight_delay", "Delay", Clock],
  ["gate_closure", "Gate closure", DoorClosed],
  ["station_disruption", "Station closure", CloudLightning],
  ["aircraft_technical", "Aircraft fault", Wrench],
] as const;

const STATIONS = ["HYD", "DEL", "BOM", "BLR", "MAA", "GOI", "VGA", "RJA", "TIR", "VTZ"];

function Contacts() {
  const [station, setStation] = useState("HYD");
  const { data, error } = useLoad(() => tool<Directory>("contacts", { station }), station);
  return (
    <Panel
      flush
      title="Who to call"
      icon={<BookUser size={15} />}
      action={
        <select aria-label="Station" value={station} onChange={(e) => setStation(e.target.value)} className={`${control} h-7 w-24 text-[13px]`}>
          {STATIONS.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      }
    >
      {error ? (
        <div className="p-4">
          <Notice tone="error">{error}</Notice>
        </div>
      ) : !data ? (
        <Loading />
      ) : !data.teams?.length ? (
        <Empty>No contacts for {station}.</Empty>
      ) : (
        <ul className="divide-y divide-rule">
          {data.teams.map((t) => (
            <li key={t.team} className="px-4 py-2.5 sm:px-5">
              <p className="text-sm font-medium">{t.title}</p>
              <p className="text-xs text-muted">{t.job}</p>
              {t.contacts.map((c) => (
                <p key={c.station + c.name} className="mt-1 flex flex-wrap items-center gap-2 text-[13px]">
                  {t.per_station && <Pill>{c.station}</Pill>}
                  {c.name}
                  <a href={`tel:${c.phone.replace(/\s/g, "")}`} className="inline-flex items-center gap-1 font-mono text-accent hover:underline">
                    <Phone size={12} /> {c.phone}
                  </a>
                </p>
              ))}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export default function OperationsPage() {
  const { me, queue } = useSession();
  const { data, error } = useLoad(async () => {
    const [board, mine] = await Promise.all([settle(api<Board>("/api/board")), settle(tool<{ disruptions: ReportSummary[] }>("my_reports"))]);
    return { board, mine };
  });
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!data) return <Loading />;
  const b = data.board.ok ? data.board.value : null;
  const n = b?.next_24h;
  const mine = data.mine.ok ? data.mine.value.disruptions ?? [] : [];
  const open = mine.filter((r) => !["closed", "revoked"].includes(r.status)).length;

  return (
    <div className="animate-rise">
      <PageHeader
        eyebrow={<>Station desk · {me.name || me.user}</>}
        title="Operations"
        lede={<>The next 24 hours at a glance. Operation clock <Mono>{b?.clock ?? me.clock}</Mono>. When something goes wrong, file it once; the right desk and the right teams get it.</>}
        actions={
          <Link href="/report/">
            <Button>
              <TriangleAlert size={15} /> Report a disruption
            </Button>
          </Link>
        }
      />
      {!data.board.ok && (
        <Notice tone="error" className="mb-5">
          {data.board.error}
        </Notice>
      )}
      <Kpis>
        <Kpi icon={<Plane size={13} />} label="Flights, next 24h" value={n?.flights ?? "–"} />
        <Kpi icon={<Users size={13} />} label="Passengers" value={(n?.passengers ?? 0).toLocaleString("en-IN")} />
        <Kpi icon={<UserX size={13} />} label="Crew out today or tomorrow" value={n?.crew_out ?? "–"} tone={n?.crew_out ? "pending" : undefined} />
        <Kpi icon={<TriangleAlert size={13} />} label="Crew over a limit" value={n?.illegal ?? "–"} tone={n?.illegal ? "critical" : "ok"} />
        <Kpi icon={<ListChecks size={13} />} label="Your open reports" value={open} tone={open ? "pending" : undefined} />
      </Kpis>

      <div className="mb-5 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        {QUICK.map(([kind, label, Icon]) => (
          <Link key={kind} href={`/report/?kind=${kind}`} className="flex items-center gap-2.5 rounded-lg border border-line bg-surface px-3 py-2.5 text-sm font-medium transition-colors hover:border-control hover:bg-sunken">
            <span className="grid h-7 w-7 place-items-center rounded-md bg-sunken text-muted">
              <Icon size={15} />
            </span>
            {label}
          </Link>
        ))}
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="flex min-w-0 flex-col gap-5">
          {queue.length > 0 && (
            <Panel flush title="Waiting on you" icon={<Clock size={15} />}>
              <ul className="divide-y divide-rule">
                {queue.map((q) => (
                  <li key={q.kind + q.ref}>
                    <Link href={q.link || "#"} className="flex gap-2.5 px-5 py-2.5 hover:bg-sunken">
                      <span className={`mt-1.5 h-2 w-2 rounded-full ${q.tone === "critical" ? "bg-critical" : q.tone === "pending" ? "bg-pending" : "bg-accent"}`} />
                      <span>
                        <span className="block text-sm font-medium">{q.title}</span>
                        <span className="block text-xs text-muted">{q.detail.replace(/_/g, " ")}</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
          <Panel flush title="Your reports" icon={<ListChecks size={15} />} action={<Link className="text-accent hover:underline" href="/disruptions/">All</Link>}>
            <Part of={data.mine}>{() => <ReportRows reports={mine.slice(0, 8)} empty="You have not filed anything yet." />}</Part>
          </Panel>
          <Panel flush title="Next departures" icon={<CalendarClock size={15} />}>
            {!b?.departures?.length ? (
              <Empty>No departures in the next 24 hours.</Empty>
            ) : (
              <ul className="divide-y divide-rule">
                {b.departures.map((d) => (
                  <li key={d.flight + d.departs} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-2.5 text-sm">
                    <Mono className="w-16 font-semibold">{d.flight}</Mono>
                    <span className="w-24">{d.route}</span>
                    <span className="font-mono text-xs text-muted">{d.departs} IST</span>
                    <span className="text-xs text-muted">
                      <Mono>{d.tail}</Mono> · {d.booked} booked
                    </span>
                    <span className="ml-auto">
                      <Pill tone={d.state === "affected" ? "critical" : "ok"}>{d.state}</Pill>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
        <div className="flex min-w-0 flex-col gap-5">
          <Contacts />
          {b?.brief && (
            <Panel title="Shift brief" icon={<Plane size={15} />}>
              <p className="font-semibold">{b.brief.headline}</p>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted">
                {b.brief.lines.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}
