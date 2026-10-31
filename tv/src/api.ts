import {API_BASE} from './config';

export type Offer = {
  crew_id: string;
  name: string;
  cost_inr: number;
  answer: string;
};

export type Callout = {
  callout_id: string;
  trip_id: string;
  seat: string;
  replacing: string;
  status: string;
  asked: Offer[];
  waiting_for?: string;
  to_arrange?: string[];
};

export type Issue = {
  issue_id: string;
  kind: 'illegal' | 'fatigue' | 'certificate';
  crew_id: string;
  name: string;
  day: string;
  detail: string;
  trip_id?: string | null;
  suggestion?: string | null;
};

export type Brief = {
  mood: 'calm' | 'busy' | 'critical';
  headline: string;
  lines: string[];
  written_by: string;
};

export type Desk = {
  controller: string;
  open: number;
  filled: number;
  to_approve: number;
};

export type Departure = {
  flight: string;
  route: string;
  departs: string;
  tail: string;
  trip_id: string | null;
  booked: number;
  state: 'affected' | 'on plan';
};

export type Board = {
  clock: string;
  brief: Brief | null;
  issues: Issue[];
  callouts: Callout[];
  next_24h?: {
    flights: number;
    passengers: number;
    crew_out: number;
    open_callouts: number;
    illegal: number;
    fatigue: number;
    certificates: number;
  };
  desks?: Desk[];
  departures?: Departure[];
  standby?: {airline: string; rank: string; on_call: number}[];
  latest?: {subject: string; at: string}[];
};

/** Offers that are over: shown struck through rather than dropped. */
export const GONE = ['declined', 'unavailable', 'no answer', 'no longer legal'];

export async function fetchBoard(base: string = API_BASE): Promise<Board> {
  const res = await fetch(`${base}/api/board`).catch((e: Error) => {
    throw new Error(`cannot reach the board: ${e.message}`);
  });
  if (!res.ok) {
    throw new Error(`board unavailable (${res.status})`);
  }
  return (await res.json()) as Board;
}
