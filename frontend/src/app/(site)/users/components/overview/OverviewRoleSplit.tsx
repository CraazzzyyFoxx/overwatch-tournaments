import React from "react";
import { getTranslations } from "next-intl/server";
import { Layers } from "lucide-react";
import { UserProfile, UserRole, UserMapRead } from "@/types/user.types";
import { HeroWithUserStats } from "@/types/hero.types";
import { LogStatsName } from "@/types/stats.types";
import { CardSurface, RolePyramid, normalizeRole, type AqtRoleKey } from "@/app/(site)/users/components/shared/atoms";
import { getOverall } from "@/app/(site)/users/components/heroes/utils";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import HeroImage from "@/components/hero/HeroImage";

// Canonical English role names used ONLY for icon selection in PlayerRoleIcon.
const ROLE_ICON: Record<AqtRoleKey, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support"
};

// Reuse the shared role labels (common.roles); damage maps to the dps entry.
const ROLE_LABEL_KEY: Record<AqtRoleKey, string> = {
  tank: "common.roles.tank",
  damage: "common.roles.dps",
  support: "common.roles.support"
};

const ROLE_SHORT_KEY: Record<AqtRoleKey, string> = {
  tank: "users.overview.roleSplit.short.tank",
  damage: "users.overview.roleSplit.short.damage",
  support: "users.overview.roleSplit.short.support"
};

const ROLE_COLOR: Record<AqtRoleKey, string> = {
  tank: "var(--aqt-tank)",
  damage: "var(--aqt-damage)",
  support: "var(--aqt-support)"
};

const ROLE_ORDER: AqtRoleKey[] = ["tank", "damage", "support"];

const formatPercent = (value: number, digits = 1) => `${(value * 100).toFixed(digits)}%`;

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

const statAvg10 = (stats: HeroWithUserStats["stats"], name: LogStatsName): number | null => {
  const stat = stats.find((s) => s.name === name);
  return stat && Number.isFinite(stat.avg_10) ? stat.avg_10 : null;
};

interface Bucket {
  key: AqtRoleKey;
  role: UserRole;
  maps: number;
  won: number;
  lost: number;
  winrate: number;
  share: number;
}

interface Signature {
  key: AqtRoleKey;
  hero: HeroWithUserStats["hero"];
  games: number;
  kda: number | null;
  winPct: number | null;
}

interface Props {
  profile: UserProfile;
  /** Aggregate per-hero stats (already fetched) — source for the signature hero. */
  heroes?: HeroWithUserStats[];
  /** User maps with per-hero games — the only real per-hero game count. */
  maps?: UserMapRead[];
}

