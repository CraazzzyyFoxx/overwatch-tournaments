"use client";

import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Skeleton } from "@/components/ui/skeleton";

import TournamentHeroPlaytimePage from "@/app/(site)/tournaments/[id]/pages/TournamentHeroPlaytimePage";

import { useTournamentQuery } from "../_hooks/useTournamentClientData";

function HeroesPageSkeleton() {
  return <Skeleton className="h-[420px] w-full rounded-xl" />;
}

export default function TournamentHeroesPage() {
  const t = useTranslations();
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const tournamentQuery = useTournamentQuery(tournamentId);

  if (tournamentQuery.isLoading) {
    return <HeroesPageSkeleton />;
  }

  if (!tournamentQuery.data) {
    return (
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-8 text-center text-muted-foreground">
        {t("common.tournamentNotFound")}
      </div>
    );
  }

  return <TournamentHeroPlaytimePage tournament={tournamentQuery.data} />;
}
