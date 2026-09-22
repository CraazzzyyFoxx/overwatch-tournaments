import { getFormatter, getTranslations } from "next-intl/server";
import { ArrowRight, Swords, TrendingDown, TrendingUp } from "lucide-react";
import Link from "next/link";
import { HeroWithUserStats } from "@/types/hero.types";
import { UserMapRead } from "@/types/user.types";
import { LogStatsName } from "@/types/stats.types";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import { normalizeRole, type AqtRoleKey } from "@/lib/roster/player-role";
import { formatSeconds } from "@/lib/format";
import { formatStatValue, getOverall, statAvg10, toFraction, winrateColor } from "@/app/(site)/users/components/heroes/utils";
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
  damage: "common.roles.damage",
  support: "common.roles.support"
};

const ROLE_COLOR: Record<AqtRoleKey, string> = {
  tank: "var(--aqt-tank)",
  damage: "var(--aqt-damage)",
  support: "var(--aqt-support)"
};

interface Row {
  id: number;
  hero: HeroWithUserStats["hero"];
  /** Full per-hero stats, kept for the hover popover (design-book §11). */
  stats: HeroWithUserStats["stats"];
  roleKey: AqtRoleKey | null;
  games: number;
  /** Total seconds on the hero — this is what the table is ordered by. */
  playtime: number;
  winPct: number | null;
  kda: number | null;
  dmg10: number | null;
  /** Player winrate minus the global average on this hero (fraction). */
  vsAvg: number | null;
  lowSample: boolean;
}

/** Placeholder for a cell with no value. One glyph everywhere: the table used to
 *  mix an em dash (winrate) with an en dash (vs-avg) in the same row. */
const EMPTY = "—";

const numHeader = "aqt-tnum border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-right text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]";
const textHeader = "aqt-tnum border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-left text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]";
const numCell = "aqt-tnum px-3 py-2.5 text-right text-caption text-[color:var(--aqt-fg-muted)]";

