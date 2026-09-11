"use client";

import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { PANEL_CLASS } from "@/app/balancer/components/balancer-page-helpers";
import { MIX_STATUS_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { CustomGame } from "@/services/custom-game.service";

type PickupMixListProps = {
  canEdit: boolean;
  games: CustomGame[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  onCreateGame: () => void;
};

export function PickupMixList({
  canEdit,
  games,
  loading,
  error,
  onRetry,
  onCreateGame
}: Readonly<PickupMixListProps>) {
  const t = useTranslations("mixes");
  const format = useFormatter();
  const [view, setView] = useState<"open" | "history">("open");
  const open: CustomGame[] = [];
  const history: CustomGame[] = [];
  for (const game of games) {
    (game.status === "completed" || game.status === "cancelled" ? history : open).push(game);
  }
  const visibleGames = view === "open" ? open : history;

  return (
    <div className="flex w-full min-w-0 flex-col gap-4">
      <FilterChipGroup label={t("list.filters")}>
        <FilterChip
          active={view === "open"}
          count={loading || error ? undefined : format.number(open.length)}
          onClick={() => setView("open")}
        >
          {t("list.open")}
        </FilterChip>
        <FilterChip
          active={view === "history"}
          count={loading || error ? undefined : format.number(history.length)}
          onClick={() => setView("history")}
        >
          {t("list.history")}
        </FilterChip>
      </FilterChipGroup>

      {error ? (
        <PageStateCard
          state="error"
          title={t("list.errorTitle")}
          description={t("list.errorDescription")}
          actionLabel={t("retry")}
          onAction={onRetry}
          className="w-full min-w-0 px-4"
        />
      ) : loading ? (
        <div
          role="status"
          className={cn(PANEL_CLASS, "w-full min-w-0 divide-y divide-[color:var(--aqt-border)]")}
        >
          <span className="sr-only">{t("loading")}</span>
          {[0, 1, 2].map((row) => (
            <div key={row} aria-hidden="true" className="space-y-3 px-4 py-4">
              <div className="flex items-center gap-3">
                <Skeleton className="h-5 w-1/2 motion-reduce:animate-none" />
                <Skeleton className="ms-auto h-6 w-20 motion-reduce:animate-none" />
              </div>
              <Skeleton className="h-4 w-3/4 motion-reduce:animate-none" />
            </div>
          ))}
        </div>
      ) : games.length === 0 ? (
        <PageStateCard
          state="empty"
          title={t("list.emptyTitle")}
          description={t(canEdit ? "list.emptyHost" : "list.emptyViewer")}
          actionLabel={t("createAction")}
          onAction={canEdit ? onCreateGame : undefined}
          className="w-full min-w-0 px-4"
        />
      ) : visibleGames.length === 0 ? (
        <PageStateCard
          state="filtered-empty"
          title={t(view === "open" ? "list.noOpenTitle" : "list.noHistoryTitle")}
          description={t(view === "open" ? "list.noOpenDescription" : "list.noHistoryDescription")}
          actionLabel={t(view === "open" ? "list.showHistory" : "list.showOpen")}
          onAction={() => setView(view === "open" ? "history" : "open")}
          className="w-full min-w-0 px-4"
        />
      ) : (
        <ul
          aria-label={t("list.label")}
          className={cn(
            PANEL_CLASS,
            "flex w-full min-w-0 flex-col divide-y divide-[color:var(--aqt-border)]"
          )}
        >
          {visibleGames.map((game) => (
            <PickupMixRow key={game.id} game={game} />
          ))}
        </ul>
      )}
    </div>
  );
}

function PickupMixRow({ game }: Readonly<{ game: CustomGame }>) {
  const t = useTranslations("mixes.list");
  const format = useFormatter();

  return (
    <li className="min-w-0 first:[&>a]:rounded-t-xl last:[&>a]:rounded-b-xl">
      <Link
        href={`/balancer/mix/${game.id}`}
        className="flex min-w-0 flex-col gap-2 px-4 py-3.5 transition-colors hover:bg-[color:var(--aqt-overlay-1)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
      >
        <span className="flex min-w-0 flex-wrap items-start gap-x-3 gap-y-2">
          <span className="min-w-0 flex-1 basis-56 text-ui font-semibold text-[color:var(--aqt-fg)] [overflow-wrap:anywhere]">
            {game.name}
          </span>
          <span
            className={cn(
              "max-w-full rounded-full border px-2.5 py-1 text-caption font-medium [overflow-wrap:anywhere]",
              MIX_STATUS_CLASS[game.status]
            )}
          >
            {t(`status.${game.status}`)}
          </span>
        </span>
        <span className="flex min-w-0 flex-wrap gap-x-4 gap-y-1 text-caption text-[color:var(--aqt-fg-muted)] [overflow-wrap:anywhere]">
          <span className="min-w-0 max-w-full">
            {t("host", { name: game.host_display_name ?? `#${game.host_user_id}` })}
          </span>
          <span className="min-w-0 max-w-full tabular-nums">
            {game.matches_count > 0 ? t("matches", { count: game.matches_count }) : t("noMatches")}
          </span>
          {game.last_match_at ? (
            <time
              dateTime={game.last_match_at}
              title={game.last_match_at}
              className="min-w-0 max-w-full tabular-nums"
            >
              {t("lastMatch", {
                date: format.dateTime(new Date(game.last_match_at), {
                  month: "short",
                  day: "numeric",
                  hour: "numeric",
                  minute: "2-digit"
                })
              })}
            </time>
          ) : null}
          {game.created_at ? (
            <time
              dateTime={game.created_at}
              title={game.created_at}
              className="min-w-0 max-w-full tabular-nums text-[color:var(--aqt-fg-dim)]"
            >
              {t("created", {
                date: format.dateTime(new Date(game.created_at), {
                  year: "numeric",
                  month: "short",
                  day: "numeric"
                })
              })}
            </time>
          ) : null}
        </span>
      </Link>
    </li>
  );
}
