import { X } from "lucide-react";

import { EYEBROW_CLASS, ROLE_ICON_COLOR } from "@/app/balancer/mix/pickup-chrome";
import { splitBattleTag } from "@/components/balancer/balancer-page-helpers";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { ROLES, ROLE_LABELS } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import type { CustomGamePlayer } from "@/services/custom-game.service";

import {
  LOBBY_SIZE,
  averageRank,
  playerLabel,
  resolveRoleOrder,
  sortLineup,
  summarizeLineup,
  summarizeRoleSupply
} from "../pickup-lineup";

/**
 * The lineup, as the right half of the picker: seat count against a full
 * lobby, role supply against demand, and who is already in.
 *
 * It lives beside the roster rather than behind it so every click on the left
 * answers "have I got a lobby" without closing the dialog -- the whole reason
 * the picker stopped being a single-column overlay.
 */
export function MixLineupAside({
  rows,
  canWrite,
  onTogglePlayer,
  onDone
}: Readonly<{
  rows: CustomGamePlayer[];
  canWrite: boolean;
  onTogglePlayer: (memberId: number) => void;
  onDone: () => void;
}>) {
  const summary = summarizeLineup(rows);
  const supply = summarizeRoleSupply(rows);
  const overflow = summary.active - LOBBY_SIZE;

  return (
    <aside className="flex min-h-0 flex-col border-t border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] lg:border-l lg:border-t-0">
      <div className="flex shrink-0 items-baseline gap-2 px-4 pb-2.5 pt-3.5">
        <h3 className={EYEBROW_CLASS}>In this mix</h3>
        <span className="ml-auto flex items-baseline gap-1 tabular-nums">
          <span
            className={cn(
              "text-xl font-bold leading-none",
              overflow > 0
                ? "text-[color:var(--aqt-amber)]"
                : summary.active === LOBBY_SIZE
                  ? "text-[color:var(--aqt-teal)]"
                  : "text-[color:var(--aqt-fg)]"
            )}
          >
            {summary.active}
          </span>
          <span className="text-caption text-[color:var(--aqt-fg-faint)]">{`/ ${LOBBY_SIZE}`}</span>
        </span>
      </div>

      {/* The instrument panel. Supply against demand per role, counted the
          way the solver counts it, so "short one tank" is visible before
          Balance runs rather than inferred from a seated lineup after. */}
      <div className="grid shrink-0 grid-cols-3 gap-1.5 px-4 pb-3">
        {supply.map((entry) => {
          const icon = ROLES.find((role) => role.code === entry.role)?.icon ?? "Support";
          const short = entry.short > 0;
          return (
            <div
              key={entry.role}
              title={
                short
                  ? `${ROLE_LABELS[entry.role]}: ${entry.supply} of ${entry.need} — short ${entry.short}`
                  : `${ROLE_LABELS[entry.role]}: ${entry.supply} of ${entry.need}`
              }
              className="rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] px-2 pb-1.5 pt-1.5"
            >
              <div className="flex items-center gap-1">
                <PlayerRoleIcon role={icon} size={13} decorative />
                <span
                  className={cn(
                    "ml-auto text-label font-semibold tabular-nums",
                    short ? "text-[color:var(--aqt-amber)]" : "text-[color:var(--aqt-emerald)]"
                  )}
                >
                  {`${entry.supply}/${entry.need}`}
                </span>
              </div>
              <div className="mt-1 h-[3px] overflow-hidden rounded-full bg-[color:var(--aqt-overlay-3)]">
                <div
                  className={cn(
                    "h-full rounded-full transition-[width] duration-200",
                    short ? "bg-[color:var(--aqt-amber)]" : "bg-[color:var(--aqt-emerald)]"
                  )}
                  style={{
                    width: `${Math.min(100, Math.round((entry.supply / entry.need) * 100))}%`
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto border-t border-[color:var(--aqt-border)] px-2 py-1.5">
        {rows.length === 0 ? (
          <p className="px-2 py-8 text-center text-caption text-[color:var(--aqt-fg-dim)]">
            Nobody yet. Pick from the left, or press Enter on the highlighted row.
          </p>
        ) : (
          <ul className="space-y-0.5" aria-label="Players in this mix">
            {sortLineup(rows).map((row) => (
              <LineupChip
                key={row.workspace_member_id}
                row={row}
                canWrite={canWrite}
                onRemove={() => onTogglePlayer(row.workspace_member_id)}
              />
            ))}
          </ul>
        )}
      </div>

      <div className="flex h-14 shrink-0 items-center gap-3 border-t border-[color:var(--aqt-border)] px-4">
        <p className="min-w-0 flex-1 text-label leading-tight text-[color:var(--aqt-fg-dim)]">
          {overflow > 0
            ? `${overflow} over a full lobby \u2014 bench the rest in the lineup.`
            : overflow === 0
              ? "A full lobby. Balance is ready to run."
              : `${-overflow} more for a full lobby.`}
        </p>
        <Button type="button" className="h-9 shrink-0" onClick={onDone}>
          Done
        </Button>
      </div>
    </aside>
  );
}

/**
 * One seated player, as the right column shows them: who, what they can play in
 * what order, what they are worth, and the way out.
 *
 * The role glyphs carry no numbers and no controls. Priority here is the
 * host-set order (`resolveRoleOrder`) so this list and the lineup panel behind
 * the dialog cannot disagree about what a player plays first, and editing
 * belongs to the lineup sheet, which has the room for it.
 */
function LineupChip({
  row,
  canWrite,
  onRemove
}: Readonly<{ row: CustomGamePlayer; canWrite: boolean; onRemove: () => void }>) {
  const label = playerLabel(row);
  const { name, suffix } = splitBattleTag(label);
  const order = resolveRoleOrder(row);
  const rank = averageRank(row);

  return (
    <li
      className={cn(
        "group flex items-center gap-2 rounded-lg px-2 py-1.5 transition-colors hover:bg-[color:var(--aqt-overlay-2)]",
        row.participation === "benched" && "opacity-55"
      )}
    >
      <span className="flex min-w-0 flex-1 items-baseline gap-1">
        <span
          className="truncate text-caption font-semibold text-[color:var(--aqt-fg)]"
          title={label}
        >
          {name}
        </span>
        {suffix ? (
          <span className="shrink-0 text-label text-[color:var(--aqt-fg-faint)]">{suffix}</span>
        ) : null}
      </span>

      <span aria-hidden="true" className="flex shrink-0 items-center gap-0.5">
        {ROLES.map((role) => {
          const position = order.indexOf(role.code);
          const isOn = position !== -1;
          return (
            <span
              key={role.code}
              className={cn("flex size-5 items-center justify-center rounded", !isOn && "opacity-20")}
            >
              <PlayerRoleIcon
                role={role.icon}
                size={13}
                decorative
                color={isOn ? ROLE_ICON_COLOR[role.code] : undefined}
              />
            </span>
          );
        })}
      </span>

      <span className="w-11 shrink-0 text-right text-caption font-semibold tabular-nums text-[color:var(--aqt-fg-muted)]">
        {rank ?? "\u2014"}
      </span>

      {canWrite ? (
        <button
          type="button"
          onClick={onRemove}
          title="Remove from this mix"
          className="flex size-5 shrink-0 items-center justify-center rounded text-[color:var(--aqt-fg-faint)] opacity-0 transition-opacity hover:text-[color:var(--aqt-rose)] focus-visible:opacity-100 group-hover:opacity-100"
        >
          <X className="size-3.5" aria-hidden="true" />
          <span className="sr-only">{`Remove ${label} from this mix`}</span>
        </button>
      ) : (
        <span aria-hidden="true" className="size-5 shrink-0" />
      )}
    </li>
  );
}
