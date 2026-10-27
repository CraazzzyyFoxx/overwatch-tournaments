"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { Card } from "@/components/ui/card";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { DivisionGridReadinessSource, DivisionTier } from "@/types/workspace.types";

import {
  autoMap,
  resolveTarget,
  type MappingChoice,
  type MappingChoices,
  type MappingRow,
  type MappingTarget
} from "./autoMap";
import { rankRangeLabel, type Band, type Ladder } from "./draftReducer";
import { MappingTargetPicker, useTargetSummary } from "./MappingTargetPicker";

export interface MappingSource {
  readiness: DivisionGridReadinessSource;
  tiers: DivisionTier[];
}

export interface MappingsViewProps {
  ladder: Ladder | null;
  targetLabel: string;
  bands: Band[];
  sources: MappingSource[];
  /** source tier id → choice: the stored mapping, overlaid with this session's picks. */
  chosen: MappingChoices;
  /** `null` returns the row to the automatic mapping. */
  onChoose: (sourceTierId: number, choice: MappingChoice | null) => void;
  editable: boolean;
  /**
   * `false` until the draft has been saved once: the rules key on target tier
   * ids, and an unsaved band has none.
   */
  mappable: boolean;
  loading: boolean;
}

/**
 * Mappings (F12b ·1): where the players of every version a tournament still
 * reads land in this draft.
 *
 * Overlap on the rank scale proposes a target (Auto); a tie needs a person
 * (Split). Every row can be overridden with a range of divisions the players
 * spread over and the one they land in: when an older version sits on another
 * rank scale, overlap is only a guess and the organiser knows better. The
 * unresolved count is the tab badge and the "Ready to publish?" blocker.
 */
export function MappingsView({
  ladder,
  targetLabel,
  bands,
  sources,
  chosen,
  onChoose,
  editable,
  mappable,
  loading
}: Readonly<MappingsViewProps>) {
  const t = useTranslations("adminSettings.divisions");
  const targetSummary = useTargetSummary();

  /** How a row's target was reached: a tie to pick, a manual or automatic range, or the overlap share. */
  const matchLabel = (row: MappingRow, target: MappingTarget | null): string => {
    if (target === null) return t("mappingLabels.matchTie");
    const mode = target.manual ? "manual" : "auto";
    if (target.range.length > 1) {
      return t("mappingLabels.matchRange", { mode, count: target.range.length });
    }
    const overlap = row.candidates.find((entry) => entry.band.slug === target.primary.slug);
    return overlap
      ? t("mappingLabels.matchShare", { mode, share: overlap.weight })
      : t("mappingLabels.matchNoOverlap", { mode });
  };
  const mapped = useMemo(
    () => sources.map((source) => ({ ...source, rows: autoMap(ladder, source.tiers, bands) })),
    [bands, ladder, sources]
  );

  if (!mappable) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("mappings.saveFirst")}
      </p>
    );
  }

  if (loading) return <Skeleton className="h-48 w-full rounded-xl" />;

  if (sources.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("mappings.noMapping")}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {mapped.map(({ readiness, rows }) => {
        return (
          <section key={readiness.version_id} className="flex min-w-0 flex-col gap-2">
            <p className={eyebrowClass("muted")}>
              {t("mappingLabels.header", {
                source: readiness.version_label,
                target: targetLabel,
                tournaments: readiness.tournament_count,
                divisions: rows.length
              })}
            </p>

            <Card className="min-w-0 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left">
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t("table.versionDivision", { version: readiness.version_label })}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t("table.rankRange")}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t("mappingLabels.inTarget", { target: targetLabel })}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t("mappingLabels.match")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const target = resolveTarget(row, chosen, bands);
                    const sourceTierId = row.source.id;
                    return (
                      <tr key={row.source.slug} className="border-b border-border last:border-b-0">
                        <td className="px-3 py-2">{row.source.name}</td>
                        <td className="px-3 py-2 text-xs tabular-nums text-muted-foreground">
                          {rankRangeLabel(row.source)}
                        </td>
                        <td className="px-3 py-2">
                          {editable && sourceTierId !== undefined ? (
                            <MappingTargetPicker
                              row={row}
                              bands={bands}
                              target={target}
                              onChange={(choice) => onChoose(sourceTierId, choice)}
                            />
                          ) : target ? (
                            targetSummary(target)
                          ) : (
                            <span className="text-warning">{t("mappings.unresolved")}</span>
                          )}
                        </td>
                        <td
                          className={cn(
                            "px-3 py-2 text-xs",
                            target === null ? "text-warning" : "text-muted-foreground"
                          )}
                        >
                          {matchLabel(row, target)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Card>
          </section>
        );
      })}
    </div>
  );
}
