"use client";

import { ArrowRight, Inbox, LayoutGrid, ListChecks, Radio, TriangleAlert, UserPlus, Users } from "lucide-react";
import Link from "next/link";

import { Part } from "@/components/part";
import { CalloutList, DeskLoadTable, IssueList, NoticeList, ReportRows } from "@/components/ops";
import { useSession } from "@/components/session";
import { Button, Kpi, Kpis, Loading, Mono, Notice, PageHeader, Panel, SeverityBadge } from "@/components/ui";
import { api, tool } from "@/lib/api";
import { inr, plural } from "@/lib/format";
import { settle } from "@/lib/settle";
import type { Board, Callout, DeskLoad, Issue, Notice as NoticeT, ReportSummary } from "@/lib/types";
import { useAction, useLoad } from "@/lib/use-load";

const RUNNING = ["offered", "accepted", "needs_decision", "awaiting_approval"];

export default function DeskPage() {
  const { me, can } = useSession();
  const { busy, run } = useAction();
  const deskId = me.desk?.desk_id;
  const { data, error } = useLoad(
    async () => {
      const [board, issues, callouts, inbox, load, mine] = await Promise.all([
        settle(api<Board>("/api/board")),
        settle(tool<{ issues: Issue[] }>("open_issues", { limit: 30 })),
        settle(tool<{ callouts: Callout[] }>("callout_status", {})),
        settle(api<{ notices: NoticeT[] }>("/api/notices?limit=12")),
        can("desk_load") ? settle(tool<{ desks: DeskLoad[] }>("desk_load")) : Promise.resolve(null),
        can("disruptions")
          ? settle(tool<{ disruptions: ReportSummary[] }>("disruptions", { status: "active", ...(deskId ? { desk_id: deskId } : {}), limit: 12 }))
          : Promise.resolve(null),
      ]);
      return { board, issues, callouts, inbox, load, mine };
    },
    deskId ?? "",
  );

  if (error) return <Notice tone="error">{error}</Notice>;
  if (!data) return <Loading />;

  const board = data.board.ok ? data.board.value : null;
  const n = board?.next_24h;
  const list = data.issues.ok ? data.issues.value.issues ?? [] : [];
  const high = list.filter((i) => i.severity === "high").length;
  const callouts = data.callouts.ok ? data.callouts.value.callouts ?? [] : [];
  const running = callouts.filter((c) => RUNNING.includes(c.status));
  const handled = new Set(running.map((c) => `${c.trip_id}|${c.replacing}`));
  const top = list[0];
  const mine = data.mine?.ok ? data.mine.value.disruptions ?? [] : [];

  return (
    <div className="animate-rise">
      <PageHeader
        eyebrow={me.desk ? `${me.desk.name} · ${me.name || me.user}` : "Crew control"}
        title={me.role === "controller" ? "Your desk" : "The desks"}
        lede={<>Operation clock <Mono>{board?.clock ?? me.clock}</Mono>. Problems ranked by how soon they bite and how many passengers they reach.</>}
        actions={
          <>
            {can("report_disruption") && (
              <Link href="/report/">
                <Button tone="secondary">
                  <TriangleAlert size={15} /> Report a disruption
                </Button>
              </Link>
            )}
            {can("find_cover") && (
              <Link href="/cover/">
                <Button>
                  <UserPlus size={15} /> Find cover
                </Button>
              </Link>
            )}
          </>
        }
      />

      {top ? (
        <Notice tone={top.severity === "high" ? "error" : "pending"} className="mb-5" icon={<SeverityBadge severity={{ level: top.severity }} />}>
          <div className="flex flex-wrap items-start gap-3">
            <p className="min-w-0 flex-1 basis-80">
              <b>
                {top.name}
                {top.trip_id ? ` on ${top.trip_id}` : ""}:
              </b>{" "}
              {top.detail}. <span className="opacity-80">{top.severity_reasons.join("; ")}.</span>
              {top.suggested_cover ? ` Cheapest legal cover: ${top.suggested_cover}, ${inr(top.suggested_cost_inr)}.` : ""}
            </p>
            {top.kind === "illegal" && top.trip_id && can("start_callout") && !handled.has(`${top.trip_id}|${top.crew_id}`) && (
              <Button
                size="sm"
                disabled={busy !== null}
                onClick={() => run("top", () => tool("start_callout", { trip_id: top.trip_id, replace_crew_id: top.crew_id }), () => `Callout started for ${top.trip_id}.`)}
              >
                Start callout
              </Button>
            )}
          </div>
        </Notice>
      ) : data.issues.ok ? (
        <Notice tone="ok" className="mb-5">
          Nothing in the next 7 days breaks a rule.
        </Notice>
      ) : null}

      <Kpis>
        <Kpi icon={<TriangleAlert size={13} />} value={list.length} sub={high ? `${high} high` : undefined} label="Problems, next 7 days" tone={high ? "critical" : undefined} />
        <Kpi icon={<ListChecks size={13} />} value={n?.plans_waiting ?? 0} label="Changes waiting for approval" tone={n?.plans_waiting ? "pending" : undefined} />
        <Kpi icon={<Radio size={13} />} value={running.length} label="Callouts running" />
        <Kpi icon={<Users size={13} />} value={n?.crew_out ?? 0} label="Crew out today or tomorrow" />
        <Kpi icon={<LayoutGrid size={13} />} value={n?.flights ?? 0} sub={`${(n?.passengers ?? 0).toLocaleString("en-IN")} pax`} label="Flights, next 24 hours" />
      </Kpis>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="flex min-w-0 flex-col gap-5">
          {data.mine && (
            <Panel
              flush
              title={me.desk ? `Disruptions on ${me.desk.name}` : "Active disruptions"}
              icon={<ListChecks size={15} />}
              action={
                <Link href="/disruptions/" className="inline-flex items-center gap-1 text-accent hover:underline">
                  All <ArrowRight size={13} />
                </Link>
              }
            >
              <Part of={data.mine}>{() => <ReportRows reports={mine} empty="Nothing active on this desk." />}</Part>
            </Panel>
          )}
          <Panel flush title="Problems by urgency" icon={<TriangleAlert size={15} />} action={`${list.length} found by the watch`}>
            <Part of={data.issues}>{() => <IssueList issues={list} running={handled} />}</Part>
          </Panel>
        </div>
        <div className="flex min-w-0 flex-col gap-5">
          {data.load && (
            <Panel title="Desk load" icon={<LayoutGrid size={15} />} action="new reports go to the least loaded desk">
              <Part of={data.load}>{(v) => <DeskLoadTable desks={v.desks ?? []} />}</Part>
            </Panel>
          )}
          <Panel flush title="Callouts" icon={<Radio size={15} />} action={running.length ? `${running.length} running` : undefined}>
            <Part of={data.callouts}>{() => <CalloutList callouts={callouts.slice().reverse().slice(0, 6)} empty="No callouts. Start one from a problem." />}</Part>
          </Panel>
          <Panel flush title="Desk messages" icon={<Inbox size={15} />}>
            <Part of={data.inbox}>{(v) => <NoticeList notices={(v.notices ?? []).slice(0, 8)} />}</Part>
          </Panel>
        </div>
      </div>
    </div>
  );
}
