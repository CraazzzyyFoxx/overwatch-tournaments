"use client";

import {
  NEUTRAL_RANK_ACCENT,
  ROLE_RANK_ACCENTS,
  RoleRankControls
} from "@/app/balancer/components/RoleRankControls";
import { rectSortingStrategy } from "@dnd-kit/sortable";

import { SortableGrip, SortableRows, useSortableRow } from "@/components/kit/SortableRows";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Switch } from "@/components/ui/switch";
import { OW_REFERENCE_GRID } from "@/lib/divisions/grid";
import { ROLE_LABELS, getRoleIconName, type RoleCode } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";

import { LINEUP_ROLES } from "./pickup-lineup";

/**
 * One role's rank, as this editor should render it.
 *
 * `onChange === null` is the read-only case. A mix's ranks are the HOST's book
 * (`author_user_id = game.host_user_id`), so the host's sheet edits them from
 * here and a player's own panel only reads them -- the player owns `roles` and
 * `is_flex` and nothing else on their row.
 */
export type PickupRoleRank = {
  rankValue: number | null;
  /** Which layer the shown rank came from, badged beside it. */
  sourceLabel: string | null;
  onChange: ((next: number | null) => void) | null;
  /** Only offered when there is an own entry to drop. */
  onClear: (() => void) | null;
};

type PickupRoleOrderEditorProps = {
  /** The roles that are ON, in priority order -- position is what the balancer reads. */
  order: readonly RoleCode[];
  isFlex: boolean;
  disabled: boolean;
  /** Whose roles these are; every control's accessible name ends in it. */
  label: string;
  onReorder: (next: RoleCode[]) => void;
  onToggle: (role: RoleCode) => void;
  onFlexChange: (next: boolean) => void;
  rankFor: (role: RoleCode) => PickupRoleRank;
};

/**
 * Role priority and the flex flag, in one place for both callers.
 *
 * Priority is a drag list because the stored role order *is* the balancer's
 * priority (see `CustomGamePlayer.roles`): deriving it from a rank moved a
 * role's seat the moment any layer's number changed, with no click anyone
 * could point at. Dragging makes it what it always was on the wire.
 *
 * Off roles trail the on ones in canonical order: an unselected role has no
 * priority, so ranking them would imply one.
 */
