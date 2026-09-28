"use client";

import { useState } from "react";
import { GripVertical, Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { StatusDot } from "@/components/ui/status-dot";
import { EYEBROW_CLASS } from "@/components/kit/tone";

import { LEAF_COLOR, type RulePaletteGroup, type RulePaletteItem } from "./rule-tree";
import type { RuleBuilderLabels } from "./RuleNodes";

/** The drag payload a palette row writes and the canvas reads back. */
export const RULE_NODE_MIME = "application/rule-node";

/**
 * Node palette. Dragging onto the canvas is the mouse affordance; every row is
 * also a real button, because a drag gesture is the one interaction a keyboard
 * cannot perform. Clicking appends to the top-level group — the same place a
 * drop lands — after which the node's own buttons move it around.
 */
export function RulePalette({
  groups,
  labels,
  onAdd,
}: Readonly<{
  groups: RulePaletteGroup[];
  labels: RuleBuilderLabels;
  onAdd: (item: RulePaletteItem) => void;
}>) {
  const [search, setSearch] = useState("");
  const lc = search.toLowerCase();

  const filtered = groups
    .map((g) => ({ ...g, items: g.items.filter((i) => i.label.toLowerCase().includes(lc)) }))
    .filter((g) => g.items.length > 0);

  return (
    <div className="w-44 h-full overflow-y-auto bg-card/95 backdrop-blur border-r p-2 space-y-2 text-xs">
      <div className="relative">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" aria-hidden />
        <Input
          className="h-7 pl-7 text-xs"
          placeholder={labels.paletteSearchPlaceholder}
          aria-label={labels.paletteSearchLabel}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <p className="text-xs text-muted-foreground">{labels.paletteHint}</p>
      {filtered.length === 0 ? (
        <p className="text-xs text-muted-foreground">{labels.paletteEmpty(search)}</p>
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
                onDragStart={(e) => {
                  e.dataTransfer.setData(RULE_NODE_MIME, JSON.stringify(item));
                  e.dataTransfer.effectAllowed = "move";
                }}
                onClick={() => onAdd(item)}
                title={item.description}
                aria-label={labels.paletteAdd(item.label)}
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
