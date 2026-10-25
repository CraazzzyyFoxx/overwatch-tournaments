"use client";

import { Sparkles, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { SortableGrip, useSortableRow } from "@/components/kit/SortableRows";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { RowButton } from "@/components/ui/row-button";
import { Eyebrow } from "@/components/ui/eyebrow";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type {
  BalancerPlayerRoleEntry,
  BalancerRoleCode,
  BalancerRoleSubtype
} from "@/types/balancer-admin.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { useSlotLabel } from "@/hooks/useSlotLabel";
import type { RoleOntology } from "@/lib/roster/ontology";
import {
  AccentBadge,
  RoleRankControls,
  accentRowStyle,
  accentTextStyle,
  roleRankAccent
} from "./RoleRankControls";

type SortableRoleEntryProps = {
  id: string;
  entry: BalancerPlayerRoleEntry;
  index: number;
  grid: DivisionGrid;
  resolveDivision: (rankValue: number | null) => number | null;
  getDivisionName: (divisionNumber: number | null) => string | null;
  onUpdate: (index: number, next: BalancerPlayerRoleEntry) => void;
  onRemove: (index: number) => void;
  subtypeOptions: Record<BalancerRoleCode, Array<{ value: string; label: string }>>;
  /** The owner game's role dictionary: role names, glyphs and tints. `null` while it loads. */
  ontology: RoleOntology | null;
  /** The owner game's name when it collects native ranks (`native_rank_collection`), else `null`: no live-rank row. */
  nativeRankName: string | null;
  /** More than one role in the game: the card names its role and can reorder, turn off or remove it. */
  showsRole: boolean;
};

export function SortableRoleEntry({
  id,
  entry,
  index,
  grid,
  resolveDivision,
  getDivisionName,
  onUpdate,
  onRemove,
  subtypeOptions,
  ontology,
  nativeRankName,
  showsRole
}: Readonly<SortableRoleEntryProps>) {
  const t = useTranslations("balancerTool.playerEdit.role");
  const tCommon = useTranslations("common");
  const { ref, style, handleProps } = useSortableRow(id);

  const slotLabel = useSlotLabel(ontology);
  const roleName = slotLabel(entry.role);
  const accent = roleRankAccent(ontology, entry.role);
  // This card is the organizer's EDITING view, so every visual here follows the
  // declared flag. `is_active` is the resolver's "in play" verdict and belongs
  // to the pool/validation views: dimming a declared-on role because its rank is
  // still missing would grey out exactly the field that fixes it.
  const declaredActive = entry.is_declared_active;

  const roleSubtypeOptions = subtypeOptions[entry.role] || [];
  const subtypeLabel = entry.subtype
    ? (roleSubtypeOptions.find((option) => option.value === entry.subtype)?.label ?? entry.subtype)
    : null;
  const hasSubtypeOptions = roleSubtypeOptions.length > 0;

  // The game's live native rank (already mapped to the workspace grid) as a one-click suggestion. Only a game
  // that collects native ranks has the row; for the others there is nothing to suggest and nothing to show.
  const owRankValue = entry.ow_rank_value ?? null;
  const owSuggestionDivision = owRankValue != null ? resolveDivision(owRankValue) : null;
  const owSuggestionName =
    owSuggestionDivision != null ? getDivisionName(owSuggestionDivision) : null;
  const owMatchesCurrent = owRankValue != null && owRankValue === entry.rank_value;
  const owActionLabel =
    entry.rank_value == null ? t("liveUse") : owMatchesCurrent ? t("liveMatches") : t("liveApply");

  return (
    <div
      ref={ref}
      style={{ ...style, ...(declaredActive ? accentRowStyle(accent) : undefined) }}
      className={cn(
        "grid gap-2 rounded-xl border p-2.5 transition-colors",
        showsRole && "md:grid-cols-[32px_minmax(0,1fr)]",
        declaredActive
          ? "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)]"
          : "border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] opacity-80"
      )}
    >
      {showsRole ? (
        <div className="flex items-center justify-between md:flex-col md:items-center md:justify-center md:gap-1">
          <SortableGrip handleProps={handleProps} label={t("reorder", { role: roleName })} />
          <span className="text-label font-semibold text-[color:var(--aqt-fg-dim)]">
            #{index + 1}
          </span>
        </div>
      ) : null}

      <div className="space-y-2">
        {/* One role: nothing to name, turn off or remove -- the rank below is the whole card. */}
        {showsRole ? (
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5">
              <PlayerRoleIcon role={entry.role} ontology={ontology} size={15} decorative />
              <span
                className="text-xs font-semibold"
                style={declaredActive ? accentTextStyle(accent) : { color: "var(--aqt-fg-muted)" }}
              >
                {roleName}
              </span>
              {subtypeLabel ? (
                <AccentBadge accent={accent}>{subtypeLabel}</AccentBadge>
              ) : null}
            </div>

            <div className="flex items-center gap-1.5">
              <div className="flex h-6 items-center gap-1.5 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2">
                <Switch
                  checked={declaredActive}
                  size="sm"
                  onCheckedChange={(checked) =>
                    onUpdate(index, { ...entry, is_declared_active: checked })
                  }
                  aria-label={declaredActive ? t("disable") : t("enable")}
                />
                <span
                  className="text-label font-semibold uppercase tracking-label"
                  style={declaredActive ? accentTextStyle(accent) : { color: "var(--aqt-fg-dim)" }}
                >
                  {declaredActive ? t("active") : t("off")}
                </span>
              </div>

              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 shrink-0 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] text-[color:var(--aqt-fg-dim)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
                aria-label={t("remove", { role: roleName })}
                onClick={() => onRemove(index)}
              >
                <Trash2 className="h-3 w-3" aria-hidden="true" />
              </Button>
            </div>
          </div>
        ) : null}

        <div
          className={cn(
            "grid gap-2",
            showsRole
              ? "lg:grid-cols-[minmax(0,140px)_minmax(0,1fr)_130px]"
              : "lg:grid-cols-[minmax(0,1fr)_130px]"
          )}
        >
          {/* Sub-roles specialise one of several roles; a one-role game's card names neither. */}
          {showsRole ? (
            <div className="space-y-1">
              <Eyebrow tone="dim">{t("subRole")}</Eyebrow>
              <Select
                value={entry.subtype ?? "none"}
                disabled={!hasSubtypeOptions}
                onValueChange={(value) =>
                  onUpdate(index, {
                    ...entry,
                    subtype: value === "none" ? null : (value as BalancerRoleSubtype)
                  })
                }
              >
                <SelectTrigger
                  size="sm"
                  className={cn(
                    "h-7 w-full px-2",
                    !declaredActive && "text-[color:var(--aqt-fg-dim)]"
                  )}
                >
                  <SelectValue placeholder={t("subRole")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t("noSubRole")}</SelectItem>
                  {roleSubtypeOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}

          <RoleRankControls
            rankValue={entry.rank_value}
            grid={grid}
            sourceLabel={
              entry.rank_source && entry.rank_source !== "none" ? t(`source.${entry.rank_source}`) : null
            }
            accent={accent}
            active={declaredActive}
            onClear={
              entry.rank_value == null
                ? null
                : () => onUpdate(index, { ...entry, rank_value: null, division_number: null })
            }
            onChange={(rankValue, divisionNumber) =>
              onUpdate(index, { ...entry, rank_value: rankValue, division_number: divisionNumber })
            }
          />
        </div>

        {nativeRankName === null ? null : owRankValue != null ? (
          <RowButton
            type="button"
            onClick={() =>
              onUpdate(index, {
                ...entry,
                rank_value: owRankValue,
                division_number: owSuggestionDivision
              })
            }
            title={
              owSuggestionName
                ? t("applyLiveDivision", {
                    game: nativeRankName,
                    division: owSuggestionName,
                    value: String(owRankValue)
                  })
                : t("applyLive", { game: nativeRankName, value: String(owRankValue) })
            }
            className="flex items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2 py-1.5 hover:bg-[color:var(--aqt-overlay-3)]"
          >
            <Sparkles className="h-3 w-3 shrink-0 text-amber-300/70" />
            <Eyebrow tone="dim">{nativeRankName}</Eyebrow>
            {owSuggestionDivision != null ? (
              <DivisionIcon
                division={owSuggestionDivision}
                tournamentGrid={grid}
                width={16}
                height={16}
              />
            ) : null}
            <span className="truncate text-label font-medium text-[color:var(--aqt-fg-muted)]">
              {owSuggestionName ?? tCommon("divisionWithId", { id: String(owSuggestionDivision) })}
            </span>
            <span className="text-label tabular-nums text-[color:var(--aqt-fg-dim)]">
              ({owRankValue})
            </span>
            <AccentBadge accent={accent} className="ml-auto shrink-0 font-semibold">
              {owActionLabel}
            </AccentBadge>
          </RowButton>
        ) : (
          <div className="flex w-full items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] px-2 py-1.5 text-left">
            <Sparkles className="h-3 w-3 shrink-0 text-[color:var(--aqt-fg-faint)]" />
            <Eyebrow tone="dim">{nativeRankName}</Eyebrow>
            <span className="text-label text-[color:var(--aqt-fg-dim)]">
              {t("noLiveRank", { game: nativeRankName })}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