const OverviewTopHeroesTable = async ({ heroes, maps, userSlug, limit = DEFAULT_LIMIT }: Props) => {
  if (heroes.length === 0) return null;

  const t = await getTranslations();
  const format = await getFormatter();

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
    .map(({ h, playtime }) => {
      const winStat = h.stats.find((s) => s.name === LogStatsName.Winrate);
      const winFrac = toFraction(winStat?.avg_10);
      const globalFrac = winStat && winStat.avg_10_all > 0 ? toFraction(winStat.avg_10_all) : null;
      const games = gamesByHero.get(h.hero.id) ?? 0;
      const lowSample = hasGamesData && games < LOW_SAMPLE_GAMES;
      return {
        id: h.hero.id,
        hero: h.hero,
        stats: h.stats,
        roleKey: normalizeRole(h.hero.type ?? h.hero.role),
        games,
        playtime,
        winPct: lowSample || winFrac == null ? null : winFrac * 100,
        kda: statAvg10(h.stats, LogStatsName.KDA),
        dmg10: statAvg10(h.stats, LogStatsName.HeroDamageDealt),
        vsAvg: lowSample || winFrac == null || globalFrac == null ? null : winFrac - globalFrac,
        lowSample
      };
    });

  // Only render a metric column when at least one row can fill it. The overview
  // fetches heroes without an explicit stat list, and the backend's default set
  // omits winrate — which shipped WIN% and VS AVG as two full columns of dashes.
  // Gating on the data (as the games column already did) keeps the table honest
  // and self-heals the day those stats start arriving.
  const columns = {
    games: hasGamesData,
    playtime: rows.some((r) => r.playtime > 0),
    winrate: rows.some((r) => r.winPct != null),
    kda: rows.some((r) => r.kda != null),
    dmg10: rows.some((r) => r.dmg10 != null),
    vsAvg: rows.some((r) => r.vsAvg != null)
  };

  const lowSampleTitle = t("users.overview.topHeroes.lowSampleTitle", { games: LOW_SAMPLE_GAMES });

  return (
    <CardSurface
      title={t("users.overview.topHeroes.title")}
      icon={<Swords size={15} />}
      subtitle={t("users.overview.topHeroes.playedByTime", { count: heroes.length })}
      action={
        <Link href={`/users/${userSlug}?tab=heroes`} className="aqt-seeall">
          {t("common.all")} {heroes.length}
          <ArrowRight aria-hidden className="size-3" />
        </Link>
      }
    >
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-caption">
          <thead>
            <tr>
              <th className={textHeader}>{t("users.overview.topHeroes.col.hero")}</th>
              <th className={`${textHeader} text-center`}>{t("users.overview.topHeroes.col.role")}</th>
              {columns.games ? <th className={numHeader}>{t("users.overview.topHeroes.col.games")}</th> : null}
              {columns.playtime ? <th className={numHeader}>{t("users.overview.topHeroes.col.time")}</th> : null}
              {columns.winrate ? <th className={numHeader}>{t("users.overview.topHeroes.col.winrate")}</th> : null}
              {columns.kda ? <th className={numHeader}>{t("users.overview.topHeroes.col.kda")}</th> : null}
              {columns.dmg10 ? <th className={numHeader}>{t("users.overview.topHeroes.col.dmg10")}</th> : null}
              {columns.vsAvg ? <th className={numHeader}>{t("users.overview.topHeroes.col.vsAvg")}</th> : null}
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
                        <div className="truncate text-caption font-bold text-[color:var(--aqt-fg)]">
                          {r.hero.name}
                        </div>
                        {r.lowSample ? (
                          <span
                            className="aqt-tnum text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]"
                            title={lowSampleTitle}
                          >
                            {t("users.overview.topHeroes.lowSample")}
                          </span>
                        ) : null}
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex justify-center" title={roleName}>
                      <PlayerRoleIcon
                        role={r.roleKey ? ROLE_ICON_NAME[r.roleKey] : null}
                        size={16}
                        color={r.roleKey ? ROLE_COLOR[r.roleKey] : "var(--aqt-fg-muted)"}
                      />
                    </div>
                  </td>
                  {columns.games ? <td className={numCell}>{r.games}</td> : null}
                  {columns.playtime ? (
                    <td className={numCell}>{r.playtime > 0 ? formatSeconds(r.playtime) : EMPTY}</td>
                  ) : null}
                  {columns.winrate ? (
                    <td className={numCell}>
                      {r.winPct == null ? (
                        <span title={r.lowSample ? lowSampleTitle : undefined} className="text-[color:var(--aqt-fg-faint)]">
                          {EMPTY}
                        </span>
                      ) : (
                        <span className="font-bold" style={{ color: winrateColor(r.winPct) }}>
                          {r.winPct.toFixed(0)}%
                        </span>
                      )}
                    </td>
                  ) : null}
                  {columns.kda ? (
                    <td className={`${numCell} font-semibold text-[color:var(--aqt-fg)]`}>
                      {r.kda == null ? EMPTY : r.kda.toFixed(2)}
                    </td>
                  ) : null}
                  {columns.dmg10 ? (
                    <td className={numCell}>{r.dmg10 == null ? EMPTY : formatStatValue(format, "dmg", r.dmg10)}</td>
                  ) : null}
                  {columns.vsAvg ? (
                    <td className={numCell}>
                      {r.vsAvg == null ? (
                        <span
                          className="text-[color:var(--aqt-fg-faint)]"
                          title={r.lowSample ? lowSampleTitle : t("users.overview.topHeroes.vsAvgTitle")}
                        >
                          {EMPTY}
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
                          {r.vsAvg > 0 ? (
                            <TrendingUp aria-hidden className="inline size-4 align-[-3px]" />
                          ) : r.vsAvg < 0 ? (
                            <TrendingDown aria-hidden className="inline size-4 align-[-3px]" />
                          ) : (
                            <span aria-hidden>–</span>
                          )}{" "}
                          {/* The icon is decorative; direction reaches AT through this. */}
                          <span className="sr-only">{r.vsAvg > 0 ? "+" : r.vsAvg < 0 ? "−" : ""}</span>
                          {Math.abs(r.vsAvg * 100).toFixed(0)}
                        </span>
                      )}
                    </td>
                  ) : null}
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
