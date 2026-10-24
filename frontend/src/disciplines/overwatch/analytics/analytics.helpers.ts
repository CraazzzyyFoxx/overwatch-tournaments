import {
  AlgorithmAnalytics,
  PerformanceV2,
  TeamAnalytics,
  TournamentAnalyticsSummary,
} from "@/types/analytics.types";
import { GlossaryTerm } from "@/disciplines/overwatch/analytics/analytics-glossary";

const RECOMMENDED_ALGORITHM_ORDER = [
  "Linear",
  "Points",
  "OpenSkill",
  "OpenSkill + ML",
] as const;

// The ML shift algorithm is preferred as the default *when it has data* for the
// tournament — it consumes Performance v2 and is the richest signal. Until a v2
// inference run populates it, the display/fallback order above still applies.
const PREFERRED_ML_ALGORITHM_NAME = "OpenSkill + ML";

const algorithmPriority = new Map<string, number>(
  RECOMMENDED_ALGORITHM_ORDER.map((name, index) => [name, index]),
);

export function sortAnalyticsAlgorithms(
  algorithms: AlgorithmAnalytics[],
): AlgorithmAnalytics[] {
  return [...algorithms].sort((left, right) => {
    const leftPriority = algorithmPriority.get(left.name) ?? Number.MAX_SAFE_INTEGER;
    const rightPriority = algorithmPriority.get(right.name) ?? Number.MAX_SAFE_INTEGER;

    if (leftPriority !== rightPriority) {
      return leftPriority - rightPriority;
    }

    return left.name.localeCompare(right.name) || left.id - right.id;
  });
}

export function getPreferredAnalyticsAlgorithmId(
  algorithms: AlgorithmAnalytics[],
): number | null {
  // Prefer the ML shift algorithm when it has computed data for the tournament;
  // otherwise fall back to the recommended display order (Linear › Points › OpenSkill › ML).
  const mlWithData = algorithms.find(
    (algorithm) => algorithm.name === PREFERRED_ML_ALGORITHM_NAME && algorithm.has_data === true,
  );
  if (mlWithData) {
    return mlWithData.id;
  }
  return sortAnalyticsAlgorithms(algorithms)[0]?.id ?? null;
}

export function canShowAnalyticsAdminToolbar(
  canUpdateAnalytics: boolean,
): boolean {
  return canUpdateAnalytics;
}

export function getAnalyticsRefreshKeys(
  workspaceId: number | null | undefined,
  tournamentId: number,
  algorithmId: number | null,
): Array<Array<string | number>> {
  const scope = workspaceId ?? "global";
  const keys: Array<Array<string | number>> = [["analytics", scope, tournamentId]];

  if (algorithmId != null) {
    keys.push(["analytics", scope, tournamentId, algorithmId]);
  }

  return keys;
}

function clampConfidence(confidence: number): number {
  return Math.max(0, Math.min(1, confidence));
}

export type ConfidenceTone = "high" | "medium" | "low";

/**
 * Plain-language confidence so the read view never shows a bare 0–1 number.
 */
export function confidenceWord(confidence: number): { label: string; tone: ConfidenceTone } {
  const clamped = clampConfidence(confidence);
  if (clamped >= 0.75) return { label: "High", tone: "high" };
  if (clamped >= 0.45) return { label: "Medium", tone: "medium" };
  return { label: "Low", tone: "low" };
}

interface VerdictClause {
  /** i18n key under the `analytics.verdict` namespace. */
  key: string;
  params: Record<string, string | number>;
  tone?: "warn";
}

export interface AnalyticsVerdict {
  headlineParams: { teams: number; players: number };
  clauses: VerdictClause[];
}

type VerdictSummary = Pick<
  TournamentAnalyticsSummary,
  | "total_teams"
  | "total_players"
  | "anomaly_count"
  | "divergent_team_count"
  | "newcomer_count"
  | "avg_placement_delta"
>;

/**
 * Turn the raw summary counters into a one-glance briefing: a headline
 * (teams/players) plus only the supporting clauses that actually apply, ending
 * with a calm forecast-accuracy note. Returns i18n keys + params (not rendered
 * text) so the component translates them; optional clauses are omitted when
 * zero so a quiet tournament reads as quiet.
 */
