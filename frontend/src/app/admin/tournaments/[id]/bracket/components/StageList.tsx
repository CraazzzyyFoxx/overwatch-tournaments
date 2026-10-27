"use client";

import { useMemo, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";

import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { StatusPill } from "@/components/kit/StatusPill";
import {
  SortableGrip,
  SortableRows,
  useSortableRow
} from "@/components/kit/SortableRows";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { Progress } from "@/components/ui/progress";
import { RowButton } from "@/components/ui/row-button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { notify } from "@/lib/notify";
import { nextStageOrder, phaseOrderForArrangement } from "@/lib/tournament/stages";
import adminService from "@/services/admin.service";
import type { Stage, StageType } from "@/types/tournament.types";

import {
  getProgressPercent,
  getStageStatus,
  getStageStatusTone,
  normalizeMaxRounds,
  STAGE_TYPE_LABELS,
  type StageProgress
} from "@/lib/bracket/projection";

interface StageListProps {
  tournamentId: number;
  /** Already ordered by `order`. */
  stages: Stage[];
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
  progressByStageId,
  selectedStageId,
  onSelect,
  onChanged
}: Readonly<StageListProps>) {
  const t = useTranslations("adminBracket.list");
  const tRoot = useTranslations("adminBracket");
  const tr = (key: string) => tRoot(key as never);
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
        de_grand_final_type: stageType === "double_elimination" ? grandFinalType : "no_reset"
      }),
    onSuccess: (stage) => {
      onChanged();
      onSelect(stage.id);
      setCreateOpen(false);
      resetForm();
    }
  });

  const reorderMutation = useMutation({
    mutationFn: (arrangement: Stage[]) => {
      const phases = phaseOrderForArrangement(arrangement);
      return Promise.all(
        arrangement
          .filter((stage) => phases.get(stage.id) !== stage.order)
          .map((stage) => adminService.updateStage(stage.id, { order: phases.get(stage.id) ?? stage.order }))
      );
    },
    onSuccess: () => {
      setPendingOrder(null);
      onChanged();
    },
    onError: (error) => {
      setPendingOrder(null);
      notify.apiError(error, { title: t("reorderError") });
    }
  });


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
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <p className="text-sm font-semibold text-foreground">{t("flow")}</p>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="size-4" aria-hidden />
          {t("add")}
        </Button>
      </div>

      {stages.length > 0 ? (
        <>
          <SortableRows
            className="flex flex-col gap-1 p-2"
            items={ordered}
            getId={(stage) => String(stage.id)}
            onReorder={(next) => {
              setPendingOrder(next.map((stage) => stage.id));
              reorderMutation.mutate(next);
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
          {stages.length > 1 ? (
            <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
              {t("drag")}
            </p>
          ) : null}
        </>
      ) : null}

      <EntityFormDialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open);
          if (!open) {
            createMutation.reset();
            resetForm();
          }
        }}
        title={t("dialogTitle")}
        submitLabel={t("submit")}
        submittingLabel={t("submitting")}
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
            <Label htmlFor="new-stage-name">{t("name")}</Label>
            <Input
              id="new-stage-name"
              placeholder={t("namePlaceholder")}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="new-stage-type">{t("type")}</Label>
            <Select value={stageType} onValueChange={(value) => setStageType(value as StageType)}>
              <SelectTrigger id="new-stage-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.keys(STAGE_TYPE_LABELS).map((value) => (
                  <SelectItem key={value} value={value}>
                    {tr(`labels.types.${value}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {stageType === "swiss" ? (
            <div className="flex flex-col gap-2">
              <Label htmlFor="new-stage-max-rounds">{t("swissRounds")}</Label>
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
              <Label htmlFor="new-stage-grand-final">{t("grandFinal")}</Label>
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
                    {t("noReset")}
                  </SelectItem>
                  <SelectItem value="with_reset">
                    {t("withReset")}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          ) : null}
        </div>
      </EntityFormDialog>
    </Card>
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
  const t = useTranslations("adminBracket.list");
  const tRoot = useTranslations("adminBracket");
  const tr = (key: string) => tRoot(key as never);
  const { ref, style, handleProps } = useSortableRow(String(stage.id));
  const hasEncounters = (progress?.total ?? 0) > 0;
  const status = getStageStatus(stage, hasEncounters);
  // Completed is where every stage ends up and draft is where it starts: only
  // a stage captains are playing (or about to) earns a pill.
  const showStatus = status === "Active" || status === "Preview";

  // The select button covers the row (it owns the hover, the selected fill and
  // the focus ring), the grip sits above it, and the content beneath is
  // decoration: the button carries the stage name for assistive tech.
  return (
    <div ref={ref} style={style} className="relative flex items-start gap-2 p-2">
      <SortableGrip
        className="relative z-10"
        handleProps={handleProps}
        label={t("reorder", { name: stage.name })}
      />
      <RowButton
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        className="absolute inset-0 rounded-lg"
      >
        <span className="sr-only">{stage.name}</span>
      </RowButton>

      <div className="pointer-events-none min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <p aria-hidden className="min-w-0 truncate text-sm font-semibold text-foreground">
            {stage.name}
          </p>
          {showStatus ? (
            <StatusPill tone={getStageStatusTone(stage, hasEncounters)} className="shrink-0">
              {tr(`extra.statuses.${status.toLowerCase()}`)}
            </StatusPill>
          ) : null}
        </div>

        <p className="mt-1 text-xs tabular-nums text-muted-foreground">
          {t("phase", { number: stage.order })}
        </p>

        {progress && progress.total > 0 ? (
          <div className="mt-2 flex items-center gap-2">
            <Progress
              value={getProgressPercent(progress.completed, progress.total)}
              size="sm"
              className="flex-1"
              aria-label={t("progress", { completed: progress.completed, total: progress.total })}
            />
            <span aria-hidden className="shrink-0 text-xs tabular-nums text-muted-foreground">
              {progress.completed}/{progress.total}
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
