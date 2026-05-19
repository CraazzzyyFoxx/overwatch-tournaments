import type { ReactNode } from "react";
import { AlgorithmAnalytics, TournamentAnalyticsSummary } from "@/types/analytics.types";
import type { Tournament } from "@/types/tournament.types";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Card } from "@/components/ui/card";
import styles from "./AnalyticsRedesign.module.css";

interface AnalyticsHeroProps {
  tournaments: Tournament[];
  algorithms: AlgorithmAnalytics[];
  tournamentId: number | null;
  algorithmId: number | null;
  activeTournament: Tournament | null;
  activeAlgorithm: AlgorithmAnalytics | null;
  summary?: TournamentAnalyticsSummary;
  loadingTournaments: boolean;
  loadingAlgorithms: boolean;
  isErrorTournaments: boolean;
  isErrorAlgorithms: boolean;
  adminControls?: ReactNode;
  onTournamentChange: (value: string) => void;
  onAlgorithmChange: (value: string) => void;
}

const AnalyticsHero = ({
  tournaments,
  algorithms,
  tournamentId,
  algorithmId,
  activeTournament,
  activeAlgorithm,
  summary,
  loadingTournaments,
  loadingAlgorithms,
  isErrorTournaments,
  isErrorAlgorithms,
  adminControls,
  onTournamentChange,
  onAlgorithmChange
}: AnalyticsHeroProps) => {
  const totalTeams = summary?.total_teams ?? activeTournament?.participants_count ?? 0;
  const totalPlayers = summary?.total_players ?? 0;
  const status = activeTournament?.status ? activeTournament.status.replace(/_/g, " ") : "select context";

  return (
    <Card className="overflow-hidden">
      <div className={styles.heroGrid}>
        <div className={styles.heroTitle}>
          <div className={styles.eyebrow}>
            Analytics
            {activeTournament ? ` / Tournament #${activeTournament.id}` : ""}
          </div>
          <h1 className={styles.heroHeading}>
            {activeTournament?.name ?? "Tournament analytics"}
          </h1>
          <p className={styles.heroSub}>
            {totalTeams} teams
            {totalPlayers ? ` / ${totalPlayers} players` : ""}
            {activeAlgorithm ? (
              <>
                {" "}
                / ranked by <span className="font-semibold text-foreground">{activeAlgorithm.name}</span>
              </>
            ) : null}
          </p>
          <div className={styles.statusPill}>
            <span className={styles.statusDot} />
            <span className="capitalize">{status}</span>
          </div>
        </div>

        <div className={styles.filters}>
          <div className={styles.field}>
            <div className={styles.label}>Tournament</div>
            <Select
              value={tournamentId == null ? "" : tournamentId.toString()}
              onValueChange={onTournamentChange}
              disabled={loadingTournaments || isErrorTournaments}
            >
              <SelectTrigger aria-label="Tournament" className="h-11">
                <SelectValue
                  placeholder={
                    loadingTournaments
                      ? "Loading tournaments..."
                      : isErrorTournaments
                        ? "Failed to load tournaments"
                        : "Select a tournament"
                  }
                />
              </SelectTrigger>
              <SelectContent className="max-h-[min(var(--radix-select-content-available-height),20rem)]">
                <SelectGroup>
                  {tournaments.map((item) => (
                    <SelectItem key={item.id} value={item.id.toString()}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>

          <div className={styles.field}>
            <div className={styles.label}>Algorithm</div>
            <Select
              value={algorithmId == null ? "" : algorithmId.toString()}
              onValueChange={onAlgorithmChange}
              disabled={loadingAlgorithms || isErrorAlgorithms}
            >
              <SelectTrigger aria-label="Algorithm" className="h-11">
                <SelectValue
                  placeholder={
                    loadingAlgorithms
                      ? "Loading algorithms..."
                      : isErrorAlgorithms
                        ? "Failed to load algorithms"
                        : "Select an algorithm"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {algorithms.map((item) => (
                    <SelectItem key={item.id} value={item.id.toString()}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>

          {adminControls ? <div className={styles.actions}>{adminControls}</div> : null}
        </div>
      </div>
    </Card>
  );
};

export default AnalyticsHero;
