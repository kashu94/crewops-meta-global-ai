import type { NextConfig } from "next";

// The console is a static site: a plain export, hosted on Amplify when deployed (with the
// API's address in NEXT_PUBLIC_CREWOPS_API) or served by FastAPI on a laptop. `next dev` has
// no API of its own, so in development only, /api is proxied to a locally running backend
// (CREWOPS_API, default port 8000).
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
