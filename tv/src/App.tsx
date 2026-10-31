import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from 'react-native';
import {TVFocusGuideView} from '@amazon-devices/react-native-kepler';
import {Board, Callout, Departure, GONE, Issue, fetchBoard} from './api';
import {API_BASE, REFRESH_MS} from './config';

// The CrewOps ops-room wall: the next day at a glance, the shift brief, each controller's
// load, callouts, what the watch found, departures, standby cover and the latest messages.
// The remote's arrows move between rows; every number comes from the CrewOps API.

const C = {
  bg: '#0b1017',
  panel: '#131b25',
  line: '#223041',
  ink: '#eef2f7',
  muted: '#93a1b3',
  bad: '#ff7b72',
  warn: '#f2b45c',
  good: '#56d38a',
  focus: '#7aa2ff',
};
const MOOD = {calm: C.good, busy: C.warn, critical: C.bad};
const KIND = {illegal: C.bad, fatigue: C.warn, certificate: C.muted};
const RANK_SHORT: Record<string, string> = {
  Captain: 'CPT',
  'First Officer': 'FO',
  Purser: 'PUR',
  'Cabin Crew': 'CC',
};

/** Sizes are for a 960-wide layout and scale with the real screen, so nothing is cut off. */
const makeStyles = (k: number) =>
  StyleSheet.create({
    screen: {
      flex: 1,
      backgroundColor: C.bg,
      paddingHorizontal: 18 * k,
      paddingVertical: 10 * k,
    },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    title: {color: C.ink, fontSize: 17 * k, fontWeight: '700'},
    clock: {color: C.muted, fontSize: 10 * k},
    error: {color: C.bad, fontSize: 10 * k},
    strip: {flexDirection: 'row', marginTop: 6 * k, marginBottom: 6 * k},
    stat: {
      backgroundColor: C.panel,
      borderRadius: 5 * k,
      paddingVertical: 4 * k,
      paddingHorizontal: 8 * k,
      marginRight: 6 * k,
    },
    statValue: {color: C.ink, fontSize: 14 * k, fontWeight: '700'},
    statLabel: {color: C.muted, fontSize: 7.5 * k},
    columns: {flex: 1, flexDirection: 'row'},
    col: {flex: 1, marginRight: 8 * k},
    colLast: {flex: 1},
    section: {
      color: C.muted,
      fontSize: 7.5 * k,
      letterSpacing: 1,
      marginTop: 6 * k,
      marginBottom: 3 * k,
    },
    sectionTop: {
      color: C.muted,
      fontSize: 7.5 * k,
      letterSpacing: 1,
      marginBottom: 3 * k,
    },
    brief: {
      backgroundColor: C.panel,
      borderRadius: 6 * k,
      padding: 8 * k,
      borderLeftWidth: 4 * k,
    },
    headline: {fontSize: 13 * k, fontWeight: '700', marginBottom: 3 * k},
    line: {color: C.ink, fontSize: 9 * k, marginBottom: 2 * k},
    row: {
      backgroundColor: C.panel,
      borderRadius: 5 * k,
      paddingVertical: 5 * k,
      paddingHorizontal: 7 * k,
      marginBottom: 4 * k,
      borderWidth: 2,
      borderColor: 'transparent',
    },
    rowFocused: {borderColor: C.focus},
    rowTitle: {color: C.ink, fontSize: 9.5 * k, fontWeight: '600'},
    text: {color: C.ink, fontSize: 8.5 * k, marginTop: 1 * k},
    small: {color: C.muted, fontSize: 8 * k, marginTop: 1 * k},
    inline: {flexDirection: 'row', flexWrap: 'wrap', alignItems: 'baseline'},
    gap: {marginRight: 6 * k},
    struck: {
      color: C.muted,
      fontSize: 8.5 * k,
      textDecorationLine: 'line-through',
    },
    table: {flexDirection: 'row', justifyContent: 'space-between'},
    cell: {color: C.ink, fontSize: 8.5 * k},
    zero: {color: C.bad, fontSize: 8.5 * k, fontWeight: '700'},
  });

type Styles = ReturnType<typeof makeStyles>;
const Styled = React.createContext<Styles>(makeStyles(1));

/** A row the remote can land on, so long lists can be read with the arrow keys. */
const Row = ({
  children,
  label,
  testID,
}: {
  children: React.ReactNode;
  label: string;
  testID?: string;
}) => {
  const s = React.useContext(Styled);
  const [focused, setFocused] = useState(false);
  return (
    <Pressable
      testID={testID}
      aria-label={label}
      role="summary"
      accessibilityHint="Move up or down to read the next item"
      focusable
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={[s.row, focused && s.rowFocused]}>
      {children}
    </Pressable>
  );
};

