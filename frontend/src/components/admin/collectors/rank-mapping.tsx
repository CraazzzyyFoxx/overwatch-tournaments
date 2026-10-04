"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { CollectionSettingsPanel, useCollectionSettings } from "@/components/admin/CollectionSettingsPanel";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  OW_REFERENCE_GRID,
  getTierForRank,
  resolveDivisionFromRank,
  resolveRankFromDivision,
  sortTiersDescending
} from "@/lib/divisions/grid";
import { OW_DIVISIONS_DESC } from "@/lib/divisions/ow-ladder";
import {
  DEFAULT_RANK_MAPPING_VERSION,
  buildMappingCells,
  defaultRankForCell
} from "@/lib/divisions/ow-rank-mapping";
import type { RankMappingConfig, RankMappingEntry } from "@/types/admin.types";

const RANK_MAPPING_KEY = "parser.rank_mapping";

// The OW ladder, NOT the current workspace's grid: `parser.rank_mapping` is a
// global setting, and the backend re-resolves each stored rank_value through a
// tournament's own grid at autofill time (rank_sources._map_ow_rank_value), so
// the value written here has to stay on the OW/SR scale.
const GRID = OW_REFERENCE_GRID;

interface MappingForm {
  version: string;
  cells: RankMappingEntry[];
}

const read = (stored: Partial<RankMappingConfig> | undefined): MappingForm => ({
  version: stored?.version ?? DEFAULT_RANK_MAPPING_VERSION,
  cells: buildMappingCells(stored?.entries ?? [])
});

const isDefault = (cell: RankMappingEntry) =>
  cell.rank_value === defaultRankForCell(cell.division, cell.tier);

// Only the cells that differ from the ladder. Saving all of them froze the v1
// table into the setting, where it outlived the Emerald rebase (migration
// owmapfix01).
const write = (form: MappingForm) => ({
  version: form.version,
  entries: form.cells.filter((cell) => !isDefault(cell))
});

const countChanges = (form: MappingForm, baseline: MappingForm) =>
  form.cells.filter((cell, index) => cell.rank_value !== baseline.cells[index]?.rank_value).length;

const capitalize = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);

/**
 * `parser.rank_mapping`: which ladder division each OverFast rank lands on.
 * One group per OverFast division, one row per tier — the same rows-and-groups
 * layout as every other settings screen.
 */
export function RankMappingPanel() {
  const t = useTranslations("collectors.mapping");
  const tiers = useMemo(() => sortTiersDescending(GRID), []);
  const settings = useCollectionSettings<MappingForm>({
    settingKey: RANK_MAPPING_KEY,
    read,
    write,
    countChanges
  });

  return (
    <CollectionSettingsPanel settings={settings}>
      {(form, patch) => {
        const setRank = (target: RankMappingEntry, divisionNumber: number) =>
          patch({
            cells: form.cells.map((cell) =>
              cell === target
                ? { ...cell, rank_value: resolveRankFromDivision(GRID, divisionNumber) ?? cell.rank_value }
                : cell
            )
          });

        return (
          <>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <p className="max-w-prose text-sm text-muted-foreground">{t("description")}</p>
              <Button
                variant="outline"
                size="sm"
                disabled={form.cells.every(isDefault)}
                onClick={() =>
                  patch({
                    cells: form.cells.map((cell) => ({
                      ...cell,
                      rank_value: defaultRankForCell(cell.division, cell.tier)
                    }))
                  })
                }
              >
                {t("reset")}
              </Button>
            </div>

            {OW_DIVISIONS_DESC.map((division) => (
              <SettingGroup key={division} title={capitalize(division)}>
                {form.cells
                  .filter((cell) => cell.division === division)
                  .map((cell) => {
                    const label = `${capitalize(cell.division)} ${cell.tier}`;
                    const tier = getTierForRank(GRID, cell.rank_value);
                    const divisionNumber = resolveDivisionFromRank(GRID, cell.rank_value);
                    return (
                      <SettingRow key={cell.tier} label={label}>
                        <Select
                          value={divisionNumber != null ? String(divisionNumber) : ""}
                          onValueChange={(value) => setRank(cell, Number(value))}
                        >
                          <SelectTrigger
                            className="h-8 w-full max-w-xs text-sm"
                            aria-label={t("selectAria", { rank: label })}
                          >
                            <SelectValue placeholder={t("selectPlaceholder")}>
                              {tier ? (
                                <span className="flex items-center gap-2">
                                  {/* eslint-disable-next-line @next/next/no-img-element */}
                                  <img src={tier.icon_url} alt="" width={20} height={20} />
                                  <span className="truncate">{tier.name}</span>
                                  <span className="ml-auto text-xs tabular-nums text-muted-foreground">
                                    {tier.rank_min}
                                    {tier.rank_max != null ? `–${tier.rank_max}` : "+"}
                                  </span>
                                </span>
                              ) : null}
                            </SelectValue>
                          </SelectTrigger>
                          <SelectContent>
                            {tiers.map((option) => (
                              <SelectItem key={option.number} value={String(option.number)}>
                                <span className="flex items-center gap-2">
                                  {/* eslint-disable-next-line @next/next/no-img-element */}
                                  <img src={option.icon_url} alt="" width={18} height={18} />
                                  {option.name}
                                </span>
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </SettingRow>
                    );
                  })}
              </SettingGroup>
            ))}
          </>
        );
      }}
    </CollectionSettingsPanel>
  );
}
