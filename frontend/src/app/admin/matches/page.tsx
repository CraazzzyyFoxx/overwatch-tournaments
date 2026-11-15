"use client";

import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { AdminTabbedPage } from "@/components/admin/AdminTabbedPage";
import { PermissionGate } from "@/components/admin/PermissionGate";
import type { LinkTabItem } from "@/components/kit/LinkTabs";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { GameScopeGate } from "@/components/workspace/GameScopeGate";
import { useGameScope } from "@/hooks/useGameScope";
import { usePermissions } from "@/hooks/usePermissions";
import { useWorkspaceStore } from "@/stores/workspace.store";

const VIEWS = ["encounters", "standings", "reports", "parsed", "logs"] as const;
type MatchesView = (typeof VIEWS)[number];

/**
 * Params a view switch keeps. The tournament and stage scope, and the Game chip
 * the encounters and parsed-maps views share, are what the five views have in
 * common; `id`, `page`, `search` and the per-view chips are dropped, because a
 * row id or a `status` means a different thing in each view and carrying it
 * over would filter the next view by nonsense.
 */
const SHARED_SCOPE_PARAMS = ["tournament", "stage", "group", "discipline"] as const;

const fallback = (
  <div className="space-y-4">
    <Skeleton className="h-32 w-full rounded-xl" />
    <Skeleton className="h-64 w-full rounded-xl" />
  </div>
);

const EncountersBrowser = dynamic(
  () =>
    import("@/components/admin/EncountersBrowser").then((module) => ({
      default: module.EncountersBrowser
    })),
  { loading: () => fallback }
);
const StandingsBrowser = dynamic(
  () =>
    import("@/components/admin/StandingsBrowser").then((module) => ({
      default: module.StandingsBrowser
    })),
  { loading: () => fallback }
);
const EncounterReportsBrowser = dynamic(
  () =>
    import("@/components/admin/EncounterReportsBrowser").then((module) => ({
      default: module.EncounterReportsBrowser
    })),
  { loading: () => fallback }
);
const ParsedMatchesBrowser = dynamic(
  () =>
    import("@/components/admin/ParsedMatchesBrowser").then((module) => ({
      default: module.ParsedMatchesBrowser
    })),
  { loading: () => fallback }
);
const TournamentLogsTab = dynamic(
  () =>
    import("@/app/admin/tournaments/[id]/components/TournamentLogsTab").then((module) => ({
      default: module.TournamentLogsTab
    })),
  { loading: () => fallback }
);

/**
 * Everything that happens to a match, across every tournament in the
 * workspace: one screen with five views.
 *
 * These were five sidebar entries — Encounters, Standings, Match reports,
 * Parsed matches and the log console — each a page of its own, so answering
 * "what is wrong with this encounter" meant walking four of them and losing the
 * tournament scope at every step. The views mount the same components the
 * tournament hub does, with the tournament unpinned, and `?view=` is the only
 * state the switch owns.
 *
 * The encounters and parsed-maps views are multi (spec §6.9): every game of the
 * workspace with a "Game" column, or the game their shared Game chip
 * (`?discipline=`) filters, on the server. Standings, reports and logs are
 * game-agnostic.
 */
export default function AdminMatchesPage() {
  const t = useTranslations("adminMatches.matches");
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const { canAccessPermission, isLoaded } = usePermissions();
  const searchParams = useSearchParams();
  const gameScope = useGameScope({ axis: workspaceId ?? "all" });

  const requested = searchParams.get("view") ?? "";
  const view: MatchesView = (VIEWS as readonly string[]).includes(requested)
    ? (requested as MatchesView)
    : "encounters";

  const scope = new URLSearchParams();
  for (const key of SHARED_SCOPE_PARAMS) {
    const value = searchParams.get(key);
    if (value) scope.set(key, value);
  }

  const items: LinkTabItem[] = VIEWS.map((key) => {
    const query = new URLSearchParams(scope);
    query.set("view", key);
    return { key, label: t(key), href: `/admin/matches?${query.toString()}` };
  });

  return (
    <PermissionGate
      loaded={isLoaded}
      allowed={canAccessPermission("match.read", workspaceId)}
      description={t("noPermission")}
    >
      <AdminTabbedPage title={t("title")} tabs={items} activeKey={view} ariaLabel={t("views")}>
        {view === "encounters" ? (
          <GameScopeGate scope={gameScope}>
            {(game) => (
              <EncountersBrowser
                tournamentId={null}
                workspaceId={workspaceId}
                discipline={game}
                games={gameScope.games}
              />
            )}
          </GameScopeGate>
        ) : null}
        {view === "standings" ? (
          <StandingsBrowser tournamentId={null} workspaceId={workspaceId} />
        ) : null}
        {view === "reports" ? (
          <EncounterReportsBrowser
            tournamentId={null}
            workspaceId={workspaceId}
            canUpdateEncounter={canAccessPermission("match.result", workspaceId)}
          />
        ) : null}
        {view === "parsed" ? (
          <GameScopeGate scope={gameScope}>
            {(game) => (
              <ParsedMatchesBrowser
                tournamentId={null}
                discipline={game}
                workspaceId={workspaceId}
                games={gameScope.games}
              />
            )}
          </GameScopeGate>
        ) : null}
        {view === "logs" ? (
          <TournamentLogsTab
            tournamentId={null}
            workspaceId={workspaceId}
            encounters={[]}
            canUploadLogs={false}
          />
        ) : null}
      </AdminTabbedPage>
    </PermissionGate>
  );
}