const Stat = ({
  value,
  label,
  color,
}: {
  value: number | string;
  label: string;
  color?: string;
}) => {
  const s = React.useContext(Styled);
  return (
    <View style={s.stat}>
      <Text style={[s.statValue, color ? {color} : null]}>{value}</Text>
      <Text style={s.statLabel}>{label}</Text>
    </View>
  );
};

const CalloutRow = ({c}: {c: Callout}) => {
  const s = React.useContext(Styled);
  return (
    <Row
      testID={`callout-${c.callout_id}`}
      label={`${c.trip_id} ${c.seat}, ${c.status.replace('_', ' ')}: ${c.asked
        .map((o) => `${o.name} ${o.answer}`)
        .join(', ')}`}>
      <Text style={s.rowTitle}>
        {c.trip_id} {c.seat}{' '}
        <Text style={{color: c.status === 'filled' ? C.good : C.warn}}>
          {c.status.replace('_', ' ')}
        </Text>
      </Text>
      {/* One element per person: a strike-through must never spill onto the next name. */}
      <View style={s.inline}>
        {c.asked.map((o) => (
          <View key={o.crew_id} style={[s.inline, s.gap]}>
            <Text
              testID={`offer-${o.crew_id}`}
              style={GONE.includes(o.answer) ? s.struck : s.text}>
              {o.name}
            </Text>
            <Text style={s.small}> {o.answer}</Text>
          </View>
        ))}
      </View>
      {c.to_arrange?.length ? (
        <Text style={[s.small, {color: C.warn}]}>
          To arrange: {c.to_arrange.join('; ')}
        </Text>
      ) : null}
    </Row>
  );
};

const IssueRow = ({i}: {i: Issue}) => {
  const s = React.useContext(Styled);
  return (
    <Row
      testID={`issue-${i.issue_id}`}
      label={`${i.kind}: ${i.name}. ${i.detail}`}>
      <Text style={s.rowTitle}>
        <Text style={{color: KIND[i.kind]}}>{i.kind.toUpperCase()} </Text>
        {i.name}
        {i.trip_id ? `  ·  ${i.trip_id}` : ''}
      </Text>
      <Text style={s.text}>{i.detail.replace(/_/g, ' ')}</Text>
      {i.suggestion ? <Text style={s.small}>Cover: {i.suggestion}</Text> : null}
    </Row>
  );
};

const DepartureRow = ({d}: {d: Departure}) => {
  const s = React.useContext(Styled);
  return (
    <Row label={`${d.flight} ${d.route} at ${d.departs}, ${d.state}`}>
      <View style={s.table}>
        <Text style={s.rowTitle}>
          {d.flight} {d.route}
        </Text>
        <Text
          style={[s.cell, {color: d.state === 'affected' ? C.bad : C.good}]}>
          {d.state}
        </Text>
      </View>
      <Text style={s.small}>
        {d.departs} IST · {d.tail} · {d.booked} booked
        {d.trip_id ? ` · ${d.trip_id}` : ''}
      </Text>
    </Row>
  );
};

