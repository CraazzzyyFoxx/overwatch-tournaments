"use client";

import { RouteErrorCard } from "@/components/RouteErrorCard";

/**
 * Route-segment error boundary for the balancer tool. Renders inside
 * `balancer/layout.tsx`, which mounts the `tools` message bundle.
 */
export default function BalancerError({
  error,
  reset
}: Readonly<{
  error: Error & { digest?: string };
  reset: () => void;
}>) {
  return <RouteErrorCard error={error} reset={reset} homeHref="/" />;
}
