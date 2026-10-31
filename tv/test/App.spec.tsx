import 'react-native';
import {render, waitFor} from '@testing-library/react-native';
import * as React from 'react';

import {App} from '../src/App';
import {Board} from '../src/api';

const BOARD: Board = {
  clock: 'Thu 29 Oct, 23:30 IST',
  brief: {
    mood: 'critical',
    headline: 'Cover T-1018',
    lines: ['Pooja Chowdary (C-1111) cannot fly T-1018.'],
    written_by: 'muse-wonder',
  },
  issues: [
    {
      issue_id: 'illegal:C-1111:T-1018',
      kind: 'illegal',
      crew_id: 'C-1111',
      name: 'Pooja Chowdary',
      day: '2026-11-05',
      detail: 'FDTL-08 medical runs out',
      trip_id: 'T-1018',
      suggestion: 'Captain Pooja Fernandes (C-1167)',
    },
  ],
  callouts: [
    {
      callout_id: 'CO-1',
      trip_id: 'T-1018',
      seat: 'Captain',
      replacing: 'C-1111',
      status: 'offered',
      waiting_for: 'C-1167',
      asked: [
        {
          crew_id: 'C-1157',
          name: 'Anjali Goud',
          cost_inr: 20840,
          answer: 'unavailable',
        },
        {
          crew_id: 'C-1167',
          name: 'Pooja Fernandes',
          cost_inr: 31160,
          answer: 'waiting',
        },
      ],
    },
  ],
};

const OPS = {
  ...BOARD,
  next_24h: {
    flights: 42,
    passengers: 5120,
    crew_out: 1,
    open_callouts: 1,
    illegal: 1,
    fatigue: 5,
    certificates: 6,
  },
  desks: [{controller: 'm.iyer', open: 1, filled: 0, to_approve: 0}],
  departures: [
    {
      flight: 'SY221',
      route: 'HYD-BLR',
      departs: '05 Nov 07:30',
      tail: 'VT-SYB',
      trip_id: 'T-1018',
      booked: 116,
      state: 'affected' as const,
    },
  ],
  standby: [
    {airline: 'SY', rank: 'Captain', on_call: 2},
    {airline: 'SY', rank: 'Purser', on_call: 0},
  ],
  latest: [{subject: 'Offer withdrawn: Captain on T-1018', at: '31 Oct 12:29'}],
};

describe('App', () => {
  it('shows the ops room: the day, desks, departures and standby gaps', async () => {
    const screen = render(<App load={() => Promise.resolve(OPS)} />);
    await waitFor(() =>
      expect(screen.getByText('FLIGHTS NEXT 24H')).toBeTruthy(),
    );
    expect(screen.getByText('42')).toBeTruthy();
    expect(screen.getByText('m.iyer')).toBeTruthy();
    expect(screen.getByText('affected')).toBeTruthy();
    expect(screen.getByText(/Offer withdrawn/)).toBeTruthy();
  });

  it('shows the brief, the issues and the callouts', async () => {
    const screen = render(<App load={() => Promise.resolve(BOARD)} />);
    await waitFor(() => expect(screen.getByText('Cover T-1018')).toBeTruthy());
    expect(screen.getByText(/Thu 29 Oct, 23:30 IST/)).toBeTruthy();
    expect(screen.getByTestId('issue-illegal:C-1111:T-1018')).toBeTruthy();
    expect(
      screen.getByText(
        'Written by Muse Wonder; every figure checked against the engine',
      ),
    ).toBeTruthy();
  });

  it('strikes through crew who can no longer take the seat', async () => {
    const screen = render(<App load={() => Promise.resolve(BOARD)} />);
    const anjali = await waitFor(() => screen.getByText('Anjali Goud'));
    expect(anjali.props.style).toEqual(
      expect.objectContaining({textDecorationLine: 'line-through'}),
    );
    expect(
      screen.getByText('Pooja Fernandes').props.style.textDecorationLine,
    ).toBeUndefined();
  });

  it('says so when the board cannot be reached', async () => {
    const screen = render(
      <App load={() => Promise.reject(new Error('board unavailable (503)'))} />,
    );
    await waitFor(() =>
      expect(screen.getByText(/board unavailable \(503\)/)).toBeTruthy(),
    );
  });
});
