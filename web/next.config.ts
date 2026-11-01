import type { NextConfig } from "next";

// The console is a static site: FastAPI serves web/out on the same origin as /api, so the
// production build is a plain export. `next dev` has no API of its own, so in development
// only, /api is proxied to a locally running backend (CREWOPS_API, default port 8000).
const dev = process.env.NODE_ENV === "development";
const backend = process.env.CREWOPS_API ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  trailingSlash: true,
  images: { unoptimized: true },
  devIndicators: false,
  // keep `next dev` from writing its own instruction files into the project
  agentRules: false,
  ...(dev
    ? {
        async rewrites() {
          return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
        },
      }
    : { output: "export" as const }),
};

export default nextConfig;
