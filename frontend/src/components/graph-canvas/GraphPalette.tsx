"use client";

import { useState } from "react";
import { GripVertical, Plus, Search } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@craazzzyyfoxx/admin-kit/ui/dropdown-menu";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Input } from "@craazzzyyfoxx/admin-kit/ui/input";
import { RowButton } from "@craazzzyyfoxx/admin-kit/ui/row-button";
import { StatusDot } from "@craazzzyyfoxx/admin-kit/ui/status-dot";

/** The drag payload a palette row writes and the canvas reads back: the item's `key`. */
export const GRAPH_PALETTE_MIME = "application/graph-palette-item";

export type GraphPaletteItem = {
  /** What `onAdd` receives; unique across the palette. */
  key: string;
  label: string;
  description?: string;
  /** The dot beside the label, when the node it adds has a colour of its own. */
  color?: string;
};

export type GraphPaletteGroup = { label: string; items: GraphPaletteItem[] };

type PaletteProps = Readonly<{ groups: GraphPaletteGroup[]; onAdd: (key: string) => void }>;

/** The add-node column: every row is dragged onto the canvas or clicked (a drag is the one gesture a keyboard cannot make). */
export function GraphPalette({ groups, onAdd }: PaletteProps) {
  const t = useTranslations("common.graphCanvas.palette");
  const [search, setSearch] = useState("");
  const query = search.trim().toLowerCase();
  const shown = groups
    .map((group) => ({ ...group, items: group.items.filter((item) => item.label.toLowerCase().includes(query)) }))
    .filter((group) => group.items.length > 0);

  return (
    <div className="hidden w-44 shrink-0 flex-col gap-2 overflow-y-auto border-r bg-card/95 p-2 text-caption lg:flex">
      <div className="relative">
        <Search className="absolute left-2 top-1/2 size-3 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <Input
          size="sm"
          className="h-7 pl-7"
          placeholder={t("searchPlaceholder")}
          aria-label={t("searchLabel")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <p className="text-muted-foreground">{t("hint")}</p>
      {shown.length === 0 ? <p className="text-muted-foreground">{t("empty", { query: search })}</p> : null}
      {shown.map((group) => (
        <div key={group.label}>
          <p className={`${eyebrowClass("muted")} mb-1`}>{group.label}</p>
          {group.items.map((item) => (
            <RowButton
              key={item.key}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(GRAPH_PALETTE_MIME, item.key);
                e.dataTransfer.effectAllowed = "move";
              }}
              onClick={() => onAdd(item.key)}
              title={item.description}
              aria-label={t("add", { item: item.label })}
              className="flex cursor-grab items-center gap-1.5 rounded px-2 py-1 active:cursor-grabbing"
            >
              <GripVertical className="size-3 text-muted-foreground" aria-hidden />
              {item.color ? <StatusDot className="size-2" style={{ color: item.color }} /> : null}
              <span className="truncate">{item.label}</span>
            </RowButton>
          ))}
        </div>
      ))}
    </div>
  );
}

/** The palette as one "Add node" menu, for widths without room for the column. */
export function GraphPaletteMenu({ groups, onAdd }: PaletteProps) {
  const t = useTranslations("common.graphCanvas.palette");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="outline" size="sm">
          <Plus aria-hidden />
          {t("addMenu")}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-80 w-56 overflow-y-auto">
        {groups.map((group, index) => (
          <DropdownMenuGroup key={group.label}>
            {index > 0 ? <DropdownMenuSeparator /> : null}
            <DropdownMenuLabel>{group.label}</DropdownMenuLabel>
            {group.items.map((item) => (
              <DropdownMenuItem key={item.key} onSelect={() => onAdd(item.key)}>
                {item.color ? <StatusDot className="size-2" style={{ color: item.color }} /> : null}
                {item.label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
