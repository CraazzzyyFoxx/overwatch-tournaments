"use client";

import { useId, useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import {
  closestCenter,
  DndContext,
  DragOverlay,
  useDroppable,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ArrowUpRight, CheckCircle2, GripVertical, Pencil, Plus, Trash2, X } from "lucide-react";

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

/** One item's inputs in seed order. */
function seedOrder(item: StageItem): StageItemInput[] {
  return [...item.inputs].sort((left, right) => left.slot - right.slot);
}

/** Every item's inputs in seed order, keyed by item id: what a drag rearranges. */
type SeedLists = Record<number, StageItemInput[]>;

function listOf(lists: SeedLists, inputId: number): number | undefined {
  const entry = Object.entries(lists).find(([, inputs]) =>
    inputs.some((input) => input.id === inputId)
  );
  return entry ? Number(entry[0]) : undefined;
}

/**
 * One team slot: a sortable row that shifts aside as a team is dragged past it,
 * and a drag source once it holds a team. The grip is the only handle, so the
 * row's buttons stay clickable.
 */
function SeedSlotRow({
  input,
  label,
  dragDisabled,
  children
}: Readonly<{
  input: StageItemInput;
  label: string;
  dragDisabled: boolean;
  children: ReactNode;
}>) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
    index,
    activeIndex,
    overIndex
  } = useSortable({
    id: `input-${input.id}`,
    data: { input },
    disabled: { draggable: dragDisabled || input.team_id == null, droppable: false }
  });
  // The seed the row will hold if the drag drops now: the position it is drawn
  // at, which `arrayMove(activeIndex → overIndex)` is about to make real.
  const position =
    activeIndex < 0 || overIndex < 0
      ? index
      : index === activeIndex
        ? overIndex
        : activeIndex < index && index <= overIndex
          ? index - 1
          : overIndex <= index && index < activeIndex
            ? index + 1
            : index;

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(
        "flex items-center gap-2 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs",
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
          aria-label={`Drag ${label} to another slot`}
          className="shrink-0 cursor-grab rounded p-1 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 active:cursor-grabbing"
        >
          <GripVertical className="size-3.5" aria-hidden />
        </button>
      ) : null}
      <span className="min-w-0 flex-1 truncate">
        #{position + 1} {label}
      </span>
      {children}
    </li>
  );
}

/**
 * One item's slot list. While it holds no slots the list itself is the drop
 * target, so a team can be dragged into an empty group; after that its rows are.
 */
