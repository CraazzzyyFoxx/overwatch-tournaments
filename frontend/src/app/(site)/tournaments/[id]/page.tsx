import { notFound, redirect } from "next/navigation";

import type { TournamentStatus } from "@/types/tournament.types";

import { getTournamentOverviewState, parseCanonicalTournamentId } from "./_data";

type TournamentIndexPageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{
    tab?: string;
    page?: string;
    search?: string;
  }>;
};

const isTab = (value: string | undefined) => {
  return (
    value === "teams" ||
    value === "participants" ||
    value === "matches" ||
    value === "heroes" ||
    value === "standings"
  );
};

const REGISTRATION_PHASES = new Set<TournamentStatus>(["draft", "registration", "check_in"]);
const BRACKET_PHASES = new Set<TournamentStatus>(["live", "playoffs", "completed", "archived"]);

function getDefaultTournamentPath({
  tournamentId,
  status,
  hasStages
}: {
  tournamentId: number;
  status: TournamentStatus;
  hasStages: boolean;
}) {
  if (BRACKET_PHASES.has(status) && hasStages) {
    return `/tournaments/${tournamentId}/bracket`;
  }

  if (REGISTRATION_PHASES.has(status)) {
    return `/tournaments/${tournamentId}/participants`;
  }

  return null;
}

export default async function TournamentIndexPage({
  params,
  searchParams
}: TournamentIndexPageProps) {
  const resolvedParams = await params;
  const resolvedSearchParams = await searchParams;
  const tournamentId = parseCanonicalTournamentId(resolvedParams.id);
  if (tournamentId === null) {
    notFound();
  }
  const teamsPath = `/tournaments/${resolvedParams.id}/teams`;

  const tab = resolvedSearchParams.tab;

  if (tab && !isTab(tab)) {
    redirect(`/tournaments/${resolvedParams.id}`);
  }

  if (tab && tab !== "teams") {
    const qs = new URLSearchParams();
    if (tab === "matches") {
      if (resolvedSearchParams.page) qs.set("page", resolvedSearchParams.page);
      if (resolvedSearchParams.search) qs.set("search", resolvedSearchParams.search);
    }
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    redirect(`/tournaments/${resolvedParams.id}/${tab}${suffix}`);
  }

  if (tab === "teams") {
    redirect(teamsPath);
  }

  const overviewState = await getTournamentOverviewState(tournamentId);
  if (overviewState.kind === "not-found") {
    notFound();
  }
  if (overviewState.kind === "error") {
    return null;
  }

  const defaultPath = getDefaultTournamentPath({
    tournamentId,
    status: overviewState.overview.status,
    hasStages: overviewState.overview.stages.length > 0
  });

  if (defaultPath) {
    redirect(defaultPath);
  }

  redirect(teamsPath);
}
