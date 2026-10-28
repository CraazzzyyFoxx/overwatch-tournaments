"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleOff, FileJson } from "lucide-react";

import { StatusIcon } from "@/components/admin/StatusIcon";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FileButton } from "@/components/ui/file-button";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import adminService from "@/services/admin.service";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";
import { ALL_DISCIPLINES } from "@/lib/site/discipline-scope";
import type { AchievementRuleImportResult } from "@/types/admin.types";

type ImportSource = "workspace" | "file";

/**
 * Brings achievements in, either copied out of another workspace of the same
 * game or read from an exported JSON file. The source list and the selection
 * live here: nothing outside needs either, and the dialog is unmounted when it
 * closes, so a half-made selection is never carried over. The file import runs
 * through the page's actions (its result and error are theirs); both sources
 * end on the same report, shown here.
 */
export function AchievementImportDialog({
  onClose,
  workspaceId,
  discipline,
  onImportFile,
  isImportingFile,
  result,
  error,
  onImported,
}: Readonly<{
  onClose: () => void;
  workspaceId: number;
  /**
   * The game being copied: the source list, the selection and the import all stay inside it. `null` (no game
   * filtered): only the file import, which names each rule's game itself.
   */
  discipline: string | null;
  onImportFile: (file: File) => void;
  isImportingFile: boolean;
  result: AchievementRuleImportResult | null;
  error: string | null;
  onImported: (result: AchievementRuleImportResult) => void;
}>) {
  const t = useTranslations("adminAchievements");
  const tGame = useTranslations("common.discipline");
  const workspaceReasonId = useId();
  const queryClient = useQueryClient();
  const [source, setSource] = useState<ImportSource>(discipline === null ? "file" : "workspace");
  const [file, setFile] = useState<File | null>(null);
  const [sourceWorkspaceId, setSourceWorkspaceId] = useState<number | undefined>(undefined);
  const [selectedSlugs, setSelectedSlugs] = useState<Set<string>>(new Set());

  const { data: libraryWorkspaces } = useQuery({
    queryKey: achievementQueryKeys.libraryWorkspaces(workspaceId, discipline),
    queryFn: () => adminService.getAchievementLibraryWorkspaces(workspaceId, discipline!),
    enabled: discipline !== null,
  });

  const { data: libraryRules } = useQuery({
    queryKey: achievementQueryKeys.libraryRules(workspaceId, sourceWorkspaceId, discipline),
    queryFn: () => adminService.getAchievementLibraryRules(workspaceId, sourceWorkspaceId!, discipline!),
    enabled: discipline !== null && !!sourceWorkspaceId,
  });

  // A failed import keeps the selection: nothing was imported, and the admin can fix the cause and retry.
  const libraryMutation = useMutation({
    mutationFn: (data: { source_workspace_id: number; slugs: string[] }) =>
      adminService.importAchievementLibraryRules(workspaceId, { ...data, discipline: discipline! }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: achievementQueryKeys.adminList(workspaceId, discipline) });
      queryClient.invalidateQueries({ queryKey: achievementQueryKeys.adminList(workspaceId, ALL_DISCIPLINES) });
      queryClient.invalidateQueries({ queryKey: achievementQueryKeys.publicLists() });
      onImported(data);
    },
  });

  const allSlugs = (libraryRules ?? []).map((rule) => rule.slug);
  const allSelected = allSlugs.length > 0 && allSlugs.every((slug) => selectedSlugs.has(slug));

  const toggleSlug = (slug: string, checked: boolean) => {
    setSelectedSlugs((prev) => {
      const next = new Set(prev);
      if (checked) next.add(slug);
      else next.delete(slug);
      return next;
    });
  };

  const libraryError = libraryMutation.isError
    ? libraryMutation.error instanceof Error
      ? libraryMutation.error.message
      : t("list.importFailed")
    : null;
  const shownError = source === "file" ? error : libraryError;
  const pending = source === "file" ? isImportingFile : libraryMutation.isPending;
  const canSubmit =
    source === "file" ? file !== null : !!sourceWorkspaceId && selectedSlugs.size > 0;

  const submit = () => {
    if (source === "file") {
      if (file) onImportFile(file);
      return;
    }
    if (!sourceWorkspaceId || selectedSlugs.size === 0) return;
    libraryMutation.mutate({ source_workspace_id: sourceWorkspaceId, slugs: Array.from(selectedSlugs) });
  };

  return (
    <EntityFormDialog
      open
      onOpenChange={(next) => !next && onClose()}
      title={t("import.title")}
      onSubmit={submit}
      submitLabel={source === "file" ? t("import.importFile") : t("library.importSelected")}
      submittingLabel={t("common.importing")}
      isSubmitting={pending}
      submitDisabled={!canSubmit}
      isReadOnly={result !== null}
      errorMessage={result ? undefined : (shownError ?? undefined)}
      contentClassName="max-w-3xl"
    >
      {result ? (
        <div className="space-y-3 text-sm">
          <p className="tabular-nums">
            {t("import.summary", { created: result.created, updated: result.updated })}
          </p>
          {result.warnings.length > 0 && (
            <ul className="max-h-48 divide-y divide-border/60 overflow-y-auto">
              {result.warnings.map((warning, index) => (
                <li key={`${warning.slug}-${index}`} className="py-1.5">
                  <span className="font-mono text-caption">{warning.slug}</span>{" "}
                  <span className="text-warning">{warning.message}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="space-y-1">
            <ToggleGroup
              variant="pill"
              size="sm"
              aria-label={t("import.source")}
              value={source}
              onValueChange={(next) => setSource(next as ImportSource)}
            >
              <ToggleGroupItem
                value="workspace"
                disabled={discipline === null}
                aria-describedby={discipline === null ? workspaceReasonId : undefined}
              >
                {t("import.fromWorkspace")}
              </ToggleGroupItem>
              <ToggleGroupItem value="file">{t("import.fromFile")}</ToggleGroupItem>
            </ToggleGroup>
            {discipline === null && (
              <p id={workspaceReasonId} className="text-caption text-muted-foreground">
                {tGame("pickGameAction")}
              </p>
            )}
          </div>

          {source === "file" ? (
            <div className="space-y-2">
              <Label id="import-file-label">{t("import.fileLabel")}</Label>
              <FileButton
                variant="outline"
                accept="application/json,.json"
                onFiles={([next]) => setFile(next)}
                aria-labelledby="import-file-label import-file-name"
                className="w-full justify-start"
              >
                <FileJson aria-hidden />
                <span id="import-file-name" className="truncate">
                  {file?.name ?? t("import.chooseFile")}
                </span>
              </FileButton>
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <Label htmlFor="library-source-workspace">{t("library.sourceWorkspace")}</Label>
                <Select
                  value={sourceWorkspaceId ? String(sourceWorkspaceId) : ""}
                  onValueChange={(value) => {
                    setSourceWorkspaceId(value ? Number(value) : undefined);
                    setSelectedSlugs(new Set());
                  }}
                >
                  <SelectTrigger id="library-source-workspace">
                    <SelectValue placeholder={t("library.selectWorkspace")} />
                  </SelectTrigger>
                  <SelectContent>
                    {(libraryWorkspaces ?? []).map((workspace) => (
                      <SelectItem key={workspace.id} value={String(workspace.id)}>
                        {workspace.name} ({workspace.rules_count})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {sourceWorkspaceId && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium">
                      {t.rich("library.achievementSelection", {
                        count: selectedSlugs.size,
                        num: (chunks) => <span className="tabular-nums text-muted-foreground">{chunks}</span>,
                      })}
                    </p>
                    {allSlugs.length > 0 && (
                      <div className="flex gap-2">
                        {!allSelected && (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => setSelectedSlugs(new Set(allSlugs))}
                          >
                            {t("common.selectAll")}
                          </Button>
                        )}
                        {selectedSlugs.size > 0 && (
                          <Button type="button" variant="ghost" size="sm" onClick={() => setSelectedSlugs(new Set())}>
                            {t("common.clear")}
                          </Button>
                        )}
                      </div>
                    )}
                  </div>
                  {(libraryRules?.length ?? 0) === 0 ? (
                    <p className="text-sm text-muted-foreground">{t("library.empty")}</p>
                  ) : (
                    <ScrollArea className="h-[40vh] rounded-lg border">
                      <div className="divide-y divide-border/60">
                        {(libraryRules ?? []).map((rule) => (
                          <label key={rule.slug} className="flex items-center gap-3 px-3 py-2 text-sm">
                            <Checkbox
                              checked={selectedSlugs.has(rule.slug)}
                              onCheckedChange={(checked) => toggleSlug(rule.slug, !!checked)}
                              aria-label={t("library.copy", { name: rule.name })}
                            />
                            <div className="min-w-0 flex-1">
                              <p className="truncate font-medium">{rule.name}</p>
                              <p className="truncate text-caption text-muted-foreground">
                                {t("library.ruleMeta", {
                                  slug: rule.slug,
                                  category: t(`common.categoryValues.${rule.category}`),
                                })}
                              </p>
                            </div>
                            {!rule.enabled && (
                              <StatusIcon icon={CircleOff} label={t("common.disabled")} variant="muted" />
                            )}
                          </label>
                        ))}
                      </div>
                    </ScrollArea>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </EntityFormDialog>
  );
}
