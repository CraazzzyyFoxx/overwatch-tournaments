"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Pin, Save, UserMinus } from "lucide-react";

import { HandleCopyButton } from "@/app/balancer/components/HandleCopyControls";
import { PickupRoleOrderEditor } from "@/app/balancer/mix/PickupRoleOrderEditor";
import { HandleLabel } from "@/components/HandleLabel";
import { CAPTION_CLASS, lobbyLetter } from "@/app/balancer/mix/pickup-chrome";
import RankHistory from "@/components/RankHistory";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { IconTooltip } from "@/components/ui/icon-tooltip";
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  type CustomGamePlayer,
  type CustomGamePlayerPatch,
  type MixParticipation,
  type MixMemberStats,
  type RankSource,
} from "@/services/custom-game.service";

import {
  getLineupIssue,
  playerLabel,
  rankSourceLabel,
  resolveRoleOrder,
  roleRefsOf,
  toggleRole,
  type MixOwner,
} from "./pickup-lineup";
import { formatRecord, formatStreak } from "./pickup-stats";

/** What Save writes into the host's own rank book: `clear` falls the role back to the workspace. */
type PickupRankChange = { ranks: Record<string, number>; clear: string[] };

type PickupPlayerSheetProps = {
  row: CustomGamePlayer | null;
  canEdit: boolean;
  saving: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (patch: CustomGamePlayerPatch, rankChange: PickupRankChange | null) => void;
  onRemove: () => void;
  /** The mix's game: rank history is resolved for it. */
  discipline: string;
  /** The mix owner's game: the roles on offer, their names/tints, the rank labels and the grid. */
  owner: MixOwner;
  /** This player's all-time mix record, or `null` where the page does not read one. */
  mixStats?: MixMemberStats | null;
  /** How many lobbies the mix runs. The pin only exists, and is only sent, past 1. */
  lobbyCount?: number;
};

/** Everything the sheet edits before Save, kept apart from the server row. */
type RoleDraft = {
  participation: MixParticipation;
  /** Priority order of the roles that are on — position is what the balancer reads. */
  order: string[];
  /** Staged writes to the host's own book. A `null` value is a staged Clear. */
  rankEdits: Partial<Record<string, number | null>>;
  /** Every role this row has a rank for is treated as equally preferred, so
   * `order`'s position stops mattering as a priority hint. */
  isFlex: boolean;
  /** Which lobby the host tied this player to, or `null` for "wherever the balance puts them". */
  lobbyPin: number | null;
  /** Stepped away (spec §7.4): in no lineup until back; the must-play mark waits. */
  away: boolean;
};

function buildDraft(row: CustomGamePlayer | null, roles: readonly string[]): RoleDraft {
  return {
    participation: row?.participation ?? "pool",
    order: row ? resolveRoleOrder(row, roles) : [],
    rankEdits: {},
    isFlex: row?.is_flex ?? false,
    lobbyPin: row?.lobby_pin ?? null,
    away: row?.away ?? false,
  };
}

