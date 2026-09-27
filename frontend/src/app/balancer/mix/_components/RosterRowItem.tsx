import { Check, CornerDownLeft, Plus } from "lucide-react";

import { splitBattleTag } from "@/components/balancer/balancer-page-helpers";
import DivisionIcon from "@/components/DivisionIcon";
import { OW_REFERENCE_GRID, resolveDivisionFromRank } from "@/lib/divisions/grid";
import { ROLES, ROLE_LABELS } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";

import type { RosterRow } from "../_hooks/useRosterPicker";

/**
 * One roster row: membership indicator on the left, identity in the middle,
 * this host's three effective ranks read-only on the right.
 *
 * The whole row is the membership toggle -- there is no picker on it to miss
 * by four pixels anymore, ranks here are read-only. The keyboard path is
 * unchanged: the search field never loses focus, and Enter acts on the
 * cursor row, so adding twelve people is still twelve keystrokes without a
 * single pointer move.
 */
export function RosterRowItem({
  row,
  isInMix,
  isCursor,
  canWrite,
  onToggle
}: Readonly<{
  row: RosterRow;
  isInMix: boolean;
  isCursor: boolean;
  canWrite: boolean;
  onToggle: () => void;
}>) {
  const label = row.displayName || row.battleTag || `#${row.memberId}`;
  const { name, suffix } = splitBattleTag(label);

  return (
    <li data-roster-row>
      <button
        type="button"
        disabled={!canWrite}
        aria-pressed={isInMix}
        aria-label={isInMix ? `Remove ${label} from this mix` : `Add ${label} to this mix`}
        onClick={onToggle}
        className={cn(
          "relative flex w-full items-center gap-2.5 rounded-lg border px-2 py-1.5 text-left transition-colors",
          // A left rail rather than a filled row: at 24 rows a wash of teal
          // fought the rank crests for attention, and "already in" is a state, not
          // an emphasis.
          isInMix
            ? "border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] before:absolute before:inset-y-1.5 before:left-0 before:w-[2px] before:rounded-full before:bg-[color:var(--aqt-teal)]"
            : "border-transparent hover:border-[color:var(--aqt-border-2)] hover:bg-[color:var(--aqt-overlay-2)]",
          isCursor && "ring-1 ring-[color:color-mix(in_srgb,var(--aqt-teal)_45%,transparent)]",
          "disabled:cursor-default"
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            "flex size-6 shrink-0 items-center justify-center rounded-md border transition-colors",
            isInMix
              ? "border-[color:color-mix(in_srgb,var(--aqt-teal)_45%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_18%,transparent)] text-[color:var(--aqt-teal)]"
              : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] text-[color:var(--aqt-fg-dim)]"
          )}
        >
          {isInMix ? <Check className="size-3.5" /> : <Plus className="size-3.5" />}
        </span>

        <span className="flex min-w-0 flex-1 items-baseline gap-1.5">
          <span
            className="truncate text-caption font-semibold text-[color:var(--aqt-fg)]"
            title={label}
          >
            {name}
          </span>
          {suffix ? (
            <span className="shrink-0 text-label text-[color:var(--aqt-fg-faint)]">{suffix}</span>
          ) : null}
          {isCursor && canWrite ? (
            <span
              aria-hidden="true"
              className="ml-auto shrink-0 text-[color:color-mix(in_srgb,var(--aqt-teal)_75%,transparent)]"
            >
              <CornerDownLeft className="size-3.5" />
            </span>
          ) : null}
        </span>

        <span className="flex shrink-0 items-center gap-1.5">
          {ROLES.map((role) => {
            const own = row.authorRanks[role.code] ?? null;
            const inherited = own == null ? (row.ranks[role.code] ?? null) : null;
            // The global OW grid: a mix's ranks resolve against it
            // (`workspace_id=None`), so a workspace's tiers here would show
            // the wrong crest for the same number.
            const division = resolveDivisionFromRank(OW_REFERENCE_GRID, own ?? inherited);
            return (
              <span
                key={role.code}
                title={
                  inherited == null
                    ? `${ROLE_LABELS[role.code]} rank for ${label}`
                    : `${ROLE_LABELS[role.code]} rank for ${label}, inherited ${inherited} from the workspace`
                }
                // Dimmed means "not yours": painting an inherited number the
                // same as the host's own made "set" and "leave alone" look
                // identical, which is the exact mistake layered ranks exist
                // to make visible.
                className={cn(
                  "flex size-8 items-center justify-center rounded-md border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)]",
                  inherited != null && "opacity-45"
                )}
              >
                {division == null ? (
                  <span className="text-label text-[color:var(--aqt-fg-dim)]">{"\u2014"}</span>
                ) : (
                  <DivisionIcon
                    division={division}
                    tournamentGrid={OW_REFERENCE_GRID}
                    width={22}
                    height={22}
                  />
                )}
              </span>
            );
          })}
        </span>
      </button>
    </li>
  );
}