export function PickupRoleOrderEditor({
  order,
  isFlex,
  disabled,
  label,
  onReorder,
  onToggle,
  onFlexChange,
  rankFor
}: Readonly<PickupRoleOrderEditorProps>) {
  const offRoles = LINEUP_ROLES.filter((role) => !order.includes(role));

  return (
    // 2x2 once the container fits two cards (the mix panel); a narrow sheet stays one column.
    // `contents` on the lists lets their cards sit in this grid directly.
    <div className="@container">
      <div className="grid gap-2 @xl:grid-cols-2">
        <div
          className={cn(
            "flex items-center justify-between gap-3 rounded-lg border px-3 py-2",
            isFlex
              ? "border-emerald-400/20 bg-emerald-500/[0.08]"
              : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)]"
          )}
        >
          <div className="min-w-0">
            <span className="text-xs font-medium text-[color:var(--aqt-fg)]">Full flex</span>
            {isFlex ? (
              <p className="mt-0.5 text-label text-[color:var(--aqt-fg-dim)]">
                Every role is equally preferred — priority order stops mattering.
              </p>
            ) : (
              <p className="mt-0.5 text-label text-[color:var(--aqt-fg-dim)]">
                Drag below to set who the balancer seats first.
              </p>
            )}
          </div>
          <Switch
            checked={isFlex}
            disabled={disabled}
            aria-label={`Full flex for ${label}`}
            onCheckedChange={onFlexChange}
          />
        </div>

        <SortableRows
          items={order}
          getId={(role) => role}
          onReorder={onReorder}
          strategy={rectSortingStrategy}
          className="contents"
        >
          {(role, index) => (
            <SortableRoleCard
              key={role}
              id={role}
              role={role}
              label={label}
              priority={index + 1}
              isPrimary={index === 0}
              disabled={disabled}
              onToggle={() => onToggle(role)}
              rank={rankFor(role)}
            />
          )}
        </SortableRows>

        {offRoles.length === 0 ? null : (
          <ul className="contents">
            {offRoles.map((role) => (
              <li
                key={role}
                className="flex items-start gap-2.5 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-2.5 opacity-80"
              >
                <RoleCardBody
                  role={role}
                  label={label}
                  isOn={false}
                  isPrimary={false}
                  disabled={disabled}
                  onToggle={() => onToggle(role)}
                  rank={rankFor(role)}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** One role's card, wired to the drag list: grip, then the row's own content. */
function SortableRoleCard({
  id,
  role,
  label,
  priority,
  isPrimary,
  disabled,
  onToggle,
  rank
}: Readonly<{
  id: string;
  role: RoleCode;
  label: string;
  /** The row's position in the drag list, 1-based — what the balancer reads as priority. */
  priority: number;
  isPrimary: boolean;
  disabled: boolean;
  onToggle: () => void;
  rank: PickupRoleRank;
}>) {
  const { ref, style, handleProps } = useSortableRow(id, disabled);

  return (
    <li
      ref={ref}
      style={style}
      className={cn(
        "flex items-start gap-2.5 rounded-xl border bg-[color:var(--aqt-overlay-2)] p-2.5 transition-colors",
        "border-[color:var(--aqt-border-2)]",
        ROLE_RANK_ACCENTS[role]?.row
      )}
    >
      <div className="flex flex-col items-center gap-1">
        <SortableGrip
          handleProps={handleProps}
          label={`Reorder ${ROLE_LABELS[role]} for ${label}`}
          disabled={disabled}
        />
        <span className="text-label font-semibold text-[color:var(--aqt-fg-dim)]">{`#${priority}`}</span>
      </div>
      <RoleCardBody
        role={role}
        label={label}
        isOn
        isPrimary={isPrimary}
        disabled={disabled}
        onToggle={onToggle}
        rank={rank}
      />
    </li>
  );
}

/**
 * One role's card: name, first-choice mark, on/off, and the rank.
 *
 * Where the rank is editable (`rank.onChange`), the field edits the *effective*
 * rank — what balance will actually use — rather than only this host's own
 * entry, because a host reads the number they see and expects to be able to
 * correct it. Where it is not, the same number is printed with its layer: a
 * player must be able to see why the balancer seats them where it does without
 * being handed a control that would 422.
 */
function RoleCardBody({
  role,
  label,
  isOn,
  isPrimary,
  disabled,
  onToggle,
  rank
}: Readonly<{
  role: RoleCode;
  label: string;
  isOn: boolean;
  /** The top of the drag list — where the balancer will try to seat them first. */
  isPrimary: boolean;
  disabled: boolean;
  onToggle: () => void;
  rank: PickupRoleRank;
}>) {
  const accent = ROLE_RANK_ACCENTS[role] ?? NEUTRAL_RANK_ACCENT;

  return (
    <div className="min-w-0 flex-1 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <PlayerRoleIcon role={getRoleIconName(role)} size={15} decorative />
          <span
            className={cn(
              "text-xs font-semibold",
              isOn ? accent.text : "text-[color:var(--aqt-fg-muted)]"
            )}
          >
            {ROLE_LABELS[role]}
          </span>
          {isPrimary ? (
            <span
              className={cn(
                "shrink-0 rounded px-1.5 py-px text-label font-bold uppercase tracking-label",
                accent.chip
              )}
            >
              First
            </span>
          ) : null}
        </div>

        <div className="flex h-6 items-center gap-1.5 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2">
          <Switch
            checked={isOn}
            disabled={disabled}
            aria-label={`${ROLE_LABELS[role]} for ${label}`}
            onCheckedChange={onToggle}
            className="h-4 w-7 [&>span]:size-3 [&>span]:data-[state=checked]:translate-x-3"
          />
          <span
            className={cn(
              "text-label font-semibold uppercase tracking-label",
              isOn ? accent.text : "text-[color:var(--aqt-fg-dim)]"
            )}
          >
            {isOn ? "Active" : "Off"}
          </span>
        </div>
      </div>

      {rank.onChange == null ? (
        <div className="flex h-8 items-center gap-2 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2.5">
          <span
            className={cn(
              "text-xs font-semibold tabular-nums",
              isOn ? accent.text : "text-[color:var(--aqt-fg-dim)]"
            )}
          >
            {rank.rankValue ?? "—"}
          </span>
          {rank.sourceLabel ? (
            <span className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
              {rank.sourceLabel}
            </span>
          ) : null}
        </div>
      ) : (
        <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_130px]">
          <RoleRankControls
            rankValue={rank.rankValue}
            sourceLabel={rank.sourceLabel}
            accent={accent}
            active={isOn}
            disabled={disabled}
            onClear={rank.onClear}
            onChange={rank.onChange}
            // The global OW grid: balancer-service resolves a mix's ranks
            // against the grid with `workspace_id=None`, so the value edited
            // here is on the OW scale and a workspace's tiers would mislabel it.
            grid={OW_REFERENCE_GRID}
          />
        </div>
      )}
    </div>
  );
}
