"use client";

import { memo, useCallback, useMemo, useRef, useState } from "react";
import { DivisionGridMappingEditor } from "./MappingEditor";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CopyPlus,
  Download,
  Minus,
  Plus,
  Save,
  Star,
  Store,
  Trash2,
  Upload,
  Wand2
} from "lucide-react";
import Image from "next/image";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import { usePermissions } from "@/hooks/usePermissions";
import workspaceService from "@/services/workspace.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type {
  DivisionGridMarketplaceImportResult,
  DivisionGridVersion,
  DivisionTier
} from "@/types/workspace.types";

function buildDefaultTiers(): DivisionTier[] {
  const divisions = ["champion", "grandmaster", "master", "diamond", "platinum", "gold", "silver", "bronze"];
  const bases: Record<string, number> = {
    bronze: 1000,
    silver: 1500,
    gold: 2000,
    platinum: 2500,
    diamond: 3000,
    master: 3500,
    grandmaster: 4000,
    champion: 4500,
  };
  
  const tiers: DivisionTier[] = [];
  let sort_order = 0;
  let number = 1;
  
  for (const div of divisions) {
    const base = bases[div];
    for (let tier_num = 1; tier_num <= 5; tier_num++) {
      const slug = `${div}-${tier_num}`;
      const name = `${div.charAt(0).toUpperCase() + div.slice(1)} ${tier_num}`;
      const offset = (5 - tier_num) * 100;
      const rank_min = base + offset;
      const rank_max = (div === "champion" && tier_num === 1) ? null : rank_min + 99;
      const icon_url = `https://minio.craazzzyyfoxx.me/aqt/assets/divisions/${slug}.png`;
      
      tiers.push({
        slug,
        number,
        name,
        sort_order,
        rank_min,
        rank_max,
        icon_url,
      });
      sort_order++;
      number++;
    }
  }
  
  return tiers.sort((a, b) => a.number - b.number);
}

function emptyTier(number: number, index: number): DivisionTier {
  return {
    slug: `division-${number}`,
    number,
    name: `Division ${number}`,
    sort_order: index,
    rank_min: 1000,
    rank_max: 1099,
    icon_url: `https://minio.craazzzyyfoxx.me/aqt/assets/divisions/bronze-5.png`,
    ow_rank_min: null,
    ow_rank_max: null
  };
}

function buildEditorState(
  selectedVersion: DivisionGridVersion | null,
  isDraftMode: boolean
): {
  label: string;
  tiers: DivisionTier[];
} {
  if (!selectedVersion) {
    return {
      label: "Draft",
      tiers: buildDefaultTiers()
    };
  }

  return {
    label: isDraftMode ? selectedVersion.label : `${selectedVersion.label} Copy`,
    tiers: [...selectedVersion.tiers]
      .sort((a, b) => a.number - b.number)
      .map((tier, index) => ({ ...tier, sort_order: tier.sort_order ?? index }))
  };
}

type DivisionGridEditorCardProps = {
  workspaceId: number;
  gridId: number;
  canEdit: boolean;
  selectedVersion: DivisionGridVersion | null;
  onSaved: () => Promise<void>;
};

// Navigable column indices: 0=#, 1=name, 2=rank_min, 3=rank_max, 4=ow_rank_min, 5=ow_rank_max
const NAV_COLS = 6;
const DEFAULT_RANK_STEP = 100;

function toSafeInteger(value: number, fallback = 0) {
  return Number.isFinite(value) ? Math.trunc(value) : fallback;
}

function parseIntegerInput(value: string, fallback = 0) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function clampRank(value: number) {
  return Math.max(0, toSafeInteger(value));
}

function shiftTierRankRange(tier: DivisionTier, delta: number): DivisionTier {
  return {
    ...tier,
    rank_min: clampRank(tier.rank_min + delta),
    rank_max: tier.rank_max === null ? null : clampRank(tier.rank_max + delta)
  };
}

function getSelectedIndexes(selectedRows: Set<number>, length: number) {
  return Array.from(selectedRows)
    .filter((index) => index >= 0 && index < length)
    .sort((a, b) => a - b);
}

type TierEditorRowProps = {
  tier: DivisionTier;
  rowIndex: number;
  canEdit: boolean;
  isSelected: boolean;
  onDelete: (index: number) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLInputElement>, row: number, col: number) => void;
  onSelect: (index: number, checked: boolean) => void;
  onSetInputRef: (row: number, col: number, element: HTMLInputElement | null) => void;
  onUpdate: (index: number, field: keyof DivisionTier, value: string | number | null) => void;
  onUpload: (index: number, tier: DivisionTier, file: File) => void;
};

