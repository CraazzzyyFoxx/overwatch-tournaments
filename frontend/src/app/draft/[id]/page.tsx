"use client";

import { ShieldAlert } from "lucide-react";
import { redirect, useParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { DraftBoard, DraftStateFrame } from "@/components/draft/DraftBoard";
import { tournamentHref } from "@/lib/tournament/url";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { Button } from "@/components/ui/button";

import styles from "@/components/draft/DraftRoom.module.css";
import { DraftRoomSkeleton } from "@/components/draft/DraftRoomSkeleton";
import { shouldShowInitialDraftSkeleton } from "@/components/draft/draft-loading-state";

export default function PublicDraftRoomPage() {
  const t = useTranslations("draftRedesign");
  const params = useParams<{ id: string }>();
  // Legacy numeric ref: this route is addressed by tournament id directly
  // (not by slug), and the backend resolves a numeric ref like any other.
  const tournamentQuery = useTournamentQuery(params.id);
  const tournament = tournamentQuery.data;

  if (tournament && tournament.team_formation !== "draft") {
    redirect(tournamentHref(tournament));
  }

  if (shouldShowInitialDraftSkeleton(tournamentQuery)) {
    return <DraftRoomSkeleton />;
  }

  const initialLoadError = tournamentQuery.isError && !tournament;

  return (
    <div className={`${styles.room} site-theme`}>
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
        ) : (
          <DraftBoard tournament={tournament} />
        )}
      </main>
    </div>
  );
}
