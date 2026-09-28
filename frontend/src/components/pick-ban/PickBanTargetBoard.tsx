"use client";

import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Badge } from "@/components/ui/badge";
import { normalizePlayerRole } from "@/lib/roster/player-role";
import { formatSubroleSlug } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import type { PickBanTarget } from "@/types/tournament.types";

import type { PickBanItemLike } from "./PickBanGrid";
import { PickBanItemThumb } from "./PickBanItemThumb";

/**
 * The opponent's roster, as the board a per-player ban step is played on.
 *
 * A targeted step ("one ban per opponent player, and the hero's class must
 * match that player's role") is not a pool choice with a note attached: the
 * captain picks WHO first, and only then which hero — the legal heroes differ
 * per row. Selecting a row is what narrows the grid (`eligible.by_target`), and
 * a row that already holds an assignment shows it, so five bans over five
 * players never need counting back from the tray.
 */
export function PickBanTargetBoard({
  targets,
  selectedPlayerId,
  assignedByPlayer,
  itemsById,
  onSelect,
  teamName,
  disabled = false
}: Readonly<{
  targets: PickBanTarget[];
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

  return (
    <section
      data-pick-ban-targets
      className="flex flex-col gap-2 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card-2)]/40 p-3"
    >
      <div className="flex flex-col gap-0.5">
        <span className="text-label font-bold uppercase tracking-label text-[color:var(--aqt-rose)]">
          {t("target.eyebrow")}
        </span>
        <p className="text-xs text-[color:var(--aqt-fg-muted)]">
          {t("target.hint", { team: teamName })}
        </p>
      </div>
      <ul className="flex flex-col gap-1.5">
        {targets.map((target) => {
          const assignedId = assignedByPlayer[target.player_id];
          const assigned = assignedId != null ? itemsById[assignedId] : undefined;
          const assignedName =
            assignedId != null
              ? (assigned?.name ?? t("hero.itemNumber", { id: assignedId }))
              : null;
          const selected = selectedPlayerId === target.player_id;
          return (
            <li key={target.player_id}>
              <button
                type="button"
                disabled={disabled}
                data-target-player={target.player_id}
                aria-pressed={selected}
                onClick={() => onSelect(target.player_id)}
                className={cn(
                  "flex w-full min-w-0 items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left text-sm outline-none transition-shadow",
                  selected
                    ? "border-[color:var(--aqt-teal)] ring-2 ring-[color:var(--aqt-teal)]/40"
                    : "border-[color:var(--aqt-border)]",
                  disabled
                    ? "cursor-default opacity-70"
                    : "cursor-pointer hover:border-[color:var(--aqt-teal)]/60 focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
                )}
              >
                <PlayerRoleIcon role={normalizePlayerRole(target.role)} size={16} decorative />
                <span className="min-w-0 flex-1 truncate font-medium">{target.name}</span>
                {target.sub_role ? (
                  <Badge
                    variant="outline"
                    className="shrink-0 px-1.5 py-0 text-label font-normal text-[color:var(--aqt-fg-muted)]"
                  >
                    {formatSubroleSlug(target.sub_role)}
                  </Badge>
                ) : null}
                {target.is_substitution ? (
                  <Badge
                    variant="secondary"
                    className="shrink-0 px-1.5 py-0 text-label font-normal"
                  >
                    {t("target.sub")}
                  </Badge>
                ) : null}
                {assignedName != null ? (
                  <span className="flex shrink-0 items-center gap-1.5">
                    <PickBanItemThumb
                      kind="hero"
                      item={assigned}
                      name={assignedName}
                      size={22}
                      muted
                    />
                    <span className="hidden max-w-[7rem] truncate text-xs text-[color:var(--aqt-fg-muted)] sm:inline">
                      {assignedName}
                    </span>
                  </span>
                ) : (
                  <span className="shrink-0 text-xs text-[color:var(--aqt-fg-faint)]">
                    {t("target.empty")}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
