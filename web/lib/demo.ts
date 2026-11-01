import { api, type DemoAccount } from "./api";

/** Used only when the server does not list its demo accounts. */
const FALLBACK: DemoAccount[] = [
  { user: "m.iyer", role: "controller", crew_id: null, label: "Meera Iyer, controller (Desk 1)" },
  { user: "s.reddy", role: "controller", crew_id: null, label: "Sandeep Reddy, controller (Desk 2)" },
  { user: "d.rao", role: "controller", crew_id: null, label: "Divya Rao, controller (Desk 3)" },
  { user: "a.nair", role: "approver", crew_id: null, label: "A. Nair, approver" },
  { user: "ops.hyd", role: "reporter", crew_id: null, label: "Hyderabad station, reporter" },
  { user: "v.shah", role: "auditor", crew_id: null, label: "V. Shah, auditor" },
  { user: "k.menon", role: "admin", crew_id: null, label: "K. Menon, admin" },
  { user: "r.kapoor", role: "super_admin", crew_id: null, label: "R. Kapoor, super admin" },
  { user: "ops.speaker", role: "speaker", crew_id: null, label: "Ops-room speaker" },
  { user: "anjali", role: "crew", crew_id: "C-1157", label: "Anjali Goud, captain (crew)" },
  { user: "pooja.f", role: "crew", crew_id: "C-1167", label: "Pooja Fernandes (crew)" },
];

let cached: Promise<DemoAccount[]> | null = null;

export function demoAccounts(): Promise<DemoAccount[]> {
  cached ??= api<{ accounts: DemoAccount[] }>("/api/accounts/demo", { auth: false })
    .then((r) => (r.accounts?.length ? r.accounts : FALLBACK))
    .catch(() => FALLBACK);
  return cached;
}
