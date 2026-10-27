"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useQueries, useQuery } from "@tanstack/react-query";
import { AlertCircle, ChevronRight, ShieldAlert, UserX } from "lucide-react";

import { StatusIcon } from "@/components/admin/StatusIcon";
import { PROVIDER_LABELS } from "@/components/admin/collectors/subscription-shared";
import { useLinkedAccount } from "@/components/admin/people/PersonAccountTab";
import { SubscriptionStateIcon } from "@/components/admin/people/PersonSubscriptionPanel";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useDisciplineMetadata, useDisciplines } from "@/hooks/useDisciplineMetadata";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import type { WorkspaceAxis } from "@/lib/site/discipline-scope";
import { userQueryKeys } from "@/lib/users/query-keys";
import adminService from "@/services/admin.service";
import rankService from "@/services/rank.service";
import userService from "@/services/user.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import type { CurrentRank } from "@/types/rank.types";
import type { UserTournament } from "@/types/user.types";

const MUTED = "text-body text-muted-foreground";
const LINK = "rounded-sm hover:underline focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

/** A collector's lowercase division, cased for display: "Diamond 2". */
function divisionLabel(rank: CurrentRank): string | null {
  if (!rank.division) return null;
  const division = rank.division.charAt(0).toUpperCase() + rank.division.slice(1);
  return rank.tier != null ? `${division} ${rank.tier}` : division;
}

/** A label over its value (DESIGN §4), with the way to the tab that owns it on the label's line. */
function GlanceRow({
  label,
  href,
  linkLabel,
  children
}: Readonly<{ label: string; href: string; linkLabel: string; children: ReactNode }>) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-3 gap-y-1 py-3 first:pt-0 last:pb-0">
      <dt className={eyebrowClass("muted")}>{label}</dt>
      <dd>
        <Link
          href={href}
          className={`inline-flex items-center gap-0.5 whitespace-nowrap text-caption text-primary ${LINK}`}
        >
          {linkLabel}
          <ChevronRight aria-hidden className="size-3.5" />
        </Link>
      </dd>
      <dd className="col-span-2 min-w-0">{children}</dd>
    </div>
  );
}

function RowError({ onRetry }: Readonly<{ onRetry: () => void }>) {
  const t = useTranslations("adminPeople.glance");
  return (
    <p className={`flex flex-wrap items-center gap-x-2 ${MUTED}`}>
      <AlertCircle aria-hidden className="size-4 shrink-0 text-danger" />
      {t("loadError")}
      <Button variant="ghost" size="sm" onClick={onRetry}>
        {t("retry")}
      </Button>
    </p>
  );
}

/** One game's ranked roles, named by that game's own ontology. */
function GameRanks({
  game,
  ranks,
  axis,
  href
}: Readonly<{ game: DisciplineDescriptor; ranks: CurrentRank[]; axis: WorkspaceAxis; href: string }>) {
  const ontology = useDisciplineMetadata(axis, game.code).data ?? null;
  const slotLabel = useSlotLabel(ontology);
  return (
    <li className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-body">
      <Link href={href} className={`font-medium text-foreground ${LINK}`}>
        {game.name}
      </Link>
      <span className="tabular-nums text-muted-foreground">
        {ranks
          .map((rank) => [rank.role ? slotLabel(rank.role) : null, divisionLabel(rank)].filter(Boolean).join(" "))
          .join(" · ")}
      </span>
    </li>
  );
}

/**
 * One line per thing that lives on its own tab: current ranks per game, the
 * career, achievements, subscription verdicts, the login. Each read is the
 * owning tab's own query, so opening that tab next is a cache hit.
 */
