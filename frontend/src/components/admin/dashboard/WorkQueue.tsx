"use client";

import { useTranslations } from "next-intl";
import { AlertCircle, AlertTriangle, ChevronRight, Info, type LucideIcon } from "lucide-react";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { StatusPill } from "@/components/kit/StatusPill";
import { TONE_TEXT, type Tone } from "@/components/ui/tone";
import { Skeleton } from "@/components/ui/skeleton";
import { GameIcon } from "@/components/workspace/GameIcon";
import { cn } from "@/lib/utils";
import type { DashboardIssue, DashboardTournamentCard } from "@/types/admin-dashboard.types";
import { Block, BlockError } from "./Block";
import { issueHref } from "./model";

/** The icon shape is the cue beside the colour; `label` is its screen-reader word. */
const SEVERITY: Record<
  DashboardIssue["severity"],
  { tone: Tone; icon: LucideIcon; label: "needsImmediateAction" | "needsAttentionSoon" | "reviewWhenConvenient" }
> = {
  critical: { tone: "danger", icon: AlertTriangle, label: "needsImmediateAction" },
  warning: { tone: "warning", icon: AlertCircle, label: "needsAttentionSoon" },
  info: { tone: "info", icon: Info, label: "reviewWhenConvenient" }
};

/** "To do": issues of the tournaments that have a card, in the backend's severity order. */
export function WorkQueue({
  issues,
  cardOf,
  failed,
  onRetry,
  className
}: Readonly<{
  /** `undefined` while loading. */
  issues: DashboardIssue[] | undefined;
  cardOf: ReadonlyMap<number, DashboardTournamentCard>;
  failed: boolean;
  onRetry: () => void;
  className?: string;
}>) {
  const t = useTranslations("adminShell.dashboard");
  const title = t("workQueue");

  return (
    <Block title={title} className={className}>
      {failed ? (
        <BlockError title={title} onRetry={onRetry} />
      ) : !issues ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-9 rounded-md" />
          ))}
        </div>
      ) : issues.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("queueEmpty")}</p>
      ) : (
        <ul className="divide-y divide-border/50">
          {issues.map((issue) => {
            const severity = SEVERITY[issue.severity];
            const Icon = severity.icon;
            const card = cardOf.get(issue.tournament_id);
            return (
              <li key={`${issue.key}:${issue.tournament_id}`}>
                {/* Bleeds to the card edge so the hover fill spans the card. */}
                <HoverPrefetchLink
                  href={issueHref(issue)}
                  className="-mx-6 flex items-center gap-3 px-6 py-2.5 transition-colors hover:bg-accent/30 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                >
                  <Icon className={cn("size-4 shrink-0", TONE_TEXT[severity.tone])} aria-hidden />
                  <span className="sr-only">{t(severity.label)}: </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-foreground">{t(`issue.${issue.key}`)}</span>
                    <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                      {card ? <GameIcon slug={card.discipline} size={12} /> : null}
                      <span className="truncate">{issue.tournament_name}</span>
                      {card?.is_hidden ? (
                        <StatusPill tone="neutral" className="shrink-0">
                          {t("hidden")}
                        </StatusPill>
                      ) : null}
                    </span>
                  </span>
                  {issue.count != null ? (
                    <span className={cn("shrink-0 text-sm font-semibold tabular-nums", TONE_TEXT[severity.tone])}>
                      {issue.count}
                    </span>
                  ) : null}
                  <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                </HoverPrefetchLink>
              </li>
            );
          })}
        </ul>
      )}
    </Block>
  );
}
