import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { getTranslations } from "next-intl/server";
import { Calendar, Users } from "lucide-react";

import WorkspaceBrandIcon from "@/components/workspace/WorkspaceBrandIcon";
import { formatDateRange } from "@/lib/datetime";
import { getFormatter } from "@/lib/datetime/server";
import { tournamentHref } from "@/lib/tournament/url";
import { getTournamentStatusMeta } from "@/lib/tournament/status";
import type { Tournament } from "@/types/tournament.types";
import type { Workspace } from "@/types/workspace.types";

export type TournamentWithCount = Tournament & { registrations_count?: number };

/**
 * One live/upcoming tournament as a whole-card link: organizer identity on
 * top, status on the right, uppercase name, dates, and a registered count
 * with the "open" affordance. Shared by the site home and workspace home.
 */
export async function EventCard({
  tournament,
  workspace,
}: Readonly<{ tournament: TournamentWithCount; workspace?: Workspace }>) {
  const t = await getTranslations();
  const format = await getFormatter();
  const isLive = tournament.status === "live" || tournament.status === "playoffs";
  const statusMeta = getTournamentStatusMeta(tournament.status);
  const dateStr = formatDateRange(format, tournament.start_date, tournament.end_date);

  return (
    <HoverPrefetchLink
      href={tournamentHref(tournament)}
      className="rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--aqt-bg)]"
    >
      <div className="group h-full rounded-2xl border border-border/60 bg-card/50 p-5 flex flex-col gap-4 hover:bg-card hover:border-border transition-all duration-150">
        <div className="flex items-start justify-between gap-3">
          {workspace ? (
            <div className="flex min-w-0 items-center gap-3">
              <WorkspaceBrandIcon
                name={workspace.name}
                iconUrl={workspace.icon_url}
                className="size-12 rounded-xl text-base"
              />
              <span className="truncate text-sm font-medium text-muted-foreground">
                {workspace.name}
              </span>
            </div>
          ) : (
            <span />
          )}

          <div className="flex shrink-0 items-center gap-2">
            {tournament.is_league && (
              <span className="text-label font-bold tracking-label uppercase px-1.5 py-0.5 rounded-full border border-[color:color-mix(in_srgb,var(--aqt-violet)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-violet)_14%,transparent)] text-[color:var(--aqt-violet)]">
                {t("common.league")}
              </span>
            )}
            <span className={`flex items-center gap-1.5 text-sm font-medium ${statusMeta.textClassName}`}>
              <span className="relative flex h-2 w-2">
                {isLive && (
                  <span
                    className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${statusMeta.dotClassName}`}
                  />
                )}
                <span className={`relative inline-flex h-2 w-2 rounded-full ${statusMeta.dotClassName}`} />
              </span>
              {t(`common.statusBadge.${tournament.status}`)}
            </span>
          </div>
        </div>

        <div className="font-display text-xl font-bold uppercase leading-snug tracking-wide text-foreground flex-1">
          {tournament.name}
        </div>

        <div className="flex flex-col gap-1.5 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <Calendar className="h-4 w-4 shrink-0" aria-hidden />
            {dateStr}
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2">
              <Users className="h-4 w-4 shrink-0" aria-hidden />
              <span className="tabular-nums">{tournament.registrations_count ?? 0}</span>{" "}
              {isLive ? t("common.participants") : t("common.registered")}
            </span>
            <span className="font-semibold text-[color:var(--aqt-blue)] group-hover:underline">
              {t("common.view")}
              <span aria-hidden>→</span>
            </span>
          </div>
        </div>
      </div>
    </HoverPrefetchLink>
  );
}

/**
 * "N live · M upcoming" indicator dot + label — shared by the site home
 * page's platform-wide live events section and each workspace's own live
 * events section. Same markup on both surfaces; only the accent color
 * differs (the home page retints per tenant, a workspace page does not).
 */
export async function LiveUpcomingBadge({
  liveCount,
  upcomingCount,
  dotClassName,
  textClassName,
}: Readonly<{
  liveCount: number;
  upcomingCount: number;
  dotClassName: string;
  textClassName: string;
}>) {
  const t = await getTranslations();
  return (
    <div className="flex items-center gap-2.5 mb-4">
      <span className="relative flex h-2 w-2">
        <span
          className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${dotClassName}`}
        />
        <span className={`relative inline-flex rounded-full h-2 w-2 ${dotClassName}`} />
      </span>
      <span className={`text-label font-bold tracking-label uppercase ${textClassName}`}>
        {liveCount > 0 && t("statistics.liveCount", { count: liveCount })}
        {liveCount > 0 && upcomingCount > 0 && " · "}
        {upcomingCount > 0 && t("statistics.upcomingCount", { count: upcomingCount })}
      </span>
    </div>
  );
}

/** Loading placeholder for a 3-column grid of event cards. */
export function EventsSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="h-44 rounded-xl border border-border/60 bg-card/30 animate-pulse" />
      ))}
    </div>
  );
}
