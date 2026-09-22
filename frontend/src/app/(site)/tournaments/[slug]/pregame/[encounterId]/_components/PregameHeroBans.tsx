"use client";

import type { ReactNode } from "react";
import { Ban, Shield } from "lucide-react";
import { useTranslations } from "next-intl";

import TeamName, { type TeamNameInput } from "@/components/TeamName";
import type { AqtRoleKey } from "@/lib/roster/player-role";
import type { PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import { PickBanItemThumb } from "@/components/pick-ban/PickBanItemThumb";
import { cn } from "@/lib/utils";

/** One committed action of a round's hero ban phase, resolved against the catalog. */
export interface PregameHeroAction {
  itemId: number;
  /** Catalog name, or the room's `#id` fallback while it loads. */
  name: string;
  /** Undefined until the hero catalog resolves — the thumb falls back to initials. */
  item: PickBanItemLike | undefined;
  /** Only used to order a side's rows; null when the catalog knows no role. */
  role: AqtRoleKey | null;
  action: "ban" | "protect";
  /** The side that committed it. */
  side: "home" | "away";
}

/** One map's worth of hero actions, for replaying a finished series. */
export interface PregameHeroRound {
  /** Null for a flat (round-less) pool: one set of bans covered every map. */
  round: number | null;
  /** Null alongside a null round — there is no single map to name. */
  mapName: string | null;
  /** The map's catalog entry, for its still. Undefined until the catalog loads. */
  mapItem: PickBanItemLike | undefined;
  actions: PregameHeroAction[];
}

/** Tank-damage-support, the order the game's own hero list uses. */
const ROLE_RANK: Record<AqtRoleKey, number> = { tank: 0, damage: 1, support: 2 };

/** The side's accent, as a class because it colours the team name itself. */
const SIDE_ACCENT = {
  home: "text-[color:var(--aqt-teal)]",
  away: "text-[color:var(--aqt-rose)]"
} as const;

/**
 * The round's hero bans, on the screen where the map is played and reported.
 *
 * The room renders one phase at a time, so the moment the hero grid closes it
 * is gone — and that is exactly when the bans are needed, because they have to
 * be set up in the game lobby before the map starts. Without this the captains
 * had to memorise them (or reopen the room in another tab and read the finished
 * grid) with no screen left showing what was banned.
 *
 * Split by side, not by role: a round commits two to four actions in total, so
 * per-side grouping names who banned what once, in the same home/away geometry
 * (and the same teal/rose accents) as the score claims directly below. Within a
 * side the rows follow the game's role order, and a protect is marked with a
 * shield rather than mixed in as a ban — a protected hero must stay enabled.
 */
export function PregameHeroBans({
  actions,
  homeName,
  awayName,
  homeTeam,
  awayTeam,
  eyebrow,
  hint
}: Readonly<{
  actions: PregameHeroAction[];
  homeName: string;
  awayName: string;
  /** The side's team, for its logo — undefined when the encounter has none. */
  homeTeam: TeamNameInput | null | undefined;
  awayTeam: TeamNameInput | null | undefined;
  /**
   * Replaces the default "bans for this map" caption. Pass `null` to drop it:
   * the closing screen captions each row itself, with the map's own still, so
   * a caption here would name the map twice.
   */
  eyebrow?: ReactNode | null;
  /** Pass `null` to drop the lobby-setup hint: it only applies before a map is played. */
  hint?: string | null;
}>) {
  const t = useTranslations("pickBan.room");
  const note = hint === undefined ? t("heroBans.hint") : hint;
  const caption =
    eyebrow === undefined ? (
      <span className="text-label font-bold uppercase tracking-label text-[color:var(--aqt-rose)]">
        {t("heroBans.eyebrow")}
      </span>
    ) : (
      eyebrow
    );

  if (actions.length === 0) {
    return null;
  }

  // Width is the caller's call: the result screen aligns this with its claim
  // row, the closing screen gives each map a row of its own. Owning a `max-w`
  // here centred the block under a left-aligned heading and left a third of
  // the card empty.
  return (
    <section className="flex w-full flex-col gap-2">
      {caption != null || note != null ? (
        <div className="flex flex-col gap-0.5">
          {caption}
          {note ? (
            <p className="text-xs leading-relaxed text-[color:var(--aqt-fg-muted)]">{note}</p>
          ) : null}
        </div>
      ) : null}
      {/* Stacked below `sm` for the same reason the claim row is: two columns of
          hero names on a phone truncate to initials. */}
      <div className="grid grid-cols-1 items-start gap-2 sm:grid-cols-2 sm:gap-3">
        <SideBans
          side="home"
          name={homeName}
          team={homeTeam}
          actions={actions.filter((action) => action.side === "home")}
        />
        <SideBans
          side="away"
          name={awayName}
          team={awayTeam}
          actions={actions.filter((action) => action.side === "away")}
        />
      </div>
    </section>
  );
}

/**
 * One side's committed actions. Rendered even when empty — a sequence can give
 * a side no ban this round, and a missing column would read as data still
 * loading rather than as nothing to transfer.
 */
function SideBans({
  side,
  name,
  team,
  actions
}: Readonly<{
  side: "home" | "away";
  name: string;
  team: TeamNameInput | null | undefined;
  actions: PregameHeroAction[];
}>) {
  const t = useTranslations("pickBan.room");
  const accent = SIDE_ACCENT[side];
  const ordered = [...actions].sort(
    (left, right) =>
      (left.action === "ban" ? 0 : 1) - (right.action === "ban" ? 0 : 1) ||
      (left.role ? ROLE_RANK[left.role] : 3) - (right.role ? ROLE_RANK[right.role] : 3) ||
      left.name.localeCompare(right.name)
  );

  return (
    <div
      data-hero-bans={side}
      className="flex flex-col gap-1.5 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card-2)]/40 p-2.5"
    >
      <TeamName
        team={team}
        fallback={name}
        size="sm"
        className="gap-1.5"
        nameClassName={cn("text-xs font-semibold", accent)}
      />

      {ordered.length === 0 ? (
        <span className="px-0.5 py-1 text-xs text-[color:var(--aqt-fg-faint)]">
          {t("heroBans.none")}
        </span>
      ) : (
        <ul className="flex flex-col gap-1">
          {ordered.map((action) => {
            const banned = action.action === "ban";
            const Icon = banned ? Ban : Shield;
            return (
              <li
                key={`${action.action}-${action.itemId}`}
                data-hero-action={action.action}
                className="flex min-w-0 items-center gap-2"
              >
                <Icon
                  aria-hidden
                  className={cn(
                    "h-3.5 w-3.5 shrink-0",
                    banned ? "text-[color:var(--aqt-rose)]" : "text-[color:var(--aqt-amber)]"
                  )}
                />
                <PickBanItemThumb
                  kind="hero"
                  item={action.item}
                  name={action.name}
                  size={26}
                  muted={banned}
                />
                {/* The icon is decorative, so the state has to reach a screen
                    reader as text — it is the difference between "disable this"
                    and "leave this in". */}
                <span className="sr-only">{t(`heroBans.state.${action.action}`)}</span>
                <span
                  className={cn(
                    "min-w-0 truncate text-sm",
                    banned ? "font-semibold" : "font-medium text-[color:var(--aqt-fg-muted)]"
                  )}
                  title={action.name}
                >
                  {action.name}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
