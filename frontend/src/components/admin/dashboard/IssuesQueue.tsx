"use client";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { AlertCircle, AlertTriangle, ChevronRight, Info, type LucideIcon } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusPill } from "@/components/kit/StatusPill";
import { TONE_TEXT, type Tone } from "@/components/kit/tone";
import { cn } from "@/lib/utils";

type AttentionTone = "critical" | "warning" | "info";

export type IssueItem = {
  label: string;
  count: number;
  href: string;
  tone: AttentionTone;
};

/**
 * How each severity reads. The icon shape is the redundant cue beside the
 * colour, and `detail` is the screen-reader text for it — the row used to
 * print "Needs attention soon" under every warning, three times in a column.
 */
const SEVERITY: Record<AttentionTone, { tone: Tone; icon: LucideIcon; detail: string }> = {
  critical: { tone: "danger", icon: AlertTriangle, detail: "Needs immediate action" },
  warning: { tone: "warning", icon: AlertCircle, detail: "Needs attention soon" },
  info: { tone: "info", icon: Info, detail: "Review when convenient" }
};

interface IssuesQueueProps {
  items: IssueItem[];
}

export function IssuesQueue({ items }: Readonly<IssuesQueueProps>) {
  // The count pill takes the worst severity present. It used to be
  // `variant="destructive"` unconditionally, so an info-only list raised a red
  // alarm. `aria-hidden` because the CardDescription below states the same
  // count in words — a bare number is not an accessible name.
  const worstTone: Tone = items.some((item) => item.tone === "critical")
    ? "danger"
    : items.some((item) => item.tone === "warning")
      ? "warning"
      : "info";

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle asChild>
            <h2>Issues</h2>
          </CardTitle>
          {items.length > 0 && (
            <StatusPill tone={worstTone} className="tabular-nums" aria-hidden>
              {items.length}
            </StatusPill>
          )}
        </div>
        {items.length > 0 && (
          <CardDescription>
            {items.length} item{items.length === 1 ? "" : "s"} need
            {items.length === 1 ? "s" : ""} attention
          </CardDescription>
        )}
      </CardHeader>
      <CardContent>
        {items.length > 0 ? (
          <ul className="divide-y divide-border/50">
            {items.map((item) => {
              const severity = SEVERITY[item.tone];
              const Icon = severity.icon;
              return (
                <li key={item.label}>
                  {/* Bleeds to the card edge so the hover fill spans the card. */}
                  <HoverPrefetchLink
                    href={item.href}
                    className="-mx-6 flex items-center gap-3 px-6 py-2.5 transition-colors hover:bg-accent/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    <Icon className={cn("size-4 shrink-0", TONE_TEXT[severity.tone])} aria-hidden />
                    <span className="sr-only">{severity.detail}: </span>
                    <span className="min-w-0 flex-1 truncate text-sm text-foreground">
                      {item.label}
                    </span>
                    <span
                      className={cn(
                        "shrink-0 text-sm font-semibold tabular-nums",
                        TONE_TEXT[severity.tone]
                      )}
                    >
                      {item.count}
                    </span>
                    <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                  </HoverPrefetchLink>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            Nothing needs attention — new issues appear here as they are detected.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
