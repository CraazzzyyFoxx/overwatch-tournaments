import type { StageSummary, TournamentStatus } from "@/types/tournament.types";

export type TournamentSectionId =
  "bracket" | "teams" | "participants" | "matches" | "heroes" | "standings" | "draft";

export type TournamentNavReasonKey =
  "tournamentDetail.nav.reasons.competitionNotStarted" | "tournamentDetail.nav.reasons.noStages";

export type TournamentSectionNavItem = {
  id: TournamentSectionId;
  labelKey: `common.${TournamentSectionId}`;
  href: string;
  active: boolean;
  available: boolean;
  reasonKey: TournamentNavReasonKey | null;
};

type BuildTournamentSectionNavInput = {
  tournamentId: string;
  status: TournamentStatus;
  stages: StageSummary[];
  teamFormation?: string;
  pathname: string;
};

const competitionStatuses = new Set<TournamentStatus>([
  "live",
  "playoffs",
  "completed",
  "archived"
]);

const competitionOnlySections = new Set<TournamentSectionId>([
  "bracket",
  "teams",
  "matches",
  "heroes",
  "standings"
]);

const tournamentSections: Exclude<TournamentSectionId, "draft">[] = [
  "bracket",
  "teams",
  "participants",
  "matches",
  "heroes",
  "standings"
];

function normalizePathname(pathname: string): string {
  const path = pathname.split(/[?#]/, 1)[0] || "/";
  return path.length > 1 ? path.replace(/\/+$/, "") : path;
}

function resolveBracketHref(tournamentId: string, stages: StageSummary[]): string {
  const active = stages.find((stage) => stage.is_active);
  const elimination = stages.find(
    (stage) =>
      stage.stage_type === "single_elimination" || stage.stage_type === "double_elimination"
  );
  const group = stages.find(
    (stage) => stage.stage_type === "round_robin" || stage.stage_type === "swiss"
  );
  const primary = active ?? elimination ?? group ?? stages[0];

  return primary
    ? `/tournaments/${tournamentId}/bracket?stage=${primary.id}`
    : `/tournaments/${tournamentId}/bracket`;
}

export function buildTournamentSectionNav({
  tournamentId,
  status,
  stages,
  teamFormation,
  pathname
}: BuildTournamentSectionNavInput): TournamentSectionNavItem[] {
  const competitionStarted = competitionStatuses.has(status);
  const currentPath = normalizePathname(pathname);
  const sections: TournamentSectionId[] =
    teamFormation === "draft" ? [...tournamentSections, "draft"] : tournamentSections;

  return sections.map((id) => {
    const href =
      id === "draft"
        ? `/draft/${tournamentId}`
        : id === "bracket"
          ? resolveBracketHref(tournamentId, stages)
          : `/tournaments/${tournamentId}/${id}`;
    const canonicalPath = href.split("?", 1)[0];
    const phaseLocked = competitionOnlySections.has(id) && !competitionStarted;
    const stageLocked = id === "bracket" && competitionStarted && stages.length === 0;

    return {
      id,
      labelKey: `common.${id}`,
      href,
      active: currentPath === canonicalPath,
      available: !phaseLocked && !stageLocked,
      reasonKey: phaseLocked
        ? "tournamentDetail.nav.reasons.competitionNotStarted"
        : stageLocked
          ? "tournamentDetail.nav.reasons.noStages"
          : null
    };
  });
}

export function getTournamentPhaseNoteKey(
  status: TournamentStatus,
  hasStages: boolean
): `tournamentDetail.nav.phase.${TournamentStatus | "awaitingStages"}` {
  if (competitionStatuses.has(status) && !hasStages) {
    return "tournamentDetail.nav.phase.awaitingStages";
  }

  return `tournamentDetail.nav.phase.${status}`;
}