const TierEditorRow = memo(function TierEditorRow({
  tier,
  rowIndex,
  canEdit,
  isSelected,
  onDelete,
  onKeyDown,
  onSelect,
  onSetInputRef,
  onUpdate,
  onUpload
}: TierEditorRowProps) {
  const setInputRef = useCallback(
    (col: number) => (element: HTMLInputElement | null) => onSetInputRef(rowIndex, col, element),
    [onSetInputRef, rowIndex]
  );

  return (
    <div className="grid min-w-[1060px] grid-cols-[40px_56px_48px_minmax(160px,1fr)_220px_200px_40px_36px] gap-2 border-b px-4 py-1.5 last:border-b-0">
      <div className="flex items-center justify-center">
        <Checkbox
          checked={isSelected}
          onCheckedChange={(checked) => onSelect(rowIndex, checked === true)}
          aria-label={`Select ${tier.name}`}
          disabled={!canEdit}
        />
      </div>
      <Input
        ref={setInputRef(0)}
        inputMode="numeric"
        className="h-8 text-center tabular-nums"
        value={tier.number}
        onChange={(event) => onUpdate(rowIndex, "number", parseIntegerInput(event.target.value))}
        onKeyDown={(event) => onKeyDown(event, rowIndex, 0)}
        disabled={!canEdit}
      />
      <div className="flex items-center justify-center">
        <Image
          src={tier.icon_url}
          alt={tier.name}
          width={28}
          height={28}
          className="h-7 w-7 object-contain"
        />
      </div>
      <Input
        ref={setInputRef(1)}
        className="h-8"
        value={tier.name}
        onChange={(event) => onUpdate(rowIndex, "name", event.target.value)}
        onKeyDown={(event) => onKeyDown(event, rowIndex, 1)}
        disabled={!canEdit}
      />
      <div className="flex items-center gap-1.5">
        <Input
          ref={setInputRef(2)}
          inputMode="numeric"
          className="h-8 w-24 tabular-nums"
          value={tier.rank_min}
          onChange={(event) =>
            onUpdate(rowIndex, "rank_min", parseIntegerInput(event.target.value))
          }
          onKeyDown={(event) => onKeyDown(event, rowIndex, 2)}
          disabled={!canEdit}
        />
        <span className="shrink-0 text-xs text-muted-foreground">-</span>
        <Input
          ref={setInputRef(3)}
          inputMode="numeric"
          className="h-8 w-24 tabular-nums"
          placeholder="max"
          value={tier.rank_max ?? ""}
          onChange={(event) =>
            onUpdate(
              rowIndex,
              "rank_max",
              event.target.value === "" ? null : parseIntegerInput(event.target.value)
            )
          }
          onKeyDown={(event) => onKeyDown(event, rowIndex, 3)}
          disabled={!canEdit}
        />
      </div>
      <div className="flex items-center gap-1.5">
        <Input
          ref={setInputRef(4)}
          inputMode="numeric"
          className="h-8 w-20 tabular-nums"
          placeholder="min"
          value={tier.ow_rank_min ?? ""}
          onChange={(event) =>
            onUpdate(
              rowIndex,
              "ow_rank_min",
              event.target.value === "" ? null : parseIntegerInput(event.target.value)
            )
          }
          onKeyDown={(event) => onKeyDown(event, rowIndex, 4)}
          disabled={!canEdit}
        />
        <span className="shrink-0 text-xs text-muted-foreground">-</span>
        <Input
          ref={setInputRef(5)}
          inputMode="numeric"
          className="h-8 w-20 tabular-nums"
          placeholder="max"
          value={tier.ow_rank_max ?? ""}
          onChange={(event) =>
            onUpdate(
              rowIndex,
              "ow_rank_max",
              event.target.value === "" ? null : parseIntegerInput(event.target.value)
            )
          }
          onKeyDown={(event) => onKeyDown(event, rowIndex, 5)}
          disabled={!canEdit}
        />
      </div>
      <label className="inline-flex cursor-pointer items-center justify-center">
        <input
          type="file"
          className="hidden"
          accept="image/png,image/webp,image/jpeg,image/gif"
          disabled={!canEdit}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onUpload(rowIndex, tier, file);
            event.currentTarget.value = "";
          }}
        />
        <span className="inline-flex h-8 w-8 items-center justify-center rounded-md border hover:bg-muted">
          <Upload className="h-3.5 w-3.5" />
        </span>
      </label>
      <Button
        variant="ghost"
        size="icon"
        className="h-8 w-8 text-muted-foreground hover:text-destructive"
        onClick={() => onDelete(rowIndex)}
        disabled={!canEdit}
        aria-label={`Delete ${tier.name}`}
      >
        <Trash2 className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
});

