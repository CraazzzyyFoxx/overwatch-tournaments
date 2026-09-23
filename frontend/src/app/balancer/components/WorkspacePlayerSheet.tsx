"use client";

import { BattleTagCopyButton } from "@/app/balancer/components/BattleTagCopyControls";
import { splitBattleTag } from "@/components/balancer/balancer-page-helpers";
import {
  NEUTRAL_RANK_ACCENT,
  ROLE_RANK_ACCENTS,
  RoleRankControls,
  useDebouncedRank,
} from "@/app/balancer/components/RoleRankControls";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import RankHistory from "@/components/RankHistory";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ROLE_LABELS, ROLES, type RoleCode } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import type { RosterMember } from "@/services/workspace-player.service";

const EYEBROW_CLASS =
  "text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]";

// The panel that mounts this sheet only ever reads/writes the workspace
// canon (`WorkspacePlayersSidebar`'s sole caller is the tournament balancer
// page); the per-mix "author" layer has its own sheet (`PickupPlayerSheet`).
const SCOPE_HINT =
  "The shared fallback. A tournament or mix uses it only where nobody set their own rank.";

type WorkspacePlayerSheetProps = {
  /** `null` closes the sheet — the caller holds the row being edited. */
  member: RosterMember | null;
  canEdit: boolean;
  saving: boolean;
  onOpenChange: (open: boolean) => void;
  /** `null` drops the role from the layer rather than zeroing it. */
  onSaveRank: (role: string, rank: number | null) => void;
};

/**
 * One workspace player's ranks, in the same sheet the tournament pool opens.
 *
 * The roster rows used to carry three crest pickers each, which made the panel
 * a grid of controls nobody could clear — the picker offered divisions and
 * nothing else, so a rank set by mistake was permanent. Editing moved here for
 * the same reason the mix moved it: the frequent action is reading the roster,
 * and the rare one is correcting a number.
 *
 * Everything a tournament registration owns — statuses, pool membership, flex,
 * sub-roles, notes, priorities, apply-from-history — is deliberately absent. A
 * workspace member has no registration to carry any of it. What is left is the
 * part both sheets share: `RoleRankControls`, so all three surfaces that edit a
 * rank agree on how it is typed, sliced and cleared.
 */
export function WorkspacePlayerSheet({
  member,
  canEdit,
  saving,
  onOpenChange,
  onSaveRank,
}: Readonly<WorkspacePlayerSheetProps>) {
  const label = member ? member.display_name || member.battle_tag || `#${member.member_id}` : "";
  const { name, suffix } = splitBattleTag(label);

  return (
    <Sheet open={member != null} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full flex-col gap-0 overflow-y-auto p-0 sm:max-w-[560px]"
      >
        <SheetHeader className="space-y-0 border-b border-[color:var(--aqt-border)] px-5 pb-4 pt-5 text-left">
          <span className={EYEBROW_CLASS}>Player ranks</span>
          <SheetTitle className="flex items-baseline gap-1.5 pt-1.5 font-display text-xl">
            <span className="truncate">{name}</span>
            {suffix ? (
              <span className="text-caption font-normal text-[color:var(--aqt-fg-faint)]">
                {suffix}
              </span>
            ) : null}
            {member?.battle_tag ? (
              <BattleTagCopyButton battleTag={member.battle_tag} className="ml-0.5 shrink-0" />
            ) : null}
          </SheetTitle>
          <SheetDescription className="pt-1 text-caption text-[color:var(--aqt-fg-dim)]">
            {SCOPE_HINT}
          </SheetDescription>
        </SheetHeader>

        {member == null ? null : (
          <div className="flex min-h-0 flex-1 flex-col">
            <section className="space-y-2 border-b border-[color:var(--aqt-border)] px-5 py-4">
              <div>
                <h3 className="text-caption font-medium text-[color:var(--aqt-fg)]">
                  Roles and ranks
                </h3>
                <p className="mt-0.5 text-xs text-[color:var(--aqt-fg-dim)]">
                  A role with no rank is a role the balancer will not seat them in. Clear one to
                  drop it from this layer instead of pinning a number over it.
                </p>
              </div>

              <ul className="space-y-2">
                {ROLES.map((role) => (
                  <li
                    key={role.code}
                    className={cn(
                      "rounded-xl border bg-[color:var(--aqt-overlay-2)] p-2.5",
                      "border-[color:var(--aqt-border-2)]",
                      ROLE_RANK_ACCENTS[role.code]?.row,
                    )}
                  >
                    <RoleRankCard
                      member={member}
                      role={role.code}
                      iconName={role.icon}
                      disabled={!canEdit || saving}
                      onSaveRank={onSaveRank}
                    />
                  </li>
                ))}
              </ul>
            </section>

            {/* The one thing the roster cannot tell an organiser: what this
                player is actually ranked in Overwatch right now. Read-only, and
                the same component both other sheets use. */}
            {member.battle_tag ? (
              <section className="space-y-2 px-5 py-4">
                <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">
                  Live rank (OverFast)
                </Label>
                <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-2.5">
                  <RankHistory battleTag={member.battle_tag} />
                </div>
              </section>
            ) : null}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

/**
 * One role's card: the glyph, the role's name, and the shared rank controls.
 */
function RoleRankCard({
  member,
  role,
  iconName,
  disabled,
  onSaveRank,
}: Readonly<{
  member: RosterMember;
  role: RoleCode;
  iconName: string;
  disabled: boolean;
  onSaveRank: (role: string, rank: number | null) => void;
}>) {
  const accent = ROLE_RANK_ACCENTS[role] ?? NEUTRAL_RANK_ACCENT;
  const own = member.ranks[role] ?? null;
  const rank = useDebouncedRank(own, (next) => onSaveRank(role, next));

  return (
    <div className="min-w-0 space-y-2">
      <div className="flex items-center gap-1.5">
        <PlayerRoleIcon role={iconName} size={15} decorative />
        <span className={cn("text-xs font-semibold", accent.text)}>{ROLE_LABELS[role]}</span>
      </div>

      <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_130px]">
        <RoleRankControls
          rankValue={rank.value}
          sourceLabel={null}
          accent={accent}
          active
          disabled={disabled}
          onClear={own == null ? null : () => rank.commitNow(null)}
          onChange={(next) => rank.set(next)}
        />
      </div>
    </div>
  );
}
