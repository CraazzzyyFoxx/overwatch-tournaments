"use client";

import { useState } from "react";
import { Pin, Save, UserMinus } from "lucide-react";

import { BattleTagCopyButton } from "@/app/balancer/components/BattleTagCopyControls";
import {
  NEUTRAL_RANK_ACCENT,
  ROLE_RANK_ACCENTS,
  RoleRankControls,
} from "@/app/balancer/components/RoleRankControls";
import { SortableGrip, SortableRows, useSortableRow } from "@/app/balancer/components/SortableRows";
import { splitBattleTag } from "@/app/balancer/components/balancer-page-helpers";
import { CAPTION_CLASS, EYEBROW_CLASS } from "@/app/balancer/mix/pickup-chrome";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import RankHistory from "@/components/RankHistory";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { OW_REFERENCE_GRID } from "@/lib/division-grid";
import { ROLE_LABELS, getRoleIconName, type RoleCode } from "@/lib/roles";
import { cn } from "@/lib/utils";
import {
  RANK_SOURCE_LABELS,
  type CustomGamePlayer,
  type CustomGamePlayerPatch,
  type MixParticipation,
  type MixMemberStats,
} from "@/services/custom-game.service";

import {
  LINEUP_ISSUE_MESSAGES,
  LINEUP_ROLES,
  getLineupIssue,
  playerLabel,
  resolveRoleOrder,
  toggleRole,
} from "./pickup-lineup";
import { formatRecord, formatStreak } from "./pickup-stats";

/** What Save writes into the host's own rank book: `clear` falls the role back to the workspace. */
export type PickupRankChange = { ranks: Record<string, number>; clear: string[] };

type PickupPlayerSheetProps = {
  row: CustomGamePlayer | null;
  canEdit: boolean;
  saving: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (patch: CustomGamePlayerPatch, rankChange: PickupRankChange | null) => void;
  onRemove: () => void;
  /** This player's all-time mix record, or `null` where the page does not read one. */
  mixStats?: MixMemberStats | null;
};

/** Everything the sheet edits before Save, kept apart from the server row. */
type RoleDraft = {
  participation: MixParticipation;
  /** Priority order of the roles that are on — position is what the balancer reads. */
  order: RoleCode[];
  /** Staged writes to the host's own book. A `null` value is a staged Clear. */
  rankEdits: Partial<Record<RoleCode, number | null>>;
  /** Every role this row has a rank for is treated as equally preferred, so
   * `order`'s position stops mattering as a priority hint. */
  isFlex: boolean;
};

function buildDraft(row: CustomGamePlayer | null): RoleDraft {
  return {
    participation: row?.participation ?? "pool",
    order: row ? resolveRoleOrder(row) : [],
    rankEdits: {},
    isFlex: row?.is_flex ?? false,
  };
}

/** The three-way status picker, in the same order the lineup columns read left to right. */
const STATUS_OPTIONS: readonly {
  participation: MixParticipation;
  label: string;
  description: string;
}[] = [
  { participation: "must_play", label: "Must play", description: "Guaranteed a seat" },
  { participation: "pool", label: "In the pool", description: "In the balance" },
  { participation: "benched", label: "Benched", description: "Sitting out" },
];

/**
 * Per-player mix settings: who plays, which roles, in what priority, at what
 * rank.
 *
 * A sheet rather than an inline expansion because these are the *rare* edits —
 * a lineup row already carries the two frequent ones (bench, toggle a role), and
 * pushing priority and rank editing into the row would have made every row pay
 * for a control most rows never use.
 *
 * There is no per-mix rank pin. One number that overrode every role inside a
 * single mix was invisible from the roster, from the next mix and from every
 * tournament, so the same correction had to be re-typed per game; a rank typed
 * here lands in the host's own book instead, which is the layer that actually
 * follows them.
 *
 * Priority is a drag list, like the tournament sheet's: the stored role order
 * *is* the balancer's priority (see `CustomGamePlayer.roles`), so deriving it
 * from a rank instead — the previous design — moved a role's seat the moment
 * any layer's number changed, with no click the host could point at. Dragging
 * makes it what it always was on the wire: a choice the host makes once.
 *
 * Every edit here is staged until Save: closing the sheet any other way (the
 * corner ✕, Escape, an outside click, or Cancel) discards it, the same as the
 * tournament sheet.
 *
 * Ranks use `RoleRankControls`, the same number-field-over-division-slider the
 * tournament sheet uses.
 */
