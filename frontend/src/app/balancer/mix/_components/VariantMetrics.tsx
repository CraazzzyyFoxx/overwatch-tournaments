import { useTranslations } from "next-intl";

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
  const t = useTranslations("mixes.teams.metrics");
  const { stats } = variant;
  const offRole = stats.offRoleCount ?? 0;
  const floor = stats.offRoleFloor ?? 0;
  const avoidable = stats.offRoleAboveMinimum;
  const collisions = stats.subRoleCollisions ?? 0;
  const offRoleTitle = [
    t("offRoleHint"),
    floor > 0 ? t("offRoleForced", { count: floor }) : null,
    avoidable === 0 && offRole > 0 ? t("offRoleFloorHint") : null
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {stats.qualityScore == null ? null : (
        <span
          title={t("qualityHint")}
          className={cn(
            METRIC_PILL_CLASS,
            "border-[color:color-mix(in_srgb,var(--aqt-emerald)_25%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-emerald)_10%,transparent)] text-[color:var(--aqt-emerald)]"
          )}
        >
          {t("quality", { value: stats.qualityScore.toFixed(2) })}
        </span>
      )}
      {stats.mmrStdDev == null ? null : (
        <span
          title={t("stddevHint")}
          className={cn(
            METRIC_PILL_CLASS,
            "border-[color:color-mix(in_srgb,var(--aqt-blue)_22%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-blue)_10%,transparent)] text-[color:var(--aqt-blue)]"
          )}
        >
          {t("stddev", { value: stats.mmrStdDev.toFixed(1) })}
        </span>
      )}
      {stats.ratingGap == null ? null : (
        <span
          title={t("spreadHint")}
          className={cn(METRIC_PILL_CLASS, METRIC_NEUTRAL_CLASS)}
        >
          {t("spread", { value: String(Math.round(stats.ratingGap)) })}
        </span>
      )}
      {stats.lineGap == null ? null : (
        <span
          title={t("linesHint")}
          className={cn(METRIC_PILL_CLASS, METRIC_NEUTRAL_CLASS)}
        >
          {t("lines", { value: String(Math.round(stats.lineGap)) })}
        </span>
      )}
      {stats.laneGap == null ? null : (
        <span
          title={t("laneGapHint")}
          className={cn(METRIC_PILL_CLASS, METRIC_NEUTRAL_CLASS)}
        >
          {t("laneGap", { value: String(Math.round(stats.laneGap)) })}
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
        {t("offRole", { count: String(offRole) })}
        {avoidable === 0 && offRole > 0 ? ` ${t("floor")}` : ""}
      </span>
      {collisions > 0 ? (
        <span
          title={t("subroleHint")}
          className={cn(
            METRIC_PILL_CLASS,
            "border-[color:color-mix(in_srgb,var(--aqt-amber)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_10%,transparent)] text-[color:var(--aqt-amber)]"
          )}
        >
          {t("subrole", { count: String(collisions) })}
        </span>
      ) : null}
    </div>
  );
}
