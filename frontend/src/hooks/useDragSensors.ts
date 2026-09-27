"use client";

import { KeyboardSensor, PointerSensor, useSensor, useSensors } from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";

/**
 * The house dnd-kit sensor set, in one place.
 *
 * The pointer threshold is why this exists: with no activation constraint a
 * plain click on a draggable row (opening a sheet, toggling a role, pressing a
 * button inside it) reads as a zero-distance drag and dnd-kit swallows the
 * event. Six pixels is the default -- far enough that a click stays a click,
 * short enough that a drag still feels immediate.
 */
export function useDragSensors({
  /** Pixels of intent before a drag starts. `0` picks the item up on pointerdown with no threshold -- only for rows that carry no controls of their own. */
  distance = 6,
  /** Adds the keyboard sensor. Only for lists inside a `SortableContext`: it seats by `sortableKeyboardCoordinates`. */
  keyboard = false
}: Readonly<{ distance?: number; keyboard?: boolean }> = {}) {
  const pointer = useSensor(
    PointerSensor,
    distance > 0 ? { activationConstraint: { distance } } : undefined
  );
  const keys = useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates });
  return useSensors(pointer, keyboard ? keys : null);
}
