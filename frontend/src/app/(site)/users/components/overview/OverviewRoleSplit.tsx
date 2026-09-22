import { getTranslations } from "next-intl/server";
import { Layers } from "lucide-react";
import { UserProfile, UserRole, UserMapRead } from "@/types/user.types";
import { HeroWithUserStats } from "@/types/hero.types";
import { LogStatsName } from "@/types/stats.types";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import { getOverall, statAvg10, toFraction, winrateColor } from "@/app/(site)/users/components/heroes/utils";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import HeroImage from "@/components/hero/HeroImage";
import HeroUserStatsPopover from "@/components/hero/HeroUserStatsPopover";
import {
  normalizeRole,
  PLAYER_ROLE_LABEL_KEY,
  playerRoleTint,
  type AqtRoleKey,
  type PlayerRoleTint
} from "@/lib/roster/player-role";

// Canonical English role names used ONLY for icon selection in PlayerRoleIcon.
const ROLE_ICON: Record<PlayerRoleTint, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support",
  flex: "Flex"
};

// A tint-keyed view of the one shared role-label map (common.roles); no message
// key is restated here — `@/lib/roster/player-role` owns them.
const ROLE_LABEL_KEY = {
  tank: PLAYER_ROLE_LABEL_KEY.Tank,
  damage: PLAYER_ROLE_LABEL_KEY.Damage,
  support: PLAYER_ROLE_LABEL_KEY.Support,
  flex: PLAYER_ROLE_LABEL_KEY.Flex
} satisfies Record<PlayerRoleTint, string>;

const ROLE_COLOR: Record<PlayerRoleTint, string> = {
  tank: "var(--aqt-tank)",
  damage: "var(--aqt-damage)",
  support: "var(--aqt-support)",
  flex: "var(--aqt-flex)"
};

// Row wash + edge per role. The three original hues stay verbatim; flex reads
// its hue from the token so it tracks `--aqt-flex`.
const ROLE_ROW: Record<PlayerRoleTint, { background: string; borderColor: string }> = {
  tank: { background: "hsl(210 78% 60% / 0.06)", borderColor: "hsl(210 78% 60% / 0.2)" },
  damage: { background: "hsl(340 78% 60% / 0.06)", borderColor: "hsl(340 78% 60% / 0.25)" },
  support: { background: "hsl(142 60% 52% / 0.05)", borderColor: "hsl(142 60% 52% / 0.2)" },
  flex: {
    background: "color-mix(in srgb, var(--aqt-flex) 6%, transparent)",
    borderColor: "color-mix(in srgb, var(--aqt-flex) 20%, transparent)"
  }
};

// Flex is a real roster role, so it gets its own bucket — without one its maps
// vanish from the split while shares stay divided by `profile.maps_total`.
const ROLE_ORDER: PlayerRoleTint[] = ["tank", "damage", "support", "flex"];

const formatPercent = (value: number, digits = 1) => `${(value * 100).toFixed(digits)}%`;

