import { AnalyticsAnomaly, PlayerAnalytics, TeamAnalytics } from "@/types/analytics.types";
import type { ReactNode } from "react";
import { formatAnalyticsNumber } from "@/app/(site)/tournaments/analytics/analytics.helpers";
import DivisionIcon from "@/components/DivisionIcon";
import { Card } from "@/components/ui/card";
import styles from "./AnalyticsRedesign.module.css";

interface AnalyticsInsightsProps {
  teams: TeamAnalytics[];
}

type PlayerWithTeam = PlayerAnalytics & { teamName: string };

const anomalyHue: Record<string, string> = {
  smurf: "350 84% 65%",
  troll: "38 92% 60%",
  throw: "2 75% 62%",
  sandbag: "275 72% 68%"
};

const InsightShell = ({
  title,
  count,
  children
}: {
  title: string;
  count?: number;
  children: ReactNode;
}) => (
  <div className={styles.insight}>
    <div className={styles.insightHead}>
      <span className={styles.insightTitle}>{title}</span>
      {count != null ? <span className={styles.insightCount}>{count}</span> : null}
    </div>
    <div className={styles.insightList}>{children}</div>
  </div>
);

const EmptyInsight = ({ children }: { children: ReactNode }) => (
  <div className="text-sm text-muted-foreground">{children}</div>
);

const AnomalyMarker = ({ anomaly }: { anomaly: AnalyticsAnomaly }) => (
  <span
    className={styles.chipDot}
    style={{ background: `hsl(${anomalyHue[anomaly.kind] ?? "199 90% 60%"})` }}
  />
);

const MoveItem = ({ player }: { player: PlayerWithTeam }) => (
  <div className={styles.insightItem}>
    {player.predicted_division != null ? (
      <DivisionIcon division={player.predicted_division} width={28} height={28} />
    ) : null}
    <span className={styles.insightWho} title={player.name}>
      {player.name}
    </span>
    <span className={styles.insightMeta}>{player.teamName}</span>
  </div>
);

const AnalyticsInsights = ({ teams }: AnalyticsInsightsProps) => {
  const players: PlayerWithTeam[] = teams.flatMap((team) =>
    team.players.map((player) => ({ ...player, teamName: team.name }))
  );
  const promotions = players
    .filter((player) => player.predicted_direction === "promote")
    .sort((left, right) => Math.abs(right.predicted_delta) - Math.abs(left.predicted_delta))
    .slice(0, 4);
  const demotions = players
    .filter((player) => player.predicted_direction === "demote")
    .sort((left, right) => Math.abs(right.predicted_delta) - Math.abs(left.predicted_delta))
    .slice(0, 4);
  const divergent = [...teams]
    .filter((team) => team.placement_delta != null)
    .sort((left, right) => Math.abs(right.placement_delta ?? 0) - Math.abs(left.placement_delta ?? 0))
    .slice(0, 4);
  const anomalies = teams.flatMap((team) =>
    team.anomalies.map((anomaly) => ({ ...anomaly, teamName: team.name }))
  );
  const newcomers = players
    .filter((player) => player.is_newcomer || player.is_newcomer_role)
    .slice(0, 4);

  return (
    <Card className="overflow-hidden">
      <div className={styles.insights}>
        <InsightShell title="Promotions" count={promotions.length}>
          {promotions.length ? (
            promotions.map((player) => <MoveItem key={`promote-${player.id}`} player={player} />)
          ) : (
            <EmptyInsight>No promotions predicted.</EmptyInsight>
          )}
        </InsightShell>

        <InsightShell title="Demotions" count={demotions.length}>
          {demotions.length ? (
            demotions.map((player) => <MoveItem key={`demote-${player.id}`} player={player} />)
          ) : (
            <EmptyInsight>No demotions predicted.</EmptyInsight>
          )}
        </InsightShell>

        <InsightShell title="Predicted vs actual" count={divergent.length}>
          {divergent.length ? (
            divergent.map((team) => (
              <div key={team.id} className={styles.insightItem}>
                <span className={styles.insightWho} title={team.name}>
                  {team.name}
                </span>
                <span className={styles.insightMeta}>
                  predicted {team.predicted_place ?? "-"} / finished {team.placement ?? "-"}
                </span>
              </div>
            ))
          ) : (
            <EmptyInsight>No large placement deltas.</EmptyInsight>
          )}
        </InsightShell>

        <InsightShell title="Anomalies" count={anomalies.length}>
          {anomalies.length ? (
            anomalies.slice(0, 5).map((anomaly, index) => (
              <div key={`${anomaly.player_id}-${anomaly.kind}-${index}`} className={styles.insightItem}>
                <AnomalyMarker anomaly={anomaly} />
                <span className={styles.insightWho}>{anomaly.kind}</span>
                <span className={styles.insightMeta}>
                  {anomaly.teamName} / {formatAnalyticsNumber(anomaly.score, 2)}
                </span>
              </div>
            ))
          ) : (
            <EmptyInsight>None flagged.</EmptyInsight>
          )}
        </InsightShell>

        <InsightShell title="Newcomers" count={newcomers.length}>
          {newcomers.length ? (
            newcomers.map((player) => (
              <div key={`new-${player.id}`} className={styles.insightItem}>
                <span className={styles.chipDot} />
                <span className={styles.insightWho} title={player.name}>
                  {player.name}
                </span>
                <span className={styles.insightMeta}>{player.is_newcomer ? "new" : "new role"}</span>
              </div>
            ))
          ) : (
            <EmptyInsight>No new players.</EmptyInsight>
          )}
        </InsightShell>
      </div>
    </Card>
  );
};

export default AnalyticsInsights;
