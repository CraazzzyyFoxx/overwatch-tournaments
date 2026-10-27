"use client";

import { useId, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import Link from "next/link";
import {
  closestCenter,
  DndContext,
  DragOverlay,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent
} from "@dnd-kit/core";
import { arrayMove } from "@dnd-kit/sortable";
import { ArrowUpRight, CheckCircle2, Pencil, Plus, Trash2, X } from "lucide-react";

import { TeamCombobox } from "@/components/admin/TeamCombobox";
import { InlineEditText } from "@/components/kit/InlineEditText";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { notify } from "@/lib/notify";
import { useDragSensors } from "@/hooks/useDragSensors";
import adminService from "@/services/admin.service";
import type { Stage, StageItem, StageItemInput, StageItemType } from "@/types/tournament.types";
import type { Team } from "@/types/team.types";

import {
  getAssignedTeamIds,
  getInputDisplayLabelInfo,
  STAGE_ITEM_TYPE_LABELS,
  type StageProgress
} from "@/lib/bracket/projection";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { Spinner } from "@/components/ui/spinner";
import { Skeleton } from "@/components/ui/skeleton";

import { AddStageItemForm } from "./stage-items/AddStageItemForm";
import { inputLabel, listOf, seedOrder, SeedList, SeedSlotRow, type SeedLists } from "./stage-items/SeedSlots";

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
  const t = useTranslations("adminBracket.items");
  const tRoot = useTranslations("adminBracket");
  const [teamDrafts, setTeamDrafts] = useState<Record<number, string>>({});
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

  const updateItemTypeMutation = useMutation({
    mutationFn: ({ stageItemId, type }: { stageItemId: number; type: StageItemType }) =>
      adminService.updateStageItem(stageItemId, { type }),
    onSuccess: () => onChanged()
  });

  const updateItemNameMutation = useMutation({
    mutationFn: ({ stageItemId, name }: { stageItemId: number; name: string }) =>
      adminService.updateStageItem(stageItemId, { name }),
    onSuccess: () => onChanged(),
    onError: (error) => notify.apiError(error, { title: t("renameError") })
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
      notify.apiError(error, { title: t("moveError") });
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
      <div className="flex justify-end">
        <Button asChild variant="outline" size="sm">
          <Link href={encountersHref}>
            {t("encounters")}
            <ArrowUpRight className="size-4" aria-hidden />
          </Link>
        </Button>
      </div>

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
              {t("dragHelp")}
            </p>
          ) : null}

          <div className="grid gap-3 2xl:grid-cols-2">
            {stage.items.map((item) => {
              const inputs = listFor(item);
              const itemProgress = progress?.items.find(
                (entry) => entry.stage_item_id === item.id
              );
              return (
                <Card key={item.id} className="flex flex-col gap-3 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <InlineEditText
                        value={item.name}
                        label={t("itemName")}
                        textClassName="text-sm font-medium"
                        onSave={(name) =>
                          updateItemNameMutation.mutateAsync({ stageItemId: item.id, name })
                        }
                      />
                      <p className="flex flex-wrap gap-x-1.5 text-xs tabular-nums text-muted-foreground">
                        <span>{t("slotCount", { count: inputs.length })}</span>
                        {itemProgress && itemProgress.total > 0 ? (
                          <>
                            <span aria-hidden>·</span>
                            <span>
                              {tRoot("extra.matchesSummary", {
                                completed: itemProgress.completed,
                                total: itemProgress.total
                              })}
                            </span>
                          </>
                        ) : null}
                      </p>
                    </div>

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
                        aria-label={t("type", { name: item.name })}
                        size="sm"
                        className="ms-auto w-40 shrink-0"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {Object.keys(STAGE_ITEM_TYPE_LABELS).map((value) => (
                          <SelectItem key={value} value={value}>
                            {tRoot(`labels.itemTypes.${value}` as never)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>

                    <Button
                      size="icon"
                      variant="ghost"
                      className="size-8 shrink-0 text-danger hover:text-danger"
                      aria-label={t("delete", { name: item.name })}
                      title={t("delete", { name: item.name })}
                      onClick={() => onRequestDeleteItem(item)}
                    >
                      <Trash2 className="size-4" aria-hidden />
                    </Button>
                  </div>

                  <SeedList itemId={item.id} inputs={inputs}>
                    {inputs.length > 0 ? (
                      <ul className="flex flex-col divide-y divide-border">
                        {inputs.map((input, index) => {
                          // The position, not the stored slot: it is what the team is
                          // seeded as, gaps an older delete left included.
                          const seed = index + 1;
                          const label = inputLabel(
                            getInputDisplayLabelInfo(input, stages, teamById),
                            tRoot
                          );
                          const isEditing = editingInputId === input.id;
                          const canSwapAssignedTeams = input.team_id != null;
                          const changeTeamLabel = t(
                            input.input_type === "tentative" ? "overrideTeam" : "changeTeam",
                            { seed, name: item.name }
                          );

                          return (
                            <SeedSlotRow
                              key={input.id}
                              input={input}
                              label={label}
                              dragDisabled={isDragDisabled}
                            >
                              {isEditing ? (
                                <>
                                  <TeamCombobox
                                    teams={teams}
                                    value={
                                      editingInputTeamDraft ? Number(editingInputTeamDraft) : null
                                    }
                                    onSelect={(team) =>
                                      setEditingInputTeamDraft(team ? String(team.id) : "")
                                    }
                                    placeholder={t("pickTeam")}
                                    allowClear={false}
                                    isTeamDisabled={(team) =>
                                      assignedTeamIds.has(team.id) &&
                                      team.id !== input.team_id &&
                                      !canSwapAssignedTeams
                                    }
                                    triggerAriaLabel={t("teamForSlot", { seed, name: item.name })}
                                    size="sm"
                                    triggerClassName="h-7 w-48"
                                  />
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="size-8 shrink-0"
                                    aria-label={t("saveTeam")}
                                    title={t("saveTeam")}
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
                                    aria-label={t("cancelTeam")}
                                    title={t("cancelTeam")}
                                    onClick={() => {
                                      setEditingInputId(null);
                                      setEditingInputTeamDraft("");
                                    }}
                                  >
                                    <X className="size-4" aria-hidden />
                                  </Button>
                                </>
                              ) : input.input_type !== "empty" ? (
                                <>
                                  {input.input_type === "tentative" ? (
                                    <span className="shrink-0 text-muted-foreground">
                                      {t("tentative")}
                                    </span>
                                  ) : null}
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="size-8 shrink-0"
                                    aria-label={changeTeamLabel}
                                    title={changeTeamLabel}
                                    onClick={() => {
                                      setEditingInputId(input.id);
                                      setEditingInputTeamDraft(input.team_id?.toString() ?? "");
                                    }}
                                  >
                                    <Pencil className="size-3.5" aria-hidden />
                                  </Button>
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="size-8 shrink-0 text-danger hover:text-danger"
                                    aria-label={t("removeSlot", { seed, name: item.name })}
                                    title={t("removeSlot", { seed, name: item.name })}
                                    onClick={() =>
                                      onRequestRemoveInput(input, `${label} (#${seed})`)
                                    }
                                  >
                                    <Trash2 className="size-3.5" aria-hidden />
                                  </Button>
                                </>
                              ) : null}
                            </SeedSlotRow>
                          );
                        })}
                      </ul>
                    ) : (
                      <EmptyNote size="sm">
                        {t("empty")}
                      </EmptyNote>
                    )}
                  </SeedList>

                  <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                    {isTeamsLoading ? (
                      <div role="status">
                        <span className="sr-only">{t("loadingTeams")}</span>
                        <Skeleton aria-hidden className="h-9 w-full" />
                      </div>
                    ) : (
                      <TeamCombobox
                        teams={teams}
                        value={teamDrafts[item.id] ? Number(teamDrafts[item.id]) : null}
                        onSelect={(team) =>
                          setTeamDrafts((current) => ({
                            ...current,
                            [item.id]: team ? String(team.id) : ""
                          }))
                        }
                        placeholder={t("selectTeam")}
                        allowClear={false}
                        disabled={teams.length === 0}
                        isTeamDisabled={(team) => assignedTeamIds.has(team.id)}
                        triggerAriaLabel={t("teamToAdd", { name: item.name })}
                      />
                    )}
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
                      {t("addTeam")}
                    </Button>
                  </div>
                </Card>
              );
            })}
          </div>

          <DragOverlay>
            {activeDragInput ? (
              <span className="rounded-md border border-border bg-card px-2.5 py-1.5 text-xs">
                {inputLabel(getInputDisplayLabelInfo(activeDragInput, stages, teamById), tRoot)}
              </span>
            ) : null}
          </DragOverlay>
        </DndContext>
      ) : (
        <EmptyNote>
          {t("noItems")}
        </EmptyNote>
      )}

      <AddStageItemForm stage={stage} onChanged={onChanged} />
    </section>
  );
}
