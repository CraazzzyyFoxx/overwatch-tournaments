import { TeamAnalytics, TournamentAnalyticsSummary } from "@/types/analytics.types";
import { formatAnalyticsNumber, formatConfidencePercent } from "@/app/(site)/tournaments/analytics/analytics.helpers";
import styles from "./AnalyticsRedesign.module.css";

interface AnalyticsKpiStripProps {
  summary: TournamentAnalyticsSummary;
  teams: TeamAnalytics[];
}

const MiniSpark = ({ tone = "positive" }: { tone?: "positive" | "negative" | "warn" }) => {
  const points = [4, 7, 5, 9, 7, 11, 9, 13, 12, 14];
  const max = 16;
  const width = 50;
  const height = 22;
  const step = width / (points.length - 1);
  const path = points.map((point, index) => `${index ? "L" : "M"} ${index * step},${height - (point / max) * height}`).join(" ");
  const stroke = tone === "negative" ? "hsl(2 75% 60%)" : tone === "warn" ? "hsl(38 92% 60%)" : "hsl(146 60% 52%)";

  return (
    <svg className="h-[22px] w-[50px]" viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <path d={path} fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
};

const AnalyticsKpiStrip = ({ summary, teams }: AnalyticsKpiStripProps) => {
  const predictedMoves = teams.reduce(
    (total, team) => total + team.players.filter((player) => player.predicted_direction !== "flat").length,
    0
  );
  const promotions = teams.reduce(
    (total, team) => total + team.players.filter((player) => player.predicted_direction === "promote").length,
    0
  );
  const demotions = predictedMoves - promotions;
  const totalShift = teams.reduce((sum, team) => sum + Math.abs(team.total_shift), 0);

  return (
    <div className={styles.kpis}>
      <div className={styles.kpi}>
        <div className={styles.kpiLabel}>Teams</div>
        <div className={styles.kpiValue}>{summary.total_teams}</div>
        <div className={styles.kpiFoot}>{summary.total_players} players</div>
      </div>

      <div className={styles.kpi}>
        <div className={styles.kpiLabel}>Predicted moves</div>
        <div className={styles.kpiValue}>{predictedMoves}</div>
        <div className={styles.kpiFoot}>
          <span className={styles.trendPositive}>{promotions} up</span> /{" "}
          <span className={styles.trendNegative}>{demotions} down</span>
        </div>
      </div>

      <div className={styles.kpi}>
        <div className={styles.kpiLabel}>Avg confidence</div>
        <div className={styles.kpiValue}>
          {formatConfidencePercent(summary.avg_confidence)}
          <MiniSpark />
        </div>
        <div className={styles.kpiFoot}>{summary.newcomer_count} new or new-role players</div>
      </div>

      <div className={styles.kpi}>
        <div className={styles.kpiLabel}>Prediction miss</div>
        <div className={styles.kpiValue}>{formatAnalyticsNumber(summary.avg_placement_delta, 1)}</div>
        <div className={styles.kpiFoot}>{summary.divergent_team_count} teams off by 4+ places</div>
      </div>

      <div className={styles.kpi}>
        <div className={styles.kpiLabel}>Anomaly flags</div>
        <div className={styles.kpiValue}>
          {summary.anomaly_count}
          <MiniSpark tone={summary.anomaly_count ? "warn" : "positive"} />
        </div>
        <div className={styles.kpiFoot}>from match quality inference</div>
      </div>

      <div className={styles.kpi}>
        <div className={styles.kpiLabel}>Total shift</div>
        <div className={styles.kpiValue}>{formatAnalyticsNumber(totalShift, 1)}</div>
        <div className={styles.kpiFoot}>{summary.manual_shift_team_count} teams with manual input</div>
      </div>
    </div>
  );
};

export default AnalyticsKpiStrip;