const OverviewRoleSplit = async ({ profile, heroes = [], maps = [] }: Props) => {
  if (!profile.roles.length) return null;

  const t = await getTranslations();
  const totalMaps = profile.maps_total;
  const buckets = ROLE_ORDER.map<Bucket | null>((roleKey) => {
    const role = profile.roles.find((r) => normalizeRole(r.role) === roleKey);
    if (!role) return null;
    return {
      key: roleKey as AqtRoleKey,
      role,
      maps: role.maps,
      won: role.maps_won,
      lost: role.maps - role.maps_won,
      winrate: role.maps > 0 ? role.maps_won / role.maps : 0,
      share: totalMaps > 0 ? role.maps / totalMaps : 0
    };
  }).filter((b): b is Bucket => b !== null);

  const primary: Bucket | undefined = buckets.reduce<Bucket | undefined>(
    (best, current) => (best === undefined || current.role.tournaments > best.role.tournaments ? current : best),
    undefined
  );

  // Signature hero per role: the most-played hero the player owns in that role.
  const hasGamesData = maps.length > 0;
  const gamesByHero = new Map<number, number>();
  for (const m of maps) {
    for (const hs of m.hero_stats ?? []) {
      gamesByHero.set(hs.hero.id, (gamesByHero.get(hs.hero.id) ?? 0) + (hs.games ?? 0));
    }
  }
  const signatures: Signature[] = [];
  for (const key of ROLE_ORDER) {
    if (!buckets.some((b) => b.key === key)) continue;
    const roleHeroes = heroes.filter((h) => normalizeRole(h.hero.type ?? h.hero.role) === key);
    if (roleHeroes.length === 0) continue;
    const top = roleHeroes.reduce((best, h) =>
      getOverall(h, LogStatsName.HeroTimePlayed) > getOverall(best, LogStatsName.HeroTimePlayed) ? h : best
    );
    if (getOverall(top, LogStatsName.HeroTimePlayed) <= 0) continue;
    const winFrac = toFraction(statAvg10(top.stats, LogStatsName.Winrate));
    signatures.push({
      key,
      hero: top.hero,
      games: gamesByHero.get(top.hero.id) ?? 0,
      kda: statAvg10(top.stats, LogStatsName.KDA),
      winPct: winFrac == null ? null : winFrac * 100
    });
  }

  return (
    <CardSurface
      title={t("users.overview.roleSplit.title")}
      icon={<Layers size={15} />}
      subtitle={t("users.overview.roleSplit.subtitle", {
        maps: totalMaps,
        tournaments: profile.tournaments_count
      })}
    >
      <div className="flex flex-col gap-3.5">
        <RolePyramid
          segments={buckets.map((b) => ({
            role: b.key,
            maps: b.maps,
            label: b.maps > 0 ? `${t(ROLE_SHORT_KEY[b.key] as Parameters<typeof t>[0])} ${b.maps}` : ""
          }))}
        />
        <div className="flex flex-col gap-3">
          {buckets.map((b) => (
            <div
              key={b.key}
              className="grid grid-cols-[44px_1fr_auto] items-center gap-3 rounded-[10px] border px-3 py-2.5"
              style={{
                background:
                  b.key === "tank"
                    ? "hsl(210 78% 60% / 0.06)"
                    : b.key === "damage"
                      ? "hsl(340 78% 60% / 0.06)"
                      : "hsl(142 60% 52% / 0.05)",
                borderColor:
                  b.key === "tank"
                    ? "hsl(210 78% 60% / 0.2)"
                    : b.key === "damage"
                      ? "hsl(340 78% 60% / 0.25)"
                      : "hsl(142 60% 52% / 0.2)"
              }}
            >
              <DivisionIcon
                division={b.role.division}
                tournamentGrid={b.role.division_grid_version}
                width={44}
                height={44}
              />
              <div>
                <div
                  className="aqt-display flex items-center gap-1.5 text-[16px] font-bold uppercase leading-none tracking-[0.04em]"
                  style={{ color: ROLE_COLOR[b.key] }}
                >
                  <PlayerRoleIcon role={ROLE_ICON[b.key]} size={14} color={ROLE_COLOR[b.key]} />
                  {t(ROLE_LABEL_KEY[b.key] as Parameters<typeof t>[0])}
                  {primary && b.key === primary.key ? (
                    <span className="ml-1 text-[11px] font-semibold tracking-[0.1em] text-[color:var(--aqt-fg-muted)]"> · {t("users.overview.roleSplit.main")}</span>
                  ) : null}
                </div>
                <div className="aqt-mono mt-1 text-[12px] text-[color:var(--aqt-fg-muted)]">
                  {b.won}W · {b.lost}L · {t("users.overview.mapsCount", { count: b.maps })}
                </div>
              </div>
              <div className="text-right">
                <div
                  className="aqt-display aqt-tnum text-[22px] font-bold leading-none"
                  style={{
                    color: b.winrate > 0.55
                      ? "var(--aqt-emerald)"
                      : b.winrate < 0.5
                        ? "var(--aqt-rose)"
                        : "var(--aqt-fg)"
                  }}
                >
                  {formatPercent(b.winrate)}
                </div>
                <div className="aqt-mono mt-0.5 text-[11.5px] text-[color:var(--aqt-fg-dim)]">
                  {formatPercent(b.share)} {t("users.overview.roleSplit.ofPool")}
                </div>
              </div>
            </div>
          ))}
        </div>
        {signatures.length > 0 ? (
          <div className="flex flex-col gap-2 border-t border-[color:var(--aqt-border)] pt-3.5">
            <span className="aqt-mono text-[11px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">
              {t("users.overview.roleSplit.signatureTitle")}
            </span>
            {signatures.map((sig) => {
              const roleName = t(ROLE_LABEL_KEY[sig.key] as Parameters<typeof t>[0]);
              return (
                <div key={sig.key} className="grid grid-cols-[16px_26px_1fr_auto] items-center gap-2.5">
                  <div className="flex justify-center" title={roleName} aria-label={roleName}>
                    <PlayerRoleIcon role={ROLE_ICON[sig.key]} size={14} color={ROLE_COLOR[sig.key]} />
                  </div>
                  <HeroImage hero={sig.hero} size={26} title={sig.hero.name} />
                  <div className="min-w-0">
                    <div className="truncate text-[13px] font-bold text-[color:var(--aqt-fg)]">{sig.hero.name}</div>
                    <div className="aqt-mono text-[11px] text-[color:var(--aqt-fg-dim)]">
                      {hasGamesData && sig.games > 0 ? <>{t("users.overview.roleSplit.games", { count: sig.games })} · </> : null}
                      {sig.kda != null ? t("users.overview.roleSplit.kda", { value: sig.kda.toFixed(2) }) : "—"}
                    </div>
                  </div>
                  <div
                    className="aqt-display aqt-tnum text-[15px] font-bold"
                    style={{ color: sig.winPct != null ? winrateColor(sig.winPct) : "var(--aqt-fg-muted)" }}
                  >
                    {sig.winPct != null ? `${sig.winPct.toFixed(0)}%` : "—"}
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
    </CardSurface>
  );
};

export default OverviewRoleSplit;
