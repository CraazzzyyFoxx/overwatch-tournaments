"use client";

import { RouteErrorCard } from "@/components/RouteErrorCard";

/**
 * Route-segment error boundary for the whole (site) area.
 *
 * Renders inside the (site) layout (header/footer preserved) so a failed page
 * (e.g. a match/encounter detail SSR error) shows a branded, dark-theme card.
 */
export default function SiteError({
  error,
  reset
}: Readonly<{
  error: Error & { digest?: string };
  reset: () => void;
}>) {
  return <RouteErrorCard error={error} reset={reset} homeHref="/" />;
}
