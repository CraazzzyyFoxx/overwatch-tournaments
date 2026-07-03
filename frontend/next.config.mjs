import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pin the Turbopack workspace root to this directory. Otherwise Next infers the
  // root from lockfiles and can pick a stray parent (e.g. ~/package-lock.json),
  // which breaks module resolution (tailwindcss not found) and prints a warning.
  turbopack: {
    root: __dirname,
  },
  // Only use standalone output in production builds
  ...(process.env.NODE_ENV === 'production' && { output: "standalone" }),
  // Enable polling only inside Docker (native fs watcher doesn't work with bind mounts)
  ...(process.env.DOCKER === '1' && { watchOptions: { pollIntervalMs: 1000 } }),
  allowedDevOrigins: ['exultantly-peaceful-adjutant.cloudpub.ru'],
  async rewrites() {
    // Everything is one gateway behind one origin. In production the browser hits
    // nginx and /api/* never reaches Next, so these rewrites are only a fallback
    // for hitting the Next dev server (:3000) directly: each gateway namespace is
    // forwarded to the internal gateway. /api/auth/* route handlers and /api/account
    // are filesystem routes and take precedence over these afterFiles rewrites.
    const gateway = process.env.NEXT_INTERNAL_API_URL?.replace(/\/$/, "");
    if (!gateway) return [];
    return ["/api/v1", "/api/balancer", "/api/analytics", "/api/auth"].map((prefix) => ({
      source: `${prefix}/:path*`,
      destination: `${gateway}${prefix}/:path*`,
    }));
  },
  images: {
    unoptimized: true,
    qualities: [25, 50, 75, 100],
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'd15f34w2p8l1cc.cloudfront.net',
        port: '',
        pathname: '/overwatch/**',
      },
      {
        protocol: 'https',
        hostname: 'overfast.craazzzyyfoxx.me',
        port: '',
        pathname: '/static/**',
      },
      {
        protocol: 'https',
        hostname: 'img.clerk.com',
        port: '',
        pathname: '/**',
      },
      {
        protocol: 'https',
        hostname: 'cdn.discordapp.com',
        port: '',
        pathname: '/**',
      },
      {
        protocol: 'https',
        hostname: 'minio.craazzzyyfoxx.me',
        port: '',
        pathname: '/aqt/**',
      },
    ],
  },
};

export default nextConfig;
