"use client";

import type { ReactNode } from "react";
import {
  closestCenter,
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent
} from "@dnd-kit/core";
import { horizontalListSortingStrategy, SortableContext, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { AdminTableHead, type AdminTableHeadProps } from "@/components/data-table/AdminTableHead";
import { ADMIN_ACTION_COLUMN_ID } from "@/components/data-table/columns";
import { cn } from "@/components/data-table/host";

/**
 * Column drag-to-reorder, in its own chunk.
 *
 * `@dnd-kit` is a quarter of the admin table bundle and is used by exactly one
 * gesture, so `AdminDataTable` imports this module when a pointer first
 * reaches the table rather than statically. Until it resolves the header renders plain
 * `AdminTableHead` cells, which are the same markup minus the drag bindings.
 */
export function ColumnDndProvider({
  columnIds,
  onReorder,
  children
}: Readonly<{
  /** Draggable column ids, in render order. */
  columnIds: string[];
  onReorder: (activeId: string, overId: string) => void;
  children: ReactNode;
}>) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    onReorder(String(active.id), String(over.id));
  };

  return (
    // Mounted inside `<thead>`: its screen-reader live region cannot render
    // in place there, so it goes to <body>. This module only ever loads on the
    // client, after a pointer reached the table.
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
      accessibility={{ container: document.body }}
    >
      <SortableContext items={columnIds} strategy={horizontalListSortingStrategy}>
        {children}
      </SortableContext>
    </DndContext>
  );
}

/**
 * Header cell that can be dragged to reorder its column. Only dnd-kit's
 * pointer listeners are spread, not its `attributes`: those would put
 * `role="button"` on a `<th>`. The actions column keeps its place at the right
 * edge, so it is never draggable.
 */
export function SortableHead<TData>({
  header,
  className,
  style,
  ...rest
}: Readonly<AdminTableHeadProps<TData>>) {
  const { setNodeRef, listeners, transform, transition, isDragging } = useSortable({
    id: header.column.id,
    disabled: header.column.id === ADMIN_ACTION_COLUMN_ID
  });

  return (
    <AdminTableHead
      header={header}
      ref={setNodeRef}
      {...rest}
      {...listeners}
      className={cn(className, isDragging && "z-20 opacity-70")}
      style={{ ...style, transform: CSS.Translate.toString(transform), transition }}
    />
  );
}

/** What `AdminDataTable` holds once this chunk resolves. */
export type ColumnDndModule = {
  ColumnDndProvider: typeof ColumnDndProvider;
  SortableHead: typeof SortableHead;
};