interface Bucket {
  key: PlayerRoleTint;
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
  /** Full per-hero stats, kept for the hover popover (design-book §11). */
  stats: HeroWithUserStats["stats"];
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
    const role = profile.roles.find((r) => playerRoleTint(r.role) === roleKey);
    if (!role) return null;
    return {
      key: roleKey,
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
    // Signatures come from a hero's CLASS, which is never "flex" — filtering by
    // it would silently list the player's damage heroes under the flex bucket.
    if (key === "flex") continue;
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
      stats: top.stats,
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
        {/* Role-spectrum distribution bar (design-book §3f) — one thin
            full-width bar segmented by each role's share of maps played. */}
        <div className="flex flex-col gap-2">
          <div className="flex h-2.5 w-full overflow-hidden rounded-full border border-[color:var(--aqt-border)]" aria-hidden>
            {buckets.map((b) =>
              b.share > 0 ? (
                <div
                  key={b.key}
                  style={{ width: `${b.share * 100}%`, background: ROLE_COLOR[b.key] }}
                  title={`${t(ROLE_LABEL_KEY[b.key] as Parameters<typeof t>[0])} · ${Math.round(b.share * 100)}%`}
                />
              ) : null
            )}
          </div>
          <div className="flex flex-wrap gap-x-3.5 gap-y-1">
            {buckets.map((b) => (
              <span key={b.key} className="inline-flex items-center gap-1.5 text-label text-[color:var(--aqt-fg-muted)]">
                <span className="inline-block h-[7px] w-[7px] rounded-full" style={{ background: ROLE_COLOR[b.key] }} aria-hidden />
                {t(ROLE_LABEL_KEY[b.key] as Parameters<typeof t>[0])}
                <span className="aqt-tnum font-bold text-[color:var(--aqt-fg)]">{b.maps}</span>
                <span className="aqt-tnum text-[color:var(--aqt-fg-faint)]">{Math.round(b.share * 100)}%</span>
              </span>
            ))}
          </div>
        </div>
        <div className="flex flex-col gap-3">
          {buckets.map((b) => (
            <div
              key={b.key}
              className="grid grid-cols-[44px_1fr_auto] items-center gap-3 rounded-[10px] border px-3 py-2.5"
              style={ROLE_ROW[b.key]}
            >
              <DivisionIcon
                division={b.role.division}
                tournamentGrid={b.role.division_grid_version}
                width={44}
                height={44}
              />
              <div>
                <div
                  className="aqt-display flex items-center gap-1.5 text-base font-bold uppercase leading-none tracking-[0.04em]"
                  style={{ color: ROLE_COLOR[b.key] }}
                >
                  <PlayerRoleIcon role={ROLE_ICON[b.key]} size={14} color={ROLE_COLOR[b.key]} decorative />
                  {t(ROLE_LABEL_KEY[b.key] as Parameters<typeof t>[0])}
                  {primary && b.key === primary.key ? (
                    <span className="ml-1 text-label font-semibold tracking-label text-[color:var(--aqt-fg-muted)]"> · {t("users.overview.roleSplit.main")}</span>
                  ) : null}
                </div>
                <div className="aqt-tnum mt-1 text-label text-[color:var(--aqt-fg-muted)]">
                  {b.won}W · {b.lost}L · {t("users.overview.mapsCount", { count: b.maps })}
                </div>
              </div>
              <div className="text-right">
                <div
                  className="aqt-display aqt-tnum text-title font-bold leading-none"
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
                <div className="aqt-tnum mt-0.5 text-label text-[color:var(--aqt-fg-dim)]">
                  {formatPercent(b.share)} {t("users.overview.roleSplit.ofPool")}
                </div>
              </div>
            </div>
          ))}
        </div>
        {signatures.length > 0 ? (
          <div className="flex flex-col gap-2 border-t border-[color:var(--aqt-border)] pt-3.5">
            <span className="aqt-tnum text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
              {t("users.overview.roleSplit.signatureTitle")}
            </span>
            {signatures.map((sig) => {
              const roleName = t(ROLE_LABEL_KEY[sig.key] as Parameters<typeof t>[0]);
              return (
                <div key={sig.key} className="grid grid-cols-[16px_26px_1fr_auto] items-center gap-2.5">
                  <div className="flex justify-center" title={roleName}>
                    <PlayerRoleIcon role={ROLE_ICON[sig.key]} size={14} color={ROLE_COLOR[sig.key]} />
                  </div>
                  <HeroImage
                    hero={sig.hero}
                    size={26}
                    title={sig.hero.name}
                    popover={<HeroUserStatsPopover hero={sig.hero} stats={sig.stats} />}
                  />
                  <div className="min-w-0">
                    <div className="truncate text-caption font-bold text-[color:var(--aqt-fg)]">{sig.hero.name}</div>
                    <div className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
                      {hasGamesData && sig.games > 0 ? <>{t("users.overview.roleSplit.games", { count: sig.games })} · </> : null}
                      {sig.kda != null ? t("users.overview.roleSplit.kda", { value: sig.kda.toFixed(2) }) : "—"}
                    </div>
                  </div>
                  {/* Empty when the hero has no winrate sample: an `auto` track
                      collapses to nothing, where a placeholder dash printed a
                      column of three bare em dashes down the card. */}
                  {sig.winPct != null ? (
                    <div
                      className="aqt-display aqt-tnum text-ui font-bold"
                      style={{ color: winrateColor(sig.winPct) }}
                    >
                      {sig.winPct.toFixed(0)}%
                    </div>
                  ) : null}
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
