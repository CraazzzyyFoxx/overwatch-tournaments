"use client";

import { Ban, History, Shield } from "lucide-react";
import { useTranslations } from "next-intl";

import TeamName from "@/components/TeamName";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { classRank } from "./pick-ban-model";
import { PickBanItemThumb } from "./PickBanItemThumb";
import { seatTeam, seatsBySlot } from "@/lib/encounter/seats";
import { cn } from "@/lib/utils";
import type { EncounterTeam } from "@/types/encounter.types";

import type { PregameCharacterAction, SlotProps } from "@/disciplines/types";

/**
 * The `pregameCharacterBans` slot of a game whose draft is not typed into a custom-game lobby (League, Deadlock):
 * the round's character bans, on the screen where the game is played and reported. Split by team (a blind step is
 * two lists, and a duplicate merges into one ban on the board), then the final bans of this game. A preset that bans
 * nothing leaves the board empty and this renders nothing. Core, not a module: several modules render it, and a
 * module never imports another (Z7).
 */
export default function CharacterBansBoard({
  board,
  teams,
  eyebrow,
  hint,
  metadata
}: Readonly<SlotProps["pregameCharacterBans"]>) {
  const characterClasses = metadata.discipline.character_classes;
  const t = useTranslations("pickBan.room");
  const caption =
    eyebrow === undefined ? (
      <span className={cn(eyebrowClass(), "text-[color:var(--aqt-rose)]")}>
        {t("characterBans.eyebrow")}
      </span>
    ) : (
      eyebrow
    );

  if (board.actions.length === 0 && board.banned.length === 0) {
    return null;
  }

  const banned = board.banned.flatMap((group) => group.items);

  return (
    <section className="flex w-full flex-col gap-2">
      {caption != null || hint ? (
        <div className="flex flex-col gap-0.5">
          {caption}
          {hint ? <p className="text-xs leading-relaxed text-[color:var(--aqt-fg-muted)]">{hint}</p> : null}
        </div>
      ) : null}
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

      {banned.length > 0 ? (
        <div
          data-character-unavailable
          className="flex flex-col gap-2 rounded-xl border border-dashed border-[color:var(--aqt-rose)]/40 bg-[color:var(--aqt-card-2)]/30 p-2.5"
        >
          <span className="text-xs font-semibold text-[color:var(--aqt-rose)]">
            {board.round != null
              ? t("heroBans.unavailableOn", { n: board.round })
              : t("heroBans.unavailable")}
          </span>
          <ul className="flex flex-wrap gap-1.5">
            {banned.map((champion) => (
              <li
                key={champion.itemId}
                data-character-banned={champion.itemId}
                className="flex min-w-0 items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] py-1 pl-1 pr-2"
              >
                <PickBanItemThumb kind="hero" item={champion.item} name={champion.name} size={22} muted />
                <span className="min-w-0 truncate text-xs font-medium">{champion.name}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/** One team's committed bans and protects, in the game's class order; rendered even when empty. */
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
  const accent = seat.slot === 1 ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-rose)]";
  const ordered = [...actions].sort(
    (left, right) =>
      (left.action === "ban" ? 0 : 1) - (right.action === "ban" ? 0 : 1) ||
      classRank(left.group, characterClasses) - classRank(right.group, characterClasses) ||
      left.name.localeCompare(right.name)
  );

  return (
    <div
      data-character-bans={seat.slot}
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
        <span className="px-0.5 py-1 text-xs text-[color:var(--aqt-fg-faint)]">{t("heroBans.none")}</span>
      ) : (
        <ul className="flex flex-col gap-1">
          {ordered.map((action) => {
            const isBan = action.action === "ban";
            const Icon = isBan ? Ban : Shield;
            return (
              <li
                key={`${action.action}-${action.itemId}`}
                data-character-action={action.action}
                className="flex min-w-0 items-center gap-2"
              >
                <Icon
                  aria-hidden
                  className={cn(
                    "h-3.5 w-3.5 shrink-0",
                    isBan ? "text-[color:var(--aqt-rose)]" : "text-[color:var(--aqt-amber)]"
                  )}
                />
                <PickBanItemThumb kind="hero" item={action.item} name={action.name} size={26} muted={isBan} />
                <span className="sr-only">{t(`heroBans.state.${action.action}`)}</span>
                <span
                  className={cn(
                    "min-w-0 truncate text-sm",
                    isBan ? "font-semibold" : "font-medium text-[color:var(--aqt-fg-muted)]"
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
