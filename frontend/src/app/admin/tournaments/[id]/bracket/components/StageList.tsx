"use client";

import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { MoreHorizontal, Plus } from "lucide-react";

import { EntityFormDialog } from "@craazzzyyfoxx/admin-kit/kit/EntityFormDialog";
import { StatusPill } from "@/components/kit/StatusPill";
import {
  SortableGrip,
  SortableRows,
  useSortableRow
} from "@/components/kit/SortableRows";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger
} from "@craazzzyyfoxx/admin-kit/ui/dropdown-menu";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { Progress } from "@/components/ui/progress";
import { RowButton } from "@craazzzyyfoxx/admin-kit/ui/row-button";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { notify } from "@/lib/notify";
import { nextStageOrder, phaseOrderForArrangement, phasesBesideAbove } from "@/lib/tournament/stages";
import adminService from "@/services/admin.service";
import flowService from "@/services/flow.service";
import { useFlowErrorMessage } from "@/hooks/useFlowErrorNotifier";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { addStageChanges, defaultRule, type FeedRule } from "@/lib/flow/stageFeed";
import type { FlowStageCreate } from "@/types/flow.types";
import type { Stage, StagePairingMode, StageType } from "@/types/tournament.types";

import {
  getProgressPercent,
  getStageStatus,
  getStageStatusTone,
  normalizeMaxRounds,
  STAGE_TYPE_LABELS,
  type StageProgress
} from "@/lib/bracket/projection";
import { FeedRuleFields, type FeedField } from "./stage-settings/FeedRuleFields";

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

