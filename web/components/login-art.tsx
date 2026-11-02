/* Sign-in artwork: a runway at night on short final, kept dim behind the words as ambient
   texture. The lighting follows the real pattern: white edge lights turning amber over the
   last third, red end lights across the far end, a green threshold bar, and an approach light
   system of centreline barrettes with a crossbar. Plain SVG and CSS; motion stops under reduced
   motion. */

const W = 600;
const H = 800;
const HORIZON = 330;
const GROUND = 690;
/** Centred: the runway's symmetry is what makes it read as a runway. */
const VX = W / 2;
const HALF = 230;

/** Perspective scale of a point ``z`` units down the runway from the near end (1 = nearest). */
const scale = (z: number) => 1 / (1 + z * 0.42);
const yAt = (s: number) => HORIZON + (GROUND - HORIZON) * s;
/** Lights fade into the night haze with distance. */
const haze = (s: number) => Math.max(0, Math.min(1, (s - 0.05) / 0.3));

const RUNWAY = 30;
/** Edge lights in pairs down the runway, from the threshold (z = 0) to the far end. */
const EDGE = Array.from({ length: RUNWAY }, (_, z) => z);
/** The far third of an instrument runway's edge lights shows amber. */
const amber = (z: number) => z >= (RUNWAY * 2) / 3;

/** The approach light system before the threshold: barrettes on the extended centreline,
 * nearest first (negative z), with a wide crossbar 300 m out. */
const BARRETTES = [-0.35, -0.7, -1.05, -1.4, -1.75, -2.1];
const CROSSBAR = -1.05;

export function RunwayAtNight() {
  const end = scale(RUNWAY - 1);
  const threshold = scale(0);
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute inset-0 bg-[linear-gradient(180deg,#030915_0%,#081833_48%,#0d2546_60%,#0a1a33_72%,#050d1d_100%)]" />
      <div className="sky-glow absolute -left-1/4 -top-1/4 h-[65%] w-[85%] rounded-full bg-[#1d5c96]/20 blur-[110px]" />
      <div className="sky-glow absolute -right-1/3 top-[8%] h-[55%] w-[75%] rounded-full bg-[#3d4fb0]/15 blur-[120px] [animation-delay:-14s]" />

      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMax slice" className="runway-drift absolute inset-0 h-full w-full opacity-75">
        <defs>
          <filter id="lamp" x="-200%" y="-200%" width="500%" height="500%">
            <feGaussianBlur stdDeviation="2.2" result="soft" />
            <feMerge>
              <feMergeNode in="soft" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <g filter="url(#lamp)">
          {/* edge lights: white, amber over the far third */}
          {EDGE.map((z) => {
            const s = scale(z);
            const fill = amber(z) ? "#ffc35c" : "#f4f8ff";
            const r = 0.5 + 4 * s;
            return (
              <g key={z} opacity={haze(s)}>
                <circle cx={VX - HALF * s} cy={yAt(s)} r={r} fill={fill} />
                <circle cx={VX + HALF * s} cy={yAt(s)} r={r} fill={fill} />
              </g>
            );
          })}
          {/* centreline, every other station */}
          {EDGE.filter((z) => z % 2 === 1).map((z) => {
            const s = scale(z);
            return <circle key={`c${z}`} cx={VX} cy={yAt(s)} r={0.3 + 2.2 * s} fill="#e6f4ff" opacity={haze(s) * 0.7} />;
          })}
          {/* runway end: red, across the runway's width only */}
          {Array.from({ length: 7 }, (_, i) => (
            <circle key={`e${i}`} cx={VX - HALF * end + (2 * HALF * end * i) / 6} cy={yAt(end)} r={0.9} fill="#ff4d4d" opacity={haze(end)} />
          ))}
          {/* threshold: green, across the near end */}
          {Array.from({ length: 13 }, (_, i) => (
            <circle key={`t${i}`} cx={VX - HALF * threshold + (2 * HALF * threshold * i) / 12} cy={yAt(threshold)} r={1.2 + 2.2 * threshold} fill="#5cf08f" />
          ))}
        </g>

        {/* approach lights: centreline barrettes and the crossbar, with a sequenced flash */}
        <g filter="url(#lamp)">
          {BARRETTES.map((z, i) => {
            const s = scale(z);
            const y = yAt(s);
            const wide = z === CROSSBAR ? 9 : 2;
            return (
              <g key={`b${i}`}>
                {Array.from({ length: wide * 2 + 1 }, (_, k) => (
                  <circle key={k} cx={VX + (k - wide) * 7 * s} cy={y} r={0.6 + 1.4 * s} fill="#f4f8ff" opacity={0.85} />
                ))}
                <circle cx={VX} cy={y} r={2 + 2.4 * s} fill="#ffffff" className="strobe" style={{ animationDelay: `${(BARRETTES.length - i) * 0.08}s` }} />
              </g>
            );
          })}
        </g>
      </svg>

      {/* keep the words readable: the left and the middle darkest, a vignette all round */}
      <div className="absolute inset-0 bg-[linear-gradient(100deg,rgba(3,8,20,0.82)_0%,rgba(3,8,20,0.5)_50%,rgba(3,8,20,0.2)_100%)]" />
      <div className="absolute inset-0 bg-[radial-gradient(120%_80%_at_50%_100%,transparent_0%,rgba(3,8,20,0.45)_70%)]" />
      <div className="absolute inset-0 shadow-[inset_0_0_160px_rgba(0,0,0,0.6)]" />
    </div>
  );
}
