"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Plus, Save, Trash2 } from "lucide-react";
import Image from "next/image";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { notify } from "@/lib/notify";
import { ApiError } from "@/lib/api-error";
import workspaceService from "@/services/workspace.service";
import type { DivisionGridVersion, DivisionTier } from "@/types/workspace.types";

// ─── Internal state types ────────────────────────────────────────────────────

type TierTarget = {
  target_tier_id: number;
  weight: number;
  is_primary: boolean;
};

type SourceRow = {
  source_tier_id: number;
  targets: TierTarget[];
};

// ─── Conversion helpers ──────────────────────────────────────────────────────

function buildAutoRows(sourceTiers: DivisionTier[], targetTiers: DivisionTier[]): SourceRow[] {
  const targetByNumber = new Map(targetTiers.map((t) => [t.number, t.id!]));
  return sourceTiers.map((tier) => {
    const matchedId = targetByNumber.get(tier.number);
    return {
      source_tier_id: tier.id!,
      targets:
        matchedId != null ? [{ target_tier_id: matchedId, weight: 1.0, is_primary: false }] : []
    };
  });
}

function rulesToRows(
  rules: Array<{
    source_tier_id: number;
    target_tier_id: number;
    weight: number;
    is_primary: boolean;
  }>,
  sourceTiers: DivisionTier[]
): SourceRow[] {
  const bySource = new Map<number, TierTarget[]>();
  for (const rule of rules) {
    const arr = bySource.get(rule.source_tier_id) ?? [];
    arr.push({
      target_tier_id: rule.target_tier_id,
      weight: rule.weight,
      is_primary: rule.is_primary
    });
    bySource.set(rule.source_tier_id, arr);
  }
  return sourceTiers.map((tier) => ({
    source_tier_id: tier.id!,
    targets: bySource.get(tier.id!) ?? []
  }));
}

function rowsToRules(rows: SourceRow[]) {
  return rows.flatMap((row) => {
    // A single-target row has an implicit weight of 1 — the weight input is
    // hidden in the UI, so normalize it here regardless of internal state.
    const single = row.targets.length === 1;
    return row.targets.map((t) => ({
      source_tier_id: row.source_tier_id,
      target_tier_id: t.target_tier_id,
      weight: single ? 1.0 : t.weight,
      is_primary: t.is_primary
    }));
  });
}

function weightsOk(targets: TierTarget[]): boolean {
  if (targets.length === 0) return true;
  // A single target carries an implicit weight of 1 (no weight input shown).
  if (targets.length === 1) return true;
  const sum = targets.reduce((acc, t) => acc + t.weight, 0);
  return Math.abs(sum - 1.0) < 0.0001;
}

// ─── Component ───────────────────────────────────────────────────────────────

type Props = {
  versions: DivisionGridVersion[];
  canEdit: boolean;
};

