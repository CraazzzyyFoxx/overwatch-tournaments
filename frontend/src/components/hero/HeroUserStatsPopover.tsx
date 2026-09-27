"use client";

import { useTranslations } from "next-intl";
import { Hero } from "@/types/hero.types";
import { LogStatsName } from "@/types/stats.types";
import { normalizeRole, type AqtRoleKey } from "@/lib/roster/player-role";
import HeroImage from "@/components/hero/HeroImage";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Progress } from "@/components/ui/progress";
import { formatPercent, formatSeconds } from "@/lib/format";
import { getWinrateColor } from "@/lib/colors";
import type { UserMapHeroStats } from "@/types/user.types";
import type { HeroPopoverStat } from "@/lib/hero/popover-stats";

// Localized role name (reuses the shared role labels).
const ROLE_LABEL_KEY: Record<AqtRoleKey, string> = {
  tank: "common.roles.tank",
  damage: "common.roles.damage",
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


const avg10 = (stats: HeroPopoverStat[] | undefined, name: LogStatsName): number | null => {
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
  /** Per-hero aggregate stats, narrowed by `heroPopoverStats` to the three
   *  stats this popover reads. Optional — sources without per-hero win/kda
   *  (e.g. the playtime-only "Most played" list) omit it and the popover
   *  degrades to just the hero identity + playtime share. */
  stats?: HeroPopoverStat[];
  /** Normalized playtime share in [0, 1], shown when stats aren't available. */
  playtimeShare?: number | null;
  /**
   * Map-scoped aggregate (Maps tab): winrate / games / W-L-D plus the hero's
   * playtime share of that map. Absorbed from the former, unlocalized
   * `HeroStatsPopover`.
   */
  mapStats?: UserMapHeroStats;
}

/**
 * Editorial-Tactical hero hover-stats popover (design-book §11). Pass as the
 * `popover` prop of <HeroImage> / `renderPopover` of <HeroStrip> to attach the
 * per-hero stats we actually have (Winrate, KDA, Dmg/10 — or the map-scoped
 * winrate/games/record) to a hero avatar. Only stats that are present render —
 * never fabricates a value.
 */
const HeroUserStatsPopover = ({ hero, stats, playtimeShare, mapStats }: Props) => {
  const t = useTranslations();
  const roleKey = normalizeRole(hero.type ?? hero.role);
  const roleName = roleKey ? t(ROLE_LABEL_KEY[roleKey] as Parameters<typeof t>[0]) : (hero.type ?? hero.role ?? "");

  const cells: Cell[] = [];
  if (mapStats) {
    cells.push({
      label: t("common.heroStats.winrate"),
      value: formatPercent(mapStats.win_rate, 0),
      color: getWinrateColor(mapStats.win_rate),
    });
    cells.push({ label: t("common.heroStats.games"), value: String(mapStats.games) });
    cells.push({
      label: t("common.heroStats.record"),
      value: `${mapStats.win}-${mapStats.loss}-${mapStats.draw}`,
    });
  } else {
    const winFrac = toFraction(avg10(stats, LogStatsName.Winrate));
    if (winFrac != null) {
      const pct = winFrac * 100;
      cells.push({
        label: t("users.heroes.quick.winrate"),
        value: `${pct.toFixed(0)}%`,
        color: getWinrateColor(winFrac),
      });
    }
    const kda = avg10(stats, LogStatsName.KDA);
    if (kda != null) cells.push({ label: t("users.heroes.quick.kda"), value: kda.toFixed(2) });
    const dmg = avg10(stats, LogStatsName.HeroDamageDealt);
    if (dmg != null) cells.push({ label: t("users.heroes.quick.dmg10"), value: compact(dmg) });
  }

  const share = playtimeShare != null && Number.isFinite(playtimeShare) ? playtimeShare : null;
  const mapShare = mapStats
    ? Math.max(0, Math.min(100, mapStats.playtime_share_on_map * 100))
    : null;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <HeroImage hero={hero} size="lg" title={hero.name} />
        <div className="min-w-0">
          <div className="aqt-display truncate text-ui font-bold text-[color:var(--aqt-fg)]">{hero.name}</div>
          {roleKey ? (
            <div className="mt-0.5 flex items-center gap-1.5" style={{ color: ROLE_COLOR[roleKey] }}>
              <PlayerRoleIcon role={ROLE_ICON[roleKey]} size={13} color={ROLE_COLOR[roleKey]} decorative />
              <span className="aqt-tnum text-label font-bold uppercase tracking-label">{roleName}</span>
            </div>
          ) : null}
        </div>
      </div>

      {cells.length > 0 ? (
        <div className="grid grid-cols-3 gap-2">
          {cells.map((cell) => (
            <div key={cell.label} className="rounded-[7px] border border-[color:var(--aqt-border)] px-2 py-1.5">
              <div className="aqt-tnum text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                {cell.label}
              </div>
              <div
                className="aqt-tnum text-ui font-bold tabular-nums"
                style={{ color: cell.color ?? "var(--aqt-fg)" }}
              >
                {cell.value}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {mapStats && mapShare != null ? (
        <div className="border-t border-[color:var(--aqt-border)] pt-2">
          <div className="flex items-center justify-between">
            <span className="aqt-tnum text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
              {t("common.heroStats.playtimeOnMap")}
            </span>
            <span className="aqt-tnum text-label font-bold tabular-nums text-[color:var(--aqt-fg)]">
              {formatSeconds(mapStats.playtime_seconds)} · {mapShare.toFixed(0)}%
            </span>
          </div>
          <div className="mt-2">
            <Progress value={mapShare} aria-label={t("common.heroStats.playtimeOnMap")} />
          </div>
          <div className="mt-2 text-label text-[color:var(--aqt-fg-faint)]">
            {t("common.heroStats.countedNote")}
          </div>
        </div>
      ) : null}

      {!mapStats && share != null ? (
        <div
          className={`flex items-center justify-between ${
            cells.length > 0 ? "border-t border-[color:var(--aqt-border)] pt-2" : ""
          }`}
        >
          <span className="aqt-tnum text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
            {t("users.heroes.playtimeShare")}
          </span>
          <span className="aqt-tnum text-label font-bold tabular-nums text-[color:var(--aqt-fg)]">
            {(share * 100).toFixed(0)}%
          </span>
        </div>
      ) : null}

      {cells.length === 0 && share == null && !mapStats ? (
        <span className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]">{t("users.heroes.noStats")}</span>
      ) : null}
    </div>
  );
};

export default HeroUserStatsPopover;
