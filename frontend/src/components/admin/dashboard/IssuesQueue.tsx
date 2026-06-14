"use client";

import Link from "next/link";
import { AlertTriangle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { SurfaceCard } from "./SurfaceCard";

export type AttentionTone = "critical" | "warning" | "info";

export type IssueItem = {
  label: string;
  count: number;
  href: string;
  tone: AttentionTone;
};

function IssueDot({ tone }: { tone: AttentionTone }) {
  return (
    <div
      className={cn(
        "mt-0.5 size-2 shrink-0 rounded-full",
        tone === "critical" ? "bg-destructive" : tone === "warning" ? "bg-amber-500" : "bg-muted-foreground/50",
      )}
    />
  );
}

interface IssuesQueueProps {
  items: IssueItem[];
}

export function IssuesQueue({ items }: IssuesQueueProps) {
  return (
    <SurfaceCard>
      <CardHeader className="p-5 pb-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <div className="flex size-7 items-center justify-center rounded-lg border border-border/50 bg-background/60">
              <AlertTriangle className="size-3.5 text-muted-foreground" />
            </div>
            <CardTitle className="text-sm font-semibold">Issues</CardTitle>
          </div>
          {items.length > 0 && (
            <Badge variant="destructive" className="tabular-nums">
              {items.length}
            </Badge>
          )}
        </div>
        <CardDescription className="text-xs">
          {items.length > 0
            ? `${items.length} item${items.length === 1 ? "" : "s"} need${items.length === 1 ? "s" : ""} attention`
            : "All clear"}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 px-5 pb-5">
        {items.length > 0 ? (
          items.map((item) => (
            <Link
              key={item.label}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-xl border px-3 py-2.5 transition-colors hover:bg-accent/30",
                item.tone === "critical"
                  ? "border-destructive/30 bg-destructive/5"
                  : item.tone === "warning"
                    ? "border-amber-500/25 bg-amber-500/5"
                    : "border-border/50 bg-background/45",
              )}
            >
              <IssueDot tone={item.tone} />
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="text-sm font-medium leading-snug text-foreground">{item.label}</span>
                <span className="text-xs capitalize text-muted-foreground">{item.tone}</span>
              </div>
              <span
                className={cn(
                  "shrink-0 text-xl font-semibold tabular-nums",
                  item.tone === "critical" ? "text-destructive" : "text-foreground",
                )}
              >
                {item.count}
              </span>
            </Link>
          ))
        ) : (
          <div className="rounded-xl border border-border/50 bg-background/45 p-4 text-sm text-muted-foreground">
            No urgent issues surfaced.
          </div>
        )}
      </CardContent>
    </SurfaceCard>
  );
}
