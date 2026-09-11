import { fileURLToPath } from "node:url";
import { dirname } from "node:path";
import createNextIntlPlugin from "next-intl/plugin";

const __dirname = dirname(fileURLToPath(import.meta.url));

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pin the Turbopack workspace root to this directory. Otherwise Next infers the
  // root from lockfiles and can pick a stray parent (e.g. ~/package-lock.json),
  // which breaks module resolution (tailwindcss not found) and prints a warning.
  turbopack: {
    root: __dirname
  },
  // Dynamic segments default to a 0s client Router Cache stale time (Next 15+),
  // so every client-side navigation under a `force-dynamic` layout (e.g.
  // /tournaments/[id]/*) refetches that layout's RSC payload from scratch.
  // 30s lets flipping between tabs reuse the just-fetched shell instead of a
  // full round trip on every click.
  experimental: {
    staleTimes: {
      dynamic: 30
    },
    // 16.3 defaults this on; 16.2 does not. prod.Dockerfile cache-mounts
    // .next/cache so subsequent compose builds reuse Turbopack artifacts.
    turbopackFileSystemCacheForBuild: true
  },
  // `bun run typecheck` / CI already gate this. next build on the 8-core
  // prod box should not pay for a second tsc of the same tree.
  typescript: {
    ignoreBuildErrors: true
  },
  // Only use standalone output in production builds
  ...(process.env.NODE_ENV === "production" && { output: "standalone" }),
  // Enable polling only inside Docker (native fs watcher doesn't work with bind mounts)
  ...(process.env.DOCKER === "1" && { watchOptions: { pollIntervalMs: 1000 } }),
  allowedDevOrigins: ["exultantly-peaceful-adjutant.cloudpub.ru"],
  async rewrites() {
    // Everything is one gateway behind one origin. In production the browser hits
    // nginx and /api/* never reaches Next, so these rewrites are only a fallback
    // for hitting the Next dev server (:3000) directly: each gateway namespace is
    // forwarded to the internal gateway. /api/auth/* route handlers and /api/account
    // are filesystem routes and take precedence over these afterFiles rewrites.
    const gateway = process.env.NEXT_INTERNAL_API_URL?.replace(/\/$/, "");
    if (!gateway) return [];
    return [
      "/api/v1",
      "/api/v2",
      "/api/balancer",
      "/api/analytics",
      "/api/streams",
      "/api/auth"
    ].map((prefix) => ({
      source: `${prefix}/:path*`,
      destination: `${gateway}${prefix}/:path*`
    }));
  },
  images: {
    unoptimized: true,
    qualities: [25, 50, 75, 100],
    remotePatterns: [
      {
        protocol: "https",
        hostname: "d15f34w2p8l1cc.cloudfront.net",
        port: "",
        pathname: "/overwatch/**"
      },
      {
        protocol: "https",
        hostname: "overfast.craazzzyyfoxx.me",
        port: "",
        pathname: "/static/**"
      },
      {
        protocol: "https",
        hostname: "img.clerk.com",
        port: "",
        pathname: "/**"
      },
      {
        protocol: "https",
        hostname: "cdn.discordapp.com",
        port: "",
        pathname: "/**"
      },
      {
        protocol: "https",
        hostname: "minio.craazzzyyfoxx.me",
        port: "",
        pathname: "/aqt/**"
      },
      {
        protocol: "https",
        hostname: "static.nl.craazzzyyfoxx.me",
        port: "",
        pathname: "/aqt/**"
      },
      {
        protocol: "https",
        hostname: "rustfs.craazzzyyfoxx.me",
        port: "",
        pathname: "/aqt/**"
      },
      {
        protocol: "https",
        hostname: "s3.twcstorage.ru",
        port: "",
        pathname: "/**"
      }
    ]
  }
};

export default withNextIntl(nextConfig);
