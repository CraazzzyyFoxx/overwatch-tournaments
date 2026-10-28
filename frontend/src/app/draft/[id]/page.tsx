"use client";

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { redirect, useParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { DraftBoard, DraftStateFrame } from "@/components/draft/DraftBoard";
import { tournamentHref } from "@/lib/tournament/url";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import draftService from "@/services/draft.service";
import { useDraftBoardQuery } from "@/hooks/useDraftData";
import { usePermissions } from "@/hooks/usePermissions";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { useEntityWorkspace } from "@/hooks/useEntityWorkspace";
import { Button } from "@/components/ui/button";

import { DRAFT_ROOM_CLASS, DraftBoardSkeleton, DraftRoomSkeleton } from "@/components/draft/DraftRoomSkeleton";
import { shouldShowInitialDraftSkeleton } from "@/components/draft/draft-loading-state";

/** How often a page with no draft to follow asks the tournament again: the organizer may be seeding one. */
const LOOKUP_POLL_MS = 60_000;

export default function PublicDraftRoomPage() {
  const t = useTranslations("draftRedesign");
  const params = useParams<{ id: string }>();
  // Legacy numeric ref: this route is addressed by tournament id directly
  // (not by slug), and the backend resolves a numeric ref like any other.
  const tournamentQuery = useTournamentQuery(params.id);
  const tournament = tournamentQuery.data;
  // The room belongs to its tournament's workspace, not to whichever one the visitor last browsed.
  useEntityWorkspace(tournament?.workspace_id, tournament?.discipline);
  const { canAccessPermission } = usePermissions();
  // The tournament's current draft (active, else the latest): the room is the session's.
  const lookup = useQuery({
    queryKey: tournamentQueryKeys.draftBoard(tournament?.id ?? 0),
    queryFn: () => draftService.getTournamentBoard(tournament!.id),
    enabled: tournament != null,
    refetchInterval: (query) => (query.state.data == null ? LOOKUP_POLL_MS : false)
  });
  const sessionId = lookup.data?.session.id ?? null;
  // The room's own board (the same cache the room patches): once its draft is
  // over or erased, the tournament's next draft is the one to follow. It starts
  // from the lookup's snapshot, so opening the room reads the board once.
  const followed = useDraftBoardQuery(
    sessionId,
    lookup.data ? { board: lookup.data, updatedAt: lookup.dataUpdatedAt } : undefined
  );
  const followedStatus = followed.data?.session.status;
  const followedEnded = followed.isError || followedStatus === "completed" || followedStatus === "cancelled";
  const { refetch: refetchLookup } = lookup;
  useEffect(() => {
    if (!followedEnded) return;
    void refetchLookup();
    // ponytail: a poll while the followed draft is over; a tournament-topic "draft created" event would replace it.
    const timer = setInterval(() => void refetchLookup(), LOOKUP_POLL_MS);
    return () => clearInterval(timer);
  }, [followedEnded, refetchLookup]);

  if (tournament && tournament.team_formation !== "draft") {
    redirect(tournamentHref(tournament));
  }

  if (shouldShowInitialDraftSkeleton(tournamentQuery)) {
    return <DraftRoomSkeleton />;
  }

  const initialLoadError = tournamentQuery.isError && !tournament;

  return (
    <div className={DRAFT_ROOM_CLASS}>
      <main>
        {initialLoadError || !tournament ? (
          // The same frame the board uses for its own dead ends; the tournament
          // is unknown here, so the way out is the tournament list.
          <DraftStateFrame
            icon={<ShieldAlert className="h-6 w-6 text-[color:var(--aqt-amber)]" />}
            title={t("loadErrorTitle")}
            hint={t("loadErrorHint")}
            back={{ href: "/tournaments", label: t("room.allTournaments") }}
            action={
              <Button variant="outline" onClick={() => tournamentQuery.refetch()}>
                {t("retry")}
              </Button>
            }
          />
        ) : shouldShowInitialDraftSkeleton(lookup) ? (
          <DraftBoardSkeleton />
        ) : lookup.isError && !lookup.data ? (
          <DraftStateFrame
            icon={<ShieldAlert className="h-6 w-6 text-[color:var(--aqt-amber)]" />}
            title={t("loadErrorTitle")}
            hint={t("loadErrorHint")}
            back={{ href: tournamentHref(tournament), label: t("room.back") }}
            action={
              <Button variant="outline" onClick={() => lookup.refetch()}>
                {t("retry")}
              </Button>
            }
          />
        ) : sessionId == null ? (
          <DraftStateFrame
            icon={<ShieldAlert className="h-6 w-6 text-[color:var(--aqt-amber)]" />}
            title={t("emptyTitle")}
            hint={t("emptyHint")}
            back={{ href: tournamentHref(tournament), label: t("room.back") }}
          />
        ) : (
          <DraftBoard
            // A new session is a new draft: its room starts clean.
            key={sessionId}
            sessionId={sessionId}
            owner={{
              workspaceId: tournament.workspace_id,
              discipline: tournament.discipline,
              name: tournament.name,
              href: `/tournaments/${tournament.id}`,
              divisionGrid: tournament.division_grid_version?.tiers
                ? { tiers: tournament.division_grid_version.tiers }
                : null,
              isOrganizer: canAccessPermission("team.create", tournament.workspace_id)
            }}
          />
        )}
      </main>
    </div>
  );
}
