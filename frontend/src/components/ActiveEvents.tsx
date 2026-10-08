"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { useActiveWorkspace } from "@/components/workspace/WorkspaceSwitcher";
import { useFormatter } from "@/lib/datetime/client";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { isTournamentStatusActive } from "@/lib/tournament/status";
import { tournamentHref } from "@/lib/tournament/url";
import tournamentService from "@/services/tournament.service";
import type { Tournament } from "@/types/tournament.types";
import type { Workspace } from "@/types/workspace.types";

/**
 * "What is running right now, everywhere" — the header's live counter and the
 * list behind it, grouped by community. Where the location already fixes one
 * community (a community page, a white-label host) it lists only that one.
 * Renders nothing when nothing is active.
 */
export default function ActiveEvents() {
  const t = useTranslations();
  const format = useFormatter();
  const { workspaces, pinned } = useActiveWorkspace();

  const { data: allTournaments } = useQuery({
    queryKey: tournamentQueryKeys.allActive(),
    queryFn: () => tournamentService.getActive(),
    staleTime: 60_000
  });

  const groups = useMemo<{ workspace: Workspace; tournaments: Tournament[] }[]>(() => {
    if (!allTournaments?.results || workspaces.length === 0) return [];

    const byWorkspace = new Map<number, Tournament[]>();
    for (const tournament of allTournaments.results) {
      if (!isTournamentStatusActive(tournament.status)) continue;
      if (pinned && tournament.workspace_id !== pinned.id) continue;
      const list = byWorkspace.get(tournament.workspace_id) ?? [];
      list.push(tournament);
      byWorkspace.set(tournament.workspace_id, list);
    }

    return [...byWorkspace]
      .flatMap(([id, tournaments]) => {
        const workspace = workspaces.find((w) => w.id === id);
        return workspace
          ? [
              {
                workspace,
                tournaments: tournaments.sort(
                  (a, b) => new Date(b.start_date).getTime() - new Date(a.start_date).getTime()
                )
              }
            ]
          : [];
      })
      .sort((a, b) => a.workspace.name.localeCompare(b.workspace.name));
  }, [allTournaments, workspaces, pinned]);

  const total = groups.reduce((sum, group) => sum + group.tournaments.length, 0);
  if (total === 0) return null;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("nav.activeEvents.trigger", { count: total })}
          className="inline-flex h-9 shrink-0 items-center gap-2 whitespace-nowrap rounded-lg px-2.5 text-label font-medium text-[color:var(--aqt-emerald)] outline-none transition-colors hover:bg-[color:var(--aqt-overlay-3)] focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-[color:var(--aqt-overlay-3)]"
        >
          <span
            aria-hidden
            className="relative inline-flex size-[7px] shrink-0 rounded-full bg-current shadow-[0_0_0_3px_color-mix(in_srgb,currentColor_18%,transparent)]"
          >
            <span className="absolute inset-0 rounded-full bg-current motion-safe:animate-ping" />
          </span>
          <span aria-hidden className="aqt-tnum">
            {total}
            {/* The word yields to the nav at lg and comes back at xl. */}
            <span className="hidden sm:max-lg:inline xl:inline">
              &nbsp;{t("nav.activeEvents.word", { count: total })}
            </span>
          </span>
        </button>
      </PopoverTrigger>

      <PopoverContent
        align="end"
        sideOffset={8}
        collisionPadding={12}
        aria-label={t("nav.activeEvents.title")}
        className="w-[340px] max-w-[calc(100vw-24px)] rounded-xl border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)] p-1.5 shadow-[0_18px_50px_rgb(0_0_0/0.5)]"
      >
        <div className="border-b border-[color:var(--aqt-border)] px-2.5 pb-2.5 pt-2">
          <p className="font-semibold">{t("nav.activeEvents.title")}</p>
          <p className="text-caption text-[color:var(--aqt-fg-dim)]">
            {t("nav.activeEvents.summary", { count: total, workspaces: groups.length })}
          </p>
        </div>

        <div className="max-h-[min(70vh,420px)] overflow-y-auto pt-1.5">
          {groups.map((group) => (
            <div key={group.workspace.id}>
              <div className="flex items-center gap-2 px-2.5 pb-1.5 pt-2">
                <WorkspaceAvatar workspace={group.workspace} size={20} />
                <span className="min-w-0 flex-1 truncate text-caption font-semibold text-[color:var(--aqt-fg-muted)]">
                  {group.workspace.name}
                </span>
              </div>
              {group.tournaments.map((tournament) => {
                const counted =
                  tournament.status === "registration" || tournament.status === "check_in"
                    ? t("nav.activeEvents.registrations", {
                        count: tournament.registrations_count ?? 0
                      })
                    : t("nav.activeEvents.participants", {
                        count: tournament.participants_count ?? 0
                      });
                return (
                  <Link
                    key={tournament.id}
                    href={tournamentHref(tournament)}
                    className="flex min-h-10 items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-body outline-none transition-colors hover:bg-[color:var(--aqt-overlay-3)] focus-visible:bg-[color:var(--aqt-overlay-3)] focus-visible:shadow-[inset_0_0_0_2px_var(--aqt-teal)]"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-semibold">{tournament.name}</span>
                      <span className="block truncate text-caption text-[color:var(--aqt-fg-dim)]">
                        {t(`common.statusBadge.${tournament.status}`)} · {counted}
                      </span>
                    </span>
                    <span
                      className="aqt-tnum shrink-0 text-caption text-[color:var(--aqt-fg-dim)]"
                      title={format.dateTime(new Date(tournament.start_date), {
                        day: "numeric",
                        month: "long",
                        year: "numeric"
                      })}
                    >
                      {format.dateTime(new Date(tournament.start_date), {
                        day: "numeric",
                        month: "short"
                      })}
                    </span>
                  </Link>
                );
              })}
            </div>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