export function buildVerdict(
  summary: VerdictSummary,
  predictedMoves: number,
): AnalyticsVerdict {
  const clauses: VerdictClause[] = [];
  if (predictedMoves > 0) {
    clauses.push({ key: "analytics.verdict.moves", params: { count: predictedMoves } });
  }
  if (summary.anomaly_count > 0) {
    clauses.push({
      key: "analytics.verdict.flags",
      params: { count: summary.anomaly_count },
      tone: "warn",
    });
  }
  if (summary.divergent_team_count > 0) {
    clauses.push({
      key: "analytics.verdict.misses",
      params: { count: summary.divergent_team_count },
    });
  }
  if (summary.newcomer_count > 0) {
    clauses.push({ key: "analytics.verdict.newcomers", params: { count: summary.newcomer_count } });
  }
  clauses.push({
    key: "analytics.verdict.forecast",
    params: { delta: (summary.avg_placement_delta ?? 0).toFixed(1) },
  });

  return {
    headlineParams: { teams: summary.total_teams, players: summary.total_players },
    clauses,
  };
}

export function formatConfidencePercent(confidence: number): string {
  return `${Math.round(clampConfidence(confidence) * 100)}%`;
}

export function formatAnalyticsNumber(
  value: number | null | undefined,
  fractionDigits = 2,
): string {
  if (value == null || Number.isNaN(value)) {
    return "0";
  }

  // Round to ``fractionDigits`` then drop trailing zeros — but only in the
  // FRACTIONAL part. ``Number(...).toString()`` does exactly that without the
  // old ``/\.?0+$/`` regex bug, which also stripped trailing zeros from whole
  // numbers (e.g. "100" -> "1") when ``fractionDigits`` was 0.
  const rounded = String(Number(value.toFixed(fractionDigits)));
  if (rounded === "-0") {
    return "0";
  }

  return rounded;
}

// ────────────────────────────────────────────────────────────────────────────
// Community layer — fan-facing derivations shared by the redesigned page.
// Pure functions only (no i18n / React) so they stay unit-testable; components
// translate the returned keys/ids.
// ────────────────────────────────────────────────────────────────────────────

/**
 * The real v2 `impact_score` (0–100 percentile within tournament+role) when the viewer may read it and a row
 * exists; otherwise none — impact is never derived from the shift.
 */
export function resolveImpact(
  perf: Pick<PerformanceV2, "impact_score"> | undefined,
  canReadV2: boolean,
): number | null {
  if (canReadV2 && perf && Number.isFinite(perf.impact_score)) {
    return Math.max(0, Math.min(100, Math.round(perf.impact_score)));
  }
  return null;
}

const ORDINAL_SUFFIX_RULES = new Intl.PluralRules("en-US", { type: "ordinal" });
const ORDINAL_SUFFIXES: Record<Intl.LDMLPluralRule, string> = {
  zero: "th",
  one: "st",
  two: "nd",
  few: "rd",
  many: "th",
  other: "th",
};

/** English ordinal ("1st", "2nd", "13th") for compact rank displays. */
export function ordinal(n: number): string {
  if (!Number.isFinite(n)) return String(n);
  const suffix = ORDINAL_SUFFIXES[ORDINAL_SUFFIX_RULES.select(n)] ?? "th";
  return `${n}${suffix}`;
}

/**
 * Locale-aware place formatter the community components feed into the `{place}`
 * / `{predicted}` translation slots: English shows an ordinal ("3rd"), Russian
 * keeps a bare number (the RU copy supplies the surrounding "№"/"место"). Null
 * places render as an em dash.
 */
export function formatPlace(n: number | null | undefined, locale: "en" | "ru"): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return locale === "en" ? ordinal(n) : String(n);
}

/**
 * Sort key for the standings order: the actual place once the bracket has been
 * played, the forecast while it has not, unrated teams last. Without the
 * fallback an unplayed tournament has no places at all and the standings
 * collapse to alphabetical order instead of showing the predicted finish.
 */
