"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useDroppable } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { StageItem, StageItemInput } from "@/types/tournament.types";
import type { InputDisplayLabelInfo } from "@/lib/bracket/projection";

/** What a seed slot shows: the team, or nothing yet. */
export function inputLabel(
  info: InputDisplayLabelInfo,
  t: ReturnType<typeof useTranslations<"adminBracket">>
): string {
  if (info.key === "team") return info.label;
  return t("labels.emptySlot");
}

/** One item's inputs in seed order. */
export function seedOrder(item: StageItem): StageItemInput[] {
  return [...item.inputs].sort((left, right) => left.slot - right.slot);
}

/** Every item's inputs in seed order, keyed by item id: what a drag rearranges. */
export type SeedLists = Record<number, StageItemInput[]>;

export function listOf(lists: SeedLists, inputId: number): number | undefined {
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
export function SeedSlotRow({
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
  const t = useTranslations("adminBracket.items");
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
        "flex items-center gap-2 bg-card py-1.5 text-xs",
        isDragging && "opacity-50"
      )}
    >
      {input.team_id != null ? (
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          ref={setActivatorNodeRef}
          {...attributes}
          {...listeners}
          disabled={dragDisabled}
          aria-label={t("drag", { label })}
          className="shrink-0 cursor-grab text-muted-foreground hover:text-foreground active:cursor-grabbing"
        >
          <GripVertical aria-hidden />
        </Button>
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
export function SeedList({
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