function SeedList({
  itemId,
  inputs,
  children
}: Readonly<{ itemId: number; inputs: StageItemInput[]; children: ReactNode }>) {
  const { setNodeRef, isOver } = useDroppable({
    id: `item-${itemId}`,
    data: { itemId },
    disabled: inputs.length > 0
  });

  return (
    <SortableContext
      items={inputs.map((input) => `input-${input.id}`)}
      strategy={verticalListSortingStrategy}
    >
      <div ref={setNodeRef} className={cn("rounded-md", isOver && "ring-2 ring-ring")}>
        {children}
      </div>
    </SortableContext>
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
  const [draftType, setDraftType] = useState<StageItemType>(
    getDefaultStageItemType(stage.stage_type)
  );
  const [teamDrafts, setTeamDrafts] = useState<Record<number, string>>({});
  const [editingItemTypeId, setEditingItemTypeId] = useState<number | null>(null);
  const [editingInputId, setEditingInputId] = useState<number | null>(null);
  const [editingInputTeamDraft, setEditingInputTeamDraft] = useState("");
  const [activeDragInput, setActiveDragInput] = useState<StageItemInput | null>(null);
  // The order a drag is showing, and the `stage.items` it was laid out from: the
  // refetch after a move hands down a new array, and the server's order takes over.
  const [dragLists, setDragLists] = useState<{ base: StageItem[]; lists: SeedLists } | null>(null);
  const sensors = useDragSensors({ keyboard: true });
  // Without it dnd-kit numbers the grips' `aria-describedby` from a module
  // counter the server and client disagree on (as in `SortableRows`).
  const dndId = useId();
  const listFor = (item: StageItem) =>
    (dragLists?.base === stage.items ? dragLists.lists[item.id] : undefined) ?? seedOrder(item);

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

  const moveSeedMutation = useMutation({
    mutationFn: ({
      inputId,
      stageItemId,
      slot
    }: {
      inputId: number;
      stageItemId: number;
      slot: number;
    }) => adminService.updateStageItemInput(inputId, { stage_item_id: stageItemId, slot }),
    onSuccess: () => onChanged(),
    onError: (error) => {
      setDragLists(null);
      notify.apiError(error, { title: "Could not move this team" });
    }
  });

  const isDragDisabled =
    editingInputId !== null || moveSeedMutation.isPending || updateInputMutation.isPending;
  const hasSeededSlot = stage.items.some((item) =>
    item.inputs.some((input) => input.team_id != null)
  );

  const cancelDrag = () => {
    setActiveDragInput(null);
    setDragLists(null);
  };

  const handleDragStart = (event: DragStartEvent) => {
    setActiveDragInput((event.active.data.current?.input as StageItemInput | undefined) ?? null);
    setDragLists({
      base: stage.items,
      lists: Object.fromEntries(stage.items.map((item) => [item.id, seedOrder(item)]))
    });
  };

  // Across lists the row has to change hands mid-drag, or the target list never
  // opens a gap for it; within one list `SortableContext` shifts the rows itself.
  const handleDragOver = ({ active, over }: DragOverEvent) => {
    const moving = active.data.current?.input as StageItemInput | undefined;
    if (!moving || !over) return;
    const overInput = over.data.current?.input as StageItemInput | undefined;
    const overItemId = over.data.current?.itemId as number | undefined;
    const translated = active.rect.current.translated;
    const below = translated != null && translated.top > over.rect.top + over.rect.height / 2;
    setDragLists((current) => {
      if (!current) return current;
      const from = listOf(current.lists, moving.id);
      const to = overInput ? listOf(current.lists, overInput.id) : overItemId;
      if (from === undefined || to === undefined || from === to) return current;
      const target = current.lists[to];
      const at = overInput
        ? target.findIndex((input) => input.id === overInput.id) + (below ? 1 : 0)
        : target.length;
      return {
        ...current,
        lists: {
          ...current.lists,
          [from]: current.lists[from].filter((input) => input.id !== moving.id),
          [to]: [...target.slice(0, at), moving, ...target.slice(at)]
        }
      };
    });
  };

  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    const moving = active.data.current?.input as StageItemInput | undefined;
    const itemId = moving && dragLists ? listOf(dragLists.lists, moving.id) : undefined;
    if (!moving || !over || !dragLists || itemId === undefined) return cancelDrag();
    setActiveDragInput(null);

    const list = dragLists.lists[itemId];
    const from = list.findIndex((input) => input.id === moving.id);
    const overInput = over.data.current?.input as StageItemInput | undefined;
    const overIndex = overInput ? list.findIndex((input) => input.id === overInput.id) : -1;
    const to = overIndex >= 0 ? overIndex : from;
    const home = stage.items.find((item) => item.id === moving.stage_item_id);
    const homeIndex = home ? seedOrder(home).findIndex((input) => input.id === moving.id) : -1;
    if (itemId === moving.stage_item_id && to === homeIndex) return cancelDrag();

    setDragLists({
      ...dragLists,
      lists: { ...dragLists.lists, [itemId]: arrayMove(list, from, to) }
    });
    moveSeedMutation.mutate({ inputId: moving.id, stageItemId: itemId, slot: to + 1 });
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
          id={dndId}
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={handleDragStart}
          onDragOver={handleDragOver}
          onDragEnd={handleDragEnd}
          onDragCancel={cancelDrag}
        >
          {hasSeededSlot ? (
            <p className="text-xs text-muted-foreground">
              Drag a team by its handle to re-seed it in its group or move it to another one.
            </p>
          ) : null}

          <div className="grid gap-3 2xl:grid-cols-2">
            {stage.items.map((item) => {
              const inputs = listFor(item);
              return (
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
                        {inputs.length} slot(s)
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

                  <SeedList itemId={item.id} inputs={inputs}>
                    {inputs.length > 0 ? (
                      <ul className="flex flex-col gap-1">
                        {inputs.map((input, index) => {
                          // The position, not the stored slot: it is what the team is
                          // seeded as, gaps an older delete left included.
                          const seed = index + 1;
                          const label = getInputDisplayLabel(input, stages, teamById);
                          const isEditing = editingInputId === input.id;
                          const canSwapAssignedTeams = input.team_id != null;

                          return (
                            <SeedSlotRow
                              key={input.id}
                              input={input}
                              label={label}
                              dragDisabled={isDragDisabled}
                            >
                              {isEditing ? (
                                <>
                                  <Select
                                    value={editingInputTeamDraft}
                                    onValueChange={setEditingInputTeamDraft}
                                  >
                                    <SelectTrigger
                                      aria-label={`Team for slot ${seed} of ${item.name}`}
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
                                            ? `Override team in slot ${seed} of ${item.name}`
                                            : `Change team in slot ${seed} of ${item.name}`
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
                                        aria-label={`Remove slot ${seed} of ${item.name}`}
                                        onClick={() =>
                                          onRequestRemoveInput(input, `${label} (#${seed})`)
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
                  </SeedList>

                  <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                    <Select
                      value={teamDrafts[item.id]}
                      onValueChange={(value) =>
                        setTeamDrafts((current) => ({ ...current, [item.id]: value }))
                      }
                      disabled={isTeamsLoading || teams.length === 0}
                    >
                      <SelectTrigger aria-label={`Team to add to ${item.name}`} className="h-9">
                        <SelectValue
                          placeholder={isTeamsLoading ? "Loading teams…" : "Select team"}
                        />
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
                          slot:
                            item.inputs.reduce((max, input) => Math.max(max, input.slot), 0) + 1,
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
              );
            })}
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
