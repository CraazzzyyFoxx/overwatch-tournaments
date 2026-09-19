"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus } from "lucide-react";

import { InlineEditText } from "@/components/kit/InlineEditText";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { ROLES, ROLE_LABELS, canonicalToRegistrationRole } from "@/lib/roles";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { PlayerSubRole } from "@/types/admin.types";

/**
 * Workspace sub-role catalog (`PlayerSubRole`). This used to live inside a
 * tournament's registration form builder, where creating or removing an entry
 * silently rewrote the options of every *other* tournament in the workspace —
 * plus the player, roster and balancer pickers that read the same table. The
 * catalog is workspace-global, so it is configured here; a registration form
 * only chooses which catalog entries it offers.
 */
export default function WorkspaceSubRolesSettingsPage() {
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const { canAccessPermission } = usePermissions();
  const queryClient = useQueryClient();
  const [draftLabels, setDraftLabels] = useState<Record<string, string>>({});

  const canEdit = canAccessPermission("player.update", workspaceId);
  const canCreate = canAccessPermission("player.create", workspaceId);
  const canDeactivate = canAccessPermission("player.delete", workspaceId);

  const catalogQuery = useQuery({
    // Same key family every sub-role picker uses, with an `"all"` leaf because
    // this page is the only reader that wants the deactivated rows too. Sharing
    // the prefix means one `invalidateQueries` refreshes this page *and* every
    // picker in the app.
    queryKey: ["admin", "player-sub-roles", workspaceId, "all"],
    // Inactive entries are included so a deactivated sub-role can be restored;
    // the tournament form builder only ever sees the active ones.
    queryFn: () =>
      adminService.getPlayerSubRoles({
        workspace_id: workspaceId as number,
        include_inactive: true
      }),
    enabled: workspaceId !== null
  });

  const invalidateCatalog = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "player-sub-roles"] });

  const createMutation = useMutation({
    mutationFn: ({ role, label }: { role: string; label: string }) => {
      if (workspaceId === null) throw new Error("No workspace selected");
      return adminService.createPlayerSubRole({ workspace_id: workspaceId, role, label });
    },
    onSuccess: async (_created, { role }) => {
      setDraftLabels((prev) => ({ ...prev, [role]: "" }));
      await invalidateCatalog();
      notify.success("Sub-role added");
    },
    onError: (error) => notify.apiError(error, { title: "Could not add the sub-role" })
  });

  const renameMutation = useMutation({
    mutationFn: ({ id, label }: { id: number; label: string }) =>
      // The slug is deliberately left alone: it is what every stored player
      // assignment references, so renaming is a display-label change only.
      adminService.updatePlayerSubRole(id, { label }),
    onSuccess: async () => {
      await invalidateCatalog();
      notify.success("Sub-role renamed");
    },
    onError: (error) => notify.apiError(error, { title: "Could not rename the sub-role" })
  });

  const setActiveMutation = useMutation({
    // Deactivation keeps going through DELETE so it stays gated by
    // `player.delete` exactly as it was in the form builder; the endpoint only
    // flips `is_active`, nothing is destroyed. Restoring is a plain update.
    mutationFn: ({ id, isActive }: { id: number; isActive: boolean }) =>
      isActive
        ? adminService.updatePlayerSubRole(id, { is_active: true }).then(() => undefined)
        : adminService.deletePlayerSubRole(id),
    onSuccess: async (_result, { isActive }) => {
      await invalidateCatalog();
      notify.success(isActive ? "Sub-role restored" : "Sub-role deactivated");
    },
    onError: (error) => notify.apiError(error, { title: "Could not update the sub-role" })
  });

  const byRole = useMemo(() => {
    const grouped: Record<string, PlayerSubRole[]> = Object.fromEntries(
      ROLES.map((role) => [role.code, [] as PlayerSubRole[]])
    );
    for (const row of catalogQuery.data ?? []) {
      const code = canonicalToRegistrationRole(row.role);
      if (code && grouped[code]) {
        grouped[code].push(row);
      }
    }
    return grouped;
  }, [catalogQuery.data]);

  const isMutating =
    createMutation.isPending || renameMutation.isPending || setActiveMutation.isPending;

  if (workspaceId === null) {
    return (
      <PageStateCard
        state="empty"
        title="No workspace selected"
        description="Pick a workspace in the sidebar to manage its sub-role catalog."
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-3">
        {ROLES.map((role) => {
          const entries = byRole[role.code] ?? [];
          const draft = draftLabels[role.code] ?? "";
          const submitCreate = () => {
            const label = draft.trim();
            if (label) {
              createMutation.mutate({ role: role.code, label });
            }
          };

          return (
            <Card key={role.code}>
              <CardHeader>
                <CardTitle asChild>
                  <h2>{ROLE_LABELS[role.code] ?? role.display}</h2>
                </CardTitle>
                <CardDescription>
                  {entries.length === 0
                    ? "No sub-roles yet."
                    : `${entries.filter((entry) => entry.is_active).length} of ${entries.length} active.`}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {catalogQuery.isLoading ? (
                  <Skeleton className="h-32 w-full rounded-md" />
                ) : (
                  <ul className="space-y-1.5">
                    {entries.map((entry) => (
                      <li
                        key={entry.id}
                        className="flex items-center gap-2 rounded-md border border-border/60 px-2.5 py-1.5"
                      >
                        <div className="min-w-0 flex-1">
                          <InlineEditText
                            value={entry.label}
                            label={`${ROLE_LABELS[role.code] ?? role.display} sub-role name`}
                            canEdit={canEdit}
                            onSave={(label) => renameMutation.mutateAsync({ id: entry.id, label })}
                            textClassName={entry.is_active ? undefined : "text-muted-foreground"}
                          />
                          <p className="truncate font-mono text-xs text-muted-foreground/70">
                            {entry.slug}
                          </p>
                        </div>
                        <Switch
                          checked={entry.is_active}
                          disabled={isMutating || (entry.is_active ? !canDeactivate : !canEdit)}
                          onCheckedChange={(isActive) =>
                            setActiveMutation.mutate({ id: entry.id, isActive })
                          }
                          aria-label={
                            entry.is_active ? `Deactivate ${entry.label}` : `Restore ${entry.label}`
                          }
                        />
                      </li>
                    ))}
                  </ul>
                )}

                {canCreate && (
                  <div className="flex items-center gap-2">
                    <Input
                      value={draft}
                      onChange={(event) =>
                        setDraftLabels((prev) => ({ ...prev, [role.code]: event.target.value }))
                      }
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          submitCreate();
                        }
                      }}
                      placeholder={`Add a ${ROLE_LABELS[role.code] ?? role.display} sub-role`}
                      className="h-8 text-xs"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-8 shrink-0"
                      disabled={isMutating || !draft.trim()}
                      onClick={submitCreate}
                    >
                      {createMutation.isPending ? (
                        <Loader2 className="mr-1 size-3.5 animate-spin" aria-hidden />
                      ) : (
                        <Plus className="mr-1 size-3.5" aria-hidden />
                      )}
                      Add
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      <p className="text-xs text-muted-foreground">
        Deactivating a sub-role hides it from every picker but keeps it on the players already
        assigned to it. Which of these a specific tournament offers is chosen in that
        tournament&apos;s registration form.
      </p>
    </div>
  );
}
