"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Field, FieldDescription, FieldLabel, FieldTitle } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  PICK_BAN_MODES,
  type PickBanDraft,
  type PickBanDraftSlot
} from "@/lib/tournament/pick-ban-config";
import type { MapVetoMode, PickBanKind } from "@/types/tournament.types";

import { CatalogueChips, CataloguePicker, type CatalogueItem } from "./CataloguePicker";

/** Step 1: which maps or heroes this scope plays, and in what shape. */
export function PoolStep({
  ids,
  draft,
  kind,
  slotCount,
  isStageScope,
  roundsLoading,
  roundLabelFor,
  catalogue,
  catalogueById,
  catalogueLoading,
  canManage,
  patch,
  patchSlot,
  patchRoundSlot,
  onModeChange,
  toggleItem
}: Readonly<{
  ids: string;
  draft: PickBanDraft;
  kind: PickBanKind;
  /** Groups the bracket calls for in a one-round scope; the list is this long. */
  slotCount: number;
  /** A whole stage is on screen, so any groups here cover every round of it. */
  isStageScope: boolean;
  /** The stage's rounds are still being predicted, so they cannot be listed. */
  roundsLoading: boolean;
  /** What the bracket calls a round — "LB Round 1", "Grand Final", not "-1". */
  roundLabelFor: (round: number) => string;
  catalogue: CatalogueItem[];
  catalogueById: Map<number, CatalogueItem>;
  catalogueLoading: boolean;
  canManage: boolean;
  patch: (values: Partial<PickBanDraft>) => void;
  patchSlot: (index: number, slotPatch: Partial<PickBanDraftSlot>) => void;
  patchRoundSlot: (
    roundIndex: number,
    slotIndex: number,
    slotPatch: Partial<PickBanDraftSlot>
  ) => void;
  /** Owns the round dimension the pool shape decides, so it lives upstairs. */
  onModeChange: (mode: MapVetoMode) => void;
  toggleItem: (itemId: number) => void;
}>) {
  const t = useTranslations("pickBan.admin");
  const isHero = kind === "hero";

  return (
    <>
      <div>
        <FieldTitle className="text-sm">{t("poolSection")}</FieldTitle>
        <FieldDescription>{t("poolSectionHint")}</FieldDescription>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor={`${ids}-mode`}>{t("modeLabel")}</FieldLabel>
          <Select
            value={draft.mode}
            disabled={!canManage}
            onValueChange={(value) => onModeChange(value as MapVetoMode)}
          >
            <SelectTrigger id={`${ids}-mode`} aria-describedby={`${ids}-mode-hint`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PICK_BAN_MODES.map((mode) => (
                <SelectItem key={mode} value={mode}>
                  {mode === "pool" ? t("modePool") : t("modeSlots")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <FieldDescription id={`${ids}-mode-hint`}>
            {draft.mode === "pool" ? t("modePoolHint") : t("modeSlotsHint")}
          </FieldDescription>
        </Field>
      </div>

      {draft.mode === "pool" ? (
        <Field>
          <FieldTitle className="text-sm">
            {isHero ? t("poolHeroLabel") : t("poolMapLabel")}
            <Badge variant="secondary">{t("poolCount", { count: draft.itemIds.length })}</Badge>
          </FieldTitle>
          <FieldDescription>{t("poolHint")}</FieldDescription>
          <CatalogueChips
            itemIds={draft.itemIds}
            catalogue={catalogueById}
            disabled={!canManage}
            onRemove={toggleItem}
            leading={
              <CataloguePicker
                mode="multi"
                kind={kind}
                options={catalogue}
                selectedIds={draft.itemIds}
                disabled={catalogueLoading || !canManage}
                onToggle={toggleItem}
                onSelectVisible={(itemIds) =>
                  patch({
                    itemIds: [
                      ...draft.itemIds,
                      ...itemIds.filter((id) => !draft.itemIds.includes(id))
                    ]
                  })
                }
                onClearVisible={(itemIds) =>
                  patch({ itemIds: draft.itemIds.filter((id) => !itemIds.includes(id)) })
                }
              />
            }
          />
        </Field>
      ) : draft.roundSlots.length > 0 ? (
        <div className="flex flex-col gap-4">
          <FieldDescription>{t("roundGroupsHint")}</FieldDescription>

          {draft.roundSlots.map((section, roundIndex) => (
            <div
              key={section.round}
              className="flex flex-col gap-2 rounded-xl border border-border bg-muted/20 p-3"
            >
              <FieldTitle className="text-sm">
                {roundLabelFor(section.round)}
                <Badge variant="outline">
                  {t("roundGroupCount", { count: section.slots.length })}
                </Badge>
              </FieldTitle>

              {section.slots.map((slot, index) => (
                <SlotCard
                  key={index}
                  label={t("slotTitle", { n: index + 1 })}
                  reserveLabel={t("slotReserveAria", { n: index + 1 })}
                  slot={slot}
                  kind={kind}
                  catalogue={catalogue}
                  catalogueById={catalogueById}
                  catalogueLoading={catalogueLoading}
                  canManage={canManage}
                  onPatch={(slotPatch) => patchRoundSlot(roundIndex, index, slotPatch)}
                />
              ))}
            </div>
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <FieldDescription>
            {roundsLoading
              ? t("roundHintLoading")
              : isStageScope
                ? t("roundsUnknownStageWide")
                : t("slotCountFromBracket", { maps: slotCount })}
          </FieldDescription>

          {draft.slots.map((slot, index) => (
            <SlotCard
              key={index}
              label={t("slotTitle", { n: index + 1 })}
              reserveLabel={t("slotReserveAria", { n: index + 1 })}
              slot={slot}
              kind={kind}
              catalogue={catalogue}
              catalogueById={catalogueById}
              catalogueLoading={catalogueLoading}
              canManage={canManage}
              onPatch={(slotPatch) => patchSlot(index, slotPatch)}
            />
          ))}
        </div>
      )}
    </>
  );
}

/**
 * One group: its candidates in play order, its reserve, and the pickers for
 * both. The same card whether it belongs to a single round's scope or to one
 * round of a stage screen — only where the patch lands differs.
 */
function SlotCard({
  label,
  reserveLabel,
  slot,
  kind,
  catalogue,
  catalogueById,
  catalogueLoading,
  canManage,
  onPatch
}: Readonly<{
  label: string;
  reserveLabel: string;
  slot: PickBanDraftSlot;
  kind: PickBanKind;
  catalogue: CatalogueItem[];
  catalogueById: Map<number, CatalogueItem>;
  catalogueLoading: boolean;
  canManage: boolean;
  onPatch: (slotPatch: Partial<PickBanDraftSlot>) => void;
}>) {
  const t = useTranslations("pickBan.admin");

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <FieldTitle className="text-sm">
          {label}
          <Badge variant="secondary">
            {t("slotCandidates", { count: slot.candidates.length })}
          </Badge>
        </FieldTitle>
        <CataloguePicker
          mode="single"
          kind={kind}
          triggerLabel={reserveLabel}
          triggerPrefix={t("slotReserve")}
          value={slot.reserveItemId}
          // The server rejects a reserve that is also a candidate, so it is
          // never offered here.
          options={catalogue.filter((option) => !slot.candidates.includes(option.id))}
          disabled={catalogueLoading || !canManage}
          onChange={(itemId) => onPatch({ reserveItemId: itemId })}
        />
      </div>

      <CatalogueChips
        itemIds={slot.candidates}
        catalogue={catalogueById}
        disabled={!canManage}
        onRemove={(itemId) =>
          onPatch({ candidates: slot.candidates.filter((id) => id !== itemId) })
        }
        leading={
          <CataloguePicker
            mode="multi"
            kind={kind}
            options={catalogue}
            selectedIds={slot.candidates}
            disabled={catalogueLoading || !canManage}
            onToggle={(itemId) =>
              onPatch({
                candidates: slot.candidates.includes(itemId)
                  ? slot.candidates.filter((id) => id !== itemId)
                  : [...slot.candidates, itemId],
                // A candidate can no longer be this group's reserve.
                reserveItemId: slot.reserveItemId === itemId ? null : slot.reserveItemId
              })
            }
            onSelectVisible={(itemIds) =>
              onPatch({
                candidates: [
                  ...slot.candidates,
                  ...itemIds.filter((id) => !slot.candidates.includes(id))
                ],
                // The catalogue offered here isn't narrowed like the reserve
                // picker's is, so a bulk add can catch the current reserve;
                // drop it rather than leave a candidate double-booked as its
                // own group's reserve.
                reserveItemId:
                  slot.reserveItemId != null && itemIds.includes(slot.reserveItemId)
                    ? null
                    : slot.reserveItemId
              })
            }
            onClearVisible={(itemIds) =>
              onPatch({ candidates: slot.candidates.filter((id) => !itemIds.includes(id)) })
            }
          />
        }
      />
      <FieldDescription>{t("slotReserveHint")}</FieldDescription>
    </div>
  );
}
