"use client";

import Link from "next/link";
import { Building2, ChevronDown, FileJson, Import, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { SettingsHeaderActions } from "@/components/admin/workspace-settings/WorkspaceSettingsShell";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@craazzzyyfoxx/admin-kit/ui/dropdown-menu";

/**
 * The page's own actions, beside its title: a new grid, and the two ways a grid comes in from elsewhere. Both make a
 * grid, so both need `division_grid.create`; without it the header carries nothing.
 */
export function DivisionsHeaderActions({
  canCreate,
  onNewGrid,
  onImportJson,
  importPending
}: Readonly<{
  canCreate: boolean;
  onNewGrid: () => void;
  /** Opens the file picker the page owns (it must outlive this portal). */
  onImportJson: () => void;
  importPending: boolean;
}>) {
  const t = useTranslations("adminSettings.divisions");
  if (!canCreate) return null;
  // Below `sm` both are icons with their names kept for assistive tech: two labelled buttons would squeeze the page
  // title beside them to a few letters.
  return (
    <SettingsHeaderActions>
      <Button variant="outline" size="sm" onClick={onNewGrid}>
        <Plus aria-hidden className="size-4" />
        <span className="sr-only sm:not-sr-only">{t("newGrid")}</span>
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm">
            <Import aria-hidden className="size-4 sm:hidden" />
            <span className="sr-only sm:not-sr-only">{t("importMenu")}</span>
            <ChevronDown aria-hidden className="hidden size-4 sm:block" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-60">
          <DropdownMenuItem className="gap-2" disabled={importPending} onSelect={onImportJson}>
            <FileJson aria-hidden className="size-3.5" />
            {t("importJson")}
          </DropdownMenuItem>
          <DropdownMenuItem className="gap-2" asChild>
            <Link href="/admin/settings/divisions/import">
              <Building2 aria-hidden className="size-3.5" />
              {t("importWorkspace")}
            </Link>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </SettingsHeaderActions>
  );
}
