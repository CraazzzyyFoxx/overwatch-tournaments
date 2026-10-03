"use client";

import { Ban, Repeat2 } from "lucide-react";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { getDivisionLabel } from "@/lib/divisions/grid";
import { normalizePlayerRole, PLAYER_ROLE_LABEL_KEY } from "@/lib/roster/player-role";
import { formatSubroleSlug } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import type { PickBanTarget } from "@/types/tournament.types";

import type { PickBanItemLike } from "./PickBanGrid";
import { PickBanItemThumb } from "./PickBanItemThumb";
import { PickBanPlayerHeroes } from "./PickBanPlayerHeroes";

/**
 * The opponent's roster, as the board a per-player ban step is played on.
 *
 * A targeted step ("one ban per opponent player, and the hero's class must
 * match that player's role") is not a pool choice with a note attached: the
 * captain picks WHO first, and only then which hero — the legal heroes differ
 * per row. Selecting a row is what narrows the grid (`eligible.by_target`), and
 * a row that already holds an assignment shows it, so five bans over five
 * players never need counting back from the tray.
 *
 * The ban slot is the one loud thing here: an assigned hero keeps its colour
 * inside a rose ring, an open slot is the same dashed circle the draft tray
 * draws — so the column of slots reads as "done / still to do" at a glance.
 */
export function PickBanTargetBoard({
  targets,
  previousMatchId,
  selectedPlayerId,
  assignedByPlayer,
  itemsById,
  onSelect,
  teamName,
  disabled = false
}: Readonly<{
  targets: PickBanTarget[];
  previousMatchId: number | null;
  selectedPlayerId: number | null;
  /** Item id already assigned to a player in the viewer's own draft. */
  assignedByPlayer: Record<number, number | undefined>;
  itemsById: Record<number, PickBanItemLike | undefined>;
  onSelect: (playerId: number) => void;
  /** The opponent's team name — whose roster this is. */
  teamName: string;
  /** True once the draft is locked: the rows stay readable, they stop moving. */
  disabled?: boolean;
}>) {
  const t = useTranslations("pickBan.room");
  const tRoot = useTranslations();
  const divisionGrid = useDivisionGrid();

  return (
    <Card data-pick-ban-targets>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t("target.title")}</CardTitle>
        <p className="text-sm text-[color:var(--aqt-fg-muted)]">
          {t("target.hint", { team: teamName })}
        </p>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-2">
          {targets.map((target) => {
            const assignedId = assignedByPlayer[target.player_id];
            const assigned = assignedId != null ? itemsById[assignedId] : undefined;
            const assignedName =
              assignedId != null
                ? (assigned?.name ?? t("hero.itemNumber", { id: assignedId }))
                : null;
            const selected = selectedPlayerId === target.player_id;
            const role = target.role != null ? normalizePlayerRole(target.role) : null;
            const roleText = target.sub_role
              ? formatSubroleSlug(target.sub_role)
              : role != null
                ? tRoot(PLAYER_ROLE_LABEL_KEY[role])
                : null;
            return (
              <li
                key={target.player_id}
                className={cn(
                  "rounded-lg border transition-colors",
                  selected
                    ? "border-[color:var(--aqt-teal)]/60 bg-[color:var(--aqt-teal)]/10"
                    : "border-[color:var(--aqt-border)]",
                  !disabled ? "hover:border-[color:var(--aqt-teal)]/50" : null
                )}
              >
                <button
                  type="button"
                  disabled={disabled}
                  data-target-player={target.player_id}
                  aria-pressed={selected}
                  onClick={() => onSelect(target.player_id)}
                  className={cn(
                    "flex w-full min-w-0 items-center gap-3 rounded-lg px-3 py-2.5 text-left outline-none",
                    disabled
                      ? "cursor-default opacity-70"
                      : "cursor-pointer focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
                  )}
                >
                  <span
                    className="shrink-0"
                    title={getDivisionLabel(divisionGrid, target.division) ?? undefined}
                  >
                    <DivisionIcon division={target.division} width={30} height={30} />
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="truncate text-sm font-semibold">{target.name}</span>
                    <span className="flex min-w-0 items-center gap-2.5 text-xs text-[color:var(--aqt-fg-muted)]">
                      {roleText != null ? (
                        <span className="flex min-w-0 items-center gap-1">
                          <PlayerRoleIcon role={role} size={12} decorative />
                          <span className="truncate">{roleText}</span>
                        </span>
                      ) : null}
                      {target.is_substitution ? (
                        <span className="flex shrink-0 items-center gap-1">
                          <Repeat2 className="h-3 w-3" aria-hidden />
                          {t("target.sub")}
                        </span>
                      ) : null}
                    </span>
                  </span>
                  <span
                    className={cn(
                      "sr-only max-w-[7rem] truncate text-sm sm:not-sr-only",
                      assignedName != null
                        ? "font-medium"
                        : selected
                          ? "text-[color:var(--aqt-teal)]"
                          : "text-[color:var(--aqt-fg-muted)]"
                    )}
                  >
                    {assignedName ?? t("target.empty")}
                  </span>
                  {assignedName != null ? (
                    <span
                      aria-hidden
                      className="relative shrink-0 rounded-full ring-2 ring-[color:var(--aqt-rose)] ring-offset-2 ring-offset-[color:var(--aqt-card)]"
                    >
                      <PickBanItemThumb kind="hero" item={assigned} name={assignedName} size={32} />
                      <span className="absolute -bottom-1 -right-1 grid h-4 w-4 place-items-center rounded-full bg-[color:var(--aqt-rose)] text-[color:var(--aqt-card)]">
                        <Ban className="h-2.5 w-2.5" strokeWidth={3} />
                      </span>
                    </span>
                  ) : (
                    <span
                      aria-hidden
                      className={cn(
                        "h-8 w-8 shrink-0 rounded-full border border-dashed",
                        selected
                          ? "border-[color:var(--aqt-teal)]"
                          : "border-[color:var(--aqt-border-3)]"
                      )}
                    />
                  )}
                </button>
                <PickBanPlayerHeroes
                  playerId={target.player_id}
                  matchId={previousMatchId}
                />
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
