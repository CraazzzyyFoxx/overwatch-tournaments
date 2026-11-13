"use client";

import { Shuffle, Sprout } from "lucide-react";
import { useTranslations } from "next-intl";

import { PersonLabel } from "@/components/PlayerName";
import { IconTooltip } from "@craazzzyyfoxx/admin-kit/ui/icon-tooltip";
import { cn } from "@/lib/utils";
import type { PlayerVM } from "@/disciplines/overwatch/analytics/useAnalyticsViewModel";

interface PlayerNickProps {
  player: Pick<PlayerVM, "display" | "role" | "is_newcomer" | "is_newcomer_role">;
  /** Size and weight of the nick (a type role); the `#tag` keeps the faint colour. */
  className?: string;
}

/**
 * A player's nick with its BattleTag discriminator in `--aqt-fg-faint` and the
 * newcomer / new-role marks `RosterPlayer` draws (DESIGN.md §4: icons, not "new" chips).
 */
export default function PlayerNick({ player, className }: Readonly<PlayerNickProps>) {
  const t = useTranslations();
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <PersonLabel display={player.display} className={cn("text-[color:var(--aqt-fg)]", className)} />
      {player.is_newcomer ? (
        <IconTooltip label={t("teams.roster.newcomer")} hint={t("teams.roster.newcomerHint")} className="shrink-0">
          <Sprout aria-hidden className="size-4 text-[color:var(--aqt-rose)]" />
        </IconTooltip>
      ) : null}
      {/* A flex player has no role to be new to (the same rule as the Teams tab). */}
      {player.is_newcomer_role && player.role != null ? (
        <IconTooltip
          label={t("teams.roster.newcomerRole")}
          hint={t("teams.roster.newcomerRoleHint")}
          className="shrink-0"
        >
          <Shuffle aria-hidden className="size-4 text-[color:var(--aqt-amber)]" />
        </IconTooltip>
      ) : null}
    </span>
  );
}
