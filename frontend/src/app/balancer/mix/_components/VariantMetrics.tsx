import { METRIC_NEUTRAL_CLASS, METRIC_PILL_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { cn } from "@/lib/utils";

import type { PickupVariant } from "../pickup-lineup";

/**
 * The solver's own verdict on this option, as read-only pills.
 *
 * Off-role is the one that changes colour, because it is the only number a host
 * can act on: it names players who will be unhappy, where quality, spread and
 * line gap only rank the option against its siblings. A metric the solver did
 * not report is left out rather than shown as zero -- hand-swapping a seat
 * clears the scored ones server-side, precisely so nothing stale is displayed.
 */
export function VariantMetrics({ variant }: Readonly<{ variant: PickupVariant }>) {
  const { stats } = variant;
  const offRole = stats.offRoleCount ?? 0;
  const floor = stats.offRoleFloor ?? 0;
  const avoidable = stats.offRoleAboveMinimum;
  const collisions = stats.subRoleCollisions ?? 0;
  const offRoleTitle = [
    "Players the solver had to seat outside their first-choice role.",
    floor > 0 ? `${floor} of them are forced by the pool — no split avoids those.` : null,
    avoidable === 0 && offRole > 0 ? "This option is as comfortable as the pool allows." : null
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {stats.qualityScore == null ? null : (
        <span
          title="Solver score for this option across rank balance and role comfort \u2014 lower is better, and comparable only against the other options of this run."
          className={cn(
            METRIC_PILL_CLASS,
            "border-[color:color-mix(in_srgb,var(--aqt-emerald)_25%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-emerald)_10%,transparent)] text-[color:var(--aqt-emerald)]"
          )}
        >
          {`QUALITY ${stats.qualityScore.toFixed(2)}`}
        </span>
      )}
      {stats.mmrStdDev == null ? null : (
        <span
          title="Standard deviation of team rank \u2014 lower means the teams are closer together."
          className={cn(
            METRIC_PILL_CLASS,
            "border-[color:color-mix(in_srgb,var(--aqt-blue)_22%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-blue)_10%,transparent)] text-[color:var(--aqt-blue)]"
          )}
        >
          {`STDDEV ${stats.mmrStdDev.toFixed(1)}`}
        </span>
      )}
      {stats.ratingGap == null ? null : (
        <span
          title="Rank gap between the strongest and weakest team."
          className={cn(METRIC_PILL_CLASS, METRIC_NEUTRAL_CLASS)}
        >
          {`SPREAD ${Math.round(stats.ratingGap)}`}
        </span>
      )}
      {stats.lineGap == null ? null : (
        <span
          title="Average rank gap per role line between the teams \u2014 catches a tank or support mismatch the team totals hide."
          className={cn(METRIC_PILL_CLASS, METRIC_NEUTRAL_CLASS)}
        >
          {`LINES ${Math.round(stats.lineGap)}`}
        </span>
      )}
      <span
        title={offRoleTitle}
        className={cn(
          METRIC_PILL_CLASS,
          offRole > 0 && avoidable !== 0
            ? "border-[color:color-mix(in_srgb,var(--aqt-amber)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_10%,transparent)] text-[color:var(--aqt-amber)]"
            : METRIC_NEUTRAL_CLASS
        )}
      >
        {`OFF-ROLE ${offRole}`}
        {avoidable === 0 && offRole > 0 ? " (floor)" : ""}
      </span>
      {collisions > 0 ? (
        <span
          title="Pairs of players sharing a role subclass inside the same team \u2014 two main tanks, two snipers."
          className={cn(
            METRIC_PILL_CLASS,
            "border-[color:color-mix(in_srgb,var(--aqt-amber)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_10%,transparent)] text-[color:var(--aqt-amber)]"
          )}
        >
          {`SUBROLE ${collisions}`}
        </span>
      ) : null}
    </div>
  );
}
