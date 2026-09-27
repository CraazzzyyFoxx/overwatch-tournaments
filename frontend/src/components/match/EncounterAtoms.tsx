import React from "react";
import Link from "next/link";

import { cn } from "@/lib/utils";
import { formatSubRoleLabel, getPlayerSlug } from "@/lib/player";
import styles from "@/components/match/EncounterDetail.module.css";

/**
 * Presentational atoms shared by the encounter detail page. No hooks, so they
 * render from both the server page and its client panels.
 */

export interface PlayerIdentityInput {
  name: string;
  sub_role?: string | null;
}

/**
 * Player name + BattleTag discriminator + specialization.
 *
 * Deliberately NOT the shared `PlayerName`: that one paints the tag with a
 * shadcn `<Badge variant="secondary">` and the specialization with
 * `text-muted-foreground`, both of which resolve against the shadcn theme
 * variables and read a shade off on these `--aqt-*` surfaces.
 */
export function PlayerIdentity({
  player,
  className
}: Readonly<{
  player: PlayerIdentityInput;
  className?: string;
}>) {
  const [handle, tag] = player.name.split("#");
  const specialization = formatSubRoleLabel(player.sub_role);

  return (
    <span className={cn(styles.rosterPlayerName, className)}>
      <Link href={`/users/${getPlayerSlug(player.name)}`} className={styles.playerLink}>
        {handle}
        {tag ? <span className={styles.playerTag}>#{tag}</span> : null}
      </Link>
      {specialization ? <span className={styles.playerSpec}>{specialization}</span> : null}
    </span>
  );
}

/** Label-over-value block used by the hairline fact strips. */
export function Fact({
  label,
  children,
  className
}: Readonly<{
  label: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}>) {
  return (
    <div className={cn(styles.fact, className)}>
      <span className={styles.label}>{label}</span>
      <span className={styles.factValue}>{children}</span>
    </div>
  );
}

export type PillTone = "neutral" | "accent" | "good" | "warn" | "danger";

const PILL_TONE: Record<PillTone, string | undefined> = {
  neutral: undefined,
  accent: styles.pillAccent,
  good: styles.pillGood,
  warn: styles.pillWarn,
  danger: styles.pillDanger
};

export function Pill({
  tone = "neutral",
  live,
  className,
  children
}: Readonly<{
  tone?: PillTone;
  /** Prefix the pill with the pulsing live dot. */
  live?: boolean;
  className?: string;
  children: React.ReactNode;
}>) {
  return (
    <span className={cn(styles.pill, PILL_TONE[tone], className)}>
      {live ? <span aria-hidden className={styles.livePulse} /> : null}
      {children}
    </span>
  );
}

/** A `label: value` pair inside a pill, for compact team/series facts. */
export function PillFact({
  label,
  value,
  tone
}: Readonly<{
  label: React.ReactNode;
  value: React.ReactNode;
  tone?: PillTone;
}>) {
  return (
    <Pill tone={tone}>
      <span className={styles.label}>{label}</span>
      <span className={styles.mono}>{value}</span>
    </Pill>
  );
}
