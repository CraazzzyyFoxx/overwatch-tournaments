"use client";

// Moved as-is from /admin/settings (D10): rank collection config + rank mapping,
// now the Settings slot of /admin/collectors/rank.

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { NumberInput } from "@/components/ui/number-input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  OW_REFERENCE_GRID,
  getTierForRank,
  resolveDivisionFromRank,
  resolveRankFromDivision,
  sortTiersDescending
} from "@/lib/division-grid";
import {
  DEFAULT_RANK_MAPPING_VERSION,
  buildMappingCells,
  defaultRankForCell
} from "@/lib/ow-rank-mapping";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type {
  RankCollectionConfig,
  RankMappingConfig,
  RankMappingEntry,
  SettingRead
} from "@/types/admin.types";
import { EYEBROW_CLASS } from "@/components/admin/tone";

const RANK_COLLECTION_KEY = "parser.rank_collection";
const RANK_MAPPING_KEY = "parser.rank_mapping";

const DEFAULT_COLLECTION: RankCollectionConfig = {
  enabled: false,
  interval_seconds: 900,
  batch_size: 50,
  rate_limit_per_minute: 30,
  scope: "registrations_only",
  extra_accounts_per_registration: 0,
  max_consecutive_failures: 5,
  backoff_base_seconds: 60,
  auto_pace: true,
  jitter_fraction: 0.15,
  max_per_tick: null
};

export function RankSettingsPanel() {
  const queryClient = useQueryClient();

  const settingsQuery = useQuery({
    queryKey: ["admin", "settings"],
    queryFn: () => adminService.getSettings()
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["admin", "settings"] });

  if (settingsQuery.isLoading) {
    return <p className="text-muted-foreground">Loading…</p>;
  }

  if (settingsQuery.isError) {
    return (
      <p className="text-danger">
        Couldn&apos;t load settings. Check your connection and reload the page.
      </p>
    );
  }

  return (
    <>
      <RankCollectionSection
        setting={settingsQuery.data?.find((s) => s.key === RANK_COLLECTION_KEY)}
        onSaved={invalidate}
      />
      {/* Subscription collection config lives with its own collector, at
          /admin/collectors/subscriptions?tab=settings. */}
      <RankMappingSection
        setting={settingsQuery.data?.find((s) => s.key === RANK_MAPPING_KEY)}
        onSaved={invalidate}
      />
    </>
  );
}

/** Shared save button + success/error status shown by both settings cards below. */
function SaveButtonStatus({
  mutation
}: Readonly<{
  mutation: { mutate: () => void; isPending: boolean; isSuccess: boolean; isError: boolean };
}>) {
  return (
    <>
      <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
        {mutation.isPending ? "Saving…" : "Save"}
      </Button>
      {mutation.isSuccess && <span className="text-sm text-success">Saved</span>}
      {mutation.isError && (
        <span className="text-sm text-danger">Save failed — check the values and try again.</span>
      )}
    </>
  );
}

function RankCollectionSection({
  setting,
  onSaved
}: Readonly<{
  setting: SettingRead | undefined;
  onSaved: () => void;
}>) {
  const initial = useMemo<RankCollectionConfig>(
    () => ({ ...DEFAULT_COLLECTION, ...((setting?.value as Partial<RankCollectionConfig>) ?? {}) }),
    [setting]
  );
  const [form, setForm] = useState<RankCollectionConfig>(initial);
  const [prevInitial, setPrevInitial] = useState<RankCollectionConfig>(initial);

  if (initial !== prevInitial) {
    setPrevInitial(initial);
    setForm(initial);
  }

  const mutation = useMutation({
    mutationFn: () =>
      adminService.updateSetting(RANK_COLLECTION_KEY, {
        value: form as unknown as Record<string, unknown>
      }),
    onSuccess: onSaved
  });

  const num = (key: keyof RankCollectionConfig) => (next: number | null) =>
    setForm({ ...form, [key]: next ?? 0 });

  return (
    <Card>
      <CardHeader>
        <CardTitle asChild>
          <h2>Rank collection</h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2">
          <Switch
            id="rank-collection-enabled"
            checked={form.enabled}
            onCheckedChange={(checked) => setForm({ ...form, enabled: checked })}
          />
          <Label htmlFor="rank-collection-enabled" className="cursor-pointer">
            Enabled
          </Label>
        </div>

        <div className="flex items-center gap-2">
          <Switch
            id="rank-collection-auto-pace"
            checked={form.auto_pace}
            onCheckedChange={(checked) => setForm({ ...form, auto_pace: checked })}
          />
          <Label htmlFor="rank-collection-auto-pace" className="cursor-pointer">
            Auto-pace (spread the population evenly across the interval)
          </Label>
        </div>

        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          <div className="space-y-1">
            <Label htmlFor="rank-interval">Interval (seconds)</Label>
            <NumberInput
              id="rank-interval"
              integer
              min={60}
              value={form.interval_seconds}
              onValueChange={num("interval_seconds")}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="rank-batch-size">Batch size</Label>
            <NumberInput
              id="rank-batch-size"
              integer
              min={1}
              value={form.batch_size}
              onValueChange={num("batch_size")}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="rank-rate-limit">Rate limit (per minute)</Label>
            <NumberInput
              id="rank-rate-limit"
              integer
              min={1}
              value={form.rate_limit_per_minute}
              onValueChange={num("rate_limit_per_minute")}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="rank-scope">Scope</Label>
            <Select
              value={form.scope}
              onValueChange={(value) =>
                setForm({ ...form, scope: value as RankCollectionConfig["scope"] })
              }
            >
              <SelectTrigger id="rank-scope">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="registrations_only">Registrations only</SelectItem>
                <SelectItem value="all">All users</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="rank-extra-accounts">Extra accounts / registration</Label>
            <NumberInput
              id="rank-extra-accounts"
              integer
              min={0}
              value={form.extra_accounts_per_registration}
              onValueChange={num("extra_accounts_per_registration")}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="rank-max-failures">Max consecutive failures</Label>
            <NumberInput
              id="rank-max-failures"
              integer
              min={1}
              value={form.max_consecutive_failures}
              onValueChange={num("max_consecutive_failures")}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="rank-backoff">Backoff base (seconds)</Label>
            <NumberInput
              id="rank-backoff"
              integer
              min={1}
              value={form.backoff_base_seconds}
              onValueChange={num("backoff_base_seconds")}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="rank-jitter">Jitter fraction (0–1)</Label>
            <NumberInput
              id="rank-jitter"
              min={0}
              max={1}
              value={form.jitter_fraction}
              onValueChange={num("jitter_fraction")}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="rank-max-per-tick">Max per tick (blank = auto)</Label>
            <NumberInput
              id="rank-max-per-tick"
              integer
              min={1}
              placeholder="auto"
              value={form.max_per_tick}
              onValueChange={(next) => setForm({ ...form, max_per_tick: next })}
            />
          </div>
        </div>

        <div className="flex items-center gap-3">
          <SaveButtonStatus mutation={mutation} />
        </div>
      </CardContent>
    </Card>
  );
}