/** The three-way status picker, in the same order the lineup columns read left to right. */
const STATUS_OPTIONS: readonly MixParticipation[] = ["must_play", "pool", "benched"];

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
  discipline,
  owner,
  mixStats = null,
  lobbyCount = 1,
}: Readonly<PickupPlayerSheetProps>) {
  const label = row ? playerLabel(row) : "";
  const t = useTranslations("mixes.lobbies");
  const tRoom = useTranslations("mixes.room");
  const tSheet = useTranslations("mixes.sheet");
  const tLineup = useTranslations("mixes.lineup");
  const tCommon = useTranslations("common");
  const layerLabel = (source: RankSource) => tSheet(`source.${source}`);
  // The record across every mix, not this one: a caption, because it is
  // context for the settings below it and nothing here edits it.
  const mixStreak = mixStats ? formatStreak(mixStats.streak) : null;
  const mixRecord =
    mixStats != null && mixStats.games > 0
      ? `${tSheet("record", { record: formatRecord(mixStats), rate: Math.round(mixStats.win_rate * 100) })}${mixStreak ? ` · ${mixStreak}` : ""}`
      : null;
  const [draft, setDraft] = useState<RoleDraft>(() => buildDraft(row, owner.roles));
  // Keyed on the member id rather than the whole row: a background refetch of
  // this same player (another host's edit landing mid-session) must not wipe
  // out an edit still in progress. Resetting during render (not an effect) on
  // an id change is React's own pattern for "state derived from a prop that
  // should reset when the prop's identity changes".
  const [draftedMemberId, setDraftedMemberId] = useState(row?.workspace_member_id);
  if (row?.workspace_member_id !== draftedMemberId) {
    setDraftedMemberId(row?.workspace_member_id);
    setDraft(buildDraft(row, owner.roles));
  }

  // Reads the draft, not the server row: a role turned on (or a rank typed
  // for one) must clear this warning immediately, not once Save round-trips.
  const issue = row ? getLineupIssue(draftRow(row, draft, owner.showsRoles), owner.roles) : null;
  const disabled = !canEdit || saving;

  const toggle = (role: string) =>
    setDraft((current) => ({ ...current, order: toggleRole(current.order, role) }));

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      setDraft(buildDraft(row, owner.roles));
    }
    onOpenChange(open);
  };

  const handleSave = () => {
    // Role references are written in the owner's rated dimension; without it nothing is written.
    if (!row || owner.dimension == null) return;
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
      {
        participation: draft.participation,
        // A one-role game has nothing to order: `null` is every ranked role, and repairs a stored `[]` that
        // would refuse the balance once the first rank lands.
        roles: owner.showsRoles ? roleRefsOf(draft.order, owner.dimension) : null,
        // A game without Full flex never sends one, which also clears a flag stored before it lost it.
        is_flex: owner.flex && draft.isFlex,
        away: draft.away,
        // A one-lobby mix 422s this field, and there is no control to set it.
        ...(lobbyCount > 1 ? { lobby_pin: draft.lobbyPin } : {}),
      },
      Object.keys(draft.rankEdits).length > 0 ? { ranks, clear } : null,
    );
    // The mutations fire-and-forget from here (the page owns their pending
    // state via `saving`); waiting for them to settle before closing left the
    // sheet open with nothing left to do until the network round-tripped.
    handleOpenChange(false);
  };

  return (
    <Sheet open={row != null} onOpenChange={handleOpenChange}>
      <SheetContent side="right" variant="panel" className="w-full sm:max-w-[640px]">
        <SheetHeader variant="panel">
          <Eyebrow>{tLineup("advanced")}</Eyebrow>
          <SheetTitle className="flex items-baseline gap-1.5">
            <HandleLabel handle={label} tagClassName="text-caption" />
            {row?.identity?.handle ? (
              <HandleCopyButton handle={row.identity.handle} className="ml-0.5 shrink-0" />
            ) : null}
          </SheetTitle>
          {mixRecord ? <span className={CAPTION_CLASS}>{mixRecord}</span> : null}
          <SheetDescription>{canEdit ? tSheet("draftHint") : tSheet("readOnly")}</SheetDescription>
        </SheetHeader>

        {row == null ? null : (
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
            <section className="space-y-2.5 border-b border-[color:var(--aqt-border)] px-5 py-4">
              <h3 className="text-caption font-medium text-[color:var(--aqt-fg)]">{tCommon("status")}</h3>
              <ToggleGroup
                variant="card"
                size="sm"
                aria-label={tSheet("statusFor", { name: label })}
                value={draft.participation}
                onValueChange={(participation) =>
                  setDraft((current) => ({ ...current, participation: participation as MixParticipation }))
                }
                className="grid-cols-3 gap-1.5"
              >
                {STATUS_OPTIONS.map((participation) => {
                  const optionLabel = tLineup(`columns.${participation}.title`);
                  return (
                    <ToggleGroupItem
                      key={participation}
                      value={participation}
                      aria-label={tSheet("optionFor", { option: optionLabel, name: label })}
                      disabled={disabled}
                      accent={participation === "must_play" ? "var(--aqt-amber)" : undefined}
                      className="items-center text-center"
                    >
                      <span className="flex items-center gap-1 font-semibold">
                        {participation === "must_play" ? (
                          <Pin
                            className="size-3"
                            aria-hidden="true"
                            fill={draft.participation === "must_play" ? "currentColor" : "none"}
                          />
                        ) : null}
                        {optionLabel}
                      </span>
                      <span className="text-label text-[color:var(--aqt-fg-dim)]">
                        {tSheet(`statusHint.${participation}`)}
                      </span>
                    </ToggleGroupItem>
                  );
                })}
              </ToggleGroup>
              <div className="flex items-center gap-2 pt-1">
                <Switch
                  checked={draft.away}
                  disabled={disabled}
                  aria-label={tRoom("away")}
                  onCheckedChange={(away) => setDraft((current) => ({ ...current, away }))}
                />
                <span className="text-caption text-[color:var(--aqt-fg-muted)]">{tRoom("awayHint")}</span>
              </div>
            </section>

            {lobbyCount > 1 ? (
              <section className="space-y-2.5 border-b border-[color:var(--aqt-border)] px-5 py-4">
                <h3 className="text-caption font-medium text-[color:var(--aqt-fg)]">
                  {t("pinHeading")}
                </h3>
                <ToggleGroup
                  variant="card"
                  size="sm"
                  aria-label={t("pinGroup", { name: label })}
                  value={draft.lobbyPin == null ? "auto" : String(draft.lobbyPin)}
                  onValueChange={(pin) =>
                    setDraft((current) => ({ ...current, lobbyPin: pin === "auto" ? null : Number(pin) }))
                  }
                  className="grid-cols-4 gap-1.5"
                >
                  {/* No tie, then one option per lobby the mix actually runs.
                      "Auto" is a word of its own rather than an interpolated
                      letter, so a locale phrases it apart from the tab label. */}
                  {[null, ...Array.from({ length: lobbyCount }, (_, index) => index)].map((value) => {
                    const optionLabel = value == null ? t("pinAuto") : t("tab", { letter: lobbyLetter(value) });
                    return (
                      <ToggleGroupItem
                        key={value ?? "auto"}
                        value={value == null ? "auto" : String(value)}
                        aria-label={t("pinOption", { option: optionLabel, name: label })}
                        disabled={disabled}
                        className="items-center text-center"
                      >
                        {optionLabel}
                      </ToggleGroupItem>
                    );
                  })}
                </ToggleGroup>
                <p className="text-label text-[color:var(--aqt-fg-dim)]">{t("pinHint")}</p>
              </section>
            ) : null}

            <section className="space-y-2.5 border-b border-[color:var(--aqt-border)] px-5 py-4">
              <h3 className="text-caption font-medium text-[color:var(--aqt-fg)]">
                {owner.showsRoles ? tSheet("rolesAndRanks") : t("rankHeading")}
              </h3>

              <PickupRoleOrderEditor
                owner={owner}
                order={draft.order}
                isFlex={draft.isFlex}
                disabled={disabled}
                label={label}
                onReorder={(nextOrder) => setDraft((current) => ({ ...current, order: nextOrder }))}
                onToggle={toggle}
                onFlexChange={(checked) => setDraft((current) => ({ ...current, isFlex: checked }))}
                rankFor={(role) => {
                  const field = stagedRankFor(row, draft, role, owner.gameName, layerLabel);
                  return {
                    rankValue: field.rankValue,
                    sourceLabel: field.sourceLabel,
                    onChange: (next) =>
                      setDraft((current) => ({
                        ...current,
                        rankEdits: { ...current.rankEdits, [role]: next },
                      })),
                    onClear: field.hasOwnEntry
                      ? () =>
                          setDraft((current) => ({
                            ...current,
                            rankEdits: { ...current.rankEdits, [role]: null },
                          }))
                      : null,
                  };
                }}
              />

              {issue ? (
                <p className="text-xs text-rose-200">{tLineup(`issue.${issue}`)}</p>
              ) : null}
            </section>

            {/* The one thing the mix cannot tell the host: what this player is
                actually ranked in the game right now — only for a game that
                collects a native rank. Read-only, and the same component the
                tournament sheet uses. */}
            {owner.nativeRankName !== null && row.identity?.handle ? (
              <section className="space-y-2 px-5 py-4">
                <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">
                  {tSheet("liveRank", { game: owner.nativeRankName })}
                </Label>
                <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-2.5">
                  <RankHistory userId={row.player_id} discipline={discipline} />
                </div>
              </section>
            ) : null}
          </div>
        )}

        {row != null && canEdit ? (
          <SheetFooter variant="panel" className="sm:justify-between">
            <IconTooltip control label={tLineup("remove")} className="shrink-0">
              <Button
                type="button"
                variant="ghost-destructive"
                size="icon-sm"
                disabled={saving}
                onClick={onRemove}
              >
                <UserMinus aria-hidden="true" />
                <span className="sr-only">{tLineup("removeNamed", { name: label })}</span>
              </Button>
            </IconTooltip>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleOpenChange(false)}
              >
                {tCommon("cancel")}
              </Button>
              <Button
                onClick={handleSave}
                disabled={saving || owner.dimension == null}
                size="sm"
              >
                <Save className="mr-1 h-3.5 w-3.5" />
                {tCommon("save")}
              </Button>
            </div>
          </SheetFooter>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

/** The server row with every staged edit folded in, for `getLineupIssue`: its roles are the ones Save writes. */
function draftRow(row: CustomGamePlayer, draft: RoleDraft, showsRoles: boolean): CustomGamePlayer {
  const ranks = { ...row.ranks };
  for (const [role, value] of Object.entries(draft.rankEdits)) {
    if (value == null) {
      delete ranks[role];
    } else {
      ranks[role] = value;
    }
  }
  return {
    ...row,
    participation: draft.participation,
    // Only the codes are read back (`resolveRoleOrder`), so the dimension is irrelevant here.
    roles: showsRoles ? roleRefsOf(draft.order, "") : null,
    ranks,
  };
}

/** The rank field's value, source badge and clearability, from the server row plus any staged edit. */
function stagedRankFor(
  row: CustomGamePlayer,
  draft: RoleDraft,
  role: string,
  gameName: string | null,
  layerLabel: (source: RankSource) => string,
): { rankValue: number | null; sourceLabel: string | null; hasOwnEntry: boolean } {
  const staged = draft.rankEdits[role];
  if (staged !== undefined) {
    return {
      rankValue: staged,
      sourceLabel: staged == null ? null : rankSourceLabel("author", gameName, layerLabel),
      hasOwnEntry: staged != null,
    };
  }
  const source = row.rank_sources[role] ?? null;
  return {
    rankValue: row.ranks[role] ?? null,
    sourceLabel: source ? rankSourceLabel(source, gameName, layerLabel) : null,
    hasOwnEntry: row.author_ranks[role] != null,
  };
}
