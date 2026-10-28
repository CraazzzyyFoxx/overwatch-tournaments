"use client";

import { Archive, ArchiveRestore, Download, FilePlus2, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import type { DivisionGridEntity } from "@/types/workspace.types";

/** One menu row: `null` handlers and a missing grant drop it; `disabled` keeps it with the menu's reason line. */
interface GridMenuAction {
  key: string;
  label: string;
  icon: typeof Pencil;
  onSelect: () => void;
  disabled?: boolean;
  destructive?: boolean;
}

/**
 * Everything done to the open grid besides its next step (DESIGN §14 "Header actions": the next step is the in-force
 * card's button, the rest live here). Permission hides an item; the grid being in force disables archive and delete,
 * and the reason is printed in the menu rather than hidden in a tooltip.
 */
export function GridMenu({
  grid,
  inForce,
  newDraft,
  ladderDraft,
  onRename,
  onExport,
  onArchive,
  onRestore,
  onDelete,
  pending
}: Readonly<{
  grid: DivisionGridEntity;
  /** The grid holds the version in force for its game. */
  inForce: boolean;
  /** "New draft from vN" when it is not already the card's next step. */
  newDraft: { label: string; onSelect: () => void } | null;
  /** "New draft from the <game> ladder" when it is not already the card's next step. */
  ladderDraft: { label: string; onSelect: () => void } | null;
  onRename: (() => void) | null;
  onExport: () => void;
  onArchive: (() => void) | null;
  onRestore: (() => void) | null;
  onDelete: (() => void) | null;
  /** A grid write is in flight: nothing else may start. */
  pending: boolean;
}>) {
  const t = useTranslations("adminSettings.divisions");
  const archived = grid.archived_at !== null;

  const present = (actions: (GridMenuAction | null)[]) =>
    actions.filter((action): action is GridMenuAction => action !== null);

  const work = present([
    newDraft ? { key: "draft", label: newDraft.label, icon: FilePlus2, onSelect: newDraft.onSelect } : null,
    ladderDraft ? { key: "ladder", label: ladderDraft.label, icon: FilePlus2, onSelect: ladderDraft.onSelect } : null,
    onRename ? { key: "rename", label: t("gridMenu.rename"), icon: Pencil, onSelect: onRename } : null,
    { key: "export", label: t("exportJson"), icon: Download, onSelect: onExport }
  ]);

  const lifecycle = present([
    !archived && onArchive
      ? { key: "archive", label: t("gridMenu.archive"), icon: Archive, onSelect: onArchive, disabled: inForce }
      : null,
    archived && onRestore
      ? { key: "restore", label: t("gridMenu.restore"), icon: ArchiveRestore, onSelect: onRestore }
      : null,
    onDelete
      ? {
          key: "delete",
          label: t("gridMenu.delete"),
          icon: Trash2,
          onSelect: onDelete,
          disabled: inForce,
          destructive: true
        }
      : null
  ]);

  const item = (action: GridMenuAction) => {
    const Icon = action.icon;
    return (
      <DropdownMenuItem
        key={action.key}
        disabled={pending || action.disabled}
        onSelect={action.onSelect}
        variant={action.destructive ? "destructive" : "default"}
      >
        <Icon aria-hidden className="size-3.5" />
        {action.label}
      </DropdownMenuItem>
    );
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={t("gridMenu.label", { name: grid.name })}>
          <MoreHorizontal aria-hidden className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        {work.map(item)}
        {lifecycle.length > 0 ? <DropdownMenuSeparator /> : null}
        {lifecycle.map(item)}
        {inForce && lifecycle.some((action) => action.disabled) ? (
          <p className="px-2 pb-1.5 pt-0.5 text-caption text-muted-foreground">{t("gridMenu.inForceReason")}</p>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
