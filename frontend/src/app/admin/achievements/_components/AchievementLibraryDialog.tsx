"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle, CircleOff, LibraryBig } from "lucide-react";

import { StatusIcon } from "@/components/admin/StatusIcon";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import adminService from "@/services/admin.service";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";
import type { AchievementRuleImportResult } from "@/types/admin.types";

/**
 * Copies achievements out of another workspace. Both the source list and the
 * selection are scoped to the dialog — nothing outside it needs either, and a
 * closed dialog should not be holding a half-made selection.
 */
export function AchievementLibraryDialog({
  open,
  onOpenChange,
  workspaceId,
  canImport,
  onImported,
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: number;
  canImport: boolean;
  onImported: (result: AchievementRuleImportResult) => void;
}>) {
  const queryClient = useQueryClient();
  const [sourceWorkspaceId, setSourceWorkspaceId] = useState<number | undefined>(undefined);
  const [selectedSlugs, setSelectedSlugs] = useState<Set<string>>(new Set());

  const { data: libraryWorkspaces } = useQuery({
    queryKey: achievementQueryKeys.libraryWorkspaces(workspaceId),
    queryFn: () => adminService.getAchievementLibraryWorkspaces(workspaceId),
    enabled: open,
  });

  const { data: libraryRules } = useQuery({
    queryKey: achievementQueryKeys.libraryRules(workspaceId, sourceWorkspaceId),
    queryFn: () => adminService.getAchievementLibraryRules(workspaceId, sourceWorkspaceId!),
    enabled: open && !!sourceWorkspaceId,
  });

  const importMutation = useMutation({
    mutationFn: (data: { source_workspace_id: number; slugs: string[] }) =>
      adminService.importAchievementLibraryRules(workspaceId, data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: achievementQueryKeys.adminList(workspaceId) });
      onImported(data);
      onOpenChange(false);
      setSelectedSlugs(new Set());
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

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) {
          setSelectedSlugs(new Set());
        }
      }}
    >
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Achievement library</DialogTitle>
          <DialogDescription>
            Import achievements from another workspace into the current workspace.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="library-source-workspace">Source workspace</Label>
            <Select
              value={sourceWorkspaceId ? String(sourceWorkspaceId) : ""}
              onValueChange={(value) => {
                setSourceWorkspaceId(value ? Number(value) : undefined);
                setSelectedSlugs(new Set());
              }}
            >
              <SelectTrigger id="library-source-workspace">
                <SelectValue placeholder="Select workspace" />
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

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">
                Achievements{" "}
                <span className="tabular-nums text-muted-foreground">
                  ({selectedSlugs.size > 0 ? `${selectedSlugs.size} selected` : "none selected"})
                </span>
              </p>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setSelectedSlugs(new Set(allSlugs))}
                  disabled={allSlugs.length === 0 || allSelected}
                >
                  Select all
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setSelectedSlugs(new Set())}
                  disabled={selectedSlugs.size === 0}
                >
                  Clear
                </Button>
              </div>
            </div>
            <ScrollArea className="h-[40vh] rounded border p-3">
              {!sourceWorkspaceId && (
                <p className="text-sm text-muted-foreground">
                  Pick a source workspace above to list the achievements you can copy.
                </p>
              )}
              {sourceWorkspaceId && (libraryRules?.length ?? 0) === 0 && (
                <p className="text-sm text-muted-foreground">
                  That workspace has no achievements to copy. Choose another source workspace.
                </p>
              )}
              <div className="space-y-2">
                {(libraryRules ?? []).map((rule) => (
                  <label
                    key={rule.slug}
                    className="flex items-center justify-between gap-3 rounded border px-3 py-2 text-sm"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <Checkbox
                        checked={selectedSlugs.has(rule.slug)}
                        onCheckedChange={(checked) => toggleSlug(rule.slug, !!checked)}
                        aria-label={`Copy ${rule.name}`}
                      />
                      <div className="min-w-0">
                        <p className="font-medium truncate">{rule.name}</p>
                        <p className="text-xs text-muted-foreground truncate">
                          {rule.slug} · {rule.category}
                        </p>
                      </div>
                    </div>
                    {rule.enabled ? (
                      <StatusIcon icon={CheckCircle} label="On" variant="success" />
                    ) : (
                      <StatusIcon icon={CircleOff} label="Off" variant="muted" />
                    )}
                  </label>
                ))}
              </div>
            </ScrollArea>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              if (!sourceWorkspaceId || selectedSlugs.size === 0) return;
              importMutation.mutate({
                source_workspace_id: sourceWorkspaceId,
                slugs: Array.from(selectedSlugs),
              });
            }}
            disabled={
              !sourceWorkspaceId ||
              selectedSlugs.size === 0 ||
              importMutation.isPending ||
              !canImport
            }
          >
            <LibraryBig className={`mr-2 h-4 w-4 ${importMutation.isPending ? "animate-spin" : ""}`} aria-hidden />
            {importMutation.isPending ? "Importing…" : "Import selected"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
