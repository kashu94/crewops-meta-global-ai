/* Sign-in artwork: the network at night, seen as a route map. Stations sit where they are on
   the map of India, the routes out of the Hyderabad hub glow and carry traffic, and a slow
   radar sweep turns over the hub. Plain SVG and CSS; motion stops under reduced motion. */

type Pt = [number, number];

// Longitude and latitude, projected onto a 600 x 700 canvas.
const at = (lon: number, lat: number): Pt => [(lon - 68) * 34 + 20, (31 - lat) * 34 + 20];

const STATIONS: Record<string, Pt> = {
  DEL: at(77.1, 28.6),
  BOM: at(72.9, 19.1),
  GOI: at(73.8, 15.4),
  BLR: at(77.7, 13.2),
  MAA: at(80.2, 13.0),
  HYD: at(78.4, 17.2),
  VGA: at(80.8, 16.5),
  RJA: at(81.8, 17.1),
  TIR: at(79.5, 13.6),
  VTZ: at(83.2, 17.7),
};

const ROUTES: [string, string, number][] = [
  ["HYD", "DEL", 0],
  ["HYD", "BOM", 1],
  ["HYD", "BLR", 2],
  ["HYD", "MAA", 3],
  ["HYD", "GOI", 4],
  ["HYD", "VTZ", 5],
  ["HYD", "TIR", 6],
  ["BOM", "DEL", 7],
  ["BOM", "GOI", 8],
  ["BLR", "MAA", 9],
  ["VGA", "BLR", 10],
  ["RJA", "BOM", 11],
  ["DEL", "VTZ", 12],
];

function arc(a: Pt, b: Pt, bend = 0.18): string {
  const [x1, y1] = a;
  const [x2, y2] = b;
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  return `M${x1.toFixed(1)},${y1.toFixed(1)} Q${(mx - dy * bend).toFixed(1)},${(my + dx * bend).toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`;
}

const HUB = STATIONS.HYD;

export function RouteMap() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(120%_80%_at_70%_70%,#123457_0%,#0a1c33_45%,#050c18_100%)]" />
      <div className="haze absolute -right-1/4 top-1/4 h-[70%] w-[90%] rounded-full bg-[#1d5c96]/25 blur-[110px]" />
      <div className="haze absolute -left-1/4 -top-1/4 h-[60%] w-[70%] rounded-full bg-[#2a7f8f]/15 blur-[120px] [animation-delay:-12s]" />

      <svg viewBox="0 0 600 700" preserveAspectRatio="xMaxYMid slice" className="absolute inset-0 h-full w-full">
        <defs>
          <pattern id="dots" width="14" height="14" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="0.8" fill="#8fb6dc" opacity="0.14" />
          </pattern>
          <radialGradient id="sweep-fade" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stopColor="#7fb2e5" stopOpacity="0.16" />
            <stop offset="1" stopColor="#7fb2e5" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="route" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#7fd3ff" stopOpacity="0.55" />
            <stop offset="1" stopColor="#f6c35b" stopOpacity="0.45" />
          </linearGradient>
          <filter id="soft" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2.4" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <rect width="600" height="700" fill="url(#dots)" />

        {/* range rings and the radar sweep over the hub */}
        {[70, 140, 210, 280].map((r) => (
          <circle key={r} cx={HUB[0]} cy={HUB[1]} r={r} fill="none" stroke="#8fb6dc" strokeOpacity={0.09} strokeDasharray="2 6" />
        ))}
        <g style={{ transformOrigin: `${HUB[0]}px ${HUB[1]}px`, transformBox: "view-box" }} className="radar-sweep">
          <path d={`M${HUB[0]},${HUB[1]} L${HUB[0] + 280},${HUB[1]} A280,280 0 0,0 ${HUB[0] + 280 * Math.cos(-0.5)},${HUB[1] + 280 * Math.sin(-0.5)} Z`} fill="url(#sweep-fade)" />
        </g>

        {/* the routes, each with traffic moving along it */}
        {ROUTES.map(([from, to, i]) => {
          const d = arc(STATIONS[from], STATIONS[to]);
          return (
            <g key={`${from}-${to}`}>
              <path d={d} fill="none" stroke="#8fb6dc" strokeOpacity={0.12} strokeWidth={1} />
              <path d={d} fill="none" stroke="url(#route)" strokeWidth={1.4} className="route-flow" style={{ animationDelay: `${-i * 0.37}s` }} />
              <circle r={2.3} fill="#fff6d6" filter="url(#soft)" className="plane-dot">
                <animateMotion dur={`${9 + (i % 5) * 2.2}s`} begin={`${-i * 1.3}s`} repeatCount="indefinite" path={d} />
              </circle>
            </g>
          );
        })}

        {/* stations */}
        {Object.entries(STATIONS).map(([code, [x, y]], i) => (
          <g key={code}>
            <circle cx={x} cy={y} r={code === "HYD" ? 9 : 6} fill="#7fd3ff" opacity={0.18} className="station-blip" style={{ animationDelay: `${-i * 0.4}s` }} />
            <circle cx={x} cy={y} r={code === "HYD" ? 3.6 : 2.6} fill={code === "HYD" ? "#f6c35b" : "#dff3ff"} filter="url(#soft)" />
            <text x={x + 8} y={y + 4} fill="#c9d8e8" fillOpacity={0.75} fontSize="10.5" fontFamily="var(--font-plex-mono), monospace" letterSpacing="0.06em">
              {code}
            </text>
          </g>
        ))}
      </svg>

      {/* keep the words readable */}
      <div className="absolute inset-0 bg-[linear-gradient(100deg,rgba(4,10,22,0.86)_0%,rgba(4,10,22,0.55)_45%,rgba(4,10,22,0.05)_100%)]" />
      <style>{`@media (prefers-reduced-motion: reduce) { .plane-dot { display: none; } }`}</style>
    </div>
  );
}
