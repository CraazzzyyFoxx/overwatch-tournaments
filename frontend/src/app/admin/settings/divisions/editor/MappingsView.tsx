"use client";

import { useMemo } from "react";

import { StatusPill } from "@/components/kit/StatusPill";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { DivisionGridReadinessSource, DivisionTier } from "@/types/workspace.types";

import { autoMap, primaryTarget, unresolvedRows } from "./autoMap";
import { bandShortLabel, type Band } from "./draftReducer";

export interface MappingSource {
  readiness: DivisionGridReadinessSource;
  tiers: DivisionTier[];
}

export interface MappingsViewProps {
  targetLabel: string;
  bands: Band[];
  sources: MappingSource[];
  /** source tier id → chosen target tier id, for the rows AUTO cannot decide. */
  chosen: Record<number, number | undefined>;
  onChoose: (sourceTierId: number, targetTierId: number) => void;
  editable: boolean;
  /**
   * `false` until the draft has been saved once: the rules key on target tier
   * ids, and an unsaved band has none.
   */
  mappable: boolean;
  loading: boolean;
}

/**
 * Mappings (F12b ·1) — the old `ConflictResolver`, promoted from a
 * post-failure step to a permanent view of the editor.
 *
 * Every tournament keeps the version it was played on, so each version another
 * tournament still reads needs a translation into this draft. Overlap decides
 * it: the new division holding most of an old band's ranks wins outright
 * (AUTO), and only a band cut evenly in two needs a person to say where its
 * players go (SPLIT). That is the same count as the tab badge and the
 * "Ready to publish?" blocker — one number, computed in one place.
 */
export function MappingsView({
  targetLabel,
  bands,
  sources,
  chosen,
  onChoose,
  editable,
  mappable,
  loading
}: Readonly<MappingsViewProps>) {
  const mapped = useMemo(
    () => sources.map((source) => ({ ...source, rows: autoMap(source.tiers, bands) })),
    [bands, sources]
  );

  if (!mappable) {
    return (
      <p className="text-sm text-muted-foreground">
        Save the draft to compute mappings. Until then its divisions have no ids for the older
        versions to point at.
      </p>
    );
  }

  if (loading) return <Skeleton className="h-48 w-full rounded-xl" />;

  if (sources.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No other version is still read by a tournament, so this draft needs no mapping.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {mapped.map(({ readiness, rows }) => {
        const unresolved = unresolvedRows(rows, chosen);
        return (
          <section key={readiness.version_id} className="flex min-w-0 flex-col gap-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className={cn(EYEBROW_CLASS, "font-mono")}>
                {readiness.version_label} &rarr; {targetLabel} · {readiness.tournament_count}{" "}
                {readiness.tournament_count === 1 ? "tournament" : "tournaments"} · {rows.length}{" "}
                source divisions
              </p>
              <StatusPill tone={unresolved.length === 0 ? "success" : "warning"}>
                {unresolved.length === 0 ? "complete" : `${unresolved.length} to resolve`}
              </StatusPill>
            </div>

            <div className="min-w-0 overflow-x-auto rounded-xl border border-border bg-card">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left">
                    <th scope="col" className="px-3 py-2 font-medium">
                      {readiness.version_label} division
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Band
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Players
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {targetLabel} division
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Match
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const primary = primaryTarget(row, chosen);
                    const sourceTierId = row.source.id;
                    return (
                      <tr key={row.source.slug} className="border-b border-border last:border-b-0">
                        <td className="px-3 py-2">{row.source.name}</td>
                        <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                          {bandShortLabel(row.source)}
                        </td>
                        <td
                          className="px-3 py-2 text-muted-foreground"
                          title="Player distribution per division is not exposed yet (backend gap G1)."
                        >
                          &mdash;
                        </td>
                        <td className="px-3 py-2">
                          {row.kind === "split" && editable && sourceTierId !== undefined ? (
                            <Select
                              value={primary?.id === undefined ? undefined : String(primary.id)}
                              onValueChange={(value) => onChoose(sourceTierId, Number(value))}
                            >
                              <SelectTrigger
                                className="h-8 w-full min-w-48"
                                aria-label={`Target division for ${row.source.name}`}
                              >
                                <SelectValue placeholder="Choose a division" />
                              </SelectTrigger>
                              <SelectContent>
                                {row.candidates.map((candidate) => (
                                  <SelectItem
                                    key={candidate.band.slug}
                                    value={String(candidate.band.id ?? "")}
                                  >
                                    {candidate.band.name} ({bandShortLabel(candidate.band)})
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          ) : (
                            (primary?.name ?? <span className="text-warning">unresolved</span>)
                          )}
                        </td>
                        <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                          {row.kind === "auto"
                            ? `AUTO · ${Math.round(row.coverage * 100)}%`
                            : "SPLIT · choose"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}
    </div>
  );
}
