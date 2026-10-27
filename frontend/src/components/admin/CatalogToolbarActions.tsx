"use client";

/**
 * Shared pieces for the game-catalogue admin pages (maps, heroes, gamemodes).
 *
 * All three pages are the same shape — sync-from-game + create commands over
 * the table and a dialog that doubles as create and edit — so the commands and
 * the two dialog helpers live here instead of being copy-pasted three times.
 */

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import type { TableCommand } from "@/components/data-table";

interface CatalogCommandsProps {
  /**
   * Permission gate for both commands. Syncing and creating a catalogue entry
   * are granted together (superuser), so both are hidden when false.
   */
  canSync: boolean;
  /** A sync runs in the background: the command says so and stays clickable — `onSync` then reopens its modal. */
  isSyncing: boolean;
  onSync: () => void;
  /** Sentence-case label naming the object, e.g. "Sync maps from game". */
  syncLabel: string;
  onCreate: () => void;
  /** Sentence-case label naming the object, e.g. "Create map". */
  createLabel: string;
}

export function useCatalogCommands({
  canSync,
  isSyncing,
  onSync,
  syncLabel,
  onCreate,
  createLabel
}: Readonly<CatalogCommandsProps>): TableCommand[] {
  const t = useTranslations("adminWorkspace.content.catalog.sync");
  return [
    {
      id: "sync",
      label: isSyncing ? t("running") : syncLabel,
      onSelect: onSync,
      pending: isSyncing,
      hidden: !canSync
    },
    { id: "create", label: createLabel, icon: Plus, onSelect: onCreate, primary: true, hidden: !canSync }
  ];
}

/**
 * Secondary error text for a create/edit dialog: picks the mutation actually in
 * play, names the object and says what to do. `EntityFormDialog` already renders
 * the "Could not save your changes." lead, so this must not repeat it — and a
 * raw API message is never the whole message, only parenthesised detail.
 */
export function entityFormError(
  entity: string,
  isEditing: boolean,
  updateError: unknown,
  createError: unknown,
  t: (key: "formError", values: { entity: string }) => string
): string | undefined {
  const error = isEditing ? updateError : createError;
  if (!error) {
    return undefined;
  }

  const advice = t("formError", { entity });
  const detail = error instanceof Error ? error.message.trim() : "";

  return detail ? `${advice} (${detail})` : advice;
}

/**
 * `onOpenChange` for a dialog that doubles as create and edit: dismissing it has
 * to clear the create flag, the edit target and the draft together.
 */
export function onEntityDialogClose(reset: () => void): (open: boolean) => void {
  return (open) => {
    if (!open) {
      reset();
    }
  };
}
