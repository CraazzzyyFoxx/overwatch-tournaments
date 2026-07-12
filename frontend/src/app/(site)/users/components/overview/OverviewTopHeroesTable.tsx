import React from "react";
import { getTranslations } from "next-intl/server";
import { Swords } from "lucide-react";
import Link from "next/link";
import { HeroWithUserStats } from "@/types/hero.types";
import { UserMapRead } from "@/types/user.types";
import { LogStatsName } from "@/types/stats.types";
import { CardSurface, normalizeRole, type AqtRoleKey } from "@/app/(site)/users/components/shared/atoms";
import { formatStatValue, getOverall } from "@/app/(site)/users/components/heroes/utils";
import HeroImage from "@/components/hero/HeroImage";
import HeroUserStatsPopover from "@/components/hero/HeroUserStatsPopover";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";

interface Props {
  heroes: HeroWithUserStats[];
  /** User maps (with per-hero stats) — the only source of a real per-hero game
   *  count, which drives the low-sample gate (design-book §5/§6). */
  maps: UserMapRead[];
  userSlug: string;
  limit?: number;
}

// design-book §5/§6: percentile / vs-avg is noise under this many games.
const LOW_SAMPLE_GAMES = 10;
const DEFAULT_LIMIT = 8;

// Canonical English role names used ONLY to pick the PlayerRoleIcon glyph.
const ROLE_ICON_NAME: Record<AqtRoleKey, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support"
};

// Localized role name (icon-only in the table; name lives in title/aria-label).
const ROLE_NAME_KEY: Record<AqtRoleKey, string> = {
  tank: "common.roles.tank",
  damage: "common.roles.dps",
  support: "common.roles.support"
};

const ROLE_COLOR: Record<AqtRoleKey, string> = {
  tank: "var(--aqt-tank)",
  damage: "var(--aqt-damage)",
  support: "var(--aqt-support)"
};

const statAvg10 = (stats: HeroWithUserStats["stats"], name: LogStatsName): number | null => {
  const stat = stats.find((s) => s.name === name);
  return stat && Number.isFinite(stat.avg_10) ? stat.avg_10 : null;
};

// Winrate can arrive as a 0..1 fraction or an already-scaled percent; normalize
// to a fraction the same way the Heroes tab does.
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

interface Row {
  id: number;
  hero: HeroWithUserStats["hero"];
  /** Full per-hero stats, kept for the hover popover (design-book §11). */
  stats: HeroWithUserStats["stats"];
  roleKey: AqtRoleKey | null;
  games: number;
  winPct: number | null;
  kda: number | null;
  dmg10: number | null;
  /** Player winrate minus the global average on this hero (fraction). */
  vsAvg: number | null;
  lowSample: boolean;
}

const numHeader = "aqt-mono border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-right text-[11px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-faint)]";
const textHeader = "aqt-mono border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-left text-[11px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-faint)]";
const numCell = "aqt-mono px-3 py-2.5 text-right text-[13px] text-[color:var(--aqt-fg-muted)]";

