"use client";

import { Loader2, ShieldAlert } from "lucide-react";
import { useParams, redirect } from "next/navigation";

import { HeroFrame } from "@/components/site/PageHero";
import { useTranslations } from "next-intl";
import { useTournamentQuery } from "../_hooks/useTournamentClientData";
import { DraftBoard } from "./_components/DraftBoard";

export default function TournamentDraftRoutePage() {
  const t = useTranslations();
  const draftT = useTranslations("draftRedesign");
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const tournamentQuery = useTournamentQuery(tournamentId);

  if (tournamentQuery.isLoading) {
    return (
      <HeroFrame>
        <div className="flex min-h-64 flex-col items-start justify-center gap-3 px-6 py-12 md:px-10" role="status" aria-live="polite">
          <Loader2 className="h-6 w-6 animate-spin text-[color:var(--aqt-teal)] motion-reduce:animate-none" />
          <h1 className="font-onest text-2xl font-semibold">{draftT("loadingTitle")}</h1>
          <p className="text-sm text-[color:var(--aqt-fg-muted)]">{draftT("loadingHint")}</p>
        </div>
      </HeroFrame>
    );
  }

  if (!tournamentQuery.data) {
    return (
      <HeroFrame>
        <div className="flex min-h-64 flex-col items-start justify-center gap-3 px-6 py-12 md:px-10">
          <ShieldAlert className="h-6 w-6 text-[color:var(--aqt-warm)]" />
          <h1 className="font-onest text-2xl font-semibold">{t("common.tournamentNotFound")}</h1>
        </div>
      </HeroFrame>
    );
  }

  if (tournamentQuery.data.team_formation !== "draft") {
    redirect(`/tournaments/${tournamentId}`);
  }

  return <DraftBoard tournament={tournamentQuery.data} />;
}