export function PickupPlayerSheet({
  row,
  canEdit,
  saving,
  onOpenChange,
  onSave,
  onRemove,
  mixStats = null,
}: Readonly<PickupPlayerSheetProps>) {
  const label = row ? playerLabel(row) : "";
  const { name, suffix } = splitBattleTag(label);
  // The record across every mix, not this one: a caption, because it is
  // context for the settings below it and nothing here edits it.
  const mixStreak = mixStats ? formatStreak(mixStats.streak) : null;
  const mixRecord =
    mixStats != null && mixStats.games > 0
      ? `Mixes: ${formatRecord(mixStats)} · ${Math.round(mixStats.win_rate * 100)}%${mixStreak ? ` · ${mixStreak}` : ""}`
      : null;
  const [draft, setDraft] = useState<RoleDraft>(() => buildDraft(row));
  // Keyed on the member id rather than the whole row: a background refetch of
  // this same player (another host's edit landing mid-session) must not wipe
  // out an edit still in progress. Resetting during render (not an effect) on
  // an id change is React's own pattern for "state derived from a prop that
  // should reset when the prop's identity changes".
  const [draftedMemberId, setDraftedMemberId] = useState(row?.workspace_member_id);
  if (row?.workspace_member_id !== draftedMemberId) {
    setDraftedMemberId(row?.workspace_member_id);
    setDraft(buildDraft(row));
  }

  // Reads the draft, not the server row: a role turned on (or a rank typed
  // for one) must clear this warning immediately, not once Save round-trips.
  const issue = row ? getLineupIssue(draftRow(row, draft)) : null;
  const disabled = !canEdit || saving;
  // Off roles trail the on ones in canonical order: an unselected role has no
  // priority, so ranking them would imply one.
  const offRoles = LINEUP_ROLES.filter((role) => !draft.order.includes(role));

  const toggle = (role: RoleCode) =>
    setDraft((current) => ({ ...current, order: toggleRole(current.order, role) }));

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      setDraft(buildDraft(row));
    }
    onOpenChange(open);
  };

  const handleSave = () => {
    if (!row) return;
    const ranks: Record<string, number> = {};
    const clear: string[] = [];
    for (const [role, value] of Object.entries(draft.rankEdits)) {
      if (value == null) {
        clear.push(role);
      } else {
        ranks[role] = value;
      }
    }
    onSave(
      { participation: draft.participation, roles: draft.order, is_flex: draft.isFlex },
      Object.keys(draft.rankEdits).length > 0 ? { ranks, clear } : null,
    );
    // The mutations fire-and-forget from here (the page owns their pending
    // state via `saving`); waiting for them to settle before closing left the
    // sheet open with nothing left to do until the network round-tripped.
    handleOpenChange(false);
  };

  return (
    <Sheet open={row != null} onOpenChange={handleOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full flex-col gap-0 overflow-hidden p-0 sm:max-w-[640px]"
      >
        <SheetHeader className="space-y-0 border-b border-[color:var(--aqt-border)] px-5 pb-4 pt-5 text-left">
          <span className={EYEBROW_CLASS}>Advanced settings</span>
          <SheetTitle className="flex items-baseline gap-1.5 pt-1.5 font-display text-xl">
            <span className="truncate">{name}</span>
            {suffix ? (
              <span className="text-caption font-normal text-[color:var(--aqt-fg-faint)]">
                {suffix}
              </span>
            ) : null}
            {row?.battle_tag ? (
              <BattleTagCopyButton battleTag={row.battle_tag} className="ml-0.5 shrink-0" />
            ) : null}
          </SheetTitle>
          {mixRecord ? <span className={cn(CAPTION_CLASS, "pt-1")}>{mixRecord}</span> : null}
          <SheetDescription className="pt-1 text-caption text-[color:var(--aqt-fg-dim)]">
            {canEdit
              ? "Nothing here writes until you press Save."
              : "Read-only — only this mix's host can edit it."}
          </SheetDescription>
        </SheetHeader>

        {row == null ? null : (
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
            <section className="space-y-2.5 border-b border-[color:var(--aqt-border)] px-5 py-4">
              <h3 className="text-caption font-medium text-[color:var(--aqt-fg)]">Status</h3>
              <div
                role="radiogroup"
                aria-label={`Lineup status for ${label}`}
                className="grid grid-cols-3 gap-1.5"
              >
                {STATUS_OPTIONS.map((option) => {
                  const selected = draft.participation === option.participation;
                  return (
                    <button
                      key={option.participation}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      aria-label={`${option.label} for ${label}`}
                      disabled={disabled}
                      onClick={() =>
                        setDraft((current) => ({ ...current, participation: option.participation }))
                      }
                      className={cn(
                        "flex flex-col items-center gap-0.5 rounded-lg border px-2 py-2 text-center transition-colors",
                        selected
                          ? option.participation === "must_play"
                            ? "border-[color:var(--aqt-amber)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_12%,transparent)] text-[color:var(--aqt-amber)]"
                            : "border-[color:var(--aqt-teal)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_10%,transparent)] text-[color:var(--aqt-teal)]"
                          : "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-muted)] hover:border-[color:var(--aqt-border-3)]",
                        "disabled:cursor-default disabled:opacity-60",
                      )}
                    >
                      <span className="flex items-center gap-1">
                        {option.participation === "must_play" ? (
                          <Pin
                            className="size-3"
                            aria-hidden="true"
                            fill={selected ? "currentColor" : "none"}
                          />
                        ) : null}
                        <span className="text-caption font-semibold">{option.label}</span>
                      </span>
                      <span className="text-label text-[color:var(--aqt-fg-dim)]">
                        {option.description}
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>

            <section className="space-y-2.5 border-b border-[color:var(--aqt-border)] px-5 py-4">
              <h3 className="text-caption font-medium text-[color:var(--aqt-fg)]">
                Roles and ranks
              </h3>

              <div
                className={cn(
                  "flex items-center justify-between gap-3 rounded-lg border px-3 py-2",
                  draft.isFlex
                    ? "border-emerald-400/20 bg-emerald-500/[0.08]"
                    : "border-[color:var(--aqt-border-2)] bg-white/[0.03]",
                )}
              >
                <div className="min-w-0">
                  <span className="text-xs font-medium text-[color:var(--aqt-fg)]">Full flex</span>
                  {draft.isFlex ? (
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
                  checked={draft.isFlex}
                  disabled={disabled}
                  aria-label={`Full flex for ${label}`}
                  onCheckedChange={(checked) =>
                    setDraft((current) => ({ ...current, isFlex: checked }))
                  }
                />
              </div>

              <SortableRows
                items={draft.order}
                getId={(role) => role}
                onReorder={(nextOrder) => setDraft((current) => ({ ...current, order: nextOrder }))}
                className="space-y-2"
              >
                {(role, index) => {
                  const field = stagedRankFor(row, draft, role);
                  return (
                    <SortableRoleCard
                      key={role}
                      id={role}
                      role={role}
                      label={label}
                      priority={index + 1}
                      isPrimary={index === 0}
                      disabled={disabled}
                      onToggle={() => toggle(role)}
                      rankValue={field.rankValue}
                      sourceLabel={field.sourceLabel}
                      hasOwnEntry={field.hasOwnEntry}
                      onRankChange={(next) =>
                        setDraft((current) => ({
                          ...current,
                          rankEdits: { ...current.rankEdits, [role]: next },
                        }))
                      }
                      onRankClear={() =>
                        setDraft((current) => ({
                          ...current,
                          rankEdits: { ...current.rankEdits, [role]: null },
                        }))
                      }
                    />
                  );
                }}
              </SortableRows>

              {offRoles.length === 0 ? null : (
                <ul className="space-y-2 pt-0.5">
                  {offRoles.map((role) => {
                    const field = stagedRankFor(row, draft, role);
                    return (
                      <li
                        key={role}
                        className="flex items-start gap-2.5 rounded-xl border border-[color:var(--aqt-border)] bg-white/2 p-2.5 opacity-80"
                      >
                        <RoleCardBody
                          role={role}
                          label={label}
                          isOn={false}
                          isPrimary={false}
                          disabled={disabled}
                          onToggle={() => toggle(role)}
                          rankValue={field.rankValue}
                          sourceLabel={field.sourceLabel}
                          hasOwnEntry={field.hasOwnEntry}
                          onRankChange={(next) =>
                            setDraft((current) => ({
                              ...current,
                              rankEdits: { ...current.rankEdits, [role]: next },
                            }))
                          }
                          onRankClear={() =>
                            setDraft((current) => ({
                              ...current,
                              rankEdits: { ...current.rankEdits, [role]: null },
                            }))
                          }
                        />
                      </li>
                    );
                  })}
                </ul>
              )}

              {issue ? (
                <p className="text-xs text-rose-200">{LINEUP_ISSUE_MESSAGES[issue]}</p>
              ) : null}
            </section>

            {/* The one thing the mix cannot tell the host: what this player is
                actually ranked in Overwatch right now. Read-only, and the same
                component the tournament sheet uses. */}
            <section className="space-y-2 px-5 py-4">
              <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">
                Live rank (OverFast)
              </Label>
              <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-white/[0.03] p-2.5">
                <RankHistory battleTag={row.battle_tag} />
              </div>
            </section>
          </div>
        )}

        {row != null && canEdit ? (
          <SheetFooter className="shrink-0 border-t border-[color:var(--aqt-border)] px-5 py-2.5 sm:justify-between sm:space-x-0">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              disabled={saving}
              onClick={onRemove}
              title={`Remove ${label} from this mix`}
              className="h-8 w-8 shrink-0 rounded-lg border border-[color:color-mix(in_srgb,var(--aqt-rose)_35%,transparent)] bg-rose-500/10 text-rose-200 hover:bg-rose-500/20 hover:text-rose-100"
            >
              <UserMinus className="h-3.5 w-3.5" aria-hidden="true" />
              <span className="sr-only">{`Remove ${label} from this mix`}</span>
            </Button>
            <div className="flex gap-2">
              <Button
                variant="outline"
                className="h-8 border-[color:var(--aqt-border-2)] bg-black/20 px-3 text-xs text-[color:var(--aqt-fg)] hover:bg-white/5 hover:text-[color:var(--aqt-fg)]"
                onClick={() => handleOpenChange(false)}
              >
                Cancel
              </Button>
              <Button
                onClick={handleSave}
                disabled={saving}
                className="h-8 bg-primary px-3 text-xs text-primary-foreground hover:bg-primary/90"
              >
                <Save className="mr-1 h-3.5 w-3.5" />
                Save
              </Button>
            </div>
          </SheetFooter>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

/** The server row with every staged edit folded in, for `getLineupIssue`. */
function draftRow(row: CustomGamePlayer, draft: RoleDraft): CustomGamePlayer {
  const ranks = { ...row.ranks };
  for (const [role, value] of Object.entries(draft.rankEdits)) {
    if (value == null) {
      delete ranks[role];
    } else {
      ranks[role] = value;
    }
  }
  return { ...row, participation: draft.participation, roles: draft.order, ranks };
}

/** The rank field's value, source badge and clearability, from the server row plus any staged edit. */
function stagedRankFor(
  row: CustomGamePlayer,
  draft: RoleDraft,
  role: RoleCode,
): { rankValue: number | null; sourceLabel: string | null; hasOwnEntry: boolean } {
  const staged = draft.rankEdits[role];
  if (staged !== undefined) {
    return {
      rankValue: staged,
      sourceLabel: staged == null ? null : RANK_SOURCE_LABELS.author,
      hasOwnEntry: staged != null,
    };
  }
  const source = row.rank_sources[role] ?? null;
  return {
    rankValue: row.ranks[role] ?? null,
    sourceLabel: source ? RANK_SOURCE_LABELS[source] : null,
    hasOwnEntry: row.author_ranks[role] != null,
  };
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
  rankValue,
  sourceLabel,
  hasOwnEntry,
  onRankChange,
  onRankClear,
}: Readonly<{
  id: string;
  role: RoleCode;
  label: string;
  /** The row's position in the drag list, 1-based — what the balancer reads as priority. */
  priority: number;
  isPrimary: boolean;
  disabled: boolean;
  onToggle: () => void;
  rankValue: number | null;
  sourceLabel: string | null;
  hasOwnEntry: boolean;
  onRankChange: (next: number | null) => void;
  onRankClear: () => void;
}>) {
  const { ref, style, handleProps } = useSortableRow(id, disabled);

  return (
    <li
      ref={ref}
      style={style}
      className={cn(
        "flex items-start gap-2.5 rounded-xl border bg-white/3 p-2.5 transition-colors",
        "border-[color:var(--aqt-border-2)]",
        ROLE_RANK_ACCENTS[role]?.row,
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
        rankValue={rankValue}
        sourceLabel={sourceLabel}
        hasOwnEntry={hasOwnEntry}
        onRankChange={onRankChange}
        onRankClear={onRankClear}
      />
    </li>
  );
}

/**
 * One role's card: name, first-choice mark, on/off, and the shared rank controls.
 *
 * The field edits the *effective* rank — what balance will actually use — rather
 * than only this host's own entry, because a host reads the number they see and
 * expects to be able to correct it. Typing stages the corrected value in their
 * own book; Clear stages dropping that entry, so the field falls back to
 * whatever the workspace (or Overwatch) says once Save writes it.
 */
function RoleCardBody({
  role,
  label,
  isOn,
  isPrimary,
  disabled,
  onToggle,
  rankValue,
  sourceLabel,
  hasOwnEntry,
  onRankChange,
  onRankClear,
}: Readonly<{
  role: RoleCode;
  label: string;
  isOn: boolean;
  /** The top of the drag list — where the balancer will try to seat them first. */
  isPrimary: boolean;
  disabled: boolean;
  onToggle: () => void;
  rankValue: number | null;
  sourceLabel: string | null;
  hasOwnEntry: boolean;
  onRankChange: (next: number | null) => void;
  onRankClear: () => void;
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
              isOn ? accent.text : "text-[color:var(--aqt-fg-muted)]",
            )}
          >
            {ROLE_LABELS[role]}
          </span>
          {isPrimary ? (
            <span
              className={cn(
                "shrink-0 rounded px-1.5 py-px text-label font-bold uppercase tracking-label",
                accent.chip,
              )}
            >
              First
            </span>
          ) : null}
        </div>

        <div className="flex h-6 items-center gap-1.5 rounded-md border border-[color:var(--aqt-border-2)] bg-black/15 px-2">
          <Switch
            checked={isOn}
            disabled={disabled}
            aria-label={`${ROLE_LABELS[role]} for ${label}`}
            onCheckedChange={onToggle}
            className="h-4 w-7 [&>span]:size-3 [&>span]:data-[state=checked]:translate-x-3"
          />
          <span
            className={cn(
              "text-label font-semibold uppercase tracking-wide",
              isOn ? accent.text : "text-[color:var(--aqt-fg-dim)]",
            )}
          >
            {isOn ? "Active" : "Off"}
          </span>
        </div>
      </div>

      <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_130px]">
        <RoleRankControls
          rankValue={rankValue}
          sourceLabel={sourceLabel}
          accent={accent}
          active={isOn}
          disabled={disabled}
          onClear={hasOwnEntry ? onRankClear : null}
          onChange={onRankChange}
          // The global OW grid: balancer-service resolves a mix's ranks against
          // the grid with `workspace_id=None`, so the value edited here is on
          // the OW scale and a workspace's tiers would mislabel it.
          grid={OW_REFERENCE_GRID}
        />
      </div>
    </div>
  );
}