const OverviewTopHeroesTable = async ({ heroes, maps, userSlug, limit = DEFAULT_LIMIT }: Props) => {
  if (heroes.length === 0) return null;

  const t = await getTranslations();

  // Real per-hero game count (and wins) aggregated across every map the hero
  // was played on. This is the only place the profile exposes a games count.
  const hasGamesData = maps.length > 0;
  const gamesByHero = new Map<number, number>();
  for (const m of maps) {
    for (const hs of m.hero_stats ?? []) {
      gamesByHero.set(hs.hero.id, (gamesByHero.get(hs.hero.id) ?? 0) + (hs.games ?? 0));
    }
  }

  const rows: Row[] = heroes
    .map((h) => ({ h, playtime: getOverall(h, LogStatsName.HeroTimePlayed) }))
    .sort((a, b) => b.playtime - a.playtime)
    .slice(0, limit)
    .map(({ h }) => {
      const winStat = h.stats.find((s) => s.name === LogStatsName.Winrate);
      const winFrac = toFraction(winStat?.avg_10);
      const globalFrac = winStat && winStat.avg_10_all > 0 ? toFraction(winStat.avg_10_all) : null;
      const games = gamesByHero.get(h.hero.id) ?? 0;
      return {
        id: h.hero.id,
        hero: h.hero,
        stats: h.stats,
        roleKey: normalizeRole(h.hero.type ?? h.hero.role),
        games,
        winPct: winFrac == null ? null : winFrac * 100,
        kda: statAvg10(h.stats, LogStatsName.KDA),
        dmg10: statAvg10(h.stats, LogStatsName.HeroDamageDealt),
        vsAvg: winFrac != null && globalFrac != null ? winFrac - globalFrac : null,
        lowSample: hasGamesData && games < LOW_SAMPLE_GAMES
      };
    });

  const lowSampleTitle = t("users.overview.topHeroes.lowSampleTitle", { games: LOW_SAMPLE_GAMES });

  return (
    <CardSurface
      title={t("users.overview.topHeroes.title")}
      icon={<Swords size={15} />}
      subtitle={t("users.overview.topHeroes.played", { count: heroes.length })}
      action={
        <Link href={`/users/${userSlug}?tab=heroes`} className="aqt-seeall">
          {t("common.all")} {heroes.length} →
        </Link>
      }
    >
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr>
              <th className={textHeader}>{t("users.overview.topHeroes.col.hero")}</th>
              <th className={`${textHeader} text-center`}>{t("users.overview.topHeroes.col.role")}</th>
              {hasGamesData ? <th className={numHeader}>{t("users.overview.topHeroes.col.games")}</th> : null}
              <th className={numHeader}>{t("users.overview.topHeroes.col.winrate")}</th>
              <th className={numHeader}>{t("users.overview.topHeroes.col.kda")}</th>
              <th className={numHeader}>{t("users.overview.topHeroes.col.dmg10")}</th>
              <th className={numHeader}>{t("users.overview.topHeroes.col.vsAvg")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const roleName = r.roleKey
                ? t(ROLE_NAME_KEY[r.roleKey] as Parameters<typeof t>[0])
                : (r.hero.type ?? r.hero.role);
              return (
                <tr
                  key={r.id}
                  className="border-b border-[color:var(--aqt-border)] last:border-b-0 hover:bg-[hsl(0_0%_100%/0.02)]"
                >
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2.5">
                      <HeroImage
                        hero={r.hero}
                        size="sm"
                        title={r.hero.name}
                        popover={<HeroUserStatsPopover hero={r.hero} stats={r.stats} />}
                      />
                      <div className="min-w-0">
                        <div className="truncate text-[13.5px] font-bold text-[color:var(--aqt-fg)]">
                          {r.hero.name}
                        </div>
                        {r.lowSample ? (
                          <span
                            className="aqt-mono text-[9.5px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-faint)]"
                            title={lowSampleTitle}
                          >
                            {t("users.overview.topHeroes.lowSample")}
                          </span>
                        ) : null}
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex justify-center" title={roleName} aria-label={roleName}>
                      <PlayerRoleIcon
                        role={r.roleKey ? ROLE_ICON_NAME[r.roleKey] : null}
                        size={16}
                        color={r.roleKey ? ROLE_COLOR[r.roleKey] : "var(--aqt-fg-muted)"}
                      />
                    </div>
                  </td>
                  {hasGamesData ? (
                    <td className={numCell}>{r.games}</td>
                  ) : null}
                  <td className={numCell}>
                    {r.lowSample || r.winPct == null ? (
                      <span title={r.lowSample ? lowSampleTitle : undefined} className="text-[color:var(--aqt-fg-faint)]">
                        —
                      </span>
                    ) : (
                      <span className="font-bold" style={{ color: winrateColor(r.winPct) }}>
                        {r.winPct.toFixed(0)}%
                      </span>
                    )}
                  </td>
                  <td className={`${numCell} font-semibold text-[color:var(--aqt-fg)]`}>
                    {r.kda == null ? "—" : r.kda.toFixed(2)}
                  </td>
                  <td className={numCell}>{r.dmg10 == null ? "—" : formatStatValue("dmg", r.dmg10)}</td>
                  <td className={numCell}>
                    {r.lowSample ? (
                      <span title={lowSampleTitle} className="text-[color:var(--aqt-fg-faint)]">
                        —
                      </span>
                    ) : r.vsAvg == null ? (
                      <span className="text-[color:var(--aqt-fg-faint)]" title={t("users.overview.topHeroes.vsAvgTitle")}>
                        –
                      </span>
                    ) : (
                      <span
                        className="font-bold"
                        title={t("users.overview.topHeroes.vsAvgTitle")}
                        style={{
                          color:
                            r.vsAvg > 0
                              ? "var(--aqt-emerald)"
                              : r.vsAvg < 0
                                ? "var(--aqt-rose)"
                                : "var(--aqt-fg-muted)"
                        }}
                      >
                        {r.vsAvg > 0 ? "▲" : r.vsAvg < 0 ? "▼" : "–"} {Math.abs(r.vsAvg * 100).toFixed(0)}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </CardSurface>
  );
};

export default OverviewTopHeroesTable;
