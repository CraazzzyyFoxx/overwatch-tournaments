"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Image from "next/image";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import {
  getTierForRank,
  resolveDivisionFromRank,
  resolveExactRankFromDivision,
  sortTiersDescending
} from "@/lib/division-grid";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type {
  RankCollectionConfig,
  RankMappingConfig,
  RankMappingEntry,
  SettingRead
} from "@/types/admin.types";

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
  backoff_base_seconds: 60
};

// Default OverFast SR-aligned lower bound per division (tier 5 = base, +100 per tier up).
const DIVISION_BASE: Record<string, number> = {
  bronze: 1000,
  silver: 1500,
  gold: 2000,
  platinum: 2500,
  diamond: 3000,
  master: 3500,
  grandmaster: 4000,
  // OverFast labels the top division "ultimate" (in-game "Champion").
  ultimate: 4500
};

function findSetting(settings: SettingRead[] | undefined, key: string): SettingRead | undefined {
  return settings?.find((s) => s.key === key);
}

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({
    queryKey: ["admin", "settings"],
    queryFn: () => adminService.getSettings()
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Settings</h1>
        <p className="text-muted-foreground mt-2">Global system settings (superuser only)</p>
      </div>

      {settingsQuery.isLoading ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : settingsQuery.isError ? (
        <p className="text-destructive">Failed to load settings.</p>
      ) : (
        <>
          <RankCollectionSection
            setting={findSetting(settingsQuery.data, RANK_COLLECTION_KEY)}
            onSaved={() => queryClient.invalidateQueries({ queryKey: ["admin", "settings"] })}
          />
          <RankMappingSection
            setting={findSetting(settingsQuery.data, RANK_MAPPING_KEY)}
            onSaved={() => queryClient.invalidateQueries({ queryKey: ["admin", "settings"] })}
          />
        </>
      )}
    </div>
  );
}

