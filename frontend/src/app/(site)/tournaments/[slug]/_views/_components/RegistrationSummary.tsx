"use client";

import { useTranslations } from "next-intl";

import { normalizePlayerRole, playerRoleSlotCode } from "@/lib/player-role";
import { ROSTER_SLOT_CODES, type RosterSlotCode } from "@/lib/roster-shape";
import { cn } from "@/lib/utils";

import styles from "../../TournamentDetail.module.css";

/** The site's role tints (`PlayerRoleIcon` uses the same tokens), keyed by slot code. */
export const ROLE_TINT: Record<RosterSlotCode, string> = {
  tank: "var(--aqt-tank)",
  dps: "var(--aqt-damage)",
  support: "var(--aqt-support)",
  flex: "var(--aqt-flex)"
};

export function StatTile({
  label,
  value,
  hint,
  accent
}: Readonly<{ label: string; value: string; hint?: string; accent?: string }>) {
  return (
    <div className={styles.figure}>
      <div className={cn(styles.figureLabel, "flex items-center gap-1.5")}>
        {accent ? (
          <span aria-hidden className="size-1.5 rounded-full" style={{ background: accent }} />
        ) : null}
        {label}
      </div>
      <div className={styles.figureValue}>
        {value}
        {hint ? <span className={styles.figureHint}>{hint}</span> : null}
      </div>
    </div>
  );
}

/**
 * Folds the server's raw registration role codes onto the four slot codes the
 * site renders. The server counts one bucket per registration (its primary
 * role) and sends whatever code that row stores; `dps`/`damage` and friends
 * resolve here rather than in two places.
 */
export function toRoleSlotCounts(
  roleCounts: Readonly<Record<string, number>> | undefined
): Record<RosterSlotCode, number> {
  const counts: Record<RosterSlotCode, number> = { tank: 0, dps: 0, support: 0, flex: 0 };
  for (const [role, count] of Object.entries(roleCounts ?? {})) {
    counts[playerRoleSlotCode(normalizePlayerRole(role))] += count;
  }
  return counts;
}

/**
 * Count + split by role, from the server's own aggregate.
 *
 * The one place this shape is rendered: the overview's registration card shows
 * it beside the latest sign-ups, and the participants page shows it INSTEAD of
 * the roster when the organizer hid the list — in which case it is the only
 * thing either page can say, because the server sends no rows at all.
 */
export function RegistrationSummary({
  total,
  roleCounts,
  maxParticipants
}: Readonly<{
  total: number;
  roleCounts: Readonly<Record<string, number>>;
  /** Advisory capacity. Rendered as a `/ N` suffix; never compared against `total`. */
  maxParticipants?: number | null;
}>) {
  const t = useTranslations();
  const counts = toRoleSlotCounts(roleCounts);
  // Only roles somebody actually declared: four tiles of which three read zero
  // describe the component, not the field.
  const shares = ROSTER_SLOT_CODES.filter((code) => counts[code] > 0);
  const shareTotal = shares.reduce((sum, code) => sum + counts[code], 0);

  return (
    <>
      <div className="grid gap-2 sm:grid-cols-4">
        <StatTile
          label={t("tournamentDetail.overview.registration.total")}
          value={String(total)}
          hint={
            maxParticipants != null && maxParticipants > 0 ? `/ ${maxParticipants}` : undefined
          }
        />
        {shares.map((code) => (
          <StatTile
            key={code}
            label={t(`common.roles.${code}`)}
            value={String(counts[code])}
            accent={ROLE_TINT[code]}
          />
        ))}
      </div>
      {shares.length > 1 && shareTotal > 0 ? (
        <div aria-hidden className="mt-3 flex h-1.5 gap-px overflow-hidden rounded-sm">
          {shares.map((code) => (
            <span
              key={code}
              style={{
                width: `${(counts[code] / shareTotal) * 100}%`,
                background: ROLE_TINT[code]
              }}
            />
          ))}
        </div>
      ) : null}
    </>
  );
}
