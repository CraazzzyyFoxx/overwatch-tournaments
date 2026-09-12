"use client";

import { useMemo, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { StatusPill } from "@/components/admin/kit/StatusPill";
import {
  SortableGrip,
  SortableRows,
  useSortableRow
} from "@/app/balancer/components/SortableRows";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { notify } from "@/lib/notify";
import { nextStageOrder } from "@/lib/tournament-stages";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";

import {
  getProgressPercent,
  getStageAssignedTeams,
  getStageStatus,
  getStageStatusTone,
  getStageTeamSlots,
  normalizeMaxRounds,
  STAGE_TYPE_LABELS,
  type StageProgress
} from "../projection";

interface StageListProps {
  tournamentId: number;
  /** Already ordered by `order`. */
  stages: Stage[];
  teamsCount: number;
  progressByStageId: Map<number, StageProgress>;
  selectedStageId: number | null;
  onSelect: (stageId: number) => void;
  /** Invalidate the hub's stage queries after a write. */
  onChanged: () => void;
}

/**
 * The master column of the Bracket tab: the tournament flow, top to bottom.
 *
 * Selecting a stage is navigation (`?stage=`), not local state, so a stage can
 * be linked to. Order is the seeding order, so it is draggable — the old screen
 * could only reorder by deleting and re-creating a stage.
 */
export function StageList({
  tournamentId,
  stages,
  teamsCount,
  progressByStageId,
  selectedStageId,
  onSelect,
  onChanged
}: Readonly<StageListProps>) {
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [stageType, setStageType] = useState<StageType>("round_robin");
  const [maxRounds, setMaxRounds] = useState("5");
  const [grandFinalType, setGrandFinalType] = useState<"no_reset" | "with_reset">("no_reset");
  // Applied while the reorder PATCHes are in flight, so the row stays where it
  // was dropped instead of snapping back until the refetch lands.
  const [pendingOrder, setPendingOrder] = useState<number[] | null>(null);

  const resetForm = () => {
    setName("");
    setStageType("round_robin");
    setMaxRounds("5");
    setGrandFinalType("no_reset");
  };

  const createMutation = useMutation({
    mutationFn: () =>
      adminService.createStage(tournamentId, {
        name: name.trim(),
        stage_type: stageType,
        max_rounds: normalizeMaxRounds(maxRounds),
        order: nextStageOrder(stages),
        settings_json:
          stageType === "double_elimination" ? { de_grand_final_type: grandFinalType } : null
      }),
    onSuccess: (stage) => {
      onChanged();
      onSelect(stage.id);
      setCreateOpen(false);
      resetForm();
    }
  });

  const reorderMutation = useMutation({
    mutationFn: (orderedIds: number[]) =>
      Promise.all(
        orderedIds
          .map((stageId, index) => ({ stageId, index }))
          .filter(({ stageId, index }) => stages.find((s) => s.id === stageId)?.order !== index)
          .map(({ stageId, index }) => adminService.updateStage(stageId, { order: index }))
      ),
    onSuccess: () => {
      setPendingOrder(null);
      onChanged();
    },
    onError: (error) => {
      setPendingOrder(null);
      notify.apiError(error, { title: "Could not reorder the stages" });
    }
  });
  const ordersTied = new Set(stages.map((stage) => stage.order)).size !== stages.length;


  const ordered = useMemo(() => {
    if (!pendingOrder) {
      return [...stages].sort((left, right) => left.order - right.order || left.id - right.id);
    }
    const byId = new Map(stages.map((stage) => [stage.id, stage]));
    const moved = pendingOrder
      .map((id) => byId.get(id))
      .filter((stage): stage is Stage => stage !== undefined);
    return moved.length === stages.length ? moved : stages;
  }, [pendingOrder, stages]);

  const dirty =
    name.trim().length > 0 ||
    stageType !== "round_robin" ||
    maxRounds !== "5" ||
    grandFinalType !== "no_reset";

  return (
    <div className="rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-foreground">Tournament flow</p>
          <p className="text-xs tabular-nums text-muted-foreground">
            {stages.length} stage{stages.length === 1 ? "" : "s"} · {teamsCount} teams
          </p>
        </div>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="size-4" aria-hidden />
          Add stage
        </Button>
      </div>

      {stages.length === 0 ? (
        <p className="p-4 text-sm text-muted-foreground">
          No stages yet. Add the first phase — groups, playoffs and finals then read as a flow.
        </p>
      ) : (
        <>
          <SortableRows
            className="flex flex-col gap-1 p-2"
            items={ordered}
            getId={(stage) => String(stage.id)}
            onReorder={(next) => {
              if (ordersTied) return;
              const ids = next.map((stage) => stage.id);
              setPendingOrder(ids);
              reorderMutation.mutate(ids);
            }}
          >
            {(stage) => (
              <StageCard
                key={stage.id}
                stage={stage}
                progress={progressByStageId.get(stage.id)}
                selected={selectedStageId === stage.id}
                onSelect={() => onSelect(stage.id)}
              />
            )}
          </SortableRows>
          <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
            Same phase number = parallel. Drag sequences unique phases top to bottom.
          </p>
        </>
      )}

      <EntityFormDialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open);
          if (!open) {
            createMutation.reset();
            resetForm();
          }
        }}
        title="Add stage"
        description="Create the next tournament phase and choose its initial generation format."
        submitLabel="Add stage"
        submittingLabel="Adding…"
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          if (!name.trim()) return;
          createMutation.mutate();
        }}
        isSubmitting={createMutation.isPending}
        errorMessage={createMutation.isError ? createMutation.error.message : undefined}
        isDirty={dirty}
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="new-stage-name">Stage name</Label>
            <Input
              id="new-stage-name"
              placeholder="Playoffs, Group A, Finals…"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="new-stage-type">Stage type</Label>
            <Select value={stageType} onValueChange={(value) => setStageType(value as StageType)}>
              <SelectTrigger id="new-stage-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(STAGE_TYPE_LABELS).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {stageType === "swiss" ? (
            <div className="flex flex-col gap-2">
              <Label htmlFor="new-stage-max-rounds">Swiss max rounds</Label>
              <NumberInput
                id="new-stage-max-rounds"
                integer
                min={1}
                value={maxRounds === "" ? null : Number(maxRounds)}
                onValueChange={(next) => setMaxRounds(next == null ? "" : String(next))}
              />
            </div>
          ) : null}

          {stageType === "double_elimination" ? (
            <div className="flex flex-col gap-2">
              <Label htmlFor="new-stage-grand-final">Grand final format</Label>
              <Select
                value={grandFinalType}
                onValueChange={(value) =>
                  setGrandFinalType(value as "no_reset" | "with_reset")
                }
              >
                <SelectTrigger id="new-stage-grand-final">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="no_reset">
                    No reset · UB winner wins after one GF win
                  </SelectItem>
                  <SelectItem value="with_reset">
                    With reset · LB champion can force a rematch
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          ) : null}
        </div>
      </EntityFormDialog>
    </div>
  );
}

