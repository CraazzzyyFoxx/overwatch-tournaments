import type { useTranslations } from "next-intl";

import { LogStatsName } from "@/types/stats.types";

/**
 * The one named translator contract for this tree. Consumers import `Translate`
 * rather than restating `ReturnType<...>` at each site.
 *
 * It has to be derived: neither `next-intl` nor `use-intl` exports a translator
 * type — next-intl's own `useTranslations.d.ts` is itself
 * `ReturnType<typeof useTranslationsType>` — so there is no upstream name to
 * import. Declaring it once here is the closest thing to owning it.
 */
export type Translate = ReturnType<typeof useTranslations<never>>;

/**
 * Maps a role type to its shared `common.roles.*` message key.
 * Re-exported under this tree's historical name so there is exactly one role
 * label map in the codebase — the canonical one in `@/lib/roster/player-role`.
 */
export { PLAYER_ROLE_LABEL_KEY as ROLE_LABEL_KEY } from "@/lib/roster/player-role";

export type HeroMetricLabelKey =
  | "users.list.heroMetrics.elims"
  | "users.list.heroMetrics.fb"
  | "users.list.heroMetrics.dmg"
  | "users.list.heroMetrics.heal";

// Maps a raw log-stat name to its compact metric message key (or undefined for
// names without a localized label, in which case the raw name is shown).
export const HERO_METRIC_LABEL_KEYS: Record<string, HeroMetricLabelKey> = {
  [LogStatsName.Eliminations]: "users.list.heroMetrics.elims",
  [LogStatsName.FinalBlows]: "users.list.heroMetrics.fb",
  [LogStatsName.HeroDamageDealt]: "users.list.heroMetrics.dmg",
  [LogStatsName.HealingDealt]: "users.list.heroMetrics.heal"
};

export const parsePositiveInt = (value: string | null, fallback: number): number => {
  if (!value) return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return Math.floor(parsed);
};

export const parseOptionalInt = (value: string | null): number | undefined => {
  if (!value) return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return undefined;
  return Math.floor(parsed);
};

export const formatOptional = (value: number | null): string => {
  if (value === null) return "-";
  return value.toFixed(2);
};

export const formatPlaytime = (seconds: number, t: Translate): string => {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return t("users.list.hero.playtimeFormat", {
    h: String(hours),
    m: String(minutes),
    s: String(secs)
  });
};

/**
 * Compact, language-neutral handle for a tournament in dense UI (chart axis
 * ticks, encounter chips). Tournament names are long and frequently non-Latin
 * ("Турнір Сабов Анакq #42"), so the previous `name.slice(0, 3 | 4)` emitted a
 * row of identical stubs — "ТУР" on every encounter row, "Турн" on most axis
 * ticks — which render as Latin "TYP"/"TypH" in the display face and carry no
 * information. The trailing "#N" is the handle players actually use; league legs
 * fall back to their numbered leg ("… | Day 3" → "D3").
 *
 * Returns `null` when the name yields nothing meaningful, so callers can omit
 * the label instead of printing a truncation.
 */
export const tournamentTag = (name: string): string | null => {
  const numbered = /#\s*(\d+)/.exec(name);
  if (numbered) return `T${numbered[1]}`;
  const leg = /\|\s*(.+)$/.exec(name);
  if (!leg) return null;
  const legNumber = /(\d+)/.exec(leg[1]);
  return legNumber ? `D${legNumber[1]}` : null;
};
