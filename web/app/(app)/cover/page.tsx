"use client";

import { Filter, HelpCircle, Plane, Radio, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { RiskBadge } from "@/components/ops";
import { useSession } from "@/components/session";
import { Button, control, cx, Input, Label, Loading, Mono, Notice, PageHeader, Panel, Pill, Table } from "@/components/ui";
import { message, tool } from "@/lib/api";
import { hhmm, inr, plural, short } from "@/lib/format";
import type { CoverResult, Plan, TripDetails } from "@/lib/types";
import { useAction, useLoad } from "@/lib/use-load";

const PICK: Record<string, string> = { cheapest: "cheapest", least_delay: "least delay", keeps_standby: "keeps standby free" };

function WhyNot({ trip, rank, crew }: { trip: string; rank: string; crew: string }) {
  const [out, setOut] = useState<React.ReactNode>(null);
  async function ask(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const id = String(new FormData(e.currentTarget).get("crew") ?? "").trim().toUpperCase();
    setOut(<span className="text-muted">Checking…</span>);
    try {
      const w = await tool<CoverResult>("find_cover", { trip_id: trip, rank, vacated_by: crew, explain: [id], limit: 1 });
      const x = w.why_not?.[id];
      setOut(
        !x ? (
          "No answer."
        ) : typeof x === "string" ? (
          x
        ) : (
          <>
            <b>Out at “{x.stage}”</b> <span className="text-muted">({x.rules.join(", ")})</span>
            <ul className="mt-1 list-disc pl-5">
              {x.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </>
        ),
      );
    } catch (err) {
      setOut(<span className="text-critical">{message(err)}</span>);
    }
  }
  return (
    <Panel title="Why not someone?" icon={<HelpCircle size={15} />}>
      <form onSubmit={ask} className="flex items-end gap-2">
        <Input label="Crew id" name="crew" placeholder="C-1123" pattern="[Cc]-\d{4}" required className="flex-1" />
        <Button tone="secondary">Explain</Button>
      </form>
      {out && <div className="mt-3 text-sm">{out}</div>}
    </Panel>
  );
}

export default function CoverPage() {
  const params = useSearchParams();
  const router = useRouter();
  const { can } = useSession();
  const { busy, run } = useAction();
  const trip = (params.get("trip") || "T-1018").toUpperCase();
  const crewParam = params.get("crew") || "";
  const report = params.get("report") || "";
  const [tripInput, setTripInput] = useState(trip);

  const go = (t: string, c = "") => {
    const q = new URLSearchParams({ trip: t, ...(c ? { crew: c } : {}), ...(report ? { report } : {}) });
    router.replace(`/cover/?${q}`);
  };

  const { data, error, loading } = useLoad(async () => {
    const details = await tool<TripDetails>("trip_details", { trip_id: trip });
    const seat = details.crew.find((c) => c.crew_id === crewParam) ?? details.crew[0];
    if (!seat) return { details, seat: null, cover: null, coverError: "Nobody is rostered on this trip." };
    try {
      const cover = await tool<CoverResult>("find_cover", { trip_id: trip, rank: seat.seat, vacated_by: seat.crew_id, limit: 10 });
      return { details, seat, cover, coverError: null };
    } catch (err) {
      return { details, seat, cover: null, coverError: message(err) };
    }
  }, `${trip}|${crewParam}`);

  const t = data?.details;
  const seat = data?.seat;
  const r = data?.cover;
  const pickOf = (id?: string) => (id ? Object.entries(r?.picks ?? {}).filter(([, c]) => c.crew_id === id).map(([k]) => PICK[k] ?? k) : []);

  return (
    <div className="animate-rise">
      <PageHeader
        title="Find cover"
        lede="Every legal way to fill a seat, cheapest first, with who was ruled out at each stage and why. Crew who reported they cannot fly stay on the list, struck through. Risk is shown beside each person; it never changes the order."
      />
      {report && (
        <Notice className="mb-4">
          Working cover for report{" "}
          <Link className="font-medium underline" href={`/disruptions/view/?id=${encodeURIComponent(report)}`}>
            <Mono>{report}</Mono>
          </Link>
          : plans and callouts started here are linked to it.
        </Notice>
      )}
      <form
        className="mb-5 grid gap-3 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_auto] sm:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          go(tripInput.trim().toUpperCase());
        }}
      >
        <Input label="Trip" value={tripInput} onChange={(e) => setTripInput(e.target.value)} pattern="[Tt]-\d{4}" required />
        <Label label="Who leaves the seat">
          <select className={control} value={seat?.crew_id ?? ""} onChange={(e) => go(trip, e.target.value)} disabled={!t}>
            {(t?.crew ?? []).map((c) => (
              <option key={c.crew_id} value={c.crew_id}>
                {c.seat}: {c.name} ({c.crew_id})
              </option>
            ))}
          </select>
        </Label>
        <Button type="submit">
          <Search size={15} /> Find cover
        </Button>
      </form>

      {error ? (
        <Notice tone="error">{error}</Notice>
      ) : !data ? (
        <Loading />
      ) : (
        <div className={cx("grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]", loading && "opacity-70")}>
          <Panel
            flush
            title={r ? `Choices for the ${r.seat} seat on ${r.trip_id}` : "Choices"}
            icon={<Filter size={15} />}
            action={r ? plural(r.facts?.legal_choices ?? r.choices.length, "legal crew choice") : undefined}
          >
            {data.coverError || !r ? (
              <div className="p-4">
                <Notice tone="error">{data.coverError}</Notice>
              </div>
            ) : (
              <>
                <div className="flex flex-wrap gap-px border-b border-rule bg-rule">
                  <div className="flex-1 basis-28 bg-surface px-4 py-2.5">
                    <b className="block font-mono text-lg">{r.considered}</b>
                    <span className="text-xs text-muted">could sit in the seat</span>
                  </div>
                  {r.funnel.map((s) => (
                    <div key={s.stage} className="flex-1 basis-28 bg-surface px-4 py-2.5" title={s.reason}>
                      <b className="block font-mono text-lg">{s.left}</b>
                      <span className="text-xs text-muted">
                        {s.stage} <span className="text-critical">−{s.dropped}</span>
                      </span>
                    </div>
                  ))}
                </div>
                <Table>
                  <thead>
                    <tr>
                      <th className="text-right">#</th>
                      <th>Choice</th>
                      <th>Risk</th>
                      <th className="text-right">Cost</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {r.choices.map((c) => {
                      const tags = pickOf(c.crew_id);
                      return (
                        <tr key={`${c.position}-${c.crew_id ?? c.way}`} className={tags.length ? "bg-accent-soft/50" : ""}>
                          <td className="text-right font-mono text-muted">{c.position}</td>
                          <td>
                            <span className="font-medium">{c.summary}</span>{" "}
                            {tags.map((x) => (
                              <Pill key={x} tone="accent" className="ml-1">
                                {x}
                              </Pill>
                            ))}
                            {(c.fatigue ?? []).map((f) => (
                              <span key={f.detail} className="mt-0.5 block text-xs text-pending-ink">
                                {f.severity} fatigue: {f.detail}
                              </span>
                            ))}
                            {c.to_arrange && <span className="mt-0.5 block text-xs text-muted">To arrange: {c.to_arrange.join("; ")}</span>}
                          </td>
                          <td>{c.risk ? <RiskBadge risk={c.risk} compact /> : <span className="text-faint">–</span>}</td>
                          <td className="text-right font-mono">{inr(c.cost_inr)}</td>
                          <td className="text-right">
                            {c.crew_id && can("assign_crew") && seat && (
                              <Button
                                size="sm"
                                tone="secondary"
                                disabled={busy !== null}
                                onClick={() =>
                                  run(
                                    c.crew_id!,
                                    () =>
                                      tool<Plan>("assign_crew", {
                                        trip_id: trip,
                                        replace_crew_id: seat.crew_id,
                                        with_crew_id: c.crew_id,
                                        expected_version: t!.version,
                                        reason: `cover for ${seat.crew_id}`,
                                        ...(report ? { report_id: report } : {}),
                                      }),
                                    (p) => `${p.plan_id} submitted. An approver decides it.`,
                                  )
                                }
                              >
                                Submit plan
                              </Button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                    {(r.withdrawn ?? []).map((w) => (
                      <tr key={`w-${w.crew_id}`} className="text-faint">
                        <td className="text-right">–</td>
                        <td>
                          <span className="line-through">{w.summary}</span> <Pill tone="critical">cannot fly: {w.reason}</Pill>
                        </td>
                        <td>{w.risk && <RiskBadge risk={w.risk} compact />}</td>
                        <td className="text-right font-mono">{inr(w.cost_inr)}</td>
                        <td />
                      </tr>
                    ))}
                  </tbody>
                </Table>
                {r.more_choices > 0 && <p className="border-t border-rule px-4 py-2 text-xs text-muted">{plural(r.more_choices, "more legal choice")} not shown.</p>}
              </>
            )}
          </Panel>
          <div className="flex min-w-0 flex-col gap-5">
            {t && (
              <Panel title={<>Trip <Mono>{t.trip_id}</Mono></>} icon={<Plane size={15} />} action={`version ${t.version}`}>
                <p className="text-xs text-muted">
                  {t.route} · <Mono>{t.tail}</Mono> · reports {short(t.report)}
                </p>
                <ul className="mt-3 divide-y divide-rule text-sm">
                  {t.legs.map((l) => (
                    <li key={l.flight + l.departs} className="flex items-center gap-3 py-1.5">
                      <Mono className="w-16 font-medium">{l.flight}</Mono>
                      <span className="flex-1">
                        {l.from}–{l.to}
                      </span>
                      <span className="font-mono text-xs text-muted">
                        {short(l.departs).slice(0, 6)} {hhmm(l.departs)}
                      </span>
                      <span className="w-12 text-right font-mono text-xs text-muted">{l.booked} pax</span>
                    </li>
                  ))}
                </ul>
              </Panel>
            )}
            {can("start_callout") && seat && (
              <Panel title="Call crew out" icon={<Radio size={15} />}>
                <p className="mb-3 text-sm text-muted">Offers the seat to the cheapest legal crew member, then the next, until someone accepts. It never cancels on its own.</p>
                <Button
                  disabled={busy !== null}
                  onClick={() =>
                    run("callout", () => tool("start_callout", { trip_id: trip, replace_crew_id: seat.crew_id, ...(report ? { report_id: report } : {}) }), () => "Callout started.")
                  }
                >
                  Start callout for <Mono>{seat.crew_id}</Mono>
                </Button>
              </Panel>
            )}
            {seat && <WhyNot trip={trip} rank={seat.seat} crew={seat.crew_id} />}
          </div>
        </div>
      )}
    </div>
  );
}