const DialogField: FeedField = ({ id, label, hint, children }) => (
  <div className="flex flex-col gap-2">
    <Label htmlFor={id}>{label}</Label>
    {children}
    {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
  </div>
);

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
  const tFeed = useTranslations("adminBracket.feed");
  const flowMessage = useFlowErrorMessage();
  const queryClient = useQueryClient();
  const tRoot = useTranslations("adminBracket");
  const tr = (key: string) => tRoot(key as never);
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [stageType, setStageType] = useState<StageType>("round_robin");
  const [maxRounds, setMaxRounds] = useState("5");
  const [grandFinalType, setGrandFinalType] = useState<"no_reset" | "with_reset">("no_reset");
  const [pairingMode, setPairingMode] = useState<StagePairingMode>("score");
  const [playoffTeamCount, setPlayoffTeamCount] = useState(4);
  // Who advances from the last stage; untouched until the organizer edits it, so the default follows that stage.
  const [rule, setRule] = useState<FeedRule | null>(null);
  const last = stages.at(-1);
  const feedRule = rule ?? defaultRule(last);
  // Applied while the reorder PATCHes are in flight, so the row stays where it
  // was dropped instead of snapping back until the refetch lands.
  const [pendingOrder, setPendingOrder] = useState<number[] | null>(null);

  const resetForm = () => {
    setName("");
    setStageType("round_robin");
    setMaxRounds("5");
    setGrandFinalType("no_reset");
    setPairingMode("score");
    setPlayoffTeamCount(4);
    setRule(null);
  };

  const createMutation = useMutation({
    mutationFn: async (): Promise<number | null> => {
      const body = {
        name: name.trim(),
        stage_type: stageType,
        max_rounds: normalizeMaxRounds(maxRounds),
        order: nextStageOrder(stages),
        de_grand_final_type: stageType === "double_elimination" ? grandFinalType : "no_reset",
        ...(stageType === "individual_swiss"
          ? { pairing_mode: pairingMode, playoff_team_count: playoffTeamCount }
          : {})
      };
      // The first stage is wired by the server; a later one is created with its input in one flow edit.
      if (!last) return (await adminService.createStage(tournamentId, body)).id;
      const read = await queryClient.fetchQuery({
        queryKey: adminQueryKeys.tournamentFlow(tournamentId),
        queryFn: () => flowService.getAdmin(tournamentId),
        staleTime: 0
      });
      const saved = await flowService.applyChanges(
        tournamentId,
        addStageChanges({
          name: body.name,
          stage: body as FlowStageCreate,
          source: read.nodes.find((node) => node.id === last.node_id) ?? null,
          rule: { ...feedRule, upper: stageType === "double_elimination" ? feedRule.upper : null },
          filterName: tFeed("filterName")
        })
      );
      queryClient.setQueryData(adminQueryKeys.tournamentFlow(tournamentId), saved);
      const created = saved.nodes.find(
        (node) => node.stage_id !== null && !stages.some((stage) => stage.id === node.stage_id)
      );
      return created?.stage_id ?? null;
    },
    onSuccess: (stageId) => {
      onChanged();
      if (stageId !== null) onSelect(stageId);
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

  const phaseMutation = useMutation({
    mutationFn: (phases: Map<number, number>) =>
      Promise.all([...phases].map(([id, order]) => adminService.updateStage(id, { order }))),
    onSuccess: () => onChanged(),
    onError: (error) => notify.apiError(error, { title: t("phaseError") })
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
    grandFinalType !== "no_reset" ||
    pairingMode !== "score" ||
    playoffTeamCount !== 4 ||
    rule !== null;

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
            {(stage) => {
              const index = ordered.indexOf(stage);
              return (
                <StageCard
                  key={stage.id}
                  stage={stage}
                  above={index > 0 ? ordered[index - 1] : undefined}
                  progress={progressByStageId.get(stage.id)}
                  selected={selectedStageId === stage.id}
                  onSelect={() => onSelect(stage.id)}
                  onPhase={(mode) => phaseMutation.mutate(phasesBesideAbove(ordered, stage.id, mode))}
                />
              );
            }}
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
        errorMessage={
          createMutation.isError ? (flowMessage(createMutation.error) ?? createMutation.error.message) : undefined
        }
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

          {stageType === "swiss" || stageType === "individual_swiss" ? (
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

          {stageType === "individual_swiss" ? (
            <>
              <div className="flex flex-col gap-2">
                <Label htmlFor="new-stage-pairing">{t("pairingMode")}</Label>
                <Select
                  value={pairingMode}
                  onValueChange={(value) => setPairingMode(value as StagePairingMode)}
                >
                  <SelectTrigger id="new-stage-pairing">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="score">{t("pairingScore")}</SelectItem>
                    <SelectItem value="balance">{t("pairingBalance")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="new-stage-playoff">{t("playoffTeams")}</Label>
                <NumberInput
                  id="new-stage-playoff"
                  integer
                  min={1}
                  value={playoffTeamCount}
                  onValueChange={(next) => setPlayoffTeamCount(next ?? 4)}
                />
              </div>
            </>
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

          {last ? (
            <>
              <Separator />
              <p className="text-sm font-semibold text-foreground">
                {tFeed("advanceFrom", { stage: last.name })}
              </p>
              <FeedRuleFields
                ids="new-stage-feed"
                rule={feedRule}
                source={last}
                targetStageType={stageType}
                Field={DialogField}
                onChange={(patch) => setRule({ ...feedRule, ...patch })}
              />
            </>
          ) : null}
        </div>
      </EntityFormDialog>
    </Card>
  );
}

function StageCard({
  stage,
  above,
  progress,
  selected,
  onSelect,
  onPhase
}: Readonly<{
  stage: Stage;
  /** The stage listed right above: the one this stage can run beside or after. */
  above: Stage | undefined;
  progress: StageProgress | undefined;
  selected: boolean;
  onSelect: () => void;
  onPhase: (mode: "parallel" | "after") => void;
}>) {
  const t = useTranslations("adminBracket.list");
  const side = above && stage.order === above.order ? "parallel" : "after";
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
      {above ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="relative z-10 shrink-0"
              aria-label={t("phaseMenu", { name: stage.name })}
            >
              <MoreHorizontal aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>{t("phase", { number: stage.order })}</DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={side}
              // Picking the checked side again must not move anything: "after" would shift every stage below.
              onValueChange={(mode) => {
                if (mode !== side) onPhase(mode as "parallel" | "after");
              }}
            >
              <DropdownMenuRadioItem value="parallel">{t("inParallel", { name: above.name })}</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="after">{t("after", { name: above.name })}</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </div>
  );
}
