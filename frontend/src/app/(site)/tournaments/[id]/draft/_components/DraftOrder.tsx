"use client";

import { Check, Clock3 } from "lucide-react";
import { useTranslations } from "next-intl";

import { HeroCoord } from "@/components/site/PageHero";
import { cn } from "@/lib/utils";
import type { DraftPick, DraftPlayer, DraftTeam } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

interface DraftOrderProps {
  picks: DraftPick[];
  teams: DraftTeam[];
  players: DraftPlayer[];
  compact?: boolean;
  /** Accepted but not yet consumed here — Task 12 wires division icons into the order list. */
  divisionGrid: DivisionGrid;
}

export function DraftOrder({ picks, teams, players, compact = false }: DraftOrderProps) {
  const t = useTranslations("draftRedesign");
  const teamById = new Map(teams.map((team) => [team.id, team]));
  const playerById = new Map(players.map((player) => [player.id, player]));
  const sorted = [...picks].sort((left, right) => left.overall_no - right.overall_no);
  return (
    <section aria-labelledby="draft-order-heading">
      <div className="flex items-end justify-between gap-3 border-b border-[color:var(--aqt-border)] pb-3">
        <div>
          <HeroCoord>{t("sequence")}</HeroCoord>
          <h2 id="draft-order-heading" className="mt-1 font-onest text-lg font-semibold">{t("draftOrder")}</h2>
        </div>
        <span className="font-mono text-xs text-[color:var(--aqt-fg-muted)]">{picks.length}</span>
      </div>
      <ol className={cn("mt-2 divide-y divide-[color:var(--aqt-border)]", compact && "max-h-[520px] overflow-y-auto") }>
        {sorted.map((pick) => {
          const team = teamById.get(pick.draft_team_id);
          const player = pick.picked_player_id == null ? null : playerById.get(pick.picked_player_id);
          const done = pick.status === "completed" || pick.status === "autopicked";
          return (
            <li key={pick.id} className={cn("grid min-h-12 grid-cols-[2rem_1fr_auto] items-center gap-2 py-2", pick.status === "on_clock" && "text-[color:var(--aqt-teal)]") }>
              <span className="font-mono text-xs tabular-nums text-[color:var(--aqt-fg-faint)]">{pick.overall_no}</span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium">{player?.battle_tag ?? team?.name ?? t("pending")}</span>
                <span className="block truncate text-xs text-[color:var(--aqt-fg-muted)]">{team?.name ?? t("unknownTeam")}</span>
              </span>
              {done ? <Check className="h-4 w-4 text-[color:var(--aqt-support)]" /> : pick.status === "on_clock" ? <Clock3 className="h-4 w-4" /> : <span className="h-1.5 w-1.5 rounded-full bg-[color:var(--aqt-fg-faint)]" aria-label={t("pending")} />}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

