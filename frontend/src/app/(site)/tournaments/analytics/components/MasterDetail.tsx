"use client";

import React, { useEffect, useState } from "react";
import { ChevronLeft } from "lucide-react";

import { useTranslation } from "@/i18n/LanguageContext";
import { TeamVM } from "@/app/(site)/tournaments/analytics/useAnalyticsViewModel";
import { useMasterDetailSelection } from "@/app/(site)/tournaments/analytics/useMasterDetailSelection";
import { GlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";
import StandingsList from "@/app/(site)/tournaments/analytics/components/StandingsList";
import TeamDetail from "@/app/(site)/tournaments/analytics/components/community/TeamDetail";
import PlayerDetail from "@/app/(site)/tournaments/analytics/components/community/PlayerDetail";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface MasterDetailProps {
  teams: TeamVM[];
  algorithmName?: string | null;
  canReadV2?: boolean;
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
 * Standings list + team/player drill-down. Desktop shows the list beside a
 * sticky detail aside; mobile turns the same selection reducer into a push-nav
 * stack (standings → team → player) with a back button. Selection resets when
 * the parent re-keys on tournament switch.
 */
export default function MasterDetail({
  teams,
  algorithmName,
  canReadV2,
  onExplain,
}: MasterDetailProps) {
  const { t } = useTranslation();
  const isDesktop = useMediaQuery("(min-width: 860px)");
  const defaultTeamId = teams[0]?.id ?? null;
  const selection = useMasterDetailSelection(defaultTeamId);

  const teamById = (id: number | null) => (id == null ? null : teams.find((team) => team.id === id) ?? null);

  const list = (
    <StandingsList
      teams={teams}
      algorithmName={algorithmName}
      selectedTeamId={isDesktop ? selection.selectedTeamId : null}
      onSelectTeam={selection.selectTeam}
    />
  );

  const renderTeam = (team: TeamVM) => (
    <TeamDetail
      key={`team-${team.id}`}
      team={team}
      totalTeams={teams.length}
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
    const view = selection.current;
    if (view.kind === "overview") {
      return <div className={styles.cColMain}>{list}</div>;
    }
    const team = teamById(view.teamId);
    if (!team) return <div className={styles.cColMain}>{list}</div>;
    return (
      <div className={styles.cColMain}>
        <button type="button" className={styles.cAsideBack} onClick={selection.back}>
          <ChevronLeft size={14} aria-hidden="true" />
          {view.kind === "player"
            ? t("analytics.community.player.backTo", { team: team.name })
            : t("analytics.community.standings.title")}
        </button>
        {view.kind === "player" ? renderPlayer(team, view.playerId) : renderTeam(team)}
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
