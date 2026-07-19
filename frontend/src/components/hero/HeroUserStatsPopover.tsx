"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { Hero, HeroStat } from "@/types/hero.types";
import { LogStatsName } from "@/types/stats.types";
import { normalizeRole, type AqtRoleKey } from "@/components/hero/heroRole";
import HeroImage from "@/components/hero/HeroImage";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";

// Localized role name (reuses the shared role labels; damage → the dps entry).
const ROLE_LABEL_KEY: Record<AqtRoleKey, string> = {
  tank: "common.roles.tank",
  damage: "common.roles.dps",
  support: "common.roles.support"
};

// Canonical English role name used ONLY to pick the PlayerRoleIcon glyph.
const ROLE_ICON: Record<AqtRoleKey, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support"
};

const ROLE_COLOR: Record<AqtRoleKey, string> = {
  tank: "var(--aqt-tank)",
  damage: "var(--aqt-damage)",
  support: "var(--aqt-support)"
};

// Winrate can arrive as a 0..1 fraction or an already-scaled percent; normalize.
const toFraction = (value: number | null | undefined): number | null => {
  if (value == null || !Number.isFinite(value)) return null;
  return value <= 1 ? value : value / 100;
};

// ≥60 good · 50–59 mid · <50 bad (design-book §1 winrate thresholds).
const winrateColor = (pct: number): string => {
  if (pct >= 60) return "var(--aqt-emerald)";
  if (pct >= 50) return "var(--aqt-amber)";
  return "var(--aqt-rose)";
};

const avg10 = (stats: HeroStat[] | undefined, name: LogStatsName): number | null => {
  const stat = stats?.find((s) => s.name === name);
  return stat && Number.isFinite(stat.avg_10) ? stat.avg_10 : null;
};

const compact = (value: number): string =>
  Math.abs(value) >= 1000 ? `${(value / 1000).toFixed(1)}k` : value.toFixed(0);

type HeroLike = Pick<Hero, "name" | "image_path" | "role"> & { type?: string; color?: string };

interface Cell {
  label: string;
  value: string;
  color?: string;
}

interface Props {
  hero: HeroLike;
  /** Per-hero aggregate stats (HeroWithUserStats.stats). Optional — sources
   *  without per-hero win/kda (e.g. the playtime-only "Most played" list) omit
   *  it and the popover degrades to just the hero identity + playtime share. */
  stats?: HeroStat[];
  /** Normalized playtime share in [0, 1], shown when stats aren't available. */
  playtimeShare?: number | null;
}

/**
 * Editorial-Tactical hero hover-stats popover (design-book §11). Pass as the
 * `popover` prop of <HeroImage> / `renderPopover` of <HeroStrip> to attach the
 * per-hero stats we actually have (Winrate, KDA, Dmg/10) to a hero avatar.
 * Only stats that are present render — never fabricates a value.
 */
const HeroUserStatsPopover = ({ hero, stats, playtimeShare }: Props) => {
  const t = useTranslations();
  const roleKey = normalizeRole(hero.type ?? hero.role);
  const roleName = roleKey ? t(ROLE_LABEL_KEY[roleKey] as Parameters<typeof t>[0]) : (hero.type ?? hero.role ?? "");

  const cells: Cell[] = [];
  const winFrac = toFraction(avg10(stats, LogStatsName.Winrate));
  if (winFrac != null) {
    const pct = winFrac * 100;
    cells.push({ label: t("users.heroes.quick.winrate"), value: `${pct.toFixed(0)}%`, color: winrateColor(pct) });
  }
  const kda = avg10(stats, LogStatsName.KDA);
  if (kda != null) cells.push({ label: t("users.heroes.quick.kda"), value: kda.toFixed(2) });
  const dmg = avg10(stats, LogStatsName.HeroDamageDealt);
  if (dmg != null) cells.push({ label: t("users.heroes.quick.dmg10"), value: compact(dmg) });

  const share = playtimeShare != null && Number.isFinite(playtimeShare) ? playtimeShare : null;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <HeroImage hero={hero} size="lg" title={hero.name} />
        <div className="min-w-0">
          <div className="aqt-display truncate text-[15px] font-bold text-[color:var(--aqt-fg)]">{hero.name}</div>
          {roleKey ? (
            <div className="mt-0.5 flex items-center gap-1.5" style={{ color: ROLE_COLOR[roleKey] }}>
              <PlayerRoleIcon role={ROLE_ICON[roleKey]} size={13} color={ROLE_COLOR[roleKey]} />
              <span className="aqt-mono text-[11px] font-bold uppercase tracking-[0.1em]">{roleName}</span>
            </div>
          ) : null}
        </div>
      </div>

      {cells.length > 0 ? (
        <div className="grid grid-cols-3 gap-2">
          {cells.map((cell) => (
            <div key={cell.label} className="rounded-[7px] border border-[color:var(--aqt-border)] px-2 py-1.5">
              <div className="aqt-mono text-[10px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-faint)]">
                {cell.label}
              </div>
              <div
                className="aqt-tnum text-[15px] font-bold tabular-nums"
                style={{ color: cell.color ?? "var(--aqt-fg)" }}
              >
                {cell.value}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {share != null ? (
        <div
          className={`flex items-center justify-between ${
            cells.length > 0 ? "border-t border-[color:var(--aqt-border)] pt-2" : ""
          }`}
        >
          <span className="aqt-mono text-[11px] uppercase tracking-[0.1em] text-[color:var(--aqt-fg-faint)]">
            {t("users.heroes.playtimeShare")}
          </span>
          <span className="aqt-tnum text-[12px] font-bold tabular-nums text-[color:var(--aqt-fg)]">
            {(share * 100).toFixed(0)}%
          </span>
        </div>
      ) : null}

      {cells.length === 0 && share == null ? (
        <span className="aqt-mono text-[11px] text-[color:var(--aqt-fg-faint)]">{t("users.heroes.noStats")}</span>
      ) : null}
    </div>
  );
};

export default HeroUserStatsPopover;
