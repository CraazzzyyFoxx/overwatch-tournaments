import { Layers3, Trophy, type LucideIcon } from "lucide-react";
import type { Encounter } from "@/types/encounter.types";
import type { Team } from "@/types/team.types";
import type { Stage, Standings, Tournament } from "@/types/tournament.types";

export type TournamentFormState = {
  number: number | null;
  name: string;
  description: string;
  challonge_slug: string;
  is_league: boolean;
  is_finished: boolean;
  is_hidden: boolean;
  start_date: string;
  end_date: string;
  win_points: number;
  draw_points: number;
  loss_points: number;
  registration_opens_at: string;
  registration_closes_at: string;
  check_in_opens_at: string;
  check_in_closes_at: string;
  division_grid_version_id: number | null;
  team_formation: string;
};

export type TeamFormState = {
  name: string;
  captain_id: number;
};

export type EncounterFormState = {
  name: string;
  stage_id: number | null;
  stage_item_id: number | null;
  home_team_id: number | null;
  away_team_id: number | null;
  round: number;
  home_score: number;
  away_score: number;
  status: string;
};

export type StandingFormState = {
  position: number;
  points: number;
  win: number;
  draw: number;
  lose: number;
};

export type StandingSortKey = "position" | "team" | "scope" | "points" | "win" | "draw" | "lose";

export type StandingSortState = {
  key: StandingSortKey;
  dir: "asc" | "desc";
} | null;

export type StandingGroupOption = {
  id: string;
  name: string;
  stageOrder: number;
  itemOrder: number;
};

export type EncounterGroupOption = {
  id: string;
  name: string;
  stageOrder: number;
  itemOrder: number;
};

export type TournamentWorkspacePhase = {
  label: string;
  icon: LucideIcon;
  done: boolean;
  description: string;
  metrics: Array<{ label: string; value: string }>;
};

export const TOURNAMENT_DETAIL_PREVIEW_LIMIT = 8;

export function formatDate(value?: Date | string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleDateString();
}

export function toDateInput(value?: Date | string | null) {
  if (!value) return "";
  return new Date(value).toISOString().split("T")[0] ?? "";
}

export function toDateTimeInput(value?: Date | string | null) {
  if (!value) return "";
  return new Date(value).toISOString().slice(0, 16);
}

export function getTournamentForm(tournament: Tournament): TournamentFormState {
  return {
    number: tournament.number ?? null,
    name: tournament.name,
    description: tournament.description ?? "",
    challonge_slug: tournament.challonge_slug ?? "",
    is_league: tournament.is_league,
    is_finished: tournament.is_finished,
    is_hidden: tournament.is_hidden ?? false,
    start_date: toDateInput(tournament.start_date),
    end_date: toDateInput(tournament.end_date),
    win_points: tournament.win_points ?? 1,
    draw_points: tournament.draw_points ?? 0.5,
    loss_points: tournament.loss_points ?? 0,
    registration_opens_at: toDateTimeInput(tournament.registration_opens_at),
    registration_closes_at: toDateTimeInput(tournament.registration_closes_at),
    check_in_opens_at: toDateTimeInput(tournament.check_in_opens_at),
    check_in_closes_at: toDateTimeInput(tournament.check_in_closes_at),
    division_grid_version_id: tournament.division_grid_version_id ?? null,
    team_formation: tournament.team_formation ?? "balancer"
  };
}

export function getEmptyTeamForm(): TeamFormState {
  return {
    name: "",
    captain_id: 0
  };
}

export function getTeamForm(team: Team): TeamFormState {
  return {
    name: team.name,
    captain_id: team.captain_id
  };
}

export function getEmptyEncounterForm(
  defaultStageId: number | null,
  defaultStageItemId: number | null
): EncounterFormState {
  return {
    name: "",
    stage_id: defaultStageId,
    stage_item_id: defaultStageItemId,
    home_team_id: null,
    away_team_id: null,
    round: 1,
    home_score: 0,
    away_score: 0,
    status: "open"
  };
}

export function getEncounterForm(encounter: Encounter): EncounterFormState {
  return {
    name: encounter.name,
    stage_id: encounter.stage_id ?? null,
    stage_item_id: encounter.stage_item_id ?? null,
    home_team_id: encounter.home_team_id,
    away_team_id: encounter.away_team_id,
    round: encounter.round,
    home_score: encounter.score.home,
    away_score: encounter.score.away,
    status: encounter.status
  };
}

export function getStandingForm(standing: Standings): StandingFormState {
  return {
    position: standing.position,
    points: standing.points,
    win: standing.win,
    draw: standing.draw,
    lose: standing.lose
  };
}

export function getEncounterStageLabel(encounter: Encounter) {
  return encounter.stage_item?.name ?? encounter.stage?.name ?? "-";
}

export function getEncounterScopeKey(encounter: Encounter): string {
  if (encounter.stage_item_id != null) return `stage-item-${encounter.stage_item_id}`;
  if (encounter.stage_id != null) return `stage-${encounter.stage_id}`;
  return "unassigned";
}

export function getEncounterScopeLabel(encounter: Encounter): string {
  return encounter.stage_item?.name ?? encounter.stage?.name ?? "Unassigned";
}

export function getEncounterGroups(encounters: Encounter[]): EncounterGroupOption[] {
  return Array.from(
    new Map(
      encounters.map((encounter) => [
        getEncounterScopeKey(encounter),
        {
          id: getEncounterScopeKey(encounter),
          name: getEncounterScopeLabel(encounter),
          stageOrder: encounter.stage?.order ?? Number.MAX_SAFE_INTEGER,
          itemOrder: encounter.stage_item?.order ?? Number.MAX_SAFE_INTEGER
        }
      ])
    ).values()
  ).sort(
    (left, right) =>
      left.stageOrder - right.stageOrder ||
      left.itemOrder - right.itemOrder ||
      left.name.localeCompare(right.name)
  );
}