function RankMappingSection({
  setting,
  onSaved
}: Readonly<{
  setting: SettingRead | undefined;
  onSaved: () => void;
}>) {
  // The OW ladder, NOT the current workspace's grid: `parser.rank_mapping` is a
  // global setting, and the backend re-resolves each stored rank_value through a
  // tournament's own grid at autofill time (rank_sources._map_ow_rank_value), so
  // the value written here has to stay on the OW/SR scale.
  const grid = OW_REFERENCE_GRID;
  const internalTiers = useMemo(() => sortTiersDescending(grid), [grid]);

  const initial = useMemo<RankMappingConfig>(() => {
    const value = (setting?.value as Partial<RankMappingConfig>) ?? {};
    return { version: value.version ?? DEFAULT_RANK_MAPPING_VERSION, entries: value.entries ?? [] };
  }, [setting]);
  const [cells, setCells] = useState<RankMappingEntry[]>(() => buildMappingCells(initial.entries));
  const [prevInitial, setPrevInitial] = useState<RankMappingConfig>(initial);

  if (initial !== prevInitial) {
    setPrevInitial(initial);
    setCells(buildMappingCells(initial.entries));
  }

  const mutation = useMutation({
    mutationFn: () =>
      adminService.updateSetting(RANK_MAPPING_KEY, {
        value: { version: initial.version, entries: cells }
      }),
    onSuccess: onSaved
  });

  const setCellDivision = (index: number, divisionNumber: number) =>
    setCells((current) =>
      current.map((cell, i) =>
        i === index
          ? {
              ...cell,
              rank_value: resolveRankFromDivision(grid, divisionNumber) ?? cell.rank_value
            }
          : cell
      )
    );

  const resetToDefaults = () =>
    setCells((current) =>
      current.map((cell) => ({ ...cell, rank_value: defaultRankForCell(cell.division, cell.tier) }))
    );

  return (
    <Card>
      <CardHeader>
        <CardTitle asChild>
          <h2>Rank mapping</h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Map each competitive rank to a rank value on the Overwatch ladder. The division&apos;s
          lower bound is stored; each workspace resolves it against its own grid.
        </p>

        <div className="overflow-hidden rounded-md border">
          <div
            className={cn(
              EYEBROW_CLASS,
              "grid grid-cols-[minmax(140px,1fr)_24px_minmax(0,1.4fr)] gap-3 border-b bg-muted/40 px-4 py-2"
            )}
          >
            <span>OverFast rank</span>
            <span />
            <span>Ladder division</span>
          </div>
          {cells.map((cell, index) => {
            const tier = getTierForRank(grid, cell.rank_value);
            const divisionNumber = resolveDivisionFromRank(grid, cell.rank_value);
            const isDivisionTop = cell.tier === 1;
            return (
              <div
                key={`${cell.division}-${cell.tier}`}
                className={cn(
                  "grid grid-cols-[minmax(140px,1fr)_24px_minmax(0,1.4fr)] items-center gap-3 px-4 py-1.5",
                  isDivisionTop ? "border-t border-border/60" : ""
                )}
              >
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-medium capitalize">{cell.division}</span>
                  <span className="text-xs text-muted-foreground">· Tier {cell.tier}</span>
                </div>
                <ArrowRight className="mx-auto size-4 text-muted-foreground" aria-hidden />
                <Select
                  value={divisionNumber != null ? String(divisionNumber) : ""}
                  onValueChange={(value) => setCellDivision(index, Number(value))}
                >
                  <SelectTrigger
                    className="h-9 w-full max-w-xs"
                    aria-label={`Ladder division for ${cell.division} tier ${cell.tier}`}
                  >
                    <SelectValue>
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
                      ) : (
                        "Select division"
                      )}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {internalTiers.map((t) => (
                      <SelectItem key={t.number} value={String(t.number)}>
                        <span className="flex items-center gap-2">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img src={t.icon_url} alt="" width={18} height={18} />
                          {t.name}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" size="sm" onClick={resetToDefaults}>
            Reset to OW2 defaults
          </Button>
          <SaveButtonStatus mutation={mutation} />
        </div>
      </CardContent>
    </Card>
  );
}