export const App = ({load = fetchBoard}: {load?: () => Promise<Board>}) => {
  const {width} = useWindowDimensions();
  const s = useMemo(() => makeStyles(Math.max(0.6, width / 960)), [width]);
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    load()
      .then((b) => {
        setBoard(b);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [load]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const n = board?.next_24h;
  const brief = board?.brief;
  const standby = board?.standby ?? [];
  const airlines = [...new Set(standby.map((x) => x.airline))];
  const ranks = Object.keys(RANK_SHORT);

  return (
    <Styled.Provider value={s}>
      <View style={s.screen}>
        <View style={s.header}>
          <Text style={s.title}>CrewOps Board (Meta)</Text>
          <Text style={error ? s.error : s.clock} testID="clock">
            {error
              ? `${error} · ${API_BASE}`
              : board
              ? `Operation clock ${board.clock}`
              : 'Loading…'}
          </Text>
        </View>

        {n ? (
          <View style={s.strip} testID="strip">
            <Stat value={n.flights} label="FLIGHTS NEXT 24H" />
            <Stat
              value={n.passengers.toLocaleString('en-IN')}
              label="PASSENGERS"
            />
            <Stat
              value={n.crew_out}
              label="CREW OUT"
              color={n.crew_out ? C.warn : undefined}
            />
            <Stat
              value={n.open_callouts}
              label="OPEN CALLOUTS"
              color={n.open_callouts ? C.warn : undefined}
            />
            <Stat
              value={n.illegal}
              label="ILLEGAL"
              color={n.illegal ? C.bad : C.good}
            />
            <Stat
              value={n.fatigue}
              label="FATIGUE"
              color={n.fatigue ? C.warn : undefined}
            />
            <Stat value={n.certificates} label="CERTS DUE" />
          </View>
        ) : null}

        <TVFocusGuideView style={s.columns}>
          <View style={s.col}>
            <View
              style={[
                s.brief,
                {borderLeftColor: brief ? MOOD[brief.mood] : C.line},
              ]}
              testID="brief">
              <Text
                style={[s.headline, {color: brief ? MOOD[brief.mood] : C.ink}]}>
                {brief?.headline ?? 'Shift brief on the way'}
              </Text>
              {brief?.lines.map((line) => (
                <Text key={line} style={s.line}>
                  • {line.replace(/_/g, ' ')}
                </Text>
              ))}
              {brief ? (
                <Text style={s.small}>
                  {brief.written_by === 'muse-wonder'
                    ? 'Written by Muse Wonder; every figure checked against the engine'
                    : 'Built from the engine’s facts'}
                </Text>
              ) : null}
            </View>
            <Text style={s.section}>CONTROLLER DESKS</Text>
            {board?.desks?.length ? (
              board.desks.map((d) => (
                <Row
                  key={d.controller}
                  label={`${d.controller}: ${d.open} open`}>
                  <View style={s.table}>
                    <Text style={s.rowTitle}>{d.controller}</Text>
                    <Text style={s.cell}>
                      {d.open} open · {d.filled} filled
                      {d.to_approve ? ` · ${d.to_approve} to approve` : ''}
                    </Text>
                  </View>
                </Row>
              ))
            ) : (
              <Text style={s.small}>No callouts in progress.</Text>
            )}
            <Text style={s.section}>CALLOUTS</Text>
            <ScrollView>
              {board?.callouts.length ? (
                board.callouts.map((c) => (
                  <CalloutRow key={c.callout_id} c={c} />
                ))
              ) : (
                <Text style={s.small}>None.</Text>
              )}
            </ScrollView>
          </View>

          <View style={s.col}>
            <Text style={s.sectionTop}>WHAT THE WATCH FOUND</Text>
            <ScrollView>
              {board?.issues.length ? (
                board.issues.map((i) => <IssueRow key={i.issue_id} i={i} />)
              ) : (
                <Text style={s.small}>Nothing found.</Text>
              )}
            </ScrollView>
          </View>

          <View style={s.colLast}>
            <Text style={s.sectionTop}>NEXT DEPARTURES</Text>
            {board?.departures?.slice(0, 6).map((d) => (
              <DepartureRow key={`${d.flight}-${d.departs}`} d={d} />
            ))}
            <Text style={s.section}>STANDBY ON CALL (TODAY AND TOMORROW)</Text>
            <View style={s.row}>
              <View style={s.table}>
                <Text
                  style={[s.cell, {color: C.muted, width: 40 * (width / 960)}]}>
                  {' '}
                </Text>
                {ranks.map((r) => (
                  <Text key={r} style={[s.cell, {color: C.muted}]}>
                    {RANK_SHORT[r]}
                  </Text>
                ))}
              </View>
              {airlines.map((a) => (
                <View key={a} style={s.table}>
                  <Text style={[s.cell, {width: 40 * (width / 960)}]}>{a}</Text>
                  {ranks.map((r) => {
                    const on =
                      standby.find((x) => x.airline === a && x.rank === r)
                        ?.on_call ?? 0;
                    return (
                      <Text key={r} style={on ? s.cell : s.zero}>
                        {on}
                      </Text>
                    );
                  })}
                </View>
              ))}
            </View>
            <Text style={s.section}>LATEST</Text>
            {board?.latest?.length ? (
              board.latest.slice(0, 4).map((m) => (
                <Text
                  key={`${m.at}-${m.subject}`}
                  style={s.small}
                  numberOfLines={1}>
                  {m.at} {m.subject}
                </Text>
              ))
            ) : (
              <Text style={s.small}>No messages yet.</Text>
            )}
          </View>
        </TVFocusGuideView>
      </View>
    </Styled.Provider>
  );
};
