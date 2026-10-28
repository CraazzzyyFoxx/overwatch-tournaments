"use client";

import { useMemo } from "react";
import { ChevronLeft } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useQueryParams } from "@/hooks/useQueryParams";
import type { RoleOntology } from "@/lib/roster/ontology";
import type { PerformanceV2, StandingsDistribution } from "@/types/analytics.types";
import type { GlossaryTerm } from "@/disciplines/overwatch/analytics/analytics-glossary";
import type { TeamVM } from "@/disciplines/overwatch/analytics/useAnalyticsViewModel";
import { useMasterDetailSelection } from "@/disciplines/overwatch/analytics/useMasterDetailSelection";

import AnalyticsStandings from "./AnalyticsStandings";
import MatchQualityCard from "./MatchQualityCard";
import PlayerDetail from "./community/PlayerDetail";
import TeamDetail from "./community/TeamDetail";
import StandingsList, { type StandingsMode } from "./StandingsList";

interface MasterDetailProps {
  tournamentId: number;
  teams: TeamVM[];
  canReadV2: boolean;
  /** The tournament has ended: places 1–3 are medals. */
  ended: boolean;
  /** The teams span several groups, so rows carry their group chip. */
  showGroups: boolean;
  mode: StandingsMode;
  onModeChange: (mode: StandingsMode) => void;
  performanceByPlayer: Map<number, PerformanceV2>;
  distributionByTeam?: Map<number, StandingsDistribution>;
  /** The tournament's own role dictionary (its game's metadata), for player role names and glyphs. */
  ontology: RoleOntology;
  onExplain: (term: GlossaryTerm) => void;
}

type StandingsView = "list" | "table";

/** The split's breakpoint (`lg`): below it the list and the panels take turns. */
const DESKTOP_QUERY = "(min-width: 1024px)";

/**
 * The single team spine: the standings list beside a sticky team/player panel
 * (desktop) or taking turns with it (mobile push-nav). A List / Table switch,
 * kept in `?view=` like a tournament section's view, swaps the list for the
 * dense per-player table. Organizer-only depth (match quality, the v2 columns,
 * Monte-Carlo) is woven in where the viewer has `analytics.read`. Selection
 * resets when the parent re-keys on a tournament or ranking switch.
 */
export default function MasterDetail({
  tournamentId,
  teams,
  canReadV2,
  ended,
  showGroups,
  mode,
  onModeChange,
  performanceByPlayer,
  distributionByTeam,
  ontology,
  onExplain
}: Readonly<MasterDetailProps>) {
  const t = useTranslations();
  // Desktop-first: the server render and the first client render agree on the common case.
  const isDesktop = useMediaQuery(DESKTOP_QUERY, true);
  // Client-only state: the History API, not a server round trip; the default is never written.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [], shallow: true });
  const view: StandingsView = searchParams?.get("view") === "table" ? "table" : "list";
  const selection = useMasterDetailSelection(teams[0]?.id ?? null);
  const teamById = (id: number | null) => (id == null ? null : (teams.find((team) => team.id === id) ?? null));
  const playerNames = useMemo(
    () => new Map(teams.flatMap((team) => team.players.map((player) => [player.id, player.name] as const))),
    [teams]
  );

  const viewToggle = (
    <ToggleGroup
      variant="pill"
      size="sm"
      value={view}
      onValueChange={(next) => {
        if (next) setParams({ view: next === "list" ? null : next });
      }}
      aria-label={t("analytics.community.standings.viewLabel")}
    >
      <ToggleGroupItem value="list">{t("analytics.community.standings.viewList")}</ToggleGroupItem>
      <ToggleGroupItem value="table">{t("analytics.community.standings.viewTable")}</ToggleGroupItem>
    </ToggleGroup>
  );

  if (view === "table") {
    return (
      <div className="flex flex-col gap-6">
        <AnalyticsStandings
          teams={teams}
          performanceByPlayer={performanceByPlayer}
          distributionByTeam={distributionByTeam}
          ontology={ontology}
          canReadV2={canReadV2}
          ended={ended}
          onExplain={onExplain}
          headerEnd={viewToggle}
        />
        {canReadV2 ? (
          <MatchQualityCard tournamentId={tournamentId} onExplain={onExplain} playerNames={playerNames} />
        ) : null}
      </div>
    );
  }

  const list = (
    <StandingsList
      teams={teams}
      selectedTeamId={isDesktop ? selection.selectedTeamId : null}
      onSelectTeam={selection.selectTeam}
      mode={mode}
      onModeChange={onModeChange}
      ended={ended}
      showGroups={showGroups}
      headerEnd={viewToggle}
    />
  );

  const renderTeam = (team: TeamVM) => (
    <TeamDetail
      key={`team-${team.id}`}
      team={team}
      distribution={canReadV2 ? distributionByTeam?.get(team.id) : undefined}
      ontology={ontology}
      showGroup={showGroups}
      onSelectPlayer={(playerId) => selection.selectPlayer(team.id, playerId)}
      onExplain={onExplain}
    />
  );

  const renderPlayer = (team: TeamVM, playerId: number) => {
    const player = team.players.find((candidate) => candidate.id === playerId);
    if (!player) return renderTeam(team);
    return (
      <PlayerDetail
        key={`player-${player.id}`}
        player={player}
        teamName={team.name}
        tournamentGrid={team.tournament?.division_grid_version}
        ontology={ontology}
        canReadV2={canReadV2}
        onExplain={onExplain}
      />
    );
  };

  const back = (label: string, onClick: () => void) => (
    <Button type="button" variant="ghost" size="sm" onClick={onClick} className="-ml-2 self-start">
      <ChevronLeft aria-hidden />
      {label}
    </Button>
  );

  // ── Mobile: one column, list → team → player, each with its way back ──
  if (!isDesktop) {
    const current = selection.current;
    const team = current.kind === "overview" ? null : teamById(current.teamId);
    if (!team || current.kind === "overview") return list;
    return (
      <div className="flex flex-col gap-3">
        {current.kind === "player"
          ? back(t("analytics.community.player.backTo", { team: team.name }), selection.back)
          : back(t("analytics.community.standings.title"), selection.back)}
        {current.kind === "player" ? renderPlayer(team, current.playerId) : renderTeam(team)}
      </div>
    );
  }

  // ── Desktop: the list beside a sticky panel ──
  const selectedTeam = teamById(selection.selectedTeamId);
  const selectedPlayer =
    selectedTeam && selection.selectedPlayerId != null
      ? (selectedTeam.players.find((player) => player.id === selection.selectedPlayerId) ?? null)
      : null;

  return (
    // The panel takes ~40% of the row (never under 21rem): a roster line keeps its nick, flag and move on one line.
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(21rem,1fr)]">
      {list}
      {/* Sticky under the site header; scrolls inside itself when a player's panel outgrows the window. */}
      <aside className="flex flex-col gap-3 lg:sticky lg:top-20 lg:max-h-[calc(100dvh-6rem)] lg:overflow-y-auto">
        {selectedPlayer && selectedTeam ? (
          <>
            {back(t("analytics.community.player.backTo", { team: selectedTeam.name }), () =>
              selection.selectTeam(selectedTeam.id)
            )}
            {renderPlayer(selectedTeam, selectedPlayer.id)}
          </>
        ) : selectedTeam ? (
          renderTeam(selectedTeam)
        ) : (
          <p className="text-caption text-[color:var(--aqt-fg-muted)]">{t("analytics.community.team.pickPrompt")}</p>
        )}
      </aside>
    </div>
  );
}
