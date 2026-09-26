"use client";

import { useEffect } from "react";
import Link from "next/link";
import { TriangleAlert, Home, RotateCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

type RouteErrorCardProps = {
  error: Error & { digest?: string };
  reset: () => void;
  /** Where "back home" lands — a zone's own root, not always `/`. */
  homeHref: string;
};

/**
 * The card every route-segment `error.tsx` renders. One implementation, four
 * boundaries ((site), admin, balancer, draft): each zone mounts it inside its
 * own layout, so a failed page keeps that zone's chrome and its message
 * bundle instead of Next's unstyled white "This page couldn't load" fallback.
 */
export function RouteErrorCard({ error, reset, homeHref }: Readonly<RouteErrorCardProps>) {
  const t = useTranslations();

  useEffect(() => {
    // Surface for observability; the digest ties back to the server log line.
    console.error(error);
  }, [error]);

  return (
    <div className="flex flex-1 items-center justify-center py-10 md:py-16">
      <Card
        role="alert"
        className="w-full max-w-lg border-border/60 bg-card/80 p-8 text-center"
      >
        <div className="mx-auto mb-5 flex size-12 items-center justify-center rounded-2xl border border-destructive/30 bg-destructive/10 text-destructive">
          <TriangleAlert className="size-6" aria-hidden="true" />
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {t("errors.boundary.title")}
        </h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          {t("errors.boundary.description")}
        </p>
        {error?.digest ? (
          <p className="mt-3 text-label uppercase tracking-label text-muted-foreground/60">
            {t("errors.boundary.digest", { digest: error.digest })}
          </p>
        ) : null}
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          <Button onClick={() => reset()}>
            <RotateCw className="size-4" aria-hidden="true" />
            {t("errors.boundary.retry")}
          </Button>
          <Button asChild variant="outline">
            <Link href={homeHref}>
              <Home className="size-4" aria-hidden="true" />
              {t("errors.boundary.home")}
            </Link>
          </Button>
        </div>
      </Card>
    </div>
  );
}
