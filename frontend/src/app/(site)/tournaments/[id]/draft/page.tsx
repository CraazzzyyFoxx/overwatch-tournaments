"use client";

import { useParams, redirect } from "next/navigation";

import { useTranslations } from "next-intl";
import { useTournamentQuery } from "../_hooks/useTournamentClientData";
import { DraftBoard } from "./_components/DraftBoard";

export default function TournamentDraftRoutePage() {
  const t = useTranslations();
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const tournamentQuery = useTournamentQuery(tournamentId);

  if (tournamentQuery.isLoading) {
    return (
      <div className="rounded-xl border border-[color:var(--aqt-border)] bg-white/[0.02] px-4 py-8 text-center text-muted-foreground">
        {t("common.loading")}
      </div>
    );
  }

  if (!tournamentQuery.data) {
    return (
      <div className="rounded-xl border border-[color:var(--aqt-border)] bg-white/[0.02] px-4 py-8 text-center text-muted-foreground">
        {t("common.tournamentNotFound")}
      </div>
    );
  }

  if (tournamentQuery.data.team_formation !== "draft") {
    redirect(`/tournaments/${tournamentId}`);
  }

  return <DraftBoard tournament={tournamentQuery.data} />;
}
