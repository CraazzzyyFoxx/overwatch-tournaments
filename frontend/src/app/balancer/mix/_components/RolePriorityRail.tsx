"use client";

import { ROLE_ICON_COLOR } from "@/app/balancer/mix/pickup-chrome";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { ROLE_LABELS, ROLES } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import type { CustomGamePlayer, CustomGamePlayerPatch } from "@/services/custom-game.service";

import { LINEUP_ROLES, resolveRoleOrder, toggleRole } from "../pickup-lineup";

/**
 * The roles a player can be seated in, in the order the host set them.
 *
 * Three facts in one 102px rail, none of them a number: **which** roles the
 * balancer may use (a tinted tile vs a flat dim glyph), **which one comes
 * first** (the role-coloured underline, and leftmost position), and **which
 * selection will fail** (the amber ring — a role switched on with no rank
 * behind it, which rejects the whole run server-side).
 *
 * The order is the balancer's stored priority (see `resolveRoleOrder`), so a
 * click here only ever turns a role on or off — reordering belongs to the
 * player sheet, which has room for a drag list.
 */
export function RolePriorityRail({
  row,
  label,
  canWrite,
  saving,
  onPatch
}: Readonly<{
  row: CustomGamePlayer;
  label: string;
  canWrite: boolean;
  saving: boolean;
  onPatch: (patch: CustomGamePlayerPatch) => void;
}>) {
  const order = resolveRoleOrder(row);
  // Off roles trail the selected ones in canonical order: an unselected role
  // has no priority, so placing them at all would imply one.
  const off = LINEUP_ROLES.filter((role) => !order.includes(role));

  return (
    <div
      role="group"
      aria-label={`Roles for ${label}`}
      className="flex w-[102px] shrink-0 items-center justify-end gap-1.5"
    >
      {[...order, ...off].map((role) => {
        const position = order.indexOf(role);
        const isOn = position !== -1;
        const isPrimary = position === 0;
        const roleRank = row.ranks[role];
        const icon = ROLES.find((item) => item.code === role)?.icon ?? "Support";
        return (
          <button
            key={role}
            type="button"
            disabled={!canWrite || saving}
            aria-pressed={isOn}
            aria-label={`${ROLE_LABELS[role]} for ${label}, ${
              isOn ? (isPrimary ? "first choice" : "also plays") : "off"
            }${roleRank == null ? ", no rank" : `, ${roleRank} points`}`}
            title={
              roleRank == null
                ? `${ROLE_LABELS[role]}: no rank`
                : `${ROLE_LABELS[role]}: ${roleRank} pts`
            }
            onClick={() => onPatch({ roles: toggleRole(order, role) })}
            className={cn(
              "relative flex size-[30px] shrink-0 items-center justify-center rounded-lg transition-opacity",
              isOn ? "opacity-100" : "opacity-30",
              isOn && roleRank == null && "ring-1 ring-amber-400/70",
              "disabled:cursor-default"
            )}
          >
            <PlayerRoleIcon
              role={icon}
              size={19}
              decorative
              color={isOn ? ROLE_ICON_COLOR[role] : undefined}
            />
          </button>
        );
      })}
    </div>
  );
}
