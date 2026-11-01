"use client";

import {
  BadgeAlert,
  Camera,
  CalendarOff,
  Clock,
  CloudLightning,
  DoorClosed,
  FileWarning,
  MoveRight,
  Send,
  UserX,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { CrewPicker, type CrewPick } from "@/components/crew-picker";
import { PhotoIntake } from "@/components/photo-intake";
import { useSession } from "@/components/session";
import { Button, Chips, cx, Input, Notice, PageHeader, Panel, Select, Spinner, TextArea } from "@/components/ui";
import { message, tool } from "@/lib/api";
import { addDays, workDay } from "@/lib/clock";
import type { Report } from "@/lib/types";

type Kind =
  | "crew_unavailable"
  | "planned_leave"
  | "certification_lapse"
  | "flight_delay"
  | "aircraft_technical"
  | "station_disruption"
  | "gate_closure"
  | "gate_change"
  | "photo";

const KINDS: { id: Kind; label: string; hint: string; icon: LucideIcon }[] = [
  { id: "crew_unavailable", label: "Crew can't fly", hint: "Sick, fatigue, personal: every seat they leave", icon: UserX },
  { id: "planned_leave", label: "Planned leave", hint: "Annual, medical, training: book it ahead", icon: CalendarOff },
  { id: "certification_lapse", label: "Certificate lapse", hint: "A licence, medical or training runs out", icon: BadgeAlert },
  { id: "flight_delay", label: "Delay", hint: "A trip leaves late: who breaks a limit", icon: Clock },
  { id: "aircraft_technical", label: "Aircraft fault", hint: "Out of service: the day's flights slip", icon: Wrench },
  { id: "station_disruption", label: "Station closure", hint: "Weather or runway: flights held", icon: CloudLightning },
  { id: "gate_closure", label: "Gate closure", hint: "Gates shut: where each flight boards", icon: DoorClosed },
  { id: "gate_change", label: "Gate change", hint: "Move a departure: is the gate free", icon: MoveRight },
  { id: "photo", label: "From a photo", hint: "Sick note, board, defect, certificate", icon: Camera },
];

const STATIONS = ["HYD", "DEL", "BOM", "BLR", "MAA", "GOI", "VGA", "RJA", "TIR", "VTZ"];
const CERTS = [
  ["licence", "Licence"],
  ["medical", "Medical"],
  ["recurrent_training", "Recurrent training"],
  ["safety_equipment", "Safety equipment"],
];

function allowed(role: string): Kind[] {
  if (role === "admin" || role === "super_admin") return ["planned_leave"];
  if (role === "crew") return ["crew_unavailable"];
  return KINDS.map((k) => k.id);
}

export default function ReportPage() {
  const { me, can, flash, bump } = useSession();
  const router = useRouter();
  const params = useSearchParams();
  const kinds = allowed(me.role);
  const wanted = params.get("kind") as Kind | null;
  const [kind, setKind] = useState<Kind>(wanted && kinds.includes(wanted) ? wanted : kinds[0]);
  const [crew, setCrew] = useState<CrewPick[]>([]);
  const [reason, setReason] = useState("sick");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const today = workDay(me.clock);
  const def = KINDS.find((k) => k.id === kind)!;

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = Object.fromEntries([...new FormData(e.currentTarget)].filter(([, v]) => v !== "")) as Record<string, string>;
    const args: Record<string, unknown> = { kind };
    if (["crew_unavailable", "planned_leave", "certification_lapse"].includes(kind)) {
      if (!crew.length) return setError("Choose at least one crew member.");
      args.crew_ids = crew.map((c) => c.crew_id);
    }
    if (kind === "crew_unavailable") args.reason_kind = reason;
    for (const k of ["first_day", "last_day", "since", "leave", "cert", "trip_id", "day", "tail", "start", "end", "station", "leg_id", "gate", "note"]) {
      if (f[k]) args[k] = k === "trip_id" || k === "tail" || k === "station" ? f[k].toUpperCase() : f[k];
    }
    if (f.hours) args.hours = Number(f.hours);
    if (f.gates) args.gates = f.gates.split(",").map((g) => g.trim()).filter(Boolean);
    setBusy(true);
    setError(null);
    try {
      const r = await tool<Report>("report_disruption", args);
      flash(`${r.report_id} filed${r.desk ? ` and sent to ${r.desk.name} (${r.desk.controller})` : ""}.`);
      bump();
      router.push(`/disruptions/view/?id=${encodeURIComponent(r.report_id)}`);
    } catch (err) {
      setError(message(err));
      setBusy(false);
    }
  }

  const crewKind = ["crew_unavailable", "planned_leave", "certification_lapse"].includes(kind);

  return (
    <div className="animate-rise">
      <PageHeader
        title="Report a disruption"
        lede="File it once: CrewOps works out what it breaks, who must be told and what it costs, and sends it to the least loaded desk. Nothing changes the roster without an approver."
      />
      {!can("report_disruption") && (
        <Notice tone="pending" className="mb-5">
          This server does not offer filing reports to your role yet.
        </Notice>
      )}
      {kinds.length > 1 && (
        <div className="mb-5 grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-2" role="radiogroup" aria-label="Kind of disruption">
          {KINDS.filter((k) => kinds.includes(k.id)).map((k) => {
            const Icon = k.icon;
            const on = k.id === kind;
            return (
              <button
                key={k.id}
                role="radio"
                aria-checked={on}
                onClick={() => {
                  setKind(k.id);
                  setError(null);
                }}
                className={cx(
                  "flex items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors",
                  on ? "border-accent bg-accent-soft" : "border-line bg-surface hover:border-control hover:bg-sunken",
                )}
              >
                <span className={cx("mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md", on ? "bg-accent text-white" : "bg-sunken text-muted")}>
                  <Icon size={15} />
                </span>
                <span>
                  <b className="block text-sm font-semibold">{k.label}</b>
                  <span className="block text-xs text-muted">{k.hint}</span>
                </span>
              </button>
            );
          })}
        </div>
      )}

      {kind === "photo" ? (
        <Panel title="From a photo" icon={<Camera size={15} />}>
          <PhotoIntake />
        </Panel>
      ) : (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <Panel title={def.label} icon={<def.icon size={15} />}>
            <form key={kind} onSubmit={submit} className="flex flex-col gap-4">
              {crewKind && <CrewPicker value={crew} onChange={setCrew} label={kind === "crew_unavailable" ? "Who cannot fly" : "Crew"} />}
              {kind === "crew_unavailable" && (
                <>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Input label="From" type="date" name="first_day" defaultValue={today} required />
                    <Input label="Until" type="date" name="last_day" defaultValue={addDays(today, 3)} required />
                  </div>
                  <Chips
                    label="Reason"
                    value={reason}
                    onChange={setReason}
                    options={[
                      { value: "sick", label: "Sick" },
                      { value: "fatigue", label: "Fatigue" },
                      { value: "personal", label: "Personal" },
                      { value: "other", label: "Other" },
                    ]}
                  />
                  <Input label="Taken ill at (optional, India time)" type="time" name="since" hint="Duties that end before this time on the first day are still flown." />
                </>
              )}
              {kind === "planned_leave" && (
                <>
                  <div className="grid gap-4 sm:grid-cols-3">
                    <Input label="From" type="date" name="first_day" defaultValue={addDays(today, 2)} required />
                    <Input label="Until" type="date" name="last_day" defaultValue={addDays(today, 4)} required />
                    <Select label="Leave" name="leave" defaultValue="annual_leave">
                      <option value="annual_leave">Annual leave</option>
                      <option value="medical">Medical</option>
                      <option value="training">Training</option>
                      <option value="personal">Personal</option>
                    </Select>
                  </div>
                </>
              )}
              {kind === "certification_lapse" && (
                <div className="grid gap-4 sm:grid-cols-3">
                  <Select label="Certificate" name="cert" defaultValue="medical">
                    {CERTS.map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </Select>
                  <Input label="Not valid from" type="date" name="first_day" defaultValue={today} required />
                  <Input label="Renewed by (optional)" type="date" name="last_day" />
                </div>
              )}
              {kind === "flight_delay" && (
                <div className="grid gap-4 sm:grid-cols-3">
                  <Input label="Trip" name="trip_id" defaultValue="T-1018" pattern="[Tt]-\d{4}" required />
                  <Input label="Hours late" type="number" step="0.25" min="0.25" max="24" name="hours" defaultValue="3" required />
                  <Input label="Day (multi-day trips)" type="date" name="day" />
                </div>
              )}
              {kind === "aircraft_technical" && (
                <div className="grid gap-4 sm:grid-cols-3">
                  <Input label="Aircraft" name="tail" defaultValue="VT-SYB" pattern="[Vv][Tt]-[A-Za-z]{3}" required />
                  <Input label="Out of service from (IST)" type="datetime-local" name="start" defaultValue={`${today}T06:00`} required />
                  <Input label="Back (IST)" type="datetime-local" name="end" defaultValue={`${today}T11:00`} required />
                </div>
              )}
              {kind === "station_disruption" && (
                <div className="grid gap-4 sm:grid-cols-3">
                  <Select label="Station" name="station" defaultValue="HYD">
                    {STATIONS.map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </Select>
                  <Input label="Closes (IST)" type="datetime-local" name="start" defaultValue={`${today}T06:30`} required />
                  <Input label="Reopens (IST)" type="datetime-local" name="end" defaultValue={`${today}T09:30`} required />
                </div>
              )}
              {kind === "gate_closure" && (
                <>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Select label="Station" name="station" defaultValue="HYD">
                      {STATIONS.map((s) => (
                        <option key={s}>{s}</option>
                      ))}
                    </Select>
                    <Input label="Gates (comma separated)" name="gates" defaultValue="21, 22" required />
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Input label="Closes (IST)" type="datetime-local" name="start" defaultValue={`${today}T06:00`} required />
                    <Input label="Reopens (IST)" type="datetime-local" name="end" defaultValue={`${today}T09:00`} required />
                  </div>
                </>
              )}
              {kind === "gate_change" && (
                <div className="grid gap-4 sm:grid-cols-2">
                  <Input label="Flight and date" name="leg_id" defaultValue={`SY201-${today}`} required hint="Such as SY201-2026-11-05" />
                  <Input label="New gate" name="gate" defaultValue="22" required />
                </div>
              )}
              <TextArea label="Note for the desk (optional)" name="note" rows={2} maxLength={500} placeholder="Anything the controller should know" />
              {error && <Notice tone="error">{error}</Notice>}
              <div>
                <Button type="submit" disabled={busy || !can("report_disruption")}>
                  {busy ? <Spinner /> : <Send size={15} />} File the report
                </Button>
              </div>
            </form>
          </Panel>
          <Panel title="What happens next" icon={<FileWarning size={15} />}>
            <ol className="flex flex-col gap-3 text-sm">
              {[
                ["Worked out", "The rules engine finds every seat it empties or every flight it moves, and what breaks a duty limit."],
                ["Sent to a desk", "It goes to the controller desk with the fewest open reports; you can follow it on its own page."],
                ["Teams told", "The teams who must know (crew control, the station, maintenance) are listed with a contact."],
                ["Covered together", crewKind ? "The seats are covered together: nobody fills two, and nobody reported is used." : "Crew pushed over a limit are covered like any other seat."],
                ["Two people", "A controller plans it, an approver approves every change and confirms the resolution."],
              ].map(([t, d], i) => (
                <li key={t} className="flex gap-3">
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent-soft font-mono text-xs font-semibold text-accent">{i + 1}</span>
                  <span>
                    <b className="font-medium">{t}.</b> <span className="text-muted">{d}</span>
                  </span>
                </li>
              ))}
            </ol>
          </Panel>
        </div>
      )}
    </div>
  );
}
