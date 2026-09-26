"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Radio, Users } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { tournamentHref } from "@/lib/tournament/url";
import {
  getTournamentStatusMeta,
  isTournamentStatusActive,
} from "@/lib/tournament/status";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceSwitcher";
import tournamentService from "@/services/tournament.service";
import { Tournament } from "@/types/tournament.types";
import { Workspace } from "@/types/workspace.types";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

interface WorkspaceGroup {
  workspace: Workspace;
  tournaments: Tournament[];
  totalRegistrations: number;
}

export default function ActiveEvents() {
  const t = useTranslations();
  const { workspaces } = useWorkspaceStore();

  const { data: allTournaments } = useQuery({
    queryKey: tournamentQueryKeys.allActive(),
    queryFn: () => tournamentService.getActive(),
    staleTime: 60_000,
  });

  const activeGroups = useMemo<WorkspaceGroup[]>(() => {
    if (!allTournaments?.results || workspaces.length === 0) return [];

    const active = allTournaments.results.filter((tournament) =>
      isTournamentStatusActive(tournament.status)
    );
    if (active.length === 0) return [];

    const byWorkspace = new Map<number, Tournament[]>();
    for (const tournament of active) {
      const list = byWorkspace.get(tournament.workspace_id) ?? [];
      list.push(tournament);
      byWorkspace.set(tournament.workspace_id, list);
    }

    const groups: WorkspaceGroup[] = [];
    for (const [wsId, tournaments] of byWorkspace) {
      const workspace = workspaces.find((w) => w.id === wsId);
      if (!workspace) continue;
      groups.push({
        workspace,
        tournaments: tournaments.sort(
          (a, b) =>
            new Date(b.start_date).getTime() -
            new Date(a.start_date).getTime()
        ),
        totalRegistrations: tournaments.reduce(
          (sum, tournament) => sum + (tournament.registrations_count ?? 0),
          0
        )
      });
    }

    return groups.sort((a, b) => a.workspace.name.localeCompare(b.workspace.name));
  }, [allTournaments, workspaces]);

  const totalActive = activeGroups.reduce(
    (sum, g) => sum + g.tournaments.length,
    0
  );

  if (totalActive === 0) return null;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("nav.activeEvents.badge", { count: totalActive })}
          className={cn(
            "relative flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium",
            "transition-colors hover:bg-accent",
            "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          )}
        >
          <span aria-hidden className="relative flex size-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[color:var(--aqt-emerald)] opacity-75" />
            <span className="relative inline-flex size-2 rounded-full bg-[color:var(--aqt-emerald)]" />
          </span>
          <span aria-hidden className="hidden text-[color:var(--aqt-emerald)] sm:inline">
            {t("nav.activeEvents.badge", { count: totalActive })}
          </span>
          <span aria-hidden className="text-[color:var(--aqt-emerald)] tabular-nums sm:hidden">
            {totalActive}
          </span>
        </button>
      </PopoverTrigger>

      <PopoverContent align="end" className="w-80 p-0" sideOffset={8}>
        <div className="px-3 py-2.5 border-b border-border">
          <p className="text-sm font-medium">{t("nav.activeEvents.title")}</p>
          <p className="text-xs text-muted-foreground">
            {t("nav.activeEvents.summary", {
              count: totalActive,
              workspaces: activeGroups.length
            })}
          </p>
        </div>

        <div className="max-h-80 overflow-y-auto p-1">
          {activeGroups.map((group) => (
            <div key={group.workspace.id} className="mb-1 last:mb-0">
              <div className="flex items-center gap-2 px-2 py-1.5">
                <WorkspaceAvatar workspace={group.workspace} size="sm" />
                <span className="text-xs font-medium text-muted-foreground truncate">
                  {group.workspace.name}
                </span>
                <span className="ml-auto text-label text-muted-foreground tabular-nums">
                  {group.totalRegistrations}
                  <Users className="ml-0.5 inline size-2.5" aria-hidden />
                </span>
              </div>

              <div className="flex flex-col gap-0.5">
                {group.tournaments.map((tournament) => {
                  const statusMeta = getTournamentStatusMeta(tournament.status);
                  return (
                    <Link
                      key={tournament.id}
                      href={tournamentHref(tournament)}
                      className={cn(
                        "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm",
                        "transition-colors hover:bg-accent"
                      )}
                    >
                      <Radio className="size-3 shrink-0 text-[color:var(--aqt-emerald)]" aria-hidden />
                      <div className="min-w-0 flex-1">
                        <span className="block truncate">{tournament.name}</span>
                        <span
                          className={cn(
                            "block text-label uppercase tracking-wide",
                            statusMeta.badgeClassName
                          )}
                        >
                          {t(`common.statusBadge.${tournament.status}`)}
                        </span>
                      </div>
                      <span className="shrink-0 text-label tabular-nums text-muted-foreground">
                        {tournament.registrations_count ?? 0}
                        <Users className="ml-0.5 inline size-2.5" aria-hidden />
                      </span>
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
