"use client";

import { useTranslations } from "next-intl";

import { HandleCopyButton } from "@/app/balancer/components/HandleCopyControls";
import { HandleLabel } from "@/components/HandleLabel";
import {
  RoleRankControls,
  accentRowStyle,
  accentTextStyle,
  roleRankAccent,
  useDebouncedRank,
} from "@/app/balancer/components/RoleRankControls";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import RankHistory from "@/components/RankHistory";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { registrationRoles, type RoleOntology } from "@/lib/roster/ontology";
import type { RosterMember } from "@/services/workspace-player.service";
import type { DisciplineMetadata } from "@/types/discipline.types";
import type { DivisionGrid } from "@/types/workspace.types";

type WorkspacePlayerSheetProps = {
  /** `null` closes the sheet — the caller holds the row being edited. */
  member: RosterMember | null;
  /** The roster's game: rank history is resolved for it. */
  discipline: string;
  /** The roster game's metadata: which roles carry a rank card (names, glyphs, tints) and whether it has a live rank. */
  ontology: DisciplineMetadata | null;
  /** The grid the ranks are on: the roster game's grid in the workspace. */
  grid: DivisionGrid;
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
  discipline,
  ontology,
  grid,
  canEdit,
  saving,
  onOpenChange,
  onSaveRank,
}: Readonly<WorkspacePlayerSheetProps>) {
  const t = useTranslations("balancerTool.pool.sheet");
  const label = member ? member.display_name || member.identity?.handle || `#${member.member_id}` : "";
  // Only a game that collects native ranks has a live rank to show.
  const nativeRankName = ontology?.discipline.capabilities.native_rank_collection ? ontology.discipline.name : null;
  const roles = registrationRoles(ontology).map((role) => role.code);

  return (
    <Sheet open={member != null} onOpenChange={onOpenChange}>
      <SheetContent side="right" variant="panel" className="w-full overflow-y-auto sm:max-w-[560px]">
        <SheetHeader variant="panel">
          <Eyebrow tone="dim">{t("eyebrow")}</Eyebrow>
          <SheetTitle className="flex items-baseline gap-1.5">
            <HandleLabel handle={label} tagClassName="text-caption" />
            {member?.identity?.handle ? (
              <HandleCopyButton handle={member.identity.handle} className="ml-0.5 shrink-0" />
            ) : null}
          </SheetTitle>
          {/* The panel that mounts this sheet only ever reads/writes the workspace
              canon (`WorkspacePlayersSidebar`'s sole caller is the tournament balancer
              page); the per-mix "author" layer has its own sheet (`PickupPlayerSheet`). */}
          <SheetDescription>{t("scopeHint")}</SheetDescription>
        </SheetHeader>

        {member == null ? null : (
          <div className="flex min-h-0 flex-1 flex-col">
            <section className="space-y-2 border-b border-[color:var(--aqt-border)] px-5 py-4">
              <div>
                <h3 className="text-caption font-medium text-[color:var(--aqt-fg)]">
                  {t("rolesTitle")}
                </h3>
                <p className="mt-0.5 text-xs text-[color:var(--aqt-fg-dim)]">
                  {t("rolesHint")}
                </p>
              </div>

              <ul className="space-y-2">
                {roles.map((role) => (
                  <li
                    key={role}
                    className="rounded-xl border p-2.5"
                    style={accentRowStyle(roleRankAccent(ontology, role))}
                  >
                    <RoleRankCard
                      member={member}
                      role={role}
                      ontology={ontology}
                      grid={grid}
                      disabled={!canEdit || saving}
                      onSaveRank={onSaveRank}
                    />
                  </li>
                ))}
              </ul>
            </section>

            {/* The one thing the roster cannot tell an organiser: what this
                player is actually ranked in the game right now, for a game
                that collects a native rank. Read-only, and the same component
                both other sheets use. */}
            {nativeRankName !== null && member.identity?.handle ? (
              <section className="space-y-2 px-5 py-4">
                <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">
                  {t("liveRank", { game: nativeRankName })}
                </Label>
                <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-2.5">
                  <RankHistory userId={member.player_id} discipline={discipline} />
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
  ontology,
  grid,
  disabled,
  onSaveRank,
}: Readonly<{
  member: RosterMember;
  role: string;
  ontology: RoleOntology | null;
  grid: DivisionGrid;
  disabled: boolean;
  onSaveRank: (role: string, rank: number | null) => void;
}>) {
  const slotLabel = useSlotLabel(ontology);
  const accent = roleRankAccent(ontology, role);
  const own = member.ranks[role] ?? null;
  const rank = useDebouncedRank(own, (next) => onSaveRank(role, next));

  return (
    <div className="min-w-0 space-y-2">
      <div className="flex items-center gap-1.5">
        <PlayerRoleIcon role={role} ontology={ontology} size={15} decorative />
        <span className="text-xs font-semibold" style={accentTextStyle(accent)}>
          {slotLabel(role)}
        </span>
      </div>

      <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_130px]">
        <RoleRankControls
          rankValue={rank.value}
          sourceLabel={null}
          accent={accent}
          active
          disabled={disabled}
          grid={grid}
          onClear={own == null ? null : () => rank.commitNow(null)}
          onChange={(next) => rank.set(next)}
        />
      </div>
    </div>
  );
}
