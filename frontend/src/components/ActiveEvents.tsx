"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Radio, Users } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import {
  getTournamentStatusMeta,
  isTournamentStatusActive,
} from "@/lib/tournament-status";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { WorkspaceAvatar } from "@/components/WorkspaceSwitcher";
import tournamentService from "@/services/tournament.service";
import { Tournament } from "@/types/tournament.types";
import { Workspace } from "@/types/workspace.types";

interface WorkspaceGroup {
  workspace: Workspace;
  tournaments: Tournament[];
  totalRegistrations: number;
}

export default function ActiveEvents() {
  const { workspaces } = useWorkspaceStore();

  const { data: allTournaments } = useQuery({
    queryKey: ["tournaments", "all-active"],
    queryFn: () => tournamentService.getActive(),
    staleTime: 60_000,
  });

  const activeGroups = useMemo<WorkspaceGroup[]>(() => {
    if (!allTournaments?.results || workspaces.length === 0) return [];

    const active = allTournaments.results.filter((t) =>
      isTournamentStatusActive(t.status)
    );
    if (active.length === 0) return [];

    const byWorkspace = new Map<number, Tournament[]>();
    for (const t of active) {
      const list = byWorkspace.get(t.workspace_id) ?? [];
      list.push(t);
      byWorkspace.set(t.workspace_id, list);
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
          (sum, t) => sum + (t.registrations_count ?? 0),
          0
        ),
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
          className={cn(
            "relative flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium",
            "transition-colors hover:bg-accent",
            "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          )}
        >
          <span className="relative flex size-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
          </span>
          <span className="hidden sm:inline text-emerald-400">
            {totalActive} Active
          </span>
          <span className="sm:hidden text-emerald-400">{totalActive}</span>
        </button>
      </PopoverTrigger>

      <PopoverContent align="end" className="w-80 p-0" sideOffset={8}>
        <div className="px-3 py-2.5 border-b border-border">
          <p className="text-sm font-medium">Active Events</p>
          <p className="text-xs text-muted-foreground">
            {totalActive} ongoing across {activeGroups.length} workspace
            {activeGroups.length !== 1 ? "s" : ""}
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
                <span className="ml-auto text-[10px] text-muted-foreground tabular-nums">
                  {group.totalRegistrations}
                  <Users className="inline ml-0.5 size-2.5" />
                </span>
              </div>

              <div className="flex flex-col gap-0.5">
                {group.tournaments.map((t) => {
                  const statusMeta = getTournamentStatusMeta(t.status);
                  return (
                    <Link
                      key={t.id}
                      href={`/tournaments/${t.id}`}
                      className={cn(
                        "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm",
                        "transition-colors hover:bg-accent"
                      )}
                    >
                      <Radio className="size-3 shrink-0 text-emerald-400" />
                      <div className="min-w-0 flex-1">
                        <span className="block truncate">{t.name}</span>
                        <span
                          className={cn(
                            "block text-[10px] uppercase tracking-wide",
                            statusMeta.badgeClassName
                          )}
                        >
                          {statusMeta.badgeLabel}
                        </span>
                      </div>
                      <span className="text-[10px] text-muted-foreground tabular-nums shrink-0">
                        {t.registrations_count ?? 0}
                        <Users className="inline ml-0.5 size-2.5" />
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
