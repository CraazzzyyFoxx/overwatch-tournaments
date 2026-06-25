"use client";

import React, { useEffect, useState } from "react";
import { ChevronLeft } from "lucide-react";

import { useTranslation } from "@/i18n/LanguageContext";
import { PerformanceV2, StandingsDistribution } from "@/types/analytics.types";
import { TeamVM } from "@/app/(site)/tournaments/analytics/useAnalyticsViewModel";
import { useMasterDetailSelection } from "@/app/(site)/tournaments/analytics/useMasterDetailSelection";
import { GlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";
import StandingsList, {
  type StandingsMode,
} from "@/app/(site)/tournaments/analytics/components/StandingsList";
import AnalyticsStandings from "@/app/(site)/tournaments/analytics/components/AnalyticsStandings";
import MatchQualityCard from "@/app/(site)/tournaments/analytics/components/MatchQualityCard";
import TeamDetail from "@/app/(site)/tournaments/analytics/components/community/TeamDetail";
import PlayerDetail from "@/app/(site)/tournaments/analytics/components/community/PlayerDetail";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface MasterDetailProps {
  tournamentId: number;
  teams: TeamVM[];
  canReadV2?: boolean;
  mode: StandingsMode;
  onModeChange: (mode: StandingsMode) => void;
  performanceByPlayer: Map<number, PerformanceV2>;
  distributionByTeam?: Map<number, StandingsDistribution>;
  onExplain?: (term: GlossaryTerm) => void;
}

/** Desktop-first media query (avoids a hydration mismatch by defaulting true). */
function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(true);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const sync = () => setMatches(mql.matches);
    sync();
    mql.addEventListener("change", sync);
    return () => mql.removeEventListener("change", sync);
  }, [query]);
  return matches;
}

/**
 * The single team spine: a community standings list beside a sticky detail
 * aside (desktop) / push-nav stack (mobile). A public "List | Table" toggle —
 * sitting on each view's sort-tab row — swaps the community list for the dense
 * per-player table. Organizer-only depth (match quality, the v2 impact / vs-local
 * / Monte-Carlo columns) is woven in where the viewer has `analytics.read`.
 * Selection resets when the parent re-keys on tournament switch.
 */
export default function MasterDetail({
  tournamentId,
  teams,
  canReadV2,
  mode,
  onModeChange,
  performanceByPlayer,
  distributionByTeam,
  onExplain,
}: MasterDetailProps) {
  const { t } = useTranslation();
  const isDesktop = useMediaQuery("(min-width: 860px)");
  const [view, setView] = useState<"list" | "table">("list");
  const defaultTeamId = teams[0]?.id ?? null;
  const selection = useMasterDetailSelection(defaultTeamId);

  const teamById = (id: number | null) =>
    id == null ? null : teams.find((team) => team.id === id) ?? null;

  // The list/table view toggle is public — it rides the right edge of each
  // view's sort-tab row (passed in as `headerEnd`).
  const viewToggle = (
    <div className={styles.cViewToggle} role="tablist">
      <button
        type="button"
        role="tab"
        aria-selected={view === "list"}
        data-on={view === "list"}
        className={styles.cSegBtn}
        onClick={() => setView("list")}
      >
        {t("analytics.community.standings.viewList")}
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={view === "table"}
        data-on={view === "table"}
        className={styles.cSegBtn}
        onClick={() => setView("table")}
      >
        {t("analytics.community.standings.viewTable")}
      </button>
    </div>
  );

  // ── Table view: the dense per-player table (public). Match quality stays
  //    organizer-only — its data is permission-gated server-side. ──
  if (view === "table") {
    return (
      <div className={styles.cColMain}>
        <AnalyticsStandings
          teams={teams}
          performanceByPlayer={performanceByPlayer}
          distributionByTeam={distributionByTeam}
          headerEnd={viewToggle}
        />
        {canReadV2 ? <MatchQualityCard tournamentId={tournamentId} /> : null}
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
      headerEnd={viewToggle}
    />
  );

  const renderTeam = (team: TeamVM) => (
    <TeamDetail
      key={`team-${team.id}`}
      team={team}
      distribution={canReadV2 ? distributionByTeam?.get(team.id) : undefined}
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
        canReadV2={canReadV2}
        onExplain={onExplain}
      />
    );
  };

  // ── Mobile: single-column push-nav driven by the selection stack ──
  if (!isDesktop) {
    const current = selection.current;
    if (current.kind === "overview") {
      return <div className={styles.cColMain}>{list}</div>;
    }
    const team = teamById(current.teamId);
    if (!team) return <div className={styles.cColMain}>{list}</div>;
    return (
      <div className={styles.cColMain}>
        <button type="button" className={styles.cAsideBack} onClick={selection.back}>
          <ChevronLeft size={14} aria-hidden="true" />
          {current.kind === "player"
            ? t("analytics.community.player.backTo", { team: team.name })
            : t("analytics.community.standings.title")}
        </button>
        {current.kind === "player" ? renderPlayer(team, current.playerId) : renderTeam(team)}
      </div>
    );
  }

  // ── Desktop: list beside a sticky detail aside ──
  const selectedTeam = teamById(selection.selectedTeamId);
  const selectedPlayer =
    selectedTeam && selection.selectedPlayerId != null
      ? selectedTeam.players.find((player) => player.id === selection.selectedPlayerId) ?? null
      : null;

  return (
    <div className={styles.cMasterDetail}>
      <div className={styles.cColMain}>{list}</div>
      <aside className={styles.cAside}>
        {selectedPlayer && selectedTeam ? (
          <>
            <button
              type="button"
              className={styles.cAsideBack}
              onClick={() => selection.selectTeam(selectedTeam.id)}
            >
              <ChevronLeft size={14} aria-hidden="true" />
              {t("analytics.community.player.backTo", { team: selectedTeam.name })}
            </button>
            {renderPlayer(selectedTeam, selectedPlayer.id)}
          </>
        ) : selectedTeam ? (
          renderTeam(selectedTeam)
        ) : (
          <div className={styles.cAsideEmpty}>{t("analytics.community.team.pickPrompt")}</div>
        )}
      </aside>
    </div>
  );
}
