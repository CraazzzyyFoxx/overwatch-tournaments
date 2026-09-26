"use client";

import { RouteErrorCard } from "@/components/RouteErrorCard";

/**
 * Route-segment error boundary for the draft room. Renders inside
 * `draft/layout.tsx`, which mounts the `tools` message bundle.
 */
export default function DraftError({
  error,
  reset
}: Readonly<{
  error: Error & { digest?: string };
  reset: () => void;
}>) {
  return <RouteErrorCard error={error} reset={reset} homeHref="/" />;
}