function RankCollectionSection({
  setting,
  onSaved
}: {
  setting: SettingRead | undefined;
  onSaved: () => void;
}) {
  const initial = useMemo<RankCollectionConfig>(
    () => ({ ...DEFAULT_COLLECTION, ...((setting?.value as Partial<RankCollectionConfig>) ?? {}) }),
    [setting]
  );
  const [form, setForm] = useState<RankCollectionConfig>(initial);
  useEffect(() => setForm(initial), [initial]);

  const mutation = useMutation({
    mutationFn: () =>
      adminService.updateSetting(RANK_COLLECTION_KEY, {
        value: form as unknown as Record<string, unknown>
      }),
    onSuccess: onSaved
  });

  const num =
    (key: keyof RankCollectionConfig) => (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm({ ...form, [key]: Number(e.target.value) });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Rank collection (OverFast)</CardTitle>
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

        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          <div className="space-y-1">
            <Label>Interval (seconds)</Label>
            <Input
              type="number"
              min={60}
              value={form.interval_seconds}
              onChange={num("interval_seconds")}
            />
          </div>
          <div className="space-y-1">
            <Label>Batch size</Label>
            <Input type="number" min={1} value={form.batch_size} onChange={num("batch_size")} />
          </div>
          <div className="space-y-1">
            <Label>Rate limit (per minute)</Label>
            <Input
              type="number"
              min={1}
              value={form.rate_limit_per_minute}
              onChange={num("rate_limit_per_minute")}
            />
          </div>
          <div className="space-y-1">
            <Label>Scope</Label>
            <Select
              value={form.scope}
              onValueChange={(value) =>
                setForm({ ...form, scope: value as RankCollectionConfig["scope"] })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="registrations_only">Registrations only</SelectItem>
                <SelectItem value="all">All users</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label>Extra accounts / registration</Label>
            <Input
              type="number"
              min={0}
              value={form.extra_accounts_per_registration}
              onChange={num("extra_accounts_per_registration")}
            />
          </div>
          <div className="space-y-1">
            <Label>Max consecutive failures</Label>
            <Input
              type="number"
              min={1}
              value={form.max_consecutive_failures}
              onChange={num("max_consecutive_failures")}
            />
          </div>
          <div className="space-y-1">
            <Label>Backoff base (seconds)</Label>
            <Input
              type="number"
              min={1}
              value={form.backoff_base_seconds}
              onChange={num("backoff_base_seconds")}
            />
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {mutation.isPending ? "Saving…" : "Save"}
          </Button>
          {mutation.isSuccess && <span className="text-sm text-green-500">Saved</span>}
          {mutation.isError && <span className="text-sm text-destructive">Save failed</span>}
        </div>
      </CardContent>
    </Card>
  );
}

// OverFast competitive ladder, top rank first ("ultimate" = in-game "Champion").
const OW2_DIVISIONS_DESC = [
  "ultimate",
  "grandmaster",
  "master",
  "diamond",
  "platinum",
  "gold",
  "silver",
  "bronze"
];

function defaultRankForCell(division: string, tier: number): number {
  return (DIVISION_BASE[division] ?? 0) + (5 - tier) * 100;
}

/** All 40 OverFast cells (high→low), merging stored overrides over defaults. */
function buildMappingCells(stored: RankMappingEntry[]): RankMappingEntry[] {
  const byKey = new Map(stored.map((e) => [`${e.division.toLowerCase()}-${e.tier}`, e]));
  const cells: RankMappingEntry[] = [];
  for (const division of OW2_DIVISIONS_DESC) {
    for (let tier = 1; tier <= 5; tier++) {
      const existing = byKey.get(`${division}-${tier}`);
      cells.push({
        division,
        tier,
        rank_value: existing?.rank_value ?? defaultRankForCell(division, tier)
      });
    }
  }
  return cells;
}

function RankMappingSection({
  setting,
  onSaved
}: {
  setting: SettingRead | undefined;
  onSaved: () => void;
}) {
  const grid = useDivisionGrid();
  const internalTiers = useMemo(() => sortTiersDescending(grid), [grid]);

  const initial = useMemo<RankMappingConfig>(() => {
    const value = (setting?.value as Partial<RankMappingConfig>) ?? {};
    return { version: value.version ?? "ow2-default-v1", entries: value.entries ?? [] };
  }, [setting]);
  const [cells, setCells] = useState<RankMappingEntry[]>(() => buildMappingCells(initial.entries));
  useEffect(() => setCells(buildMappingCells(initial.entries)), [initial]);

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
          ? { ...cell, rank_value: resolveExactRankFromDivision(grid, divisionNumber) ?? cell.rank_value }
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
        <CardTitle>Rank mapping (OverFast → internal division)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Map each OverFast competitive rank to an internal division from the workspace grid. The
          division&apos;s lower bound is stored as the rank value.
        </p>

        <div className="overflow-hidden rounded-md border">
          <div className="grid grid-cols-[minmax(140px,1fr)_24px_minmax(0,1.4fr)] gap-3 border-b bg-muted/40 px-4 py-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            <span>OverFast rank</span>
            <span />
            <span>Internal division</span>
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
                  isDivisionTop ? "border-t border-white/[0.06]" : ""
                )}
              >
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-medium capitalize">{cell.division}</span>
                  <span className="text-xs text-muted-foreground">· Tier {cell.tier}</span>
                </div>
                <span className="text-center text-muted-foreground">→</span>
                <Select
                  value={divisionNumber != null ? String(divisionNumber) : ""}
                  onValueChange={(value) => setCellDivision(index, Number(value))}
                >
                  <SelectTrigger className="h-9 w-full max-w-xs">
                    <SelectValue>
                      {tier ? (
                        <span className="flex items-center gap-2">
                          <Image src={tier.icon_url} alt="" width={20} height={20} />
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
                          <Image src={t.icon_url} alt="" width={18} height={18} />
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
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {mutation.isPending ? "Saving…" : "Save"}
          </Button>
          {mutation.isSuccess && <span className="text-sm text-green-500">Saved</span>}
          {mutation.isError && <span className="text-sm text-destructive">Save failed</span>}
        </div>
      </CardContent>
    </Card>
  );
}