export function getStageScopeGroups(stages: Stage[]): EncounterGroupOption[] {
  return stages
    .flatMap((stage) => {
      if (stage.items.length === 0) {
        return [
          {
            id: `stage-${stage.id}`,
            name: stage.name,
            stageOrder: stage.order,
            itemOrder: Number.MAX_SAFE_INTEGER
          }
        ];
      }

      return stage.items.map((item) => ({
        id: `stage-item-${item.id}`,
        name: item.name,
        stageOrder: stage.order,
        itemOrder: item.order
      }));
    })
    .sort(
      (left, right) =>
        left.stageOrder - right.stageOrder ||
        left.itemOrder - right.itemOrder ||
        left.name.localeCompare(right.name)
    );
}

export function getStandingScopeKey(standing: Standings): string {
  if (standing.stage_item_id != null) return `stage-item-${standing.stage_item_id}`;
  if (standing.stage_id != null) return `stage-${standing.stage_id}`;
  return `standing-${standing.id}`;
}

export function getStandingScopeLabel(standing: Standings): string {
  return standing.stage_item?.name ?? standing.stage?.name ?? "-";
}

export function getStandingGroups(standings: Standings[]): StandingGroupOption[] {
  return Array.from(
    new Map(
      standings.map((standing) => [
        getStandingScopeKey(standing),
        {
          id: getStandingScopeKey(standing),
          name: getStandingScopeLabel(standing),
          stageOrder: standing.stage?.order ?? Number.MAX_SAFE_INTEGER,
          itemOrder: standing.stage_item?.order ?? Number.MAX_SAFE_INTEGER
        }
      ])
    ).values()
  ).sort(
    (left, right) =>
      left.stageOrder - right.stageOrder ||
      left.itemOrder - right.itemOrder ||
      left.name.localeCompare(right.name)
  );
}

export function sortStandings(standings: Standings[], sort: StandingSortState): Standings[] {
  if (!sort) return standings;

  const multiplier = sort.dir === "asc" ? 1 : -1;

  return standings.slice().sort((left, right) => {
    let result = 0;

    switch (sort.key) {
      case "position":
        result = left.position - right.position;
        break;
      case "team":
        result = (left.team?.name ?? "").localeCompare(right.team?.name ?? "");
        break;
      case "scope":
        result = getStandingScopeLabel(left).localeCompare(getStandingScopeLabel(right));
        break;
      case "points":
        result = left.points - right.points;
        break;
      case "win":
        result = left.win - right.win;
        break;
      case "draw":
        result = left.draw - right.draw;
        break;
      case "lose":
        result = left.lose - right.lose;
        break;
    }

    return result * multiplier;
  });
}

export function getTournamentWorkspacePhases(params: {
  stagesCount: number;
  teamsCount: number | null;
  encountersCount: number | null;
  standingsCount: number | null;
}): TournamentWorkspacePhase[] {
  const { stagesCount, teamsCount, encountersCount, standingsCount } = params;
  const teamsKnown = typeof teamsCount === "number";
  const encountersKnown = typeof encountersCount === "number";
  const standingsKnown = typeof standingsCount === "number";
  const teamsReady = teamsKnown && teamsCount > 0;
  const encountersReady = encountersKnown && encountersCount > 0;
  const standingsReady = standingsKnown && standingsCount > 0;
  const formatReadyMetric = (value: number | null) => {
    if (typeof value !== "number") {
      return "Loading";
    }

    return value > 0 ? `${value} ready` : "Missing";
  };
  const structureDescription = (() => {
    if (!teamsKnown) {
      return "Loading roster metrics before marking this phase complete.";
    }

    if (stagesCount > 0 && teamsReady) {
      return `${stagesCount} stages configured and ${teamsCount} teams loaded.`;
    }

    if (stagesCount === 0 && teamsCount === 0) {
      return "Create the tournament structure and add teams before scheduling play.";
    }

    return stagesCount === 0
      ? "Create at least one stage before continuing."
      : "Add or sync teams to complete the roster.";
  })();
  const playDescription = (() => {
    if (!encountersKnown || !standingsKnown) {
      return "Loading play and standings metrics before marking this phase complete.";
    }

    if (encountersReady && standingsReady) {
      return `${encountersCount} encounters tracked and standings available.`;
    }

    if (encountersCount === 0 && standingsCount === 0) {
      return "Create encounters first, then calculate standings once results exist.";
    }

    return encountersCount === 0
      ? "Schedule or sync encounters before calculating standings."
      : "Calculate standings after encounters have been completed.";
  })();

  return [
    {
      label: "Structure & roster",
      icon: Layers3,
      done: stagesCount > 0 && teamsReady,
      description: structureDescription,
      metrics: [
        { label: "Stages", value: stagesCount ? `${stagesCount} ready` : "Missing" },
        { label: "Teams", value: formatReadyMetric(teamsCount) }
      ]
    },
    {
      label: "Play & results",
      icon: Trophy,
      done: encountersReady && standingsReady,
      description: playDescription,
      metrics: [
        {
          label: "Encounters",
          value: formatReadyMetric(encountersCount)
        },
        {
          label: "Standings",
          value: formatReadyMetric(standingsCount)
        }
      ]
    }
  ];
}
