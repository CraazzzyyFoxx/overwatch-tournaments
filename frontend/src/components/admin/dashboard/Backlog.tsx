"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown } from "lucide-react";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { Card } from "@/components/ui/card";
import { triggerChevronClass } from "@/components/ui/chevron";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import { GameIcon } from "@/components/workspace/GameIcon";
import { cn } from "@/lib/utils";
import type { DashboardBacklog } from "@/types/admin-dashboard.types";
import { BLOCK_TITLE, Block, BlockError } from "./Block";

type Fact = { key: string; label: string; href: string };

/** A masked (`null`) or clean (`0`) count is no fact at all. */
function present(count: number | null | undefined): count is number {
  return count != null && count > 0;
}

/**
 * Loose ends of tournaments without a card (missing logs, empty rosters, empty
 * slots), collapsed by default: real, but never today's work.
 */
export function Backlog({
  backlog,
  failed,
  onRetry,
  className
}: Readonly<{
  /** `undefined` while loading. */
  backlog: DashboardBacklog | undefined;
  failed: boolean;
  onRetry: () => void;
  className?: string;
}>) {
  const t = useTranslations("adminShell.dashboard");
  const [open, setOpen] = useState(false);
  const title = t("backlog");

  if (failed) {
    return (
      <Block title={title} className={className}>
        <BlockError title={title} onRetry={onRetry} />
      </Block>
    );
  }
  if (!backlog) return <Skeleton className={cn("h-[4.5rem] rounded-xl", className)} />;
  if (backlog.tournaments_total === 0 && !present(backlog.users_without_identities)) return null;

  const rows = backlog.rows;
  const totals: Fact[] = [
    present(backlog.encounters_missing_logs)
      ? { key: "logs", label: t("backlogMissingLogs", { count: backlog.encounters_missing_logs }), href: "/admin/matches?view=encounters" }
      : null,
    present(backlog.teams_without_players)
      ? { key: "teams", label: t("backlogTeamsWithoutPlayers", { count: backlog.teams_without_players }), href: "/admin/teams" }
      : null,
    present(backlog.tournaments_without_stages)
      ? {
          key: "stages",
          label: t("backlogTournamentsWithoutStages", { count: backlog.tournaments_without_stages }),
          href: "/admin/tournaments"
        }
      : null,
    present(backlog.stage_slots_empty)
      ? { key: "slots", label: t("backlogEmptySlots", { count: backlog.stage_slots_empty }), href: "/admin/tournaments" }
      : null,
    present(backlog.users_without_identities)
      ? {
          key: "identities",
          label: t("backlogUnlinkedIdentities", { count: backlog.users_without_identities }),
          href: "/admin/people"
        }
      : null
  ].filter((fact): fact is Fact => fact !== null);

  return (
    <Collapsible open={open} onOpenChange={setOpen} asChild>
      <Card asChild className={className}>
        <section aria-label={title}>
          <h2>
            <CollapsibleTrigger className="group/trigger flex w-full items-baseline gap-3 rounded-xl p-6 text-left focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
              <span className={BLOCK_TITLE}>{title}</span>
              {backlog.tournaments_total > 0 ? (
                <span className="text-sm text-muted-foreground">
                  {t("backlogSummary", { count: backlog.tournaments_total })}
                </span>
              ) : null}
              <ChevronDown className={cn(triggerChevronClass, "ml-auto self-center")} aria-hidden />
            </CollapsibleTrigger>
          </h2>
          <CollapsibleContent className="space-y-4 px-6 pb-6">
            {totals.length > 0 ? <FactLinks facts={totals} /> : null}
            {rows.length > 0 ? (
              <ul className="divide-y divide-border/50">
                {rows.map((row) => {
                  const base = `/admin/tournaments/${row.tournament_id}`;
                  const facts: Fact[] = [
                    present(row.encounters_missing_logs)
                      ? { key: "logs", label: t("backlogMissingLogs", { count: row.encounters_missing_logs }), href: `${base}/matches/logs` }
                      : null,
                    present(row.teams_without_players)
                      ? {
                          key: "teams",
                          label: t("backlogTeamsWithoutPlayers", { count: row.teams_without_players }),
                          href: `${base}/teams/roster`
                        }
                      : null,
                    row.has_stages === false ? { key: "stages", label: t("backlogNoStages"), href: `${base}/bracket` } : null,
                    present(row.stage_slots_empty)
                      ? { key: "slots", label: t("backlogEmptySlots", { count: row.stage_slots_empty }), href: `${base}/bracket` }
                      : null
                  ].filter((fact): fact is Fact => fact !== null);
                  return (
                    <li key={row.tournament_id} className="flex flex-col gap-1 py-2.5 sm:flex-row sm:items-center sm:gap-3">
                      <span className="flex min-w-0 items-center gap-2 sm:w-64 sm:shrink-0">
                        <GameIcon slug={row.discipline} />
                        <HoverPrefetchLink href={base} className="truncate text-sm text-foreground hover:underline">
                          {row.tournament_name}
                        </HoverPrefetchLink>
                      </span>
                      <FactLinks facts={facts} />
                    </li>
                  );
                })}
              </ul>
            ) : null}
            {backlog.tournaments_total > backlog.rows.length ? (
              <p className="text-xs text-muted-foreground">
                {t("backlogTruncated", { shown: rows.length, total: backlog.tournaments_total })}
              </p>
            ) : null}
          </CollapsibleContent>
        </section>
      </Card>
    </Collapsible>
  );
}

function FactLinks({ facts }: Readonly<{ facts: Fact[] }>) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {facts.map((fact) => (
        <li key={fact.key}>
          <HoverPrefetchLink href={fact.href} className="tabular-nums hover:text-foreground hover:underline">
            {fact.label}
          </HoverPrefetchLink>
        </li>
      ))}
    </ul>
  );
}
