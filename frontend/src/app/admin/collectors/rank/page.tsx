"use client";

import { useTranslations } from "next-intl";

import { PermissionGate } from "@/components/admin/PermissionGate";
import { RankHealthDashboard } from "@/components/admin/collectors/rank-health";
import { RankTaskHistory } from "@/components/admin/collectors/rank-history";
import { RankSettingsPanel } from "@/components/admin/collectors/rank-settings";
import { collectsRanks } from "@/components/admin/collectors/rank-shared";
import { useCollectorTab } from "@/components/admin/collectors/useCollectorTab";
import { LinkTabs } from "@/components/kit/LinkTabs";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { GameScopeControl } from "@/components/workspace/GameScopeControl";
import { useGameScope } from "@/hooks/useGameScope";
import { usePermissions } from "@/hooks/usePermissions";

/**
 * The rank collector of the picked game: OverFast for Overwatch, the Riot API
 * for League — is the worker healthy, what has it been doing, and how is it
 * configured. The game is `?discipline=`, else the first game that collects
 * ranks.
 *
 * Health and the fetch log are one view — a `?tab=history` slot used to hide
 * the log behind a third row of tabs under the hub's, and the two answer the
 * same question ("is it working?") for the same reader. Settings is its own
 * slot: a form with its own save bar, superuser-only. Health and history are
 * gated on `rank.read` and scoped to the active workspace (see
 * `admin.service.ts`) — which is what lets a workspace owner open them at all
 * instead of 403ing on a global role. The form writes through
 * `PUT /api/v1/admin/settings/{key}`, which is superuser-only, so the slot is
 * offered only to a superuser rather than showing a form that 403s on save.
 *
 * Per-player inspection is deliberately absent: it lives on the person now
 * (People › person › Rank & subscription, F14 ·3), and the history table links
 * there.
 */
export default function RankCollectorPage() {
  const t = useTranslations("collectors");
  const { canAccessPermission, isSuperuser, isLoaded } = usePermissions();
  const canRead = canAccessPermission("rank.read");
  const gameScope = useGameScope({ pageClass: "platform", axis: "all", filter: collectsRanks });
  const discipline = gameScope.game;

  const { activeKey, items } = useCollectorTab("rank", [
    { key: "status", label: t("views.status") },
    { key: "settings", label: t("views.settings"), hidden: !isSuperuser }
  ]);

  return (
    <PermissionGate loaded={isLoaded} allowed={canRead} description={t("access.rank")} headingLevel={2}>
      <div className="space-y-4">
        <LinkTabs items={items} activeKey={activeKey} level={2} ariaLabel={t("views.rankAria")} />
        <GameScopeControl scope={gameScope} variant="single" />
        {discipline === null ? (
          gameScope.isError ? (
            <PageStateCard state="error" onAction={gameScope.refetch} />
          ) : gameScope.resolution === null ? (
            <Skeleton className="h-40 w-full rounded-xl" />
          ) : null
        ) : activeKey === "settings" ? (
          <RankSettingsPanel key={discipline} discipline={discipline} />
        ) : (
          <>
            <RankHealthDashboard discipline={discipline} />
            <RankTaskHistory discipline={discipline} />
          </>
        )}
      </div>
    </PermissionGate>
  );
}
