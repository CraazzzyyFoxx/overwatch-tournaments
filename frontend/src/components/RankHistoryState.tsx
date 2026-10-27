"use client";

import type { LucideIcon } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * The "nothing to draw" surface for rank-history cards: `<PageStateCard>`'s
 * surface, icon tones and type, at a compact size.
 *
 * Not `<PageStateCard>` itself: that is a page-level surface (px-6 py-10)
 * whereas these states render *inside* a chart card — a 300px sheet column and
 * a table's expanded row — where it would dwarf the chart it stands in for. It
 * also keeps the per-state iconography that tells "no history at all" apart
 * from "nothing for this filter".
 *
 * `framed={false}` drops the surface inside a card that already frames it.
 */
export function ChartEmptyState({
  icon: Icon,
  title,
  body,
  tone = "neutral",
  framed = true,
  className
}: Readonly<{
  icon: LucideIcon;
  title: string;
  body: string;
  /** `error` announces assertively and accents the icon. */
  tone?: "neutral" | "error";
  framed?: boolean;
  className?: string;
}>) {
  const isError = tone === "error";
  return (
    <div
      role={isError ? "alert" : "status"}
      className={cn(
        "flex flex-col items-center justify-center gap-2 p-6 text-center",
        framed && "rounded-[var(--aqt-radius)] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]",
        className
      )}
    >
      <Icon
        aria-hidden
        className={cn("size-5", isError ? "text-[color:var(--aqt-rose)]" : "text-[color:var(--aqt-fg-faint)]")}
      />
      <div className="space-y-1">
        <h4 className="text-sm font-semibold text-[color:var(--aqt-fg)]">{title}</h4>
        <p className="mx-auto max-w-xs text-caption leading-relaxed text-[color:var(--aqt-fg-muted)]">{body}</p>
      </div>
    </div>
  );
}

export function RankHistorySkeleton({
  framed = true,
  className
}: Readonly<{ framed?: boolean; className?: string }>) {
  const chart = <Skeleton className="h-[180px] w-full bg-[color:var(--aqt-overlay-1)] @lg:h-[220px]" />;
  return (
    <div className={cn("@container space-y-3", className)}>
      <Skeleton className="h-[52px] w-full bg-[color:var(--aqt-overlay-2)]" />
      <div className="flex flex-wrap items-center gap-3">
        <Skeleton className="w-[130px] h-8 bg-[color:var(--aqt-overlay-2)]" />
        <Skeleton className="w-[120px] h-8 bg-[color:var(--aqt-overlay-2)]" />
      </div>
      {framed ? (
        <Card className="p-4">
          {chart}
        </Card>
      ) : (
        chart
      )}
    </div>
  );
}