export function DivisionGridMappingEditor({ versions, canEdit }: Props) {
  const queryClient = useQueryClient();

  const [sourceVersionId, setSourceVersionId] = useState<number | null>(null);
  const [targetVersionId, setTargetVersionId] = useState<number | null>(null);
  const [mappingName, setMappingName] = useState("");
  const [rows, setRows] = useState<SourceRow[]>([]);

  const sourceVersion = versions.find((v) => v.id === sourceVersionId) ?? null;
  const targetVersion = versions.find((v) => v.id === targetVersionId) ?? null;

  const sourceTiers = (sourceVersion?.tiers ?? []).slice().sort((a, b) => a.number - b.number);
  const targetTiers = (targetVersion?.tiers ?? []).slice().sort((a, b) => a.number - b.number);
  const targetTierMap = new Map(targetTiers.map((t) => [t.id!, t]));

  const canLoad =
    sourceVersionId !== null && targetVersionId !== null && sourceVersionId !== targetVersionId;

  const mappingQuery = useQuery({
    queryKey: ["division-grid-mapping", sourceVersionId, targetVersionId],
    queryFn: async () => {
      try {
        return await workspaceService.getDivisionGridMapping(sourceVersionId!, targetVersionId!);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }
    },
    enabled: canLoad,
    staleTime: 30_000
  });

  // Populate editor state when mapping loads or version pair changes
  useEffect(() => {
    if (!canLoad || mappingQuery.isPending) return;
    const mapping = mappingQuery.data ?? null;
    if (mapping === null) {
      setMappingName(`${sourceVersion?.label ?? "Source"} → ${targetVersion?.label ?? "Target"}`);
      setRows(buildAutoRows(sourceTiers, targetTiers));
    } else {
      setMappingName(mapping.name);
      setRows(rulesToRows(mapping.rules, sourceTiers));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mappingQuery.data, mappingQuery.isPending, sourceVersionId, targetVersionId]);

  const saveMutation = useMutation({
    mutationFn: () =>
      workspaceService.putDivisionGridMapping(sourceVersionId!, targetVersionId!, {
        name: mappingName,
        rules: rowsToRules(rows)
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["division-grid-mapping", sourceVersionId, targetVersionId]
      });
      notify.success("Mapping saved");
    }
  });

  // ─── Row update helpers ───────────────────────────────────────────────────

  const updateTarget = (rowIdx: number, targetIdx: number, patch: Partial<TierTarget>) =>
    setRows((prev) =>
      prev.map((row, ri) =>
        ri !== rowIdx
          ? row
          : {
              ...row,
              targets: row.targets.map((t, ti) => (ti !== targetIdx ? t : { ...t, ...patch }))
            }
      )
    );

  const setPrimary = (rowIdx: number, targetIdx: number) =>
    setRows((prev) =>
      prev.map((row, ri) =>
        ri !== rowIdx
          ? row
          : {
              ...row,
              targets: row.targets.map((t, ti) => ({ ...t, is_primary: ti === targetIdx }))
            }
      )
    );

  const addTarget = (rowIdx: number) => {
    const firstId = targetTiers[0]?.id;
    if (firstId == null) return;
    setRows((prev) =>
      prev.map((row, ri) =>
        ri !== rowIdx
          ? row
          : {
              ...row,
              targets: [...row.targets, { target_tier_id: firstId, weight: 0, is_primary: false }]
            }
      )
    );
  };

  const removeTarget = (rowIdx: number, targetIdx: number) =>
    setRows((prev) =>
      prev.map((row, ri) =>
        ri !== rowIdx ? row : { ...row, targets: row.targets.filter((_, ti) => ti !== targetIdx) }
      )
    );

  // ─── Derived state ────────────────────────────────────────────────────────

  const allValid = rows.every((row) => weightsOk(row.targets));
  const hasUnsaved = rows.length > 0;

  if (versions.length < 2) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Version Mapping</CardTitle>
        <CardDescription>
          Define how tiers from one version map to tiers in another when recalculating standings.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Version selectors */}
        <div className="flex flex-wrap items-center gap-3">
          <Select
            value={sourceVersionId?.toString() ?? ""}
            onValueChange={(v) => setSourceVersionId(Number(v))}
          >
            <SelectTrigger className="w-60">
              <SelectValue placeholder="Source version" />
            </SelectTrigger>
            <SelectContent>
              {versions
                .slice()
                .sort((a, b) => b.version - a.version)
                .map((v) => (
                  <SelectItem
                    key={v.id}
                    value={v.id.toString()}
                    disabled={v.id === targetVersionId}
                  >
                    v{v.version} — {v.label}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>

          <span className="text-sm text-muted-foreground">→</span>

          <Select
            value={targetVersionId?.toString() ?? ""}
            onValueChange={(v) => setTargetVersionId(Number(v))}
          >
            <SelectTrigger className="w-60">
              <SelectValue placeholder="Target version" />
            </SelectTrigger>
            <SelectContent>
              {versions
                .slice()
                .sort((a, b) => b.version - a.version)
                .map((v) => (
                  <SelectItem
                    key={v.id}
                    value={v.id.toString()}
                    disabled={v.id === sourceVersionId}
                  >
                    v{v.version} — {v.label}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>

          {canLoad && !mappingQuery.isPending && (
            <Badge variant={mappingQuery.data?.is_complete ? "default" : "secondary"}>
              {mappingQuery.data == null
                ? "New"
                : mappingQuery.data.is_complete
                  ? "Complete"
                  : "Incomplete"}
            </Badge>
          )}
        </div>

        {/* Editor — shown when a version pair is selected and loaded */}
        {canLoad && !mappingQuery.isPending && rows.length > 0 && (
          <>
            <Input
              value={mappingName}
              onChange={(e) => setMappingName(e.target.value)}
              placeholder="Mapping name"
              className="max-w-sm"
            />

            <div className="rounded-md border">
              {/* Header */}
              <div className="grid grid-cols-[220px_1fr_28px] gap-3 border-b bg-muted/40 px-4 py-2 text-xs font-medium text-muted-foreground">
                <span>Source Tier</span>
                <span>Target Mappings</span>
                <span />
              </div>

              {rows.map((row, rowIdx) => {
                const sourceTier = sourceTiers.find((t) => t.id === row.source_tier_id);
                if (!sourceTier) return null;
                const valid = weightsOk(row.targets);
                const multi = row.targets.length > 1;

                return (
                  <div
                    key={row.source_tier_id}
                    className="grid grid-cols-[220px_1fr_28px] gap-3 border-b px-4 py-2.5 last:border-b-0"
                  >
                    {/* Source tier info */}
                    <div className="flex items-start gap-2 pt-1">
                      <Image
                        src={sourceTier.icon_url}
                        alt={sourceTier.name}
                        width={24}
                        height={24}
                        className="mt-0.5 shrink-0"
                      />
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium">{sourceTier.name}</div>
                        <div className="text-xs text-muted-foreground tabular-nums">
                          {sourceTier.rank_min}–{sourceTier.rank_max ?? "∞"}
                        </div>
                      </div>
                    </div>

                    {/* Target mappings */}
                    <div className="space-y-1.5">
                      {row.targets.length === 0 && (
                        <p className="pt-1 text-xs italic text-muted-foreground">Not mapped</p>
                      )}

                      {row.targets.map((target, targetIdx) => {
                        const targetTier = targetTierMap.get(target.target_tier_id);
                        return (
                          <div key={targetIdx} className="flex items-center gap-1.5">
                            {/* Target tier select */}
                            <Select
                              value={target.target_tier_id.toString()}
                              onValueChange={(v) =>
                                updateTarget(rowIdx, targetIdx, { target_tier_id: Number(v) })
                              }
                              disabled={!canEdit}
                            >
                              <SelectTrigger className="h-8 w-44">
                                <SelectValue>
                                  {targetTier ? (
                                    <span className="flex items-center gap-1.5">
                                      <Image
                                        src={targetTier.icon_url}
                                        alt=""
                                        width={16}
                                        height={16}
                                      />
                                      <span className="truncate">{targetTier.name}</span>
                                    </span>
                                  ) : (
                                    "Select tier"
                                  )}
                                </SelectValue>
                              </SelectTrigger>
                              <SelectContent>
                                {targetTiers.map((t) => (
                                  <SelectItem key={t.id} value={t.id!.toString()}>
                                    <span className="flex items-center gap-1.5">
                                      <Image src={t.icon_url} alt="" width={16} height={16} />
                                      {t.name}
                                    </span>
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>

                            {/* Weight — only for multi-target rows */}
                            {multi && (
                              <NumberInput
                                min={0}
                                max={1}
                                className="h-8 w-20 tabular-nums"
                                value={target.weight}
                                onValueChange={(next) =>
                                  updateTarget(rowIdx, targetIdx, { weight: next ?? 0 })
                                }
                                disabled={!canEdit}
                              />
                            )}

                            {/* Primary toggle — only for multi-target rows */}
                            {multi && (
                              <button
                                type="button"
                                title={target.is_primary ? "Primary" : "Set as primary"}
                                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md border text-sm transition-colors ${
                                  target.is_primary
                                    ? "border-yellow-400 bg-yellow-50 text-yellow-500 dark:bg-yellow-950"
                                    : "text-muted-foreground hover:bg-muted"
                                }`}
                                onClick={() => setPrimary(rowIdx, targetIdx)}
                                disabled={!canEdit}
                              >
                                ★
                              </button>
                            )}

                            {/* Remove target */}
                            {canEdit && (
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
                                onClick={() => removeTarget(rowIdx, targetIdx)}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            )}
                          </div>
                        );
                      })}

                      {canEdit && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-xs text-muted-foreground"
                          onClick={() => addTarget(rowIdx)}
                        >
                          <Plus className="mr-1 h-3 w-3" />
                          Add target
                        </Button>
                      )}
                    </div>

                    {/* Validity indicator */}
                    <div className="flex items-start pt-2">
                      {row.targets.length > 0 &&
                        (valid ? (
                          <CheckCircle2 className="h-4 w-4 text-green-500" />
                        ) : (
                          <span
                            title={`Weights sum to ${row.targets.reduce((s, t) => s + t.weight, 0).toFixed(2)}, must be 1.00`}
                          >
                            <AlertCircle className="h-4 w-4 text-destructive" />
                          </span>
                        ))}
                    </div>
                  </div>
                );
              })}
            </div>

            {canEdit && (
              <Button
                onClick={() => saveMutation.mutate()}
                disabled={saveMutation.isPending || !allValid || !mappingName.trim() || !hasUnsaved}
              >
                <Save className="mr-2 h-4 w-4" />
                Save Mapping
              </Button>
            )}
          </>
        )}

        {canLoad && mappingQuery.isPending && (
          <p className="text-sm text-muted-foreground">Loading mapping…</p>
        )}
      </CardContent>
    </Card>
  );
}
