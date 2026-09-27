"use client";

import { useState } from "react";
import { GripVertical, Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { StatusDot } from "@/components/ui/status-dot";
import { EYEBROW_CLASS } from "@/components/kit/tone";

import { LEAF_COLOR, SIDEBAR_GROUPS, type SidebarItem } from "./condition-flow.model";

/**
 * Node palette. Dragging onto the canvas is the mouse affordance; every row is
 * also a real button, because a drag gesture is the one interaction a keyboard
 * cannot perform. Clicking appends to the top-level group — the same place a
 * drop lands — after which the node's own buttons move it around.
 */
export function ConditionPalette({ onAdd }: Readonly<{ onAdd: (item: SidebarItem) => void }>) {
  const [search, setSearch] = useState("");
  const lc = search.toLowerCase();

  const filtered = SIDEBAR_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((i) => i.label.toLowerCase().includes(lc)),
  })).filter((g) => g.items.length > 0);

  const onDragStart = (e: React.DragEvent, item: SidebarItem) => {
    e.dataTransfer.setData("application/condition-node", JSON.stringify(item));
    e.dataTransfer.effectAllowed = "move";
  };

  return (
    <div className="w-44 h-full overflow-y-auto bg-card/95 backdrop-blur border-r p-2 space-y-2 text-xs">
      <div className="relative">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" aria-hidden />
        <Input
          className="h-7 pl-7 text-xs"
          placeholder="Search nodes…"
          aria-label="Search condition nodes"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        Drag onto the canvas, or click to append to the top-level group.
      </p>
      {filtered.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No nodes match “{search}”. Try a shorter word such as “stat” or “div”.
        </p>
      ) : null}
      {filtered.map((group) => (
        <div key={group.label}>
          <p className={`${EYEBROW_CLASS} mb-1`}>{group.label}</p>
          <div className="space-y-0.5">
            {group.items.map((item) => (
              <button
                key={item.label}
                type="button"
                draggable
                onDragStart={(e) => onDragStart(e, item)}
                onClick={() => onAdd(item)}
                aria-label={`Add ${item.label} to the condition tree`}
                className="flex w-full items-center gap-1.5 px-2 py-1 rounded text-left cursor-grab hover:bg-accent/50 active:cursor-grabbing transition-colors"
              >
                <GripVertical className="h-3 w-3 text-muted-foreground" aria-hidden />
                <StatusDot className="size-2" style={{ color: item.color ?? LEAF_COLOR }} />
                <span className="truncate">{item.label}</span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
