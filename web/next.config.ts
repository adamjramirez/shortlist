import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  skipTrailingSlashRedirect: true,
  rewrites: async () => [
    { source: "/api/:path*", destination: "http://127.0.0.1:8001/api/:path*" },
    // PostHog reverse proxy — avoids ad blockers
    { source: "/ingest/static/:path*", destination: "https://eu-assets.i.posthog.com/static/:path*" },
    { source: "/ingest/:path*", destination: "https://eu.i.posthog.com/:path*" },
    { source: "/ingest/decide", destination: "https://eu.i.posthog.com/decide" },
  ],
};

export default nextConfig;
