"use client";

import { useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import {
  DndContext,
  DragOverlay,
  pointerWithin,
  useDraggable,
  useDroppable,
  type DragEndEvent,
  type DragStartEvent
} from "@dnd-kit/core";
import {
  ArrowUpRight,
  CheckCircle2,
  GripVertical,
  Pencil,
  Plus,
  Trash2,
  X
} from "lucide-react";

import { InlineEditText } from "@/components/kit/InlineEditText";
import { Badge } from "@/components/ui/badge";
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
import { notify } from "@/lib/notify";
import { useDragSensors } from "@/hooks/useDragSensors";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type { StageItemInputUpdateInput } from "@/types/admin.types";
import type { Stage, StageItem, StageItemInput, StageItemType } from "@/types/tournament.types";
import type { Team } from "@/types/team.types";

import {
  getAssignedTeamIds,
  getDefaultStageItemType,
  getInputDisplayLabel,
  STAGE_ITEM_TYPE_LABELS,
  type StageProgress
} from "@/lib/bracket/projection";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { Spinner } from "@/components/ui/spinner";

/**
 * The `updateStageItemInput` calls that move `source`'s team into `target`'s slot.
 *
 * A filled target is one PATCH: `services/admin/stage.py:update_stage_item_input`
 * moves the team it displaces back into the slot the dragged team came from.
 */
export function seedSwapRequests(
  source: StageItemInput,
  target: StageItemInput
): Array<{ inputId: number; data: StageItemInputUpdateInput }> {
  const fill = {
    inputId: target.id,
    data: { team_id: source.team_id, input_type: "final" as const }
  };
  if (target.team_id != null) return [fill];

  // ponytail: two PATCHes, not one transaction — a failure between them leaves the
  // team unseated; give the API a move endpoint if that ever bites.
  return [{ inputId: source.id, data: { input_type: "empty" as const } }, fill];
}

/**
 * One team slot: a drop target for every drag, and a drag source once it holds
 * a team. The grip is the only handle, so the row's buttons stay clickable.
 */
function SeedSlotRow({
  input,
  dragLabel,
  dragDisabled,
  children
}: Readonly<{
  input: StageItemInput;
  dragLabel: string;
  dragDisabled: boolean;
  children: ReactNode;
}>) {
  const { setNodeRef, isOver } = useDroppable({ id: `slot-${input.id}`, data: { input } });
  const { attributes, listeners, setActivatorNodeRef, isDragging } = useDraggable({
    id: `team-${input.id}`,
    data: { input },
    disabled: dragDisabled || input.team_id == null
  });

  return (
    <li
      ref={setNodeRef}
      className={cn(
        "flex items-center gap-2 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs",
        isOver && "ring-2 ring-ring",
        isDragging && "opacity-50"
      )}
    >
      {input.team_id != null ? (
        <button
          type="button"
          ref={setActivatorNodeRef}
          {...attributes}
          {...listeners}
          disabled={dragDisabled}
          aria-label={`Drag ${dragLabel} to another slot`}
          className="shrink-0 cursor-grab rounded p-1 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 active:cursor-grabbing"
        >
          <GripVertical className="size-3.5" aria-hidden />
        </button>
      ) : null}
      {children}
    </li>
  );
}

interface StageItemsSectionProps {
  stage: Stage;
  stages: Stage[];
  teams: Team[];
  isTeamsLoading: boolean;
  progress: StageProgress | undefined;
  /** `Matches › Encounters` scoped to this stage. */
  encountersHref: string;
  onChanged: () => void;
  /** Routes to the screen's one `ConfirmDialog`. */
  onRequestDeleteItem: (item: StageItem) => void;
  /** Routes to the same dialog: removing a team slot drops a seed. */
  onRequestRemoveInput: (input: StageItemInput, label: string) => void;
}

/**
 * Groups and bracket lanes of the selected stage, and the teams in their slots.
 *
 * Matches are NOT edited here any more: the section links out to
 * `Matches › Encounters?stage=N`, which is the screen that owns them.
 */
export function StageItemsSection({
  stage,
  stages,
  teams,
  isTeamsLoading,
  progress,
  encountersHref,
  onChanged,
  onRequestDeleteItem,
  onRequestRemoveInput
}: Readonly<StageItemsSectionProps>) {
  const [draftName, setDraftName] = useState("");
  const [draftType, setDraftType] = useState<StageItemType>(getDefaultStageItemType(stage.stage_type));
  const [teamDrafts, setTeamDrafts] = useState<Record<number, string>>({});
  const [editingItemTypeId, setEditingItemTypeId] = useState<number | null>(null);
  const [editingInputId, setEditingInputId] = useState<number | null>(null);
  const [editingInputTeamDraft, setEditingInputTeamDraft] = useState("");
  const [activeDragInput, setActiveDragInput] = useState<StageItemInput | null>(null);
  const sensors = useDragSensors({ keyboard: true });

  const teamById = new Map(teams.map((team) => [team.id, team]));
  const assignedTeamIds = getAssignedTeamIds(stage);
  const nextItemName = draftType === "group" ? `Group ${stage.items.length + 1}` : "Bracket";

  const createItemMutation = useMutation({
    mutationFn: () =>
      adminService.createStageItem(stage.id, {
        name: draftName.trim() || nextItemName,
        type: draftType,
        order: stage.items.length
      }),
    onSuccess: () => {
      setDraftName("");
      onChanged();
    }
  });

  const updateItemTypeMutation = useMutation({
    mutationFn: ({ stageItemId, type }: { stageItemId: number; type: StageItemType }) =>
      adminService.updateStageItem(stageItemId, { type }),
    onSuccess: () => {
      setEditingItemTypeId(null);
      onChanged();
    }
  });

  const updateItemNameMutation = useMutation({
    mutationFn: ({ stageItemId, name }: { stageItemId: number; name: string }) =>
      adminService.updateStageItem(stageItemId, { name }),
    onSuccess: () => onChanged(),
    onError: (error) => notify.apiError(error, { title: "Could not rename this structure item" })
  });

  const updateInputMutation = useMutation({
    mutationFn: ({ inputId, teamId }: { inputId: number; teamId: number }) =>
      adminService.updateStageItemInput(inputId, { team_id: teamId, input_type: "final" }),
    onSuccess: () => {
      setEditingInputId(null);
      setEditingInputTeamDraft("");
      onChanged();
    }
  });

  const createInputMutation = useMutation({
    mutationFn: ({
      stageItemId,
      slot,
      teamId
    }: {
      stageItemId: number;
      slot: number;
      teamId: number;
    }) =>
      adminService.createStageItemInput(stageItemId, {
        slot,
        input_type: "final",
        team_id: teamId
      }),
    onSuccess: (_input, variables) => {
      setTeamDrafts((current) => {
        const next = { ...current };
        delete next[variables.stageItemId];
        return next;
      });
      onChanged();
    }
  });

  const swapSeedMutation = useMutation({
    mutationFn: async ({ source, target }: { source: StageItemInput; target: StageItemInput }) => {
      for (const request of seedSwapRequests(source, target)) {
        await adminService.updateStageItemInput(request.inputId, request.data);
      }
    },
    onSuccess: () => onChanged(),
    onError: (error) => notify.apiError(error, { title: "Could not move this team" })
  });

  const isDragDisabled =
    editingInputId !== null || swapSeedMutation.isPending || updateInputMutation.isPending;
  const hasSeededSlot = stage.items.some((item) =>
    item.inputs.some((input) => input.team_id != null)
  );

  const handleDragStart = (event: DragStartEvent) => {
    setActiveDragInput((event.active.data.current?.input as StageItemInput | undefined) ?? null);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveDragInput(null);
    const source = event.active.data.current?.input as StageItemInput | undefined;
    const target = event.over?.data.current?.input as StageItemInput | undefined;
    if (!source || !target || source.id === target.id || source.team_id == null) return;
    swapSeedMutation.mutate({ source, target });
  };

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Groups, bracket lanes and the teams in their slots.
        </p>
        <Button asChild variant="outline" size="sm">
          <Link href={encountersHref}>
            Edit matches in Matches › Encounters
            <ArrowUpRight className="size-4" aria-hidden />
          </Link>
        </Button>
      </div>

      {progress && progress.items.length > 1 ? (
        <ul className="flex flex-wrap gap-1.5">
          {progress.items.map((itemProgress) => (
            <li key={itemProgress.stage_item_id}>
              <Badge
                tone={itemProgress.is_completed ? "success" : "neutral"}
                className="tabular-nums"
              >
                {itemProgress.name}: {itemProgress.completed}/{itemProgress.total}
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}

      {stage.items.length > 0 ? (
        <DndContext
          sensors={sensors}
          collisionDetection={pointerWithin}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
          onDragCancel={() => setActiveDragInput(null)}
        >
          {hasSeededSlot ? (
            <p className="text-xs text-muted-foreground">
              Drag a slot&apos;s handle onto another slot to swap teams.
            </p>
          ) : null}

          <div className="grid gap-3 2xl:grid-cols-2">
            {stage.items.map((item) => (
              <div
                key={item.id}
                className="flex flex-col gap-3 rounded-lg border border-border bg-card p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <InlineEditText
                      value={item.name}
                      label="structure item name"
                      textClassName="text-sm font-medium"
                      onSave={(name) =>
                        updateItemNameMutation.mutateAsync({ stageItemId: item.id, name })
                      }
                    />
                    <p className="text-xs tabular-nums text-muted-foreground">
                      {item.inputs.length} slot(s)
                    </p>
                  </div>

                  {editingItemTypeId === item.id ? (
                    <div className="flex shrink-0 items-center gap-1">
                      <Select
                        defaultValue={item.type}
                        onValueChange={(value) =>
                          updateItemTypeMutation.mutate({
                            stageItemId: item.id,
                            type: value as StageItemType
                          })
                        }
                      >
                        <SelectTrigger
                          aria-label={`Structure type for ${item.name}`}
                          className="h-8 w-36 text-xs"
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {Object.entries(STAGE_ITEM_TYPE_LABELS).map(([value, label]) => (
                            <SelectItem key={value} value={value} className="text-xs">
                              {label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="size-8"
                        aria-label="Cancel item type edit"
                        onClick={() => setEditingItemTypeId(null)}
                      >
                        <X className="size-4" aria-hidden />
                      </Button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      className="flex shrink-0 items-center gap-1 rounded-md border border-transparent px-1.5 py-0.5 text-xs font-medium text-muted-foreground transition-colors hover:border-border hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      onClick={() => setEditingItemTypeId(item.id)}
                      aria-label={`Change structure type of ${item.name}`}
                    >
                      {STAGE_ITEM_TYPE_LABELS[item.type]}
                      <Pencil className="size-3.5" aria-hidden />
                    </button>
                  )}

                  <Button
                    size="icon"
                    variant="ghost"
                    className="size-8 shrink-0 text-danger hover:text-danger"
                    aria-label={`Delete ${item.name}`}
                    onClick={() => onRequestDeleteItem(item)}
                  >
                    <Trash2 className="size-4" aria-hidden />
                  </Button>
                </div>

                {item.inputs.length > 0 ? (
                  <ul className="flex flex-col gap-1">
                    {[...item.inputs]
                      .sort((left, right) => left.slot - right.slot)
                      .map((input) => {
                        const label = getInputDisplayLabel(input, stages, teamById);
                        const isEditing = editingInputId === input.id;
                        const canSwapAssignedTeams = input.team_id != null;

                        return (
                          <SeedSlotRow
                            key={input.id}
                            input={input}
                            dragLabel={label}
                            dragDisabled={isDragDisabled}
                          >
                            <span className="min-w-0 flex-1 truncate">
                              #{input.slot} {label}
                            </span>

                            {isEditing ? (
                              <>
                                <Select
                                  value={editingInputTeamDraft}
                                  onValueChange={setEditingInputTeamDraft}
                                >
                                  <SelectTrigger
                                    aria-label={`Team for slot ${input.slot} of ${item.name}`}
                                    className="h-7 w-40 text-xs"
                                  >
                                    <SelectValue placeholder="Pick team" />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {teams.map((team) => (
                                      <SelectItem
                                        key={team.id}
                                        value={team.id.toString()}
                                        disabled={
                                          assignedTeamIds.has(team.id) &&
                                          team.id !== input.team_id &&
                                          !canSwapAssignedTeams
                                        }
                                        className="text-xs"
                                      >
                                        {team.name}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  className="size-8 shrink-0"
                                  aria-label="Save team assignment"
                                  disabled={
                                    !editingInputTeamDraft ||
                                    (updateInputMutation.isPending &&
                                      updateInputMutation.variables?.inputId === input.id)
                                  }
                                  onClick={() =>
                                    updateInputMutation.mutate({
                                      inputId: input.id,
                                      teamId: Number(editingInputTeamDraft)
                                    })
                                  }
                                >
                                  {updateInputMutation.isPending &&
                                  updateInputMutation.variables?.inputId === input.id ? (
                                    <Spinner className="size-3" />
                                  ) : (
                                    <CheckCircle2 className="size-3" aria-hidden />
                                  )}
                                </Button>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  className="size-8 shrink-0"
                                  aria-label="Cancel team assignment edit"
                                  onClick={() => {
                                    setEditingInputId(null);
                                    setEditingInputTeamDraft("");
                                  }}
                                >
                                  <X className="size-4" aria-hidden />
                                </Button>
                              </>
                            ) : (
                              <>
                                <Badge
                                  tone={input.input_type === "tentative" ? "warning" : "neutral"}
                                  className="shrink-0 text-xs"
                                >
                                  {input.input_type}
                                </Badge>
                                {input.input_type !== "empty" ? (
                                  <>
                                    <button
                                      type="button"
                                      className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                      aria-label={
                                        input.input_type === "tentative"
                                          ? `Override team in slot ${input.slot} of ${item.name}`
                                          : `Change team in slot ${input.slot} of ${item.name}`
                                      }
                                      onClick={() => {
                                        setEditingInputId(input.id);
                                        setEditingInputTeamDraft(input.team_id?.toString() ?? "");
                                      }}
                                    >
                                      <Pencil className="size-3.5" aria-hidden />
                                    </button>
                                    <Button
                                      size="icon"
                                      variant="ghost"
                                      className="size-8 shrink-0 text-danger hover:text-danger"
                                      aria-label={`Remove slot ${input.slot} of ${item.name}`}
                                      onClick={() =>
                                        onRequestRemoveInput(input, `${label} (#${input.slot})`)
                                      }
                                    >
                                      <Trash2 className="size-3.5" aria-hidden />
                                    </Button>
                                  </>
                                ) : null}
                              </>
                            )}
                          </SeedSlotRow>
                        );
                      })}
                  </ul>
                ) : (
                  <EmptyNote size="sm">
                    No teams assigned yet. Pick a team below to fill the first slot.
                  </EmptyNote>
                )}

                <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                  <Select
                    value={teamDrafts[item.id]}
                    onValueChange={(value) =>
                      setTeamDrafts((current) => ({ ...current, [item.id]: value }))
                    }
                    disabled={isTeamsLoading || teams.length === 0}
                  >
                    <SelectTrigger aria-label={`Team to add to ${item.name}`} className="h-9">
                      <SelectValue placeholder={isTeamsLoading ? "Loading teams…" : "Select team"} />
                    </SelectTrigger>
                    <SelectContent>
                      {teams.map((team) => (
                        <SelectItem
                          key={team.id}
                          value={team.id.toString()}
                          disabled={assignedTeamIds.has(team.id)}
                        >
                          {team.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={
                      createInputMutation.isPending ||
                      !teamDrafts[item.id] ||
                      assignedTeamIds.has(Number(teamDrafts[item.id]))
                    }
                    onClick={() =>
                      createInputMutation.mutate({
                        stageItemId: item.id,
                        slot: item.inputs.reduce((max, input) => Math.max(max, input.slot), 0) + 1,
                        teamId: Number(teamDrafts[item.id])
                      })
                    }
                  >
                    {createInputMutation.isPending &&
                    createInputMutation.variables?.stageItemId === item.id ? (
                      <Spinner />
                    ) : (
                      <Plus className="size-4" aria-hidden />
                    )}
                    Add team
                  </Button>
                </div>
              </div>
            ))}
          </div>

          <DragOverlay>
            {activeDragInput ? (
              <span className="rounded-md border border-border bg-card px-2.5 py-1.5 text-xs shadow-lg">
                {getInputDisplayLabel(activeDragInput, stages, teamById)}
              </span>
            ) : null}
          </DragOverlay>
        </DndContext>
      ) : (
        <EmptyNote>
          This stage has no structure items yet. Add a group or bracket lane below.
        </EmptyNote>
      )}

      <div className="grid gap-2 border-t border-border pt-3 lg:grid-cols-[minmax(0,1fr)_200px_auto] lg:items-end">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="stage-item-name" className="text-xs">
            Structure item name
          </Label>
          <Input
            id="stage-item-name"
            className="h-9"
            placeholder={nextItemName}
            value={draftName}
            onChange={(event) => setDraftName(event.target.value)}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="stage-item-type" className="text-xs">
            Type
          </Label>
          <Select value={draftType} onValueChange={(value) => setDraftType(value as StageItemType)}>
            <SelectTrigger id="stage-item-type" className="h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(STAGE_ITEM_TYPE_LABELS).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Button
          size="sm"
          variant="secondary"
          disabled={createItemMutation.isPending}
          onClick={() => createItemMutation.mutate()}
        >
          {createItemMutation.isPending ? (
            <Spinner />
          ) : (
            <Plus className="size-4" aria-hidden />
          )}
          {createItemMutation.isPending ? "Adding…" : "Add structure"}
        </Button>
      </div>
    </section>
  );
}
