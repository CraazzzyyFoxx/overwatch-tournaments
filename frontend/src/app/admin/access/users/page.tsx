"use client";

import { useMemo, useState } from "react";
import { ColumnDef } from "@tanstack/react-table";
import {
  BadgeCheck,
  CheckCircle,
  Link2,
  Shield,
  ShieldAlert,
  Trash2,
  UserCog,
  XCircle
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { UserDenyEditor } from "./UserDenyEditor";
import { UserSearchCombobox } from "@/components/admin/UserSearchCombobox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { rbacService } from "@/services/rbac.service";
import type { AuthAdminUser } from "@/types/rbac.types";
import type { MinimizedUser } from "@/types/user.types";

const PAGE_SIZE = 15;

export default function AccessAdminUsersPage() {
  const queryClient = useQueryClient();
  const { hasPermission } = usePermissions();
  const canAssignRoles = hasPermission("role.assign") && hasPermission("role.read");
  const canManageLinkedPlayers = hasPermission("auth_user.update");

  const [managingUserId, setManagingUserId] = useState<number | null>(null);
  const [selectedRoleId, setSelectedRoleId] = useState<string>("");
  const [selectedAnalyticsUserId, setSelectedAnalyticsUserId] = useState<number | null>(null);
  const [selectedAnalyticsUserName, setSelectedAnalyticsUserName] = useState("");
  const [assignAsPrimary, setAssignAsPrimary] = useState(true);

  const rolesQuery = useQuery({
    queryKey: ["access-admin", "roles", "all"],
    queryFn: () => rbacService.listRolesAll(),
    enabled: canAssignRoles
  });

  const userDetailQuery = useQuery({
    queryKey: ["access-admin", "users", managingUserId],
    queryFn: () => rbacService.getUser(managingUserId as number),
    enabled: managingUserId !== null
  });

  const assignRoleMutation = useMutation({
    mutationFn: (payload: { user_id: number; role_id: number }) => rbacService.assignRole(payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["access-admin", "users"] }),
        queryClient.invalidateQueries({ queryKey: ["access-admin", "roles"] }),
        queryClient.invalidateQueries({ queryKey: ["access-admin", "users", managingUserId] })
      ]);
      setSelectedRoleId("");
      notify.success("Role assigned");
    }
  });

  const removeRoleMutation = useMutation({
    mutationFn: (payload: { user_id: number; role_id: number }) => rbacService.removeRole(payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["access-admin", "users"] }),
        queryClient.invalidateQueries({ queryKey: ["access-admin", "roles"] }),
        queryClient.invalidateQueries({ queryKey: ["access-admin", "users", managingUserId] })
      ]);
      notify.success("Role removed");
    }
  });

  const assignLinkedPlayerMutation = useMutation({
    mutationFn: (payload: { userId: number; player_id: number; is_primary: boolean }) =>
      rbacService.assignLinkedPlayer(payload.userId, {
        player_id: payload.player_id,
        is_primary: payload.is_primary
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["access-admin", "users"] }),
        queryClient.invalidateQueries({ queryKey: ["access-admin", "users", managingUserId] })
      ]);
      setSelectedAnalyticsUserId(null);
      setSelectedAnalyticsUserName("");
      setAssignAsPrimary(true);
      notify.success("Linked analytics account assigned");
    }
  });

  const removeLinkedPlayerMutation = useMutation({
    mutationFn: (payload: { userId: number; playerId: number }) =>
      rbacService.removeLinkedPlayer(payload.userId, payload.playerId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["access-admin", "users"] }),
        queryClient.invalidateQueries({ queryKey: ["access-admin", "users", managingUserId] })
      ]);
      notify.success("Linked analytics account removed");
    }
  });

  const columns: ColumnDef<AuthAdminUser>[] = [
    {
      accessorKey: "email",
      header: "Email"
    },
    {
      accessorKey: "username",
      header: "Username"
    },
    {
      id: "linkedPlayers",
      header: "Linked Account",
      cell: ({ row }) => {
        const linkedPlayers = row.original.linked_players ?? [];
        if (linkedPlayers.length === 0) {
          return <span className="text-sm text-muted-foreground">Not linked</span>;
        }

        return (
          <div className="flex flex-wrap gap-2">
            {linkedPlayers.map((player) => (
              <Badge key={player.player_id} variant={player.is_primary ? "default" : "outline"}>
                {player.player_name}
                {player.is_primary ? " (Primary)" : ""}
              </Badge>
            ))}
          </div>
        );
      }
    },
    {
      id: "status",
      header: "Status",
      cell: ({ row }) => {
        const user = row.original;
        return (
          <div className="flex flex-wrap gap-2">
            {user.is_active ? (
              <StatusIcon icon={CheckCircle} label="Active" variant="success" />
            ) : (
              <StatusIcon icon={XCircle} label="Inactive" variant="muted" />
            )}
            {user.is_verified ? (
              <StatusIcon icon={BadgeCheck} label="Verified" variant="info" />
            ) : null}
            {user.is_superuser ? (
              <StatusIcon icon={ShieldAlert} label="Superuser" variant="destructive" />
            ) : null}
          </div>
        );
      }
    },
    {
      id: "roles",
      header: "Roles",
      cell: ({ row }) => {
        const roles = row.original.roles;
        if (roles.length === 0) {
          return <span className="text-sm text-muted-foreground">No roles</span>;
        }

        return (
          <div className="flex flex-wrap gap-2">
            {roles.map((role) => (
              <Badge key={role.id} variant="secondary">
                {role.name}
              </Badge>
            ))}
          </div>
        );
      }
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <div className="flex justify-end">
          <Button variant="outline" size="sm" onClick={() => setManagingUserId(row.original.id)}>
            <UserCog className="mr-2 h-4 w-4" />
            {canAssignRoles ? "Manage" : "Inspect"}
          </Button>
        </div>
      )
    }
  ];

  const assignableRoles = useMemo(() => {
    const currentRoleIds = new Set(userDetailQuery.data?.roles.map((role) => role.id) ?? []);
    return (rolesQuery.data ?? []).filter((role) => !currentRoleIds.has(role.id));
  }, [rolesQuery.data, userDetailQuery.data]);

  return (
    <div className="space-y-6">
      <AdminPageHeader
        title="Access Users"
        description="Manage auth accounts, review assigned roles, and inspect effective permissions."
        meta={<Badge variant="secondary">RBAC</Badge>}
      />

      <AdminDataTable
        initialPageSize={PAGE_SIZE}
        pageSizeOptions={[10, 20, 50, 100]}
        queryKey={(page, search, pageSize, sortField, sortDir) => [
          "access-admin",
          "users",
          page,
          search,
          pageSize,
          sortField,
          sortDir
        ]}
        queryFn={(page, search, pageSize, sortField, sortDir) =>
          rbacService.listUsers({
            page,
            per_page: pageSize,
            sort: sortField ?? undefined,
            order: sortDir,
            search: search || undefined,
          })
        }
        columns={columns}
        searchPlaceholder="Search auth users..."
        emptyMessage="No auth users found."
        onRowDoubleClick={(row) => setManagingUserId(row.original.id)}
      />

      <Dialog
        open={managingUserId !== null}
        onOpenChange={(open) => {
          if (!open) {
            setManagingUserId(null);
            setSelectedRoleId("");
            setSelectedAnalyticsUserId(null);
            setSelectedAnalyticsUserName("");
            setAssignAsPrimary(true);
          }
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Manage Access</DialogTitle>
            <DialogDescription>
              {canAssignRoles
                ? "Assign roles, manage linked analytics accounts, and review effective permissions for this auth account."
                : "Review linked analytics accounts, assigned roles, and effective permissions for this auth account."}
            </DialogDescription>
          </DialogHeader>

          {userDetailQuery.isLoading ? (
            <div className="py-8 text-sm text-muted-foreground">Loading auth user...</div>
          ) : userDetailQuery.data ? (
            <div className="space-y-6">
              <div className="rounded-lg border border-border/60 bg-card/60 p-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="text-lg font-semibold">{userDetailQuery.data.email}</p>
                    <p className="text-sm text-muted-foreground">
                      @{userDetailQuery.data.username}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {userDetailQuery.data.is_superuser ? (
                      <StatusIcon icon={ShieldAlert} label="Superuser" variant="destructive" />
                    ) : null}
                    {userDetailQuery.data.is_active ? (
                      <StatusIcon icon={CheckCircle} label="Active" variant="success" />
                    ) : (
                      <StatusIcon icon={XCircle} label="Inactive" variant="muted" />
                    )}
                    {userDetailQuery.data.is_verified ? (
                      <StatusIcon icon={BadgeCheck} label="Verified" variant="info" />
                    ) : null}
                  </div>
                </div>
              </div>

              <UserDenyEditor userId={userDetailQuery.data.id} canEdit={canAssignRoles} />

              <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
                <div className="space-y-4 rounded-lg border border-border/60 bg-card/60 p-4">
                  <div>
                    <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                      Assigned Roles
                    </h3>
                  </div>

                  <div className="space-y-3">
                    {userDetailQuery.data.roles.length > 0 ? (
                      userDetailQuery.data.roles.map((role) => (
                        <div
                          key={role.id}
                          className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border/60 p-3"
                        >
                          <div>
                            <p className="font-medium">{role.name}</p>
                            <p className="text-sm text-muted-foreground">
                              {role.description || "No description provided."}
                            </p>
                          </div>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={!canAssignRoles || removeRoleMutation.isPending}
                            onClick={() =>
                              removeRoleMutation.mutate({
                                user_id: userDetailQuery.data!.id,
                                role_id: role.id
                              })
                            }
                          >
                            {canAssignRoles ? "Remove" : "Assigned"}
                          </Button>
                        </div>
                      ))
                    ) : (
                      <p className="text-sm text-muted-foreground">No roles assigned.</p>
                    )}
                  </div>

                  {canAssignRoles ? (
                    <div className="rounded-md border border-dashed border-border p-4">
                      <div className="space-y-3">
                        <p className="text-sm font-medium">Assign another role</p>
                        <Select value={selectedRoleId} onValueChange={setSelectedRoleId}>
                          <SelectTrigger>
                            <SelectValue placeholder="Select a role" />
                          </SelectTrigger>
                          <SelectContent>
                            {assignableRoles.map((role) => (
                              <SelectItem key={role.id} value={String(role.id)}>
                                {role.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Button
                          disabled={!selectedRoleId || assignRoleMutation.isPending}
                          onClick={() =>
                            assignRoleMutation.mutate({
                              user_id: userDetailQuery.data!.id,
                              role_id: Number(selectedRoleId)
                            })
                          }
                        >
                          <Shield className="mr-2 h-4 w-4" />
                          Assign Role
                        </Button>
                      </div>
                    </div>
                  ) : null}
                </div>

                <div className="space-y-6">
                  <div className="space-y-4 rounded-lg border border-border/60 bg-card/60 p-4">
                    <div>
                      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                        Linked Player Accounts
                      </h3>
                      <p className="mt-1 text-sm text-muted-foreground">
                        Links from this auth account to `players.user` records through
                        `AuthUserPlayer`.
                      </p>
                    </div>

                    <div className="space-y-3">
                      {(userDetailQuery.data.linked_players ?? []).length > 0 ? (
                        (userDetailQuery.data.linked_players ?? []).map((player) => (
                          <div
                            key={player.player_id}
                            className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border/60 p-3"
                          >
                            <div>
                              <p className="font-medium">{player.player_name}</p>
                              <p className="text-sm text-muted-foreground">
                                Player ID: {player.player_id}
                              </p>
                            </div>
                            <div className="flex flex-wrap gap-2">
                              {player.is_primary ? (
                                <Badge variant="secondary">Primary</Badge>
                              ) : null}
                              {canManageLinkedPlayers ? (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  disabled={removeLinkedPlayerMutation.isPending}
                                  onClick={() =>
                                    removeLinkedPlayerMutation.mutate({
                                      userId: userDetailQuery.data!.id,
                                      playerId: player.player_id
                                    })
                                  }
                                >
                                  <Trash2 className="mr-2 h-4 w-4" />
                                  Unlink
                                </Button>
                              ) : null}
                            </div>
                          </div>
                        ))
                      ) : (
                        <p className="text-sm text-muted-foreground">No linked player accounts.</p>
                      )}
                    </div>

                    {canManageLinkedPlayers ? (
                      <div className="rounded-md border border-dashed border-border p-4">
                        <div className="space-y-3">
                          <p className="text-sm font-medium">Assign analytics account</p>
                          <UserSearchCombobox
                            value={selectedAnalyticsUserId ?? undefined}
                            selectedName={selectedAnalyticsUserName || undefined}
                            placeholder="Select analytics account"
                            searchPlaceholder="Search analytics account..."
                            onSelect={(user: MinimizedUser | undefined) => {
                              setSelectedAnalyticsUserId(user?.id ?? null);
                              setSelectedAnalyticsUserName(user?.name ?? "");
                            }}
                          />
                          <div className="flex items-center space-x-2">
                            <Checkbox
                              id="assign-linked-player-primary"
                              checked={assignAsPrimary}
                              onCheckedChange={(checked) => setAssignAsPrimary(Boolean(checked))}
                            />
                            <Label
                              htmlFor="assign-linked-player-primary"
                              className="cursor-pointer"
                            >
                              Mark as primary
                            </Label>
                          </div>
                          <Button
                            disabled={
                              selectedAnalyticsUserId == null ||
                              assignLinkedPlayerMutation.isPending
                            }
                            onClick={() => {
                              if (selectedAnalyticsUserId == null) return;
                              assignLinkedPlayerMutation.mutate({
                                userId: userDetailQuery.data!.id,
                                player_id: selectedAnalyticsUserId,
                                is_primary: assignAsPrimary
                              });
                            }}
                          >
                            <Link2 className="mr-2 h-4 w-4" />
                            Assign Account
                          </Button>
                        </div>
                      </div>
                    ) : null}
                  </div>

                  <div className="space-y-4 rounded-lg border border-border/60 bg-card/60 p-4">
                    <div>
                      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                        Effective Permissions
                      </h3>
                      <p className="mt-1 text-sm text-muted-foreground">
                        Computed union of all permissions granted by assigned roles.
                      </p>
                    </div>

                    <div className="flex max-h-96 flex-wrap gap-2 overflow-y-auto pr-1">
                      {userDetailQuery.data.effective_permissions.map((permission) => (
                        <Badge key={permission} variant="outline">
                          {permission}
                        </Badge>
                      ))}
                      {userDetailQuery.data.effective_permissions.length === 0 ? (
                        <p className="text-sm text-muted-foreground">No effective permissions.</p>
                      ) : null}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="py-8 text-sm text-muted-foreground">
              Unable to load auth user details.
            </div>
          )}

          <DialogFooter>
            <Button variant="ghost" onClick={() => setManagingUserId(null)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
