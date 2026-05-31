/** @type {import('next').NextConfig} */
const nextConfig = {
  // Only use standalone output in production builds
  ...(process.env.NODE_ENV === 'production' && { output: "standalone" }),
  // Enable polling only inside Docker (native fs watcher doesn't work with bind mounts)
  ...(process.env.DOCKER === '1' && { watchOptions: { pollIntervalMs: 1000 } }),
  allowedDevOrigins: ['exultantly-peaceful-adjutant.cloudpub.ru'],
  async rewrites() {
    const apiUrl = process.env.NEXT_API_URL ?? process.env.NEXT_PUBLIC_API_URL;
    const parserUrl = process.env.NEXT_PARSER_URL ?? process.env.NEXT_PUBLIC_PARSER_API_URL;
    const tournamentUrl =
      (process.env.NEXT_TOURNAMENT_URL ?? process.env.NEXT_PUBLIC_TOURNAMENT_API_URL)?.replace(
        /\/$/,
        "",
      );
    // Single-prefix routing (mirrors Kong):
    //   /api/v1/core/*  -> app-service     (most specific, must come first)
    //   /api/v1/*       -> tournament-service (owns the rest of the namespace)
    return [
      ...(apiUrl
        ? [
            {
              source: "/api/v1/core/:path*",
              destination: `${apiUrl}/:path*`,
            },
          ]
        : []),
      ...(tournamentUrl
        ? [
            {
              source: "/api/v1/:path*",
              destination: `${tournamentUrl}/:path*`,
            },
          ]
        : []),
      ...(parserUrl
        ? [
            {
              source: "/api/parser/:path*",
              destination: `${parserUrl}/:path*`,
            },
          ]
        : []),
    ];
  },
  images: {
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
