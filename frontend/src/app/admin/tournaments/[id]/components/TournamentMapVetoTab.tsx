"use client";

import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Check,
  LoaderCircle,
  Pencil,
  Plus,
  Trash2,
  X
} from "lucide-react";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import mapService from "@/services/map.service";
import type { MapRead } from "@/types/map.types";
import type {
  MapVetoConfig,
  MapVetoConfigUpsertInput,
  Stage,
  VetoPreset,
  VetoSequenceToken
} from "@/types/tournament.types";

interface TournamentMapVetoTabProps {
  tournamentId: number;
  stages: Stage[];
  canManage: boolean;
}

type VetoLevelType = "tournament" | "stage" | "stage_round";
type StepAction = "ban" | "pick" | "decider";
type StepSide = "first" | "second";

const BO3_SEQUENCE: VetoSequenceToken[] = [
  "ban_first",
  "ban_second",
  "pick_first",
  "pick_second",
  "decider"
];

const BO5_SEQUENCE: VetoSequenceToken[] = [
  "ban_first",
  "ban_second",
  "pick_first",
  "pick_second",
  "pick_first",
  "pick_second",
  "decider"
];

/** Bo1: alternating bans (first team starts) until one map remains, then a decider. */
function buildBo1Sequence(poolSize: number): VetoSequenceToken[] {
  const sequence: VetoSequenceToken[] = [];
  for (let index = 0; index < poolSize - 1; index += 1) {
    sequence.push(index % 2 === 0 ? "ban_first" : "ban_second");
  }
  sequence.push("decider");
  return sequence;
}

function tokenAction(token: VetoSequenceToken): StepAction {
  if (token === "decider") return "decider";
  return token.startsWith("ban") ? "ban" : "pick";
}

function tokenSide(token: VetoSequenceToken): StepSide | null {
  if (token === "decider") return null;
  return token.endsWith("_first") ? "first" : "second";
}

function buildToken(action: StepAction, side: StepSide): VetoSequenceToken {
  if (action === "decider") return "decider";
  return `${action}_${side}` as VetoSequenceToken;
}

function tokenLabel(token: VetoSequenceToken): string {
  if (token === "decider") return "Decider";
  const action = tokenAction(token) === "ban" ? "Ban" : "Pick";
  return `${action} ${tokenSide(token) === "first" ? "1st" : "2nd"}`;
}

/** Mirrors backend config-upsert validation so errors surface before save. */
function validateConfigForm(
  sequence: VetoSequenceToken[],
  mapIds: number[]
): string[] {
  const errors: string[] = [];
  if (mapIds.length === 0) {
    errors.push("Select at least one map for the pool.");
  }
  if (sequence.length === 0) {
    errors.push("The sequence must contain at least one step.");
  } else {
    const deciderCount = sequence.filter((token) => token === "decider").length;
    if (deciderCount > 1) {
      errors.push("Only one decider step is allowed.");
    } else if (deciderCount === 1 && sequence[sequence.length - 1] !== "decider") {
      errors.push("The decider step must be the last step.");
    }
    if (!sequence.some((token) => tokenAction(token) !== "ban")) {
      errors.push("The sequence needs at least one pick or a decider.");
    }
  }
  if (mapIds.length > 0 && sequence.length > mapIds.length) {
    errors.push(
      `The sequence has ${sequence.length} steps but the pool only has ${mapIds.length} maps.`
    );
  }
  return errors;
}

function getLevelLabel(config: MapVetoConfig, stagesById: Map<number, Stage>): string {
  if (config.stage_id == null) return "Tournament default";
  const stageName = stagesById.get(config.stage_id)?.name ?? `Stage #${config.stage_id}`;
  if (config.round == null) return `Stage: ${stageName}`;
  return `Stage: ${stageName} · Round ${config.round}`;
}

function getPresetLabel(preset: VetoPreset | null): string {
  switch (preset) {
    case "bo1":
      return "Bo1";
    case "bo3":
      return "Bo3";
    case "bo5":
      return "Bo5";
    default:
      return "Custom";
  }
}