function DivisionGridEditorCard({
  workspaceId,
  gridId,
  canEdit,
  selectedVersion,
  onSaved
}: DivisionGridEditorCardProps) {
  const { toast } = useToast();
  const isDraftMode = selectedVersion?.status === "draft";
  const initialState = useMemo(
    () => buildEditorState(selectedVersion, !!isDraftMode),
    [selectedVersion, isDraftMode]
  );
  const [label, setLabel] = useState(initialState.label);
  const [tiers, setTiers] = useState<DivisionTier[]>(initialState.tiers);
  const [selectedRows, setSelectedRows] = useState<Set<number>>(() => new Set());
  const [rankDelta, setRankDelta] = useState(DEFAULT_RANK_STEP);
  const [rangeStart, setRangeStart] = useState(0);
  const [rangeStep, setRangeStep] = useState(DEFAULT_RANK_STEP);
  const [tiersToAdd, setTiersToAdd] = useState(1);

  // Keyboard navigation refs: key = `${row}-${col}`
  const inputRefs = useRef<Map<string, HTMLInputElement>>(new Map());
  const setInputRef = useCallback(
    (row: number, col: number, el: HTMLInputElement | null) => {
      const key = `${row}-${col}`;
      if (el) inputRefs.current.set(key, el);
      else inputRefs.current.delete(key);
    },
    []
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>, row: number, col: number) => {
      const input = e.currentTarget;
      const focus = (r: number, c: number) => {
        const target = inputRefs.current.get(`${r}-${c}`);
        if (target) {
          e.preventDefault();
          target.focus();
          target.select();
        }
      };
      switch (e.key) {
        case "ArrowDown":
        case "Enter":
          focus(row + 1, col);
          break;
        case "ArrowUp":
          focus(row - 1, col);
          break;
        case "ArrowLeft":
          if (input.selectionStart === 0 && col > 0) focus(row, col - 1);
          break;
        case "ArrowRight":
          if (input.selectionStart === input.value.length && col < NAV_COLS - 1)
            focus(row, col + 1);
          break;
      }
    },
    []
  );

  const tiersPayload = useMemo(
    () =>
      tiers.map((tier, index) => ({
        slug: tier.slug || `division-${tier.number}`,
        number: tier.number,
        name: tier.name,
        sort_order: index,
        rank_min: tier.rank_min,
        rank_max: tier.rank_max,
        icon_url: tier.icon_url,
        ow_rank_min: tier.ow_rank_min ?? null,
        ow_rank_max: tier.ow_rank_max ?? null
      })),
    [tiers]
  );

  const saveVersionMutation = useMutation({
    mutationFn: async () => {
      if (isDraftMode && selectedVersion) {
        return workspaceService.updateDivisionGridVersion(selectedVersion.id, {
          label,
          tiers: tiersPayload
        });
      }
      return workspaceService.createDivisionGridVersion(workspaceId, gridId, {
        label,
        tiers: tiersPayload
      });
    },
    onSuccess: async () => {
      await onSaved();
      toast({ title: isDraftMode ? "Draft saved" : "Draft version created" });
    },
    onError: (error: Error) =>
      toast({ title: "Error", description: error.message, variant: "destructive" })
  });

  const updateTier = useCallback(
    (index: number, field: keyof DivisionTier, value: string | number | null) => {
      setTiers((current) =>
        current.map((tier, tierIndex) => (tierIndex === index ? { ...tier, [field]: value } : tier))
      );
    },
    []
  );

  const selectedRowIndexes = useMemo(
    () => getSelectedIndexes(selectedRows, tiers.length),
    [selectedRows, tiers.length]
  );

  const bulkTargetIndexes = useMemo(
    () =>
      selectedRowIndexes.length > 0
        ? selectedRowIndexes
        : Array.from({ length: tiers.length }, (_, index) => index),
    [selectedRowIndexes, tiers.length]
  );

  const bulkTargetLabel =
    selectedRowIndexes.length > 0
      ? `${selectedRowIndexes.length} selected`
      : `all ${tiers.length} tiers`;
  const allRowsSelected = tiers.length > 0 && selectedRowIndexes.length === tiers.length;
  const someRowsSelected = selectedRowIndexes.length > 0 && !allRowsSelected;

  const toggleRowSelection = useCallback((index: number, checked: boolean) => {
    setSelectedRows((current) => {
      const next = new Set(current);
      if (checked) next.add(index);
      else next.delete(index);
      return next;
    });
  }, []);

  const toggleAllRows = useCallback(
    (checked: boolean) => {
      setSelectedRows(
        checked ? new Set(Array.from({ length: tiers.length }, (_, index) => index)) : new Set()
      );
    },
    [tiers.length]
  );

  const shiftBulkRanks = useCallback(
    (direction: 1 | -1) => {
      const delta = Math.abs(toSafeInteger(rankDelta, DEFAULT_RANK_STEP)) * direction;
      const targetSet = new Set(bulkTargetIndexes);
      setTiers((current) =>
        current.map((tier, index) =>
          targetSet.has(index) ? shiftTierRankRange(tier, delta) : tier
        )
      );
    },
    [bulkTargetIndexes, rankDelta]
  );

  const autoFillBulkRanges = useCallback(() => {
    const start = clampRank(rangeStart);
    const step = Math.max(1, Math.abs(toSafeInteger(rangeStep, DEFAULT_RANK_STEP)));
    const targetSet = new Set(bulkTargetIndexes);

    setTiers((current) => {
      const orderedIndexes = bulkTargetIndexes
        .slice()
        .sort((a, b) => current[b].number - current[a].number || b - a);
      const orderByIndex = new Map(orderedIndexes.map((index, order) => [index, order]));

      return current.map((tier, index) => {
        if (!targetSet.has(index)) return tier;

        const order = orderByIndex.get(index) ?? 0;
        const min = start + order * step;
        const shouldStayOpenEnded = tier.rank_max === null;

        return {
          ...tier,
          rank_min: min,
          rank_max: shouldStayOpenEnded ? null : min + step - 1
        };
      });
    });
  }, [bulkTargetIndexes, rangeStart, rangeStep]);

  const addTiers = useCallback(() => {
    const count = Math.max(1, Math.min(100, Math.abs(toSafeInteger(tiersToAdd, 1))));
    const step = Math.max(1, Math.abs(toSafeInteger(rangeStep, DEFAULT_RANK_STEP)));

    setTiers((current) => {
      const maxNumber = current.reduce((max, tier) => Math.max(max, tier.number), 0);
      return [
        ...current,
        ...Array.from({ length: count }, (_, offset) => {
          const number = maxNumber + offset + 1;
          return {
            ...emptyTier(number, current.length + offset),
            rank_max: step - 1
          };
        })
      ];
    });
  }, [rangeStep, tiersToAdd]);

  const removeTier = useCallback((index: number) => {
    setTiers((current) => current.filter((_, tierIndex) => tierIndex !== index));
    setSelectedRows(new Set());
  }, []);

  const removeSelectedTiers = useCallback(() => {
    setTiers((current) => current.filter((_, index) => !selectedRows.has(index)));
    setSelectedRows(new Set());
  }, [selectedRows]);

  const uploadIcon = useCallback(async (index: number, tier: DivisionTier, file: File) => {
    const slugBase = tier.slug || `division-${tier.number}`;
    const randomHash = crypto.randomUUID().replace(/-/g, "").slice(0, 8);
    const upload = await workspaceService.uploadDivisionIcon(
      `${slugBase}-${randomHash}`,
      file,
      workspaceId
    );
    updateTier(index, "icon_url", upload.public_url);
    toast({ title: "Icon uploaded" });
  }, [toast, updateTier, workspaceId]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{isDraftMode ? "Edit Draft" : "Draft Editor"}</CardTitle>
        <CardDescription>
          {isDraftMode
            ? "Edit the current draft version. Changes are saved in-place."
            : "Create a new draft version from the selected tiers."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Input
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="Version label"
        />

        <div className="rounded-md border bg-muted/20 p-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground">Bulk target</div>
              <Badge variant="outline" className="h-9 px-3">
                {bulkTargetLabel}
              </Badge>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="rank-delta">
                Rank delta
              </label>
              <Input
                id="rank-delta"
                type="number"
                inputMode="numeric"
                className="h-9 w-28 tabular-nums"
                value={rankDelta}
                onChange={(event) =>
                  setRankDelta(Math.max(0, parseIntegerInput(event.target.value)))
                }
                disabled={!canEdit}
              />
            </div>
            <Button
              variant="outline"
              onClick={() => shiftBulkRanks(1)}
              disabled={!canEdit || bulkTargetIndexes.length === 0}
            >
              <Plus className="mr-2 h-4 w-4" />
              Add
            </Button>
            <Button
              variant="outline"
              onClick={() => shiftBulkRanks(-1)}
              disabled={!canEdit || bulkTargetIndexes.length === 0}
            >
              <Minus className="mr-2 h-4 w-4" />
              Reduce
            </Button>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="range-start">
                Range start
              </label>
              <Input
                id="range-start"
                type="number"
                inputMode="numeric"
                className="h-9 w-28 tabular-nums"
                value={rangeStart}
                onChange={(event) =>
                  setRangeStart(Math.max(0, parseIntegerInput(event.target.value)))
                }
                disabled={!canEdit}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="range-step">
                Step
              </label>
              <Input
                id="range-step"
                type="number"
                inputMode="numeric"
                min={1}
                className="h-9 w-24 tabular-nums"
                value={rangeStep}
                onChange={(event) =>
                  setRangeStep(Math.max(1, parseIntegerInput(event.target.value, 1)))
                }
                disabled={!canEdit}
              />
            </div>
            <Button
              variant="outline"
              onClick={autoFillBulkRanges}
              disabled={!canEdit || bulkTargetIndexes.length === 0}
            >
              <Wand2 className="mr-2 h-4 w-4" />
              Auto ranges
            </Button>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="tiers-to-add">
                Tiers
              </label>
              <Input
                id="tiers-to-add"
                type="number"
                inputMode="numeric"
                min={1}
                className="h-9 w-20 tabular-nums"
                value={tiersToAdd}
                onChange={(event) =>
                  setTiersToAdd(Math.max(1, parseIntegerInput(event.target.value, 1)))
                }
                disabled={!canEdit}
              />
            </div>
            <Button variant="outline" onClick={addTiers} disabled={!canEdit}>
              <Plus className="mr-2 h-4 w-4" />
              Add tiers
            </Button>
            <Button
              variant="outline"
              onClick={removeSelectedTiers}
              disabled={!canEdit || selectedRowIndexes.length === 0}
              className="text-destructive hover:text-destructive"
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete selected
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Without selected rows, bulk rank actions apply to every tier.
          </p>
        </div>

        <div className="overflow-x-auto rounded-md border">
          <div className="grid min-w-[1060px] grid-cols-[40px_56px_48px_minmax(160px,1fr)_220px_200px_40px_36px] gap-2 border-b bg-muted/40 px-4 py-2 text-xs font-medium text-muted-foreground">
            <div className="flex items-center justify-center">
              <Checkbox
                checked={someRowsSelected ? "indeterminate" : allRowsSelected}
                onCheckedChange={(checked) => toggleAllRows(checked === true)}
                aria-label="Select all tiers"
                disabled={!canEdit}
              />
            </div>
            <span>#</span>
            <span>Icon</span>
            <span>Name</span>
            <span>Rank Range</span>
            <span>OW Range</span>
            <span>Upload</span>
            <span />
          </div>
          {tiers.map((tier, rowIndex) => (
            <TierEditorRow
              key={`${tier.id ?? tier.slug ?? "tier"}-${rowIndex}`}
              tier={tier}
              rowIndex={rowIndex}
              canEdit={canEdit}
              isSelected={selectedRows.has(rowIndex)}
              onDelete={removeTier}
              onKeyDown={handleKeyDown}
              onSelect={toggleRowSelection}
              onSetInputRef={setInputRef}
              onUpdate={updateTier}
              onUpload={uploadIcon}
            />
          ))}
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() => saveVersionMutation.mutate()}
            disabled={!canEdit || saveVersionMutation.isPending}
          >
            <Save className="mr-2 h-4 w-4" />
            {isDraftMode ? "Save Draft" : "Create New Draft"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function DivisionsAdminPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const { isSuperuser, canAccessAnyPermission } = usePermissions();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const getCurrentWorkspace = useWorkspaceStore((s) => s.getCurrentWorkspace);
  const fetchWorkspaces = useWorkspaceStore((s) => s.fetchWorkspaces);
  const workspace = getCurrentWorkspace();

  const canEdit =
    isSuperuser ||
    (currentWorkspaceId !== null &&
      canAccessAnyPermission(
        ["division_grid.create", "division_grid.update", "division_grid.delete", "division_grid.import"],
        currentWorkspaceId,
      ));

  const gridsQuery = useQuery({
    queryKey: ["division-grids", currentWorkspaceId],
    queryFn: () => workspaceService.getDivisionGrids(currentWorkspaceId!),
    enabled: currentWorkspaceId !== null
  });

  const marketplaceWorkspacesQuery = useQuery({
    queryKey: ["division-grid-marketplace-workspaces", currentWorkspaceId],
    queryFn: () => workspaceService.getDivisionGridMarketplaceWorkspaces(currentWorkspaceId!),
    enabled: currentWorkspaceId !== null && canEdit
  });

  const marketplaceWorkspaces = useMemo(
    () => marketplaceWorkspacesQuery.data ?? [],
    [marketplaceWorkspacesQuery.data]
  );

  const [selectedVersionId, setSelectedVersionId] = useState<number | null>(null);
  const [marketplaceSourceWorkspaceId, setMarketplaceSourceWorkspaceId] = useState<number | null>(
    null
  );
  const [selectedMarketplaceGridIds, setSelectedMarketplaceGridIds] = useState<number[]>([]);
  const [makeImportedDefault, setMakeImportedDefault] = useState(false);
  const [marketplaceImportResult, setMarketplaceImportResult] =
    useState<DivisionGridMarketplaceImportResult | null>(null);

  const grids = gridsQuery.data ?? [];
  const activeGrid = grids[0] ?? null;
  const versions = activeGrid?.versions ?? [];
  const effectiveMarketplaceSourceWorkspaceId =
    marketplaceSourceWorkspaceId !== null &&
    marketplaceWorkspaces.some((sourceWorkspace) => sourceWorkspace.id === marketplaceSourceWorkspaceId)
      ? marketplaceSourceWorkspaceId
      : null;

  const marketplaceGridsQuery = useQuery({
    queryKey: ["division-grid-marketplace", currentWorkspaceId, effectiveMarketplaceSourceWorkspaceId],
    queryFn: () =>
      workspaceService.getDivisionGridMarketplace(
        currentWorkspaceId!,
        effectiveMarketplaceSourceWorkspaceId!
      ),
    enabled: currentWorkspaceId !== null && canEdit && effectiveMarketplaceSourceWorkspaceId !== null
  });

  const marketplaceGrids = marketplaceGridsQuery.data ?? [];
  const selectedMarketplaceGridIdsSet = useMemo(
    () => new Set(selectedMarketplaceGridIds),
    [selectedMarketplaceGridIds]
  );

  const toggleMarketplaceGrid = useCallback((gridId: number, checked: boolean) => {
    setSelectedMarketplaceGridIds((current) =>
      checked ? Array.from(new Set([...current, gridId])) : current.filter((id) => id !== gridId)
    );
  }, []);

  const defaultVersionId = useMemo(() => {
    if (!workspace || versions.length === 0) return null;
    return (
      (
        versions.find((v) => v.id === workspace.default_division_grid_version_id) ??
        versions.find((v) => v.status === "published") ??
        versions[versions.length - 1] ??
        null
      )?.id ?? null
    );
  }, [versions, workspace]);

  const effectiveVersionId = selectedVersionId ?? defaultVersionId;
  const selectedVersion = versions.find((v) => v.id === effectiveVersionId) ?? null;

  const createGridMutation = useMutation({
    mutationFn: async () => {
      if (!currentWorkspaceId) return null;
      return workspaceService.createDivisionGrid(currentWorkspaceId, {
        slug: "default",
        name: `${workspace?.name ?? "Workspace"} Division Grid`
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["division-grids", currentWorkspaceId] });
      toast({ title: "Division grid created" });
    },
    onError: (error: Error) =>
      toast({ title: "Error", description: error.message, variant: "destructive" })
  });

  const cloneMutation = useMutation({
    mutationFn: async () => {
      if (!selectedVersion) return null;
      return workspaceService.cloneDivisionGridVersion(selectedVersion.id);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["division-grids", currentWorkspaceId] });
      toast({ title: "Version cloned" });
    },
    onError: (error: Error) =>
      toast({ title: "Error", description: error.message, variant: "destructive" })
  });

  const publishMutation = useMutation({
    mutationFn: async () => {
      if (!selectedVersion) return null;
      return workspaceService.publishDivisionGridVersion(selectedVersion.id);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["division-grids", currentWorkspaceId] });
      toast({ title: "Version published" });
    },
    onError: (error: Error) =>
      toast({ title: "Error", description: error.message, variant: "destructive" })
  });

  const deleteVersionMutation = useMutation({
    mutationFn: (versionId: number) => workspaceService.deleteDivisionGridVersion(versionId),
    onSuccess: async (_, versionId) => {
      if (selectedVersionId === versionId) setSelectedVersionId(null);
      await queryClient.invalidateQueries({ queryKey: ["division-grids", currentWorkspaceId] });
      toast({ title: "Version deleted" });
    },
    onError: (error: Error) =>
      toast({ title: "Cannot delete", description: error.message, variant: "destructive" })
  });

  const setDefaultMutation = useMutation({
    mutationFn: async () => {
      if (!workspace || !selectedVersion) return null;
      return workspaceService.update(workspace.id, {
        default_division_grid_version_id: selectedVersion.id
      });
    },
    onSuccess: async () => {
      await fetchWorkspaces();
      toast({ title: "Workspace default updated" });
    },
    onError: (error: Error) =>
      toast({ title: "Error", description: error.message, variant: "destructive" })
  });

  const importMarketplaceMutation = useMutation({
    mutationFn: async () => {
      if (!currentWorkspaceId || !effectiveMarketplaceSourceWorkspaceId) {
        throw new Error("Select a source workspace");
      }
      if (selectedMarketplaceGridIds.length === 0) {
        throw new Error("Select at least one grid");
      }
      return workspaceService.importDivisionGridMarketplace(currentWorkspaceId, {
        source_workspace_id: effectiveMarketplaceSourceWorkspaceId,
        source_grid_ids: selectedMarketplaceGridIds,
        set_default: makeImportedDefault
      });
    },
    onSuccess: async (result) => {
      setMarketplaceImportResult(result);
      setSelectedMarketplaceGridIds([]);
      await queryClient.invalidateQueries({ queryKey: ["division-grids", currentWorkspaceId] });
      if (makeImportedDefault) {
        await fetchWorkspaces();
      }
      toast({
        title: "Division grid imported",
        description: `${result.created_grids} grid(s), ${result.created_versions} version(s), ${result.copied_images} image(s)`
      });
    },
    onError: (error: Error) =>
      toast({ title: "Import failed", description: error.message, variant: "destructive" })
  });

  if (!currentWorkspaceId) {
    return (
      <AdminPageHeader
        title="Divisions"
        description="Select a workspace to manage division grids."
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        title="Divisions"
        description="Manage workspace division grids, versions, and tier icons."
        actions={
          canEdit ? (
            <div className="flex gap-2">
              {!activeGrid && (
                <Button
                  onClick={() => createGridMutation.mutate()}
                  disabled={createGridMutation.isPending}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  Create Grid
                </Button>
              )}
              {selectedVersion && (
                <>
                  <Button
                    variant="outline"
                    onClick={() => cloneMutation.mutate()}
                    disabled={cloneMutation.isPending}
                  >
                    <CopyPlus className="mr-2 h-4 w-4" />
                    {selectedVersion?.status === "published" ? "Fork to New Draft" : "Clone Version"}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => publishMutation.mutate()}
                    disabled={publishMutation.isPending}
                  >
                    Publish
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => setDefaultMutation.mutate()}
                    disabled={setDefaultMutation.isPending}
                  >
                    <Star className="mr-2 h-4 w-4" />
                    Set Default
                  </Button>
                </>
              )}
            </div>
          ) : null
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>Grid Status</CardTitle>
          <CardDescription>
            {activeGrid ? (
              <>
                Grid <span className="font-medium">{activeGrid.name}</span> with {versions.length}{" "}
                version(s).
              </>
            ) : (
              "No division grid created for this workspace yet."
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-4">
          {versions.length > 0 ? (
            <>
              <Select
                value={effectiveVersionId?.toString() ?? ""}
                onValueChange={(value) => setSelectedVersionId(Number(value))}
              >
                <SelectTrigger className="w-90">
                  <SelectValue placeholder="Select version" />
                </SelectTrigger>
                <SelectContent>
                  {versions
                    .slice()
                    .sort((a, b) => b.version - a.version)
                    .map((version) => (
                      <SelectItem key={version.id} value={version.id.toString()}>
                        <span className="flex items-center gap-2">
                          v{version.version} — {version.label}
                          {version.status === "published" && (
                            <Badge variant="default" className="ml-1 text-[10px] px-1.5 py-0">
                              published
                            </Badge>
                          )}
                          {workspace?.default_division_grid_version_id === version.id && (
                            <Star className="h-3 w-3 text-yellow-500" />
                          )}
                        </span>
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              {selectedVersion && (
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">Version {selectedVersion.version}</Badge>
                  <Badge variant={selectedVersion.status === "published" ? "default" : "secondary"}>
                    {selectedVersion.status}
                  </Badge>
                  {workspace?.default_division_grid_version_id === selectedVersion.id && (
                    <Badge variant="secondary">Workspace Default</Badge>
                  )}
                </div>
              )}
            </>
          ) : (
            <span className="text-sm text-muted-foreground">
              Create a grid to start versioning.
            </span>
          )}
        </CardContent>
      </Card>

      {canEdit && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Store className="h-4 w-4" />
              Marketplace
            </CardTitle>
            <CardDescription>
              Import full division grids from another workspace, including versions, mappings, and
              tier icons.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {marketplaceWorkspaces.length === 0 ? (
              <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                {marketplaceWorkspacesQuery.isLoading
                  ? "Loading available workspaces..."
                  : "No accessible workspace with division grids was found."}
              </div>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-3">
                  <Select
                    value={effectiveMarketplaceSourceWorkspaceId?.toString() ?? ""}
                    onValueChange={(value) => {
                      setMarketplaceSourceWorkspaceId(Number(value));
                      setSelectedMarketplaceGridIds([]);
                      setMarketplaceImportResult(null);
                    }}
                  >
                    <SelectTrigger className="w-80">
                      <SelectValue placeholder="Source workspace" />
                    </SelectTrigger>
                    <SelectContent>
                      {marketplaceWorkspaces.map((sourceWorkspace) => (
                        <SelectItem key={sourceWorkspace.id} value={sourceWorkspace.id.toString()}>
                          {sourceWorkspace.name} ({sourceWorkspace.grids_count} grid
                          {sourceWorkspace.grids_count === 1 ? "" : "s"})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <label className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={makeImportedDefault}
                      onCheckedChange={(checked) => setMakeImportedDefault(checked === true)}
                    />
                    Set imported grid as workspace default
                  </label>
                </div>

                {marketplaceGridsQuery.isLoading ? (
                  <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                    Loading grids...
                  </div>
                ) : marketplaceGrids.length === 0 ? (
                  <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                    This source workspace does not have division grids.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {marketplaceGrids.map((grid) => {
                      const checked = selectedMarketplaceGridIdsSet.has(grid.id);
                      return (
                        <div
                          key={grid.id}
                          className={`flex flex-wrap items-center gap-3 rounded-md border p-3 transition-colors ${
                            checked ? "border-primary bg-primary/5" : "hover:bg-muted/40"
                          }`}
                        >
                          <Checkbox
                            checked={checked}
                            onCheckedChange={(value) => toggleMarketplaceGrid(grid.id, value === true)}
                            aria-label={`Select ${grid.name}`}
                          />
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-medium">{grid.name}</span>
                              <Badge variant="outline">{grid.slug}</Badge>
                            </div>
                            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                              <span>{grid.versions_count} version(s)</span>
                              <span>{grid.tiers_count} tier(s)</span>
                              {grid.versions.slice(-2).map((version) => (
                                <Badge key={version.id} variant="secondary" className="text-[10px]">
                                  v{version.version} {version.status}
                                </Badge>
                              ))}
                            </div>
                          </div>
                          {grid.preview_icon_urls.length > 0 && (
                            <div className="flex max-w-56 flex-wrap justify-end gap-1">
                              {grid.preview_icon_urls.slice(0, 8).map((iconUrl, index) => (
                                <span
                                  key={`${grid.id}-${iconUrl}-${index}`}
                                  className="flex h-8 w-8 items-center justify-center rounded border bg-background"
                                >
                                  <Image
                                    src={iconUrl}
                                    alt=""
                                    width={24}
                                    height={24}
                                    className="h-6 w-6 object-contain"
                                  />
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                <div className="flex flex-wrap items-center gap-3">
                  <Button
                    onClick={() => importMarketplaceMutation.mutate()}
                    disabled={
                      importMarketplaceMutation.isPending ||
                      selectedMarketplaceGridIds.length === 0 ||
                      effectiveMarketplaceSourceWorkspaceId === null
                    }
                  >
                    <Download className="mr-2 h-4 w-4" />
                    Import Selected
                  </Button>
                  {selectedMarketplaceGridIds.length > 0 && (
                    <span className="text-sm text-muted-foreground">
                      {selectedMarketplaceGridIds.length} selected
                    </span>
                  )}
                </div>

                {marketplaceImportResult && (
                  <div className="rounded-md border bg-muted/30 p-3 text-sm">
                    <div className="font-medium">
                      Imported {marketplaceImportResult.created_grids} grid(s),{" "}
                      {marketplaceImportResult.created_versions} version(s),{" "}
                      {marketplaceImportResult.copied_images} image(s).
                    </div>
                    {marketplaceImportResult.warnings.length > 0 && (
                      <div className="mt-2 space-y-1 text-muted-foreground">
                        {marketplaceImportResult.warnings.map((warning, index) => (
                          <div key={`${warning.message}-${index}`}>{warning.message}</div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      )}

      {activeGrid && (
        <DivisionGridEditorCard
          key={selectedVersion?.id ?? "default-grid-editor"}
          workspaceId={currentWorkspaceId}
          gridId={activeGrid.id}
          canEdit={canEdit}
          selectedVersion={selectedVersion}
          onSaved={async () => {
            await queryClient.invalidateQueries({
              queryKey: ["division-grids", currentWorkspaceId]
            });
          }}
        />
      )}

      {versions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Versions</CardTitle>
            <CardDescription>
              Published and draft versions available in this workspace grid.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {versions
              .slice()
              .sort((a, b) => b.version - a.version)
              .map((version) => {
                const isSelected = version.id === effectiveVersionId;
                const isDefault = workspace?.default_division_grid_version_id === version.id;
                const isDeleting =
                  deleteVersionMutation.isPending && deleteVersionMutation.variables === version.id;
                return (
                  <div
                    key={version.id}
                    role="button"
                    tabIndex={0}
                    className={`flex w-full cursor-pointer items-center justify-between rounded-lg border p-3 text-left transition-colors ${
                      isSelected
                        ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                        : "hover:bg-muted/50"
                    }`}
                    onClick={() => setSelectedVersionId(version.id)}
                    onKeyDown={(e) => e.key === "Enter" && setSelectedVersionId(version.id)}
                  >
                    <div>
                      <div className="flex items-center gap-2 font-medium">
                        {version.label}
                        {isSelected && <Check className="h-4 w-4 text-primary" />}
                      </div>
                      <div className="text-sm text-muted-foreground">
                        Version {version.version} • {version.tiers.length} tiers
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant={version.status === "published" ? "default" : "secondary"}>
                        {version.status}
                      </Badge>
                      {isDefault && <Badge variant="outline">Default</Badge>}
                      {canEdit && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground hover:text-destructive"
                          disabled={isDeleting}
                          onClick={(e) => {
                            e.stopPropagation();
                            deleteVersionMutation.mutate(version.id);
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
          </CardContent>
        </Card>
      )}

      {versions.length >= 2 && <DivisionGridMappingEditor versions={versions} canEdit={canEdit} />}
    </div>
  );
}
