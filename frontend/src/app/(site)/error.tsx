"use client";

import { useEffect } from "react";
import Link from "next/link";
import { TriangleAlert, Home, RotateCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

/**
 * Route-segment error boundary for the whole (site) area.
 *
 * Renders inside the (site) layout (header/footer preserved) so a failed page
 * (e.g. a match/encounter detail SSR error) shows a branded, dark-theme card
 * instead of Next's unstyled white "This page couldn't load" fallback.
 */
export default function SiteError({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface for observability; the digest ties back to the server log line.
    console.error(error);
  }, [error]);

  return (
    <div className="flex flex-1 items-center justify-center py-10 md:py-16">
      <Card className="w-full max-w-lg border-border/60 bg-card/80 p-8 text-center">
        <div className="mx-auto mb-5 flex size-12 items-center justify-center rounded-2xl border border-destructive/30 bg-destructive/10 text-destructive">
          <TriangleAlert className="size-6" aria-hidden="true" />
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Something went wrong</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          This section failed to load. Try again, or head back to the dashboard.
        </p>
        {error?.digest ? (
          <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.2em] text-muted-foreground/60">
            Error {error.digest}
          </p>
        ) : null}
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          <Button onClick={() => reset()}>
            <RotateCw className="size-4" aria-hidden="true" />
            Try again
          </Button>
          <Button asChild variant="outline">
            <Link href="/">
              <Home className="size-4" aria-hidden="true" />
              Back to dashboard
            </Link>
          </Button>
        </div>
      </Card>
    </div>
  );
}
