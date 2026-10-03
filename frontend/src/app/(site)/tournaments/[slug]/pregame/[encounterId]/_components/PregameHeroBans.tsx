"use client";

import { useState, type ReactNode } from "react";
import { Ban, Check, ClipboardCopy, History, Shield } from "lucide-react";
import { useTranslations } from "next-intl";

import TeamName, { type TeamNameInput } from "@/components/TeamName";
import { Button } from "@/components/ui/button";
import type { AqtRoleKey } from "@/lib/roster/player-role";
import {
  lobbyCopyText,
  type PickBanRoleGroup,
  type PickBanRoleItem
} from "@/components/pick-ban/pick-ban-model";
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
  /**
   * The earlier map this ban was spent on, when its `lifetime` still covers
   * this one. Nobody acted on it here, so it is badged with its origin rather
   * than read as a ban of this round.
   */
  carriedFromRound: number | null;
}

/** One hero off on a map, as the final bans list shows it. */
export interface PregameBannedHero extends PickBanRoleItem {
  /** Undefined until the hero catalog resolves — the thumb falls back to initials. */
  item: PickBanItemLike | undefined;
}

/** One map's hero board: who banned what, and the final bans. */
export interface PregameHeroBoard {
  /** Null for a flat (round-less) pool: one set of bans covered every map. */
  round: number | null;
  actions: PregameHeroAction[];
  /** Every ban in force on this map, role-grouped — what the lobby disables. */
  banned: PickBanRoleGroup<PregameBannedHero>[];
}

/** One map's worth of hero actions, for replaying a finished series. */
export interface PregameHeroRound extends PregameHeroBoard {
  /** Null alongside a null round — there is no single map to name. */
  mapName: string | null;
  /** The map's catalog entry, for its still. Undefined until the catalog loads. */
  mapItem: PickBanItemLike | undefined;
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
 * be set up in the game lobby before the map starts.
 *
 * Split by side, because a blind step is two independent lists and a captain
 * needs to see that theirs landed: duplicates MERGE into one banned hero on
 * the board, so reading the board alone would show one side a ban short. A ban
 * carried from an earlier map wears its origin instead of a side's colour —
 * nobody spent it here. Under the two columns sits what the lobby actually
 * needs: the final bans, merged and in the game's role order, and a button
 * that puts them on the clipboard.
 */
export function PregameHeroBans({
  board,
  homeName,
  awayName,
  homeTeam,
  awayTeam,
  eyebrow,
  hint
}: Readonly<{
  board: PregameHeroBoard;
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
  const tCommon = useTranslations("common");
  const [copied, setCopied] = useState(false);
  const note = hint === undefined ? t("heroBans.hint") : hint;
  const caption =
    eyebrow === undefined ? (
      <span className="text-label font-bold uppercase tracking-label text-[color:var(--aqt-rose)]">
        {t("heroBans.eyebrow")}
      </span>
    ) : (
      eyebrow
    );

  // Nothing to transfer to the lobby at all — not even an engine-rolled ban.
  if (board.actions.length === 0 && board.banned.length === 0) {
    return null;
  }

  const roleLabel = (role: AqtRoleKey | null) =>
    role == null ? t("heroBans.roleUnknown") : tCommon(`roles.${role}`);
  const bannedHeroes = board.banned.flatMap((group) => group.items);

  // Width is the caller's call: the result screen aligns this with its claim
  // row, the closing screen gives each map a row of its own.
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
          actions={board.actions.filter((action) => action.side === "home")}
        />
        <SideBans
          side="away"
          name={awayName}
          team={awayTeam}
          actions={board.actions.filter((action) => action.side === "away")}
        />
      </div>

      {bannedHeroes.length > 0 ? (
        <div
          data-hero-unavailable
          className="flex flex-col gap-2 rounded-xl border border-dashed border-[color:var(--aqt-rose)]/40 bg-[color:var(--aqt-card-2)]/30 p-2.5"
        >
          <span className="text-xs font-semibold text-[color:var(--aqt-rose)]">
            {board.round != null
              ? t("heroBans.unavailableOn", { n: board.round })
              : t("heroBans.unavailable")}
          </span>
          <ul className="flex flex-wrap gap-1.5">
            {bannedHeroes.map((hero) => (
              <li
                key={hero.itemId}
                data-hero-banned={hero.itemId}
                className="flex min-w-0 items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] py-1 pl-1 pr-2"
              >
                <PickBanItemThumb kind="hero" item={hero.item} name={hero.name} size={22} muted />
                <span className="min-w-0 truncate text-xs font-medium">{hero.name}</span>
              </li>
            ))}
          </ul>
          <Button
            size="sm"
            variant="outline"
            className="self-start"
            onClick={() => {
              void navigator.clipboard?.writeText(lobbyCopyText(board.banned, roleLabel));
              setCopied(true);
            }}
          >
            {copied ? (
              <Check className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            ) : (
              <ClipboardCopy className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            )}
            {copied ? t("heroBans.copied") : t("heroBans.copy")}
          </Button>
        </div>
      ) : null}
    </section>
  );
}

/**
 * One side's committed actions. Rendered even when empty — a step can give a
 * side no ban this round, and a missing column would read as data still
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
                {action.carriedFromRound != null ? (
                  <span
                    data-carried-from={action.carriedFromRound}
                    className="ml-auto flex shrink-0 items-center gap-1 text-label text-[color:var(--aqt-fg-faint)]"
                  >
                    <History className="h-3 w-3" aria-hidden />
                    {t("carried.badge", { n: action.carriedFromRound })}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