export function PersonGlance({
  personId,
  canReadAuth
}: Readonly<{ personId: number; canReadAuth: boolean }>) {
  const t = useTranslations("adminPeople.glance");
  const tAccount = useTranslations("adminAccess.common");
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const gamesQuery = useDisciplines("all");
  const games = gamesQuery.data ?? [];
  const rankGames = games.filter((game) => game.capabilities.native_rank_collection);
  const tabHref = (tab: string) => `/admin/people/${personId}?tab=${tab}`;

  const currentRanks = useQueries({
    queries: rankGames.map((game) => ({
      queryKey: userQueryKeys.rankCurrent(personId, game.code),
      queryFn: () => rankService.getUserCurrentRanks(personId, game.code)
    }))
  });
  const rankLines = rankGames.flatMap((game, index) => {
    const ranks = (currentRanks[index]?.data?.ranks ?? []).filter((rank) => rank.is_ranked);
    return ranks.length > 0 ? [{ game, ranks }] : [];
  });

  // Exactly the Participations tab's reads: one per installed game, in this workspace.
  const careers = useQueries({
    queries: games.map((game) => ({
      queryKey: userQueryKeys.tournaments(personId, workspaceId, game.code),
      queryFn: () => userService.getUserTournaments(personId, game.code, workspaceId)
    }))
  });
  // The tab's rows: a tournament counts when this person has a roster row in it.
  const played = careers
    .flatMap((career) => career.data?.results ?? [])
    .filter((entry) => entry.players.some((player) => player.user_id === personId));
  // The read carries no dates; tournament ids grow with creation.
  const latest = played.reduce<UserTournament | null>(
    (best, entry) => (best && best.id > entry.id ? best : entry),
    null
  );

  const achievementsQuery = useQuery({
    queryKey: adminQueryKeys.personAchievements(personId),
    queryFn: () => userService.getUserAchievements(personId)
  });
  const achievementCount = achievementsQuery.data?.length ?? 0;

  const subscriptionsQuery = useQuery({
    queryKey: adminQueryKeys.subscriptionsCollection(workspaceId, personId),
    queryFn: () => adminService.getSubscriptionCollectionStatus(personId)
  });
  const subscriptions = subscriptionsQuery.data ?? [];
  const { accountsQuery, linked } = useLinkedAccount(personId, canReadAuth);

  const retryFailed = (queries: readonly { isError: boolean; refetch: () => unknown }[]) => () => {
    for (const query of [gamesQuery, ...queries]) if (query.isError) void query.refetch();
  };

  return (
    <dl className="divide-y divide-border/60">
      <GlanceRow label={t("ranks")} href={tabHref("ranks")} linkLabel={t("rankCollection")}>
        {gamesQuery.isLoading || currentRanks.some((query) => query.isLoading) ? (
          <Skeleton className="h-5 w-48" />
        ) : gamesQuery.isError || currentRanks.some((query) => query.isError) ? (
          <RowError onRetry={retryFailed(currentRanks)} />
        ) : rankLines.length === 0 ? (
          <p className={MUTED}>{t("noRank")}</p>
        ) : (
          <ul className="space-y-1">
            {rankLines.map(({ game, ranks }) => (
              <GameRanks
                key={game.code}
                game={game}
                ranks={ranks}
                axis={workspaceId ?? "all"}
                href={`${tabHref("ranks")}&discipline=${encodeURIComponent(game.code)}`}
              />
            ))}
          </ul>
        )}
      </GlanceRow>

      <GlanceRow label={t("participations")} href={tabHref("participations")} linkLabel={t("allParticipations")}>
        {gamesQuery.isLoading || careers.some((query) => query.isLoading) ? (
          <Skeleton className="h-5 w-48" />
        ) : gamesQuery.isError || careers.some((query) => query.isError) ? (
          <RowError onRetry={retryFailed(careers)} />
        ) : !latest ? (
          <p className={MUTED}>{t("noParticipations")}</p>
        ) : (
          <p className="flex min-w-0 items-baseline gap-1.5 text-body">
            <span className="tabular-nums">{played.length}</span>
            <span aria-hidden className="text-[color:var(--aqt-fg-dim)]">
              ·
            </span>
            <span className="truncate text-muted-foreground" title={latest.name}>
              {t("latestTournament", { name: latest.name })}
            </span>
          </p>
        )}
      </GlanceRow>

      <GlanceRow label={t("achievements")} href={tabHref("achievements")} linkLabel={t("allAchievements")}>
        {achievementsQuery.isLoading ? (
          <Skeleton className="h-5 w-16" />
        ) : achievementsQuery.isError ? (
          <RowError onRetry={() => void achievementsQuery.refetch()} />
        ) : achievementCount === 0 ? (
          <p className={MUTED}>{t("noAchievements")}</p>
        ) : (
          <p className="text-body tabular-nums">{achievementCount}</p>
        )}
      </GlanceRow>

      <GlanceRow label={t("subscriptions")} href={tabHref("subscriptions")} linkLabel={t("allChecks")}>
        {subscriptionsQuery.isLoading ? (
          <Skeleton className="h-5 w-48" />
        ) : subscriptionsQuery.isError ? (
          <RowError onRetry={() => void subscriptionsQuery.refetch()} />
        ) : subscriptions.length === 0 ? (
          <p className={MUTED}>{t("noVerdict")}</p>
        ) : (
          <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
            {subscriptions.map((row) => (
              <li
                key={`${row.workspace_id}-${row.provider}`}
                className="inline-flex items-center gap-1.5 text-body"
              >
                {row.state ? <SubscriptionStateIcon state={row.state} /> : null}
                <span className="font-medium">{PROVIDER_LABELS[row.provider] ?? row.provider}</span>
                {row.tier_label || row.workspace_name ? (
                  <span className="text-caption text-muted-foreground">
                    {[row.tier_label, row.workspace_name].filter(Boolean).join(" · ")}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </GlanceRow>

      {canReadAuth ? (
        <GlanceRow label={t("account")} href={tabHref("account")} linkLabel={t("manageAccount")}>
          {accountsQuery.isLoading ? (
            <Skeleton className="h-5 w-48" />
          ) : accountsQuery.isError ? (
            <RowError onRetry={() => void accountsQuery.refetch()} />
          ) : !linked ? (
            <p className={MUTED}>{t("noAccount")}</p>
          ) : (
            <div className="space-y-0.5">
              <p className="flex items-center gap-1.5 text-body font-medium">
                @{linked.username}
                {!linked.is_active ? (
                  <StatusIcon icon={UserX} label={tAccount("inactive")} variant="muted" />
                ) : linked.is_superuser ? (
                  <StatusIcon icon={ShieldAlert} label={tAccount("superuser")} variant="destructive" />
                ) : null}
              </p>
              {linked.roles.length > 0 ? (
                <p className="text-caption text-muted-foreground">
                  {linked.roles.map((role) => role.name).join(" · ")}
                </p>
              ) : null}
            </div>
          )}
        </GlanceRow>
      ) : null}
    </dl>
  );
}
