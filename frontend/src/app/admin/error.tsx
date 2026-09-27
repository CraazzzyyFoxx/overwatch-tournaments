"use client";

import { RouteErrorCard } from "@/components/RouteErrorCard";

/**
 * Route-segment error boundary for the admin panel. Renders inside
 * `admin/layout.tsx`, so the sidebar, the `admin` message bundle and the
 * operator's place in the panel all survive a failed page. "Home" is the
 * panel's own root — an operator dropped on the public site is lost work.
 */
export default function AdminError({
  error,
  reset
}: Readonly<{
  error: Error & { digest?: string };
  reset: () => void;
}>) {
  return <RouteErrorCard error={error} reset={reset} homeHref="/admin" />;
}