export function standingsRank(
  team: Pick<TeamAnalytics, "placement" | "predicted_place">,
): number {
  return team.placement ?? team.predicted_place ?? Number.MAX_SAFE_INTEGER;
}

interface VerdictTeam {
  id: number;
  name: string;
  /** Actual finishing place (standings). */
  place: number | null;
  /** Model's pre-bracket predicted place. */
  predicted: number | null;
  /** predicted_place − actual_place; positive = finished better than forecast. */
  delta: number;
}

export interface CommunityVerdict {
  /** Team that beat its forecast by the most (delta > 0). */
  story?: VerdictTeam;
  /** Team that fell short of its forecast by the most (delta < 0). */
  letdown?: VerdictTeam;
}

type VerdictTeamSource = Pick<
  TeamAnalytics,
  "id" | "name" | "placement" | "predicted_place" | "placement_delta"
>;

/**
 * The headline "who's the story / who's the let-down" of the bracket: the
 * teams with the largest positive and negative placement deltas. Only returns
 * a side when there is a genuine surprise (delta ≠ 0), and never names the same
 * team for both.
 */
export function buildCommunityVerdict(teams: VerdictTeamSource[]): CommunityVerdict {
  const rated = teams
    .filter((team) => team.placement_delta != null)
    .map<VerdictTeam>((team) => ({
      id: team.id,
      name: team.name,
      place: team.placement,
      predicted: team.predicted_place,
      delta: team.placement_delta as number,
    }));

  if (rated.length === 0) return {};

  const story = rated.reduce((best, team) => (team.delta > best.delta ? team : best), rated[0]);
  const letdown = rated.reduce((worst, team) => (team.delta < worst.delta ? team : worst), rated[0]);

  return {
    story: story.delta > 0 ? story : undefined,
    letdown: letdown.delta < 0 && letdown.id !== story.id ? letdown : undefined,
  };
}

export type KpiTone = "up" | "down" | "warn" | "info" | "neutral";

type KpiId =
  | "climbing"
  | "dropping"
  | "watch"
  | "avgConfidence"
  | "upsets"
  | "newFaces";

export interface KpiVM {
  id: KpiId;
  /** Glossary term opened by the KPI's info dot. */
  glossaryTerm: GlossaryTerm;
  /** Raw numeric value (count, or 0–1 for confidence). */
  value: number;
  /** Pre-formatted display string ("12", "78%"). */
  display: string;
  tone: KpiTone;
}

type KpiSummary = Pick<
  TournamentAnalyticsSummary,
  "avg_confidence" | "anomaly_count" | "divergent_team_count" | "newcomer_count"
>;

/**
 * The six fan-facing KPIs. Climbers/droppers are counted from the per-player
 * predicted direction; the rest come straight off the summary. Labels/footers
 * live in i18n keyed by {@link KpiId} so this stays render-free.
 */
export function buildKpiRail(
  summary: KpiSummary,
  teams: Array<Pick<TeamAnalytics, "players">>,
): KpiVM[] {
  let climbers = 0;
  let droppers = 0;
  for (const team of teams) {
    for (const player of team.players) {
      if (player.predicted_direction === "promote") climbers += 1;
      else if (player.predicted_direction === "demote") droppers += 1;
    }
  }

  return [
    { id: "climbing", glossaryTerm: "climbing", value: climbers, display: String(climbers), tone: "up" },
    { id: "dropping", glossaryTerm: "dropping", value: droppers, display: String(droppers), tone: "down" },
    {
      id: "watch",
      glossaryTerm: "watch",
      value: summary.anomaly_count,
      display: String(summary.anomaly_count),
      tone: "warn",
    },
    {
      id: "avgConfidence",
      glossaryTerm: "avg_confidence",
      value: summary.avg_confidence,
      display: formatConfidencePercent(summary.avg_confidence),
      tone: "info",
    },
    {
      id: "upsets",
      glossaryTerm: "upsets",
      value: summary.divergent_team_count,
      display: String(summary.divergent_team_count),
      tone: "neutral",
    },
    {
      id: "newFaces",
      glossaryTerm: "new_faces",
      value: summary.newcomer_count,
      display: String(summary.newcomer_count),
      tone: "neutral",
    },
  ];
}
