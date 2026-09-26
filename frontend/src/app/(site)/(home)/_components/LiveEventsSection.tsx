import { getTranslations } from "next-intl/server";
import { Calendar } from "lucide-react";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { Button } from "@/components/ui/button";
import {
  EventCard,
  LiveUpcomingBadge,
  type TournamentWithCount
} from "@/components/site/LiveEventsWidgets";
import tournamentService from "@/services/tournament.service";
import { isTournamentStatusActive } from "@/lib/tournament/status";
import type { Workspace } from "@/types/workspace.types";

import { getTenantMode, getWorkspaces } from "./home.helpers";

/** What is on right now, or starting soon — at most six cards. */
export async function LiveEventsSection() {
  const tenantMode = await getTenantMode();
  let activeTournaments: TournamentWithCount[] = [];
  let workspaceMap = new Map<number, Workspace>();

  try {
    const [tournamentsData, workspaces] = await Promise.all([
      tournamentService.getActive({ skipWorkspace: !tenantMode }),
      getWorkspaces()
    ]);

    activeTournaments = (tournamentsData.results as TournamentWithCount[])
      .filter((tour) => isTournamentStatusActive(tour.status))
      .slice(0, 6);

    workspaceMap = new Map(workspaces.map((w) => [w.id, w]));
  } catch {
    // fail silently — show empty state
  }

  const liveCount = activeTournaments.filter(
    (tour) => tour.status === "live" || tour.status === "playoffs"
  ).length;

  if (activeTournaments.length === 0) {
    return <NoEventsState />;
  }

  return (
    <div>
      <LiveUpcomingBadge
        liveCount={liveCount}
        upcomingCount={activeTournaments.length - liveCount}
        dotClassName="bg-[color:var(--aqt-emerald)]"
        textClassName="text-[color:var(--aqt-emerald)]"
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {activeTournaments.map((tour) => (
          <EventCard
            key={tour.id}
            tournament={tour}
            workspace={workspaceMap.get(tour.workspace_id)}
          />
        ))}
      </div>
    </div>
  );
}

async function NoEventsState() {
  const t = await getTranslations();
  return (
    <div className="flex flex-col items-center gap-3 p-8 rounded-xl border border-dashed border-border/50 max-w-sm mx-auto text-center">
      <Calendar className="h-7 w-7 text-muted-foreground/30" aria-hidden />
      <div>
        <p className="text-sm font-semibold text-muted-foreground mb-1">
          {t("home.noEventsTitle")}
        </p>
        <p className="text-xs text-muted-foreground/50 leading-relaxed">{t("home.noEventsBody")}</p>
      </div>
      <Button variant="outline" size="sm" asChild className="mt-1">
        <HoverPrefetchLink href="/tournaments">{t("home.browsePastTournaments")}</HoverPrefetchLink>
      </Button>
    </div>
  );
}
