/* Sign-in artwork: short final at night. The runway's edge lights run to a vanishing point
   right of centre, the approach strobes race towards the threshold, the glide-path lights
   show two white and two red, and the airfield's lights drift past out of focus. Plain SVG
   and CSS; motion stops under reduced motion. */

const W = 600;
const H = 800;
const HORIZON = 420;
const GROUND = 820;
/** The vanishing point: right of centre, so the words sit over open sky. */
const VX = 455;
const HALF = 270;
const ROWS = 60;

/** 1 at the near end, shrinking towards the horizon. */
const DEPTH = Array.from({ length: ROWS }, (_, i) => 1 / (1 + i * 0.32));
const yAt = (d: number) => HORIZON + (GROUND - HORIZON) * d;
/** Lights fade into the haze with distance instead of piling up at the vanishing point. */
const glow = (d: number) => Math.max(0, Math.min(1, (d - 0.06) / 0.24));

/** The approach light bars before the threshold, nearest first. */
const STROBES = Array.from({ length: 9 }, (_, i) => 1.9 - i * 0.12);

/** Far-off city along the horizon: x, radius. Fixed, so server and browser draw the same. */
const CITY: [number, number][] = [
  [372, 1.1], [388, 1.8], [401, 1], [417, 2.2], [430, 1.2], [489, 1.4], [503, 2.4], [518, 1],
  [536, 1.9], [551, 1.2], [570, 2.1], [588, 1.3], [326, 1.4], [341, 1],
];

/** Out-of-focus lights: left %, top %, size px, colour, seconds, delay. */
const BOKEH: [number, number, number, string, number, number][] = [
  [6, 14, 96, "amber", 27, 0],
  [19, 58, 58, "blue", 32, 5],
  [31, 26, 124, "white", 35, 10],
  [44, 76, 72, "amber", 29, 2],
  [57, 12, 66, "blue", 37, 7],
  [64, 44, 112, "amber", 31, 13],
  [77, 22, 50, "white", 25, 3],
  [88, 62, 98, "blue", 34, 9],
  [12, 86, 62, "white", 30, 15],
  [93, 8, 76, "amber", 36, 4],
];

const TINT: Record<string, string> = {
  amber: "rgba(246, 195, 91, 0.30)",
  blue: "rgba(127, 211, 255, 0.26)",
  white: "rgba(255, 255, 255, 0.20)",
};

export function RunwayAtNight() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="runway-drift absolute -inset-6 blur-[1.2px]">
        <div className="absolute inset-0 bg-[linear-gradient(180deg,#030915_0%,#091a35_42%,#123056_58%,#1b3a5f_66%,#0a1730_100%)]" />
        <div className="absolute inset-x-0 top-[43%] h-44 bg-[radial-gradient(ellipse_at_center,rgba(246,195,91,0.20),transparent_70%)]" />
        <div className="sky-glow absolute -left-1/4 -top-1/4 h-[70%] w-[90%] rounded-full bg-[#1d5c96]/30 blur-[95px]" />
        <div className="sky-glow absolute -right-1/4 top-[4%] h-[58%] w-[80%] rounded-full bg-[#4b4fb8]/20 blur-[110px] [animation-delay:-11s]" />
        <div className="sky-glow absolute left-[12%] top-[22%] h-[44%] w-[70%] rounded-full bg-[#2a9d8f]/15 blur-[115px] [animation-delay:-19s]" />

        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMax slice" className="absolute inset-0 h-full w-full">
          <defs>
            <filter id="lamp" x="-200%" y="-200%" width="500%" height="500%">
              <feGaussianBlur stdDeviation="3" result="soft" />
              <feMerge>
                <feMergeNode in="soft" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <linearGradient id="tarmac" gradientUnits="userSpaceOnUse" x1="0" y1={HORIZON} x2="0" y2={GROUND}>
              <stop offset="0.25" stopColor="#020611" stopOpacity="0" />
              <stop offset="1" stopColor="#020611" stopOpacity="0.85" />
            </linearGradient>
            <linearGradient id="skyline" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0.4" stopColor="#9cc9ff" stopOpacity="0" />
              <stop offset="1" stopColor="#9cc9ff" stopOpacity="0.3" />
            </linearGradient>
          </defs>

          <polygon points={`${VX - 2},${HORIZON} ${VX + 2},${HORIZON} ${VX + HALF + 50},${GROUND} ${VX - HALF - 50},${GROUND}`} fill="url(#tarmac)" />
          <line x1="0" x2={W} y1={HORIZON} y2={HORIZON} stroke="url(#skyline)" strokeWidth="1" />
          {CITY.map(([x, r]) => (
            <circle key={x} cx={x} cy={HORIZON - 3} r={r} fill="#fde7a8" filter="url(#lamp)" className="city-twinkle" style={{ animationDelay: `${(x % 7) * -0.6}s` }} />
          ))}

          <g filter="url(#lamp)">
            {DEPTH.map((d, i) => (
              <g key={i}>
                {/* edge lights, warm white */}
                <circle cx={VX - HALF * d} cy={yAt(d)} r={0.6 + 4.6 * d} fill="#fff1c9" opacity={glow(d)} />
                <circle cx={VX + HALF * d} cy={yAt(d)} r={0.6 + 4.6 * d} fill="#fff1c9" opacity={glow(d)} />
                {/* centreline, cool white, every other row */}
                {i % 2 === 0 && <circle cx={VX} cy={yAt(d)} r={0.3 + 2.6 * d} fill="#dff3ff" opacity={glow(d) * 0.8} />}
              </g>
            ))}
            {/* the threshold: a green bar across the near end */}
            {Array.from({ length: 11 }, (_, i) => {
              const d = DEPTH[3];
              const x = VX - HALF * d + (2 * HALF * d * i) / 10;
              return <circle key={`t${i}`} cx={x} cy={yAt(d)} r={1 + 2.4 * d} fill="#7cf0a6" opacity={0.85} />;
            })}
            {/* glide-path indicator left of the runway: on the slope, two white and two red */}
            {["#ffffff", "#ffffff", "#ff5a52", "#ff5a52"].map((c, i) => {
              const d = DEPTH[6];
              return <circle key={`p${i}`} cx={VX - HALF * d - 28 - i * 9 * d} cy={yAt(d) - 2} r={2.2} fill={c} opacity={0.95} />;
            })}
          </g>

          {/* the approach strobes, firing in sequence towards the runway */}
          <g filter="url(#lamp)">
            {STROBES.map((d, i) => (
              <circle key={`s${i}`} cx={VX} cy={yAt(d)} r={2 + 3.2 * d} fill="#ffffff" className="strobe" style={{ animationDelay: `${i * 0.07}s` }} />
            ))}
          </g>
        </svg>

        {BOKEH.map(([left, top, size, tint, seconds, delay]) => (
          <span
            key={`${left}-${top}`}
            className="bokeh absolute rounded-full"
            style={{
              left: `${left}%`,
              top: `${top}%`,
              width: size,
              height: size,
              background: `radial-gradient(circle, ${TINT[tint]} 0%, transparent 68%)`,
              animationDuration: `${seconds}s`,
              animationDelay: `-${delay}s`,
            }}
          />
        ))}
      </div>

      {/* keep the words readable: darker where they sit, and a soft vignette */}
      <div className="absolute inset-0 bg-[linear-gradient(100deg,rgba(3,8,20,0.82)_0%,rgba(3,8,20,0.5)_45%,rgba(3,8,20,0.08)_100%)]" />
      <div className="absolute inset-0 shadow-[inset_0_0_160px_rgba(0,0,0,0.55)]" />
    </div>
  );
}