interface VetoConfigFormState {
  levelType: VetoLevelType;
  stageId: number | null;
  round: number | null;
  mapIds: number[];
  sequence: VetoSequenceToken[];
  preset: VetoPreset;
  turnTimerSeconds: number | null;
}

const emptyFormState: VetoConfigFormState = {
  levelType: "tournament",
  stageId: null,
  round: null,
  mapIds: [],
  sequence: [],
  preset: "custom",
  turnTimerSeconds: null
};

function getConfigFormState(config: MapVetoConfig): VetoConfigFormState {
  return {
    levelType:
      config.stage_id == null ? "tournament" : config.round == null ? "stage" : "stage_round",
    stageId: config.stage_id,
    round: config.round,
    mapIds: [...config.map_ids],
    sequence: [...config.sequence],
    preset: config.preset ?? "custom",
    turnTimerSeconds: config.turn_timer_seconds
  };
}

function MapPoolCard({
  map,
  selectionIndex,
  disabled,
  onToggle
}: {
  map: MapRead;
  selectionIndex: number;
  disabled: boolean;
  onToggle: () => void;
}) {
  const selected = selectionIndex >= 0;
  return (
    <button
      type="button"
      aria-pressed={selected}
      disabled={disabled}
      onClick={onToggle}
      className={cn(
        "relative flex h-20 flex-col justify-end overflow-hidden rounded-lg border text-left transition",
        selected
          ? "border-primary ring-2 ring-primary/40"
          : "border-border/70 hover:border-primary/50",
        disabled && "cursor-not-allowed opacity-60"
      )}
    >
      {map.image_path ? (
        <div
          aria-hidden
          className="absolute inset-0 bg-cover bg-center"
          style={{ backgroundImage: `url("${map.image_path}")` }}
        />
      ) : (
        <div aria-hidden className="absolute inset-0 bg-muted/40" />
      )}
      <div aria-hidden className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent" />
      {selected ? (
        <span className="absolute right-1.5 top-1.5 flex size-5 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
          {selectionIndex + 1}
        </span>
      ) : null}
      <span className="relative truncate px-2 pb-1.5 text-xs font-medium text-white">
        {map.name}
      </span>
    </button>
  );
}

