"use client";

import { useId, type CSSProperties, type ReactNode } from "react";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DraggableAttributes,
} from "@dnd-kit/core";
import type { SyntheticListenerMap } from "@dnd-kit/core/dist/hooks/utilities";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Drag-to-reorder for a vertical list, in one place.
 *
 * The tournament player sheet grew this scaffold — sensors, `arrayMove`,
 * grip-handle wiring, the dragging elevation — for its role-priority list, and
 * the mix sheet needs the same interaction over a shorter array. Two copies of a
 * dnd-kit setup is two places for the activation distance, the keyboard sensor
 * and the lift shadow to drift apart, and the keyboard path is the one that
 * silently rots.
 *
 * The caller owns the data: nothing here holds a copy of the list, and reorder
 * is reported as a whole new array.
 *
 * Two ways in, because the two call sites lay a row out differently: the
 * `SortableRow` convenience (grip, then content) and the `useSortableRow` +
 * `SortableGrip` pair for a row that needs the grip somewhere specific — the
 * tournament sheet stacks it over a `#N` label in its own column.
 */

type SortableRowsProps<T> = {
  items: readonly T[];
  /** Stable per-item id. Index-based ids are fine for a fixed-length list. */
  getId: (item: T, index: number) => string;
  onReorder: (nextItems: T[]) => void;
  className?: string;
  children: (item: T, index: number) => ReactNode;
};

export function SortableRows<T>({
  items,
  getId,
  onReorder,
  className,
  children,
}: Readonly<SortableRowsProps<T>>) {
  // An explicit `id`: without one dnd-kit numbers its keyboard instructions
  // from a module counter that server and client disagree on, so every grip's
  // `aria-describedby` hydrates into a dangling reference.
  const dndId = useId();
  const sensors = useSensors(
    // 5px before a drag starts, so a click on a control inside a row is still a
    // click and not a one-pixel drag.
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const ids = items.map(getId);

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from === -1 || to === -1) return;

    onReorder(arrayMove([...items], from, to));
  };

  return (
    <DndContext
      id={dndId}
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        <div className={className}>{items.map((item, index) => children(item, index))}</div>
      </SortableContext>
    </DndContext>
  );
}

/**
 * The DOM props that turn an element into the drag affordance for a row —
 * dnd-kit's sortable attributes and pointer/keyboard listeners, merged.
 */
export type SortableHandleProps = DraggableAttributes &
  SyntheticListenerMap & { [key: string]: unknown };

export interface SortableRowHandle {
  /** Attach to the element that should move while dragging. */
  ref: (node: HTMLElement | null) => void;
  style: CSSProperties;
  handleProps: SortableHandleProps;
  isDragging: boolean;
}

/** What a row needs to be draggable, without dictating where its grip sits. */
export function useSortableRow(id: string, disabled = false): SortableRowHandle {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
    disabled,
  });

  const style: CSSProperties = {
    transform: CSS.Translate.toString(transform),
    transition,
    // Lifted out of flow while dragging so it renders over its siblings instead
    // of being clipped by the next row's background.
    zIndex: isDragging ? 50 : undefined,
    position: isDragging ? "relative" : undefined,
    boxShadow: isDragging ? "0 22px 56px rgba(0,0,0,0.34)" : undefined,
  };

  return {
    ref: setNodeRef,
    style,
    handleProps: { ...attributes, ...listeners } as SortableHandleProps,
    isDragging,
  };
}

type SortableGripProps = {
  handleProps: SortableHandleProps;
  /** Accessible name, e.g. "Reorder Tank for Aria#1111". */
  label: string;
  disabled?: boolean;
  className?: string;
};

/**
 * The drag affordance. Listeners live here rather than on the row, because rows
 * on both call sites contain switches, selects and buttons, and a whole-row drag
 * surface swallows their clicks.
 */
export function SortableGrip({
  handleProps,
  label,
  disabled = false,
  className,
}: Readonly<SortableGripProps>) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-label={label}
      className={cn(
        "flex size-6 shrink-0 cursor-grab touch-none items-center justify-center rounded-md",
        "border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] text-[color:var(--aqt-fg-dim)]",
        "hover:text-[color:var(--aqt-fg)] active:cursor-grabbing",
        "disabled:cursor-default disabled:opacity-40",
        className,
      )}
      {...handleProps}
    >
      <GripVertical className="size-3" aria-hidden="true" />
    </button>
  );
}

type SortableRowProps = {
  id: string;
  children: ReactNode;
  className?: string;
  handleLabel: string;
  disabled?: boolean;
};

/** Grip first, then the row's own content. */
export function SortableRow({
  id,
  children,
  className,
  handleLabel,
  disabled = false,
}: Readonly<SortableRowProps>) {
  const { ref, style, handleProps } = useSortableRow(id, disabled);

  return (
    <div ref={ref} style={style} className={className}>
      <SortableGrip handleProps={handleProps} label={handleLabel} disabled={disabled} />
      {children}
    </div>
  );
}