function StageCard({
  stage,
  progress,
  selected,
  onSelect
}: Readonly<{
  stage: Stage;
  progress: StageProgress | undefined;
  selected: boolean;
  onSelect: () => void;
}>) {
  const { ref, style, handleProps } = useSortableRow(String(stage.id));
  const hasEncounters = (progress?.total ?? 0) > 0;
  const slots = getStageTeamSlots(stage);
  const assigned = getStageAssignedTeams(stage);

  // The whole card selects. The name stays a <button> so keyboard users have a
  // focus stop; its Enter/Space click bubbles to the card's handler, so it
  // carries none of its own. A click on the grip bubbles too, which is harmless.
  return (
    <div
      ref={ref}
      style={style}
      onClick={onSelect}
      className={cn(
        "flex cursor-pointer items-start gap-2 rounded-lg border border-transparent p-2 transition-colors hover:border-border",
        selected && "border-border bg-accent/30"
      )}
    >
      <div className="flex flex-col items-center gap-1 pt-0.5">
        <SortableGrip handleProps={handleProps} label={`Reorder ${stage.name}`} />
        <span aria-hidden className="font-mono text-xs tabular-nums text-muted-foreground">
          {stage.order}
        </span>
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <button
            type="button"
            aria-current={selected ? "true" : undefined}
            className="min-w-0 truncate text-left text-sm font-semibold text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {stage.name}
          </button>
          <StatusPill tone={getStageStatusTone(stage, hasEncounters)} className="shrink-0">
            {getStageStatus(stage, hasEncounters)}
          </StatusPill>
        </div>

        <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
          <span>{STAGE_TYPE_LABELS[stage.stage_type]}</span>
          <span aria-hidden>·</span>
          <span className="tabular-nums">{stage.items.length} item(s)</span>
          <span aria-hidden>·</span>
          <span className="tabular-nums">
            {assigned}/{slots} slots
          </span>
        </p>

        {progress && progress.total > 0 ? (
          <div className="mt-2">
            <p className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
              <span>Matches</span>
              <span className="tabular-nums">
                {progress.completed}/{progress.total}
              </span>
            </p>
            <Progress
              value={getProgressPercent(progress.completed, progress.total)}
              className="h-1.5"
              aria-label={`${progress.completed} of ${progress.total} matches complete`}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
