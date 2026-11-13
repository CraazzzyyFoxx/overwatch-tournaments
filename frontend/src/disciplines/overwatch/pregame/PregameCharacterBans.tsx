"use client";

import { useState } from "react";
import { Ban, Check, ClipboardCopy, History, Shield } from "lucide-react";
import { useTranslations } from "next-intl";

import TeamName from "@/components/TeamName";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { classRank, lobbyCopyText } from "@/components/pick-ban/pick-ban-model";
import { PickBanItemThumb } from "@/components/pick-ban/PickBanItemThumb";
import { seatTeam, seatsBySlot } from "@/lib/encounter/seats";
import { cn } from "@/lib/utils";
import type { EncounterTeam } from "@/types/encounter.types";

import type { PregameCharacterAction, SlotProps } from "../../types";

/**
 * The Overwatch `pregameCharacterBans` slot: the round's hero bans, on the screen where the map is
 * played and reported.
 *
 * The room renders one phase at a time, so the moment the hero grid closes it
 * is gone — and that is exactly when the bans are needed, because they have to
 * be set up in the game lobby before the map starts.
 *
 * Split by team, because a blind step is two independent lists and a captain
 * needs to see that theirs landed: duplicates MERGE into one banned hero on
 * the board, so reading the board alone would show one team a ban short. A ban
 * carried from an earlier map wears its origin instead of a team's colour —
 * nobody spent it here. Under the two columns sits what the lobby actually
 * needs: the final bans, merged and in the game's role order, and a button
 * that puts them on the clipboard.
 */
export default function PregameCharacterBans({
  board,
  teams,
  eyebrow,
  hint,
  metadata
}: Readonly<SlotProps["pregameCharacterBans"]>) {
  const characterClasses = metadata.discipline.character_classes;
  const t = useTranslations("pickBan.room");
  const tCommon = useTranslations("common");
  const [copied, setCopied] = useState(false);
  const note = hint === undefined ? t("heroBans.hint") : hint;
  const caption =
    eyebrow === undefined ? (
      <Eyebrow className="text-[color:var(--aqt-rose)]">{t("heroBans.eyebrow")}</Eyebrow>
    ) : (
      eyebrow
    );

  // Nothing to transfer to the lobby at all — not even an engine-rolled ban.
  if (board.actions.length === 0 && board.banned.length === 0) {
    return null;
  }

  const groupLabel = (group: string | null) => {
    if (group == null) return t("heroBans.roleUnknown");
    // A class code is catalog data; only a code that has a localized word gets one.
    const key = `roles.${group}` as "roles.tank";
    return tCommon.has(key) ? tCommon(key) : group;
  };
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
        {seatsBySlot(teams).map((seat) => (
          <TeamBans
            key={seat.id}
            seat={seat}
            actions={board.actions.filter((action) => action.teamId === seat.id)}
            characterClasses={characterClasses}
          />
        ))}
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
              void navigator.clipboard?.writeText(lobbyCopyText(board.banned, groupLabel));
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
 * One team's committed actions. Rendered even when empty — a step can give a
 * team no ban this round, and a missing column would read as data still
 * loading rather than as nothing to transfer.
 */
function TeamBans({
  seat,
  actions,
  characterClasses
}: Readonly<{
  seat: EncounterTeam;
  actions: PregameCharacterAction[];
  characterClasses: readonly string[];
}>) {
  const t = useTranslations("pickBan.room");
  // The seat's accent colours the team name itself (slot 1 teal, others rose).
  const accent = seat.slot === 1 ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-rose)]";
  const ordered = [...actions].sort(
    (left, right) =>
      (left.action === "ban" ? 0 : 1) - (right.action === "ban" ? 0 : 1) ||
      classRank(left.group, characterClasses) - classRank(right.group, characterClasses) ||
      left.name.localeCompare(right.name)
  );

  return (
    <div
      data-hero-bans={seat.slot}
      className="flex flex-col gap-1.5 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card-2)]/40 p-2.5"
    >
      <TeamName
        team={seatTeam(seat)}
        fallback={seat.name}
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