export function TournamentMapVetoTab({
  tournamentId,
  stages,
  canManage
}: TournamentMapVetoTabProps) {
  const queryClient = useQueryClient();
  const configsQueryKey = ["admin", "tournament", tournamentId, "veto-configs"] as const;

  const [editorOpen, setEditorOpen] = useState(false);
  const [editingConfig, setEditingConfig] = useState<MapVetoConfig | null>(null);
  const [formState, setFormState] = useState<VetoConfigFormState>(emptyFormState);
  const [formError, setFormError] = useState<string | undefined>(undefined);
  const [configPendingDelete, setConfigPendingDelete] = useState<MapVetoConfig | null>(null);

  const configsQuery = useQuery({
    queryKey: configsQueryKey,
    queryFn: () => adminService.listVetoConfigs(tournamentId)
  });

  const mapsQuery = useQuery({
    queryKey: ["maps", "all"],
    queryFn: () => mapService.getAll({ perPage: -1, sort: "name", order: "asc" })
  });

  const maps = useMemo(() => mapsQuery.data?.results ?? [], [mapsQuery.data]);
  const mapsById = useMemo(() => new Map(maps.map((map) => [map.id, map])), [maps]);
  const stagesById = useMemo(() => new Map(stages.map((stage) => [stage.id, stage])), [stages]);
  const sortedStages = useMemo(
    () => [...stages].sort((left, right) => left.order - right.order),
    [stages]
  );

  const configs = useMemo(() => {
    const rows = configsQuery.data?.configs ?? [];
    return [...rows].sort((left, right) => {
      if (left.stage_id == null || right.stage_id == null) {
        return (left.stage_id == null ? 0 : 1) - (right.stage_id == null ? 0 : 1);
      }
      if (left.stage_id !== right.stage_id) {
        const leftOrder = stagesById.get(left.stage_id)?.order ?? left.stage_id;
        const rightOrder = stagesById.get(right.stage_id)?.order ?? right.stage_id;
        return leftOrder - rightOrder;
      }
      return (left.round ?? 0) - (right.round ?? 0);
    });
  }, [configsQuery.data, stagesById]);

  const upsertMutation = useMutation({
    meta: { suppressErrorToast: true },
    mutationFn: (data: MapVetoConfigUpsertInput) =>
      adminService.upsertVetoConfig(tournamentId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: configsQueryKey });
      resetEditor();
      notify.success("Veto config saved");
    },
    onError: (error: Error) => {
      setFormError(error.message);
    }
  });

  const deleteMutation = useMutation({
    mutationFn: (configId: number) => adminService.deleteVetoConfig(configId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: configsQueryKey });
      setConfigPendingDelete(null);
      notify.success("Veto config deleted");
    }
  });

  const resetEditor = () => {
    setEditorOpen(false);
    setEditingConfig(null);
    setFormState(emptyFormState);
    setFormError(undefined);
    upsertMutation.reset();
  };

  const openCreateEditor = () => {
    setEditingConfig(null);
    setFormState(emptyFormState);
    setFormError(undefined);
    upsertMutation.reset();
    setEditorOpen(true);
  };

  const openEditEditor = (config: MapVetoConfig) => {
    setEditingConfig(config);
    setFormState(getConfigFormState(config));
    setFormError(undefined);
    upsertMutation.reset();
    setEditorOpen(true);
  };

  const patchForm = (patch: Partial<VetoConfigFormState>) => {
    setFormState((previous) => ({ ...previous, ...patch }));
  };

  const toggleMap = (mapId: number) => {
    setFormState((previous) => {
      const selected = previous.mapIds.includes(mapId);
      const mapIds = selected
        ? previous.mapIds.filter((id) => id !== mapId)
        : [...previous.mapIds, mapId];
      // Bo1 depends on the pool size — keep the generated sequence in sync.
      const sequence =
        previous.preset === "bo1" && mapIds.length > 0
          ? buildBo1Sequence(mapIds.length)
          : previous.sequence;
      return { ...previous, mapIds, sequence };
    });
  };

  const applyPreset = (preset: Exclude<VetoPreset, "custom">) => {
    setFormState((previous) => {
      const sequence =
        preset === "bo1"
          ? buildBo1Sequence(previous.mapIds.length)
          : preset === "bo3"
            ? [...BO3_SEQUENCE]
            : [...BO5_SEQUENCE];
      return { ...previous, preset, sequence };
    });
  };

  const patchSequence = (mutate: (steps: VetoSequenceToken[]) => VetoSequenceToken[]) => {
    setFormState((previous) => ({
      ...previous,
      preset: "custom",
      sequence: mutate([...previous.sequence])
    }));
  };

  const moveStep = (index: number, direction: -1 | 1) => {
    patchSequence((steps) => {
      const target = index + direction;
      if (target < 0 || target >= steps.length) return steps;
      const [step] = steps.splice(index, 1);
      steps.splice(target, 0, step);
      return steps;
    });
  };

  const updateStep = (index: number, action: StepAction, side: StepSide) => {
    patchSequence((steps) => {
      steps[index] = buildToken(action, side);
      return steps;
    });
  };

  const validationErrors = validateConfigForm(formState.sequence, formState.mapIds);
  const stageMissing = formState.levelType !== "tournament" && formState.stageId == null;
  const roundMissing = formState.levelType === "stage_round" && formState.round == null;
  const levelErrors: string[] = [];
  if (stageMissing) levelErrors.push("Select a stage for this config level.");
  if (roundMissing) levelErrors.push("Enter a round number (rounds always belong to a stage).");
  const allErrors = [...levelErrors, ...validationErrors];
  const canSave = allErrors.length === 0 && !upsertMutation.isPending;

  const effectiveStageId = formState.levelType === "tournament" ? null : formState.stageId;
  const effectiveRound = formState.levelType === "stage_round" ? formState.round : null;
  const replacesExisting = configs.find(
    (config) =>
      config.id !== editingConfig?.id &&
      (config.stage_id ?? null) === effectiveStageId &&
      (config.round ?? null) === effectiveRound
  );

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!canSave) return;
    upsertMutation.mutate({
      stage_id: effectiveStageId,
      round: effectiveRound,
      map_ids: formState.mapIds,
      sequence: formState.sequence,
      turn_timer_seconds: formState.turnTimerSeconds,
      preset: formState.preset
    });
  };

  const presetButtons: { preset: Exclude<VetoPreset, "custom">; label: string; minPool: number }[] = [
    { preset: "bo1", label: "Bo1", minPool: 2 },
    { preset: "bo3", label: "Bo3", minPool: BO3_SEQUENCE.length },
    { preset: "bo5", label: "Bo5", minPool: BO5_SEQUENCE.length }
  ];

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
          <div className="space-y-1.5">
            <CardTitle>Map veto</CardTitle>
            <CardDescription>
              Map pools and pick/ban sequences for veto rooms. The most specific level wins:
              stage + round overrides stage, stage overrides the tournament default.
            </CardDescription>
          </div>
          {canManage ? (
            <Button onClick={openCreateEditor}>
              <Plus className="h-4 w-4" />
              Add config
            </Button>
          ) : null}
        </CardHeader>
        <CardContent>
          {configsQuery.isLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-16 w-full rounded-lg" />
              <Skeleton className="h-16 w-full rounded-lg" />
            </div>
          ) : configs.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border/70 px-4 py-8 text-center text-sm text-muted-foreground">
              No veto configs yet. Add a tournament default so veto rooms can open for
              every match, then override specific stages or rounds when needed.
            </p>
          ) : (
            <ul className="space-y-3">
              {configs.map((config) => (
                <li
                  key={config.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border/70 px-4 py-3"
                >
                  <div className="min-w-0 space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{getLevelLabel(config, stagesById)}</span>
                      <Badge variant="outline">{getPresetLabel(config.preset)}</Badge>
                      {config.turn_timer_seconds != null ? (
                        <Badge variant="secondary">{config.turn_timer_seconds}s timer</Badge>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                      <span>
                        {config.map_ids.length}{" "}
                        {config.map_ids.length === 1 ? "map" : "maps"}:
                      </span>
                      <span className="truncate">
                        {config.map_ids
                          .map((mapId) => mapsById.get(mapId)?.name ?? `#${mapId}`)
                          .join(", ")}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {config.sequence.map((token, index) => (
                        <Badge
                          key={`${config.id}-${index}`}
                          variant={tokenAction(token) === "ban" ? "destructive" : "secondary"}
                          className="text-[11px]"
                        >
                          {tokenLabel(token)}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  {canManage ? (
                    <div className="flex shrink-0 items-center gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Edit ${getLevelLabel(config, stagesById)}`}
                        onClick={() => openEditEditor(config)}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Delete ${getLevelLabel(config, stagesById)}`}
                        onClick={() => setConfigPendingDelete(config)}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={editorOpen}
        onOpenChange={(open) => {
          if (!open) {
            resetEditor();
          } else {
            setEditorOpen(true);
          }
        }}
      >
        <DialogContent className="flex max-h-[calc(100dvh-2rem)] max-w-3xl flex-col gap-0 overflow-hidden sm:max-h-[90dvh]">
          <DialogHeader className="shrink-0 border-b border-border/60 pb-4">
            <DialogTitle>{editingConfig ? "Edit veto config" : "New veto config"}</DialogTitle>
            <DialogDescription>
              Choose the maps captains can pick or ban and the order of veto steps.
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="min-h-0 flex-1 space-y-5 overflow-y-auto py-4 pr-4">
              <div className="grid gap-4 sm:grid-cols-3">
                <div className="space-y-2">
                  <Label htmlFor="veto-level">Level</Label>
                  <Select
                    value={formState.levelType}
                    onValueChange={(value) => {
                      const levelType = value as VetoLevelType;
                      patchForm({
                        levelType,
                        stageId: levelType === "tournament" ? null : formState.stageId,
                        round: levelType === "stage_round" ? formState.round : null
                      });
                    }}
                    disabled={Boolean(editingConfig)}
                  >
                    <SelectTrigger id="veto-level">
                      <SelectValue placeholder="Select level" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="tournament">Tournament default</SelectItem>
                      <SelectItem value="stage">Stage</SelectItem>
                      <SelectItem value="stage_round">Stage + round</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {formState.levelType !== "tournament" ? (
                  <div className="space-y-2">
                    <Label htmlFor="veto-stage">Stage</Label>
                    <Select
                      value={formState.stageId != null ? String(formState.stageId) : ""}
                      onValueChange={(value) => patchForm({ stageId: Number(value) })}
                      disabled={Boolean(editingConfig)}
                    >
                      <SelectTrigger id="veto-stage">
                        <SelectValue placeholder="Select stage" />
                      </SelectTrigger>
                      <SelectContent>
                        {sortedStages.map((stage) => (
                          <SelectItem key={stage.id} value={String(stage.id)}>
                            {stage.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                ) : null}
                {formState.levelType === "stage_round" ? (
                  <div className="space-y-2">
                    <Label htmlFor="veto-round">Round</Label>
                    <NumberInput
                      id="veto-round"
                      value={formState.round}
                      onValueChange={(value) => patchForm({ round: value })}
                      min={1}
                      integer
                      placeholder="Round number"
                      disabled={Boolean(editingConfig)}
                    />
                  </div>
                ) : null}
              </div>
              {replacesExisting ? (
                <p className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-600 dark:text-amber-400">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  A config already exists for this level — saving will replace it.
                </p>
              ) : null}

              <div className="space-y-2">
                <div className="flex items-baseline justify-between">
                  <Label>Map pool</Label>
                  <span className="text-xs text-muted-foreground">
                    {formState.mapIds.length} selected · click order sets the pool order
                  </span>
                </div>
                {mapsQuery.isLoading ? (
                  <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                    {Array.from({ length: 8 }).map((_, index) => (
                      <Skeleton key={index} className="h-20 rounded-lg" />
                    ))}
                  </div>
                ) : maps.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No maps available. Create maps in the admin maps section first.
                  </p>
                ) : (
                  <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                    {maps.map((map) => (
                      <MapPoolCard
                        key={map.id}
                        map={map}
                        selectionIndex={formState.mapIds.indexOf(map.id)}
                        disabled={upsertMutation.isPending}
                        onToggle={() => toggleMap(map.id)}
                      />
                    ))}
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Label>Veto sequence</Label>
                  <div className="flex items-center gap-1.5">
                    {presetButtons.map(({ preset, label, minPool }) => (
                      <Button
                        key={preset}
                        type="button"
                        size="sm"
                        variant={formState.preset === preset ? "default" : "outline"}
                        disabled={formState.mapIds.length < minPool}
                        title={
                          formState.mapIds.length < minPool
                            ? `Needs at least ${minPool} maps in the pool`
                            : undefined
                        }
                        onClick={() => applyPreset(preset)}
                      >
                        {label}
                      </Button>
                    ))}
                    <Badge variant={formState.preset === "custom" ? "default" : "outline"}>
                      Custom
                    </Badge>
                  </div>
                </div>
                {formState.sequence.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-border/70 px-4 py-6 text-center text-sm text-muted-foreground">
                    No steps yet. Apply a preset or add steps manually.
                  </p>
                ) : (
                  <ol className="space-y-1.5">
                    {formState.sequence.map((token, index) => {
                      const action = tokenAction(token);
                      const side = tokenSide(token);
                      return (
                        <li
                          key={index}
                          className="flex items-center gap-2 rounded-lg border border-border/70 px-2 py-1.5"
                        >
                          <span className="w-6 text-center text-xs font-medium text-muted-foreground">
                            {index + 1}
                          </span>
                          <Select
                            value={action}
                            onValueChange={(value) =>
                              updateStep(index, value as StepAction, side ?? "first")
                            }
                          >
                            <SelectTrigger
                              className="h-8 w-28"
                              aria-label={`Step ${index + 1} action`}
                            >
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="ban">Ban</SelectItem>
                              <SelectItem value="pick">Pick</SelectItem>
                              <SelectItem value="decider">Decider</SelectItem>
                            </SelectContent>
                          </Select>
                          {action !== "decider" ? (
                            <Select
                              value={side ?? "first"}
                              onValueChange={(value) =>
                                updateStep(index, action, value as StepSide)
                              }
                            >
                              <SelectTrigger
                                className="h-8 w-32"
                                aria-label={`Step ${index + 1} team`}
                              >
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="first">First team</SelectItem>
                                <SelectItem value="second">Second team</SelectItem>
                              </SelectContent>
                            </Select>
                          ) : (
                            <span className="w-32 text-xs text-muted-foreground">
                              auto-resolves
                            </span>
                          )}
                          <div className="ml-auto flex items-center gap-0.5">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="size-7"
                              aria-label={`Move step ${index + 1} up`}
                              disabled={index === 0}
                              onClick={() => moveStep(index, -1)}
                            >
                              <ArrowUp className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="size-7"
                              aria-label={`Move step ${index + 1} down`}
                              disabled={index === formState.sequence.length - 1}
                              onClick={() => moveStep(index, 1)}
                            >
                              <ArrowDown className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="size-7"
                              aria-label={`Remove step ${index + 1}`}
                              onClick={() =>
                                patchSequence((steps) => {
                                  steps.splice(index, 1);
                                  return steps;
                                })
                              }
                            >
                              <X className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => patchSequence((steps) => [...steps, "ban_first"])}
                >
                  <Plus className="h-4 w-4" />
                  Add step
                </Button>
              </div>

              <div className="space-y-2">
                <Label htmlFor="veto-timer">Turn timer (seconds)</Label>
                <NumberInput
                  id="veto-timer"
                  value={formState.turnTimerSeconds}
                  onValueChange={(value) => patchForm({ turnTimerSeconds: value })}
                  min={1}
                  integer
                  placeholder="No timer"
                  className="max-w-48"
                />
                <p className="text-xs text-muted-foreground">
                  Indicator only — the server never acts automatically when time runs out.
                </p>
              </div>

              {allErrors.length > 0 ? (
                <div
                  aria-live="polite"
                  className="space-y-1 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                >
                  {allErrors.map((error) => (
                    <p key={error} className="flex items-start gap-2">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      {error}
                    </p>
                  ))}
                </div>
              ) : (
                <p className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Check className="h-3.5 w-3.5 text-emerald-500" />
                  Sequence is valid for the selected pool.
                </p>
              )}

              {formError ? (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                >
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  {formError}
                </div>
              ) : null}
            </div>

            <DialogFooter className="mt-4 shrink-0 border-t border-border/60 pt-4">
              <Button
                type="button"
                variant="outline"
                onClick={resetEditor}
                disabled={upsertMutation.isPending}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={!canSave}>
                {upsertMutation.isPending ? (
                  <>
                    <LoaderCircle className="h-4 w-4 animate-spin" />
                    Saving…
                  </>
                ) : (
                  "Save config"
                )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <DeleteConfirmDialog
        open={Boolean(configPendingDelete)}
        onOpenChange={(open) => {
          if (!open) setConfigPendingDelete(null);
        }}
        onConfirm={() => {
          if (configPendingDelete) {
            deleteMutation.mutate(configPendingDelete.id);
          }
        }}
        title="Delete veto config?"
        description={
          configPendingDelete
            ? `The "${getLevelLabel(configPendingDelete, stagesById)}" veto config will be removed. Matches fall back to the next config level; running veto sessions keep their snapshot.`
            : ""
        }
        isDeleting={deleteMutation.isPending}
      />
    </>
  );
}
