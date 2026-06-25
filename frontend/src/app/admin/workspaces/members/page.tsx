"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronsUpDown, Trash2, UserPlus } from "lucide-react";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { notify } from "@/lib/notify";
import { usePermissions } from "@/hooks/usePermissions";
import { cn } from "@/lib/utils";
import { rbacService } from "@/services/rbac.service";
import workspaceService from "@/services/workspace.service";
import { WorkspaceMember } from "@/types/workspace.types";
import type { RbacRole } from "@/types/rbac.types";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from "@/components/ui/command";

function RoleMultiSelect({
  roles,
  value,
  onChange,
  disabled
}: {
  roles: RbacRole[];
  value: number[];
  onChange: (roleIds: number[]) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const selected = useMemo(() => roles.filter((role) => value.includes(role.id)), [roles, value]);

  const toggleRole = (roleId: number) => {
    onChange(value.includes(roleId) ? value.filter((id) => id !== roleId) : [...value, roleId]);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          className="w-full justify-between"
          disabled={disabled}
        >
          <span className="truncate">
            {selected.length > 0 ? selected.map((role) => role.name).join(", ") : "Select roles..."}
          </span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0">
        <Command>
          <CommandInput placeholder="Search roles..." />
          <CommandList>
            <CommandEmpty>No roles found.</CommandEmpty>
            <CommandGroup>
              {roles.map((role) => {
                const checked = value.includes(role.id);
                return (
                  <CommandItem key={role.id} value={role.name} onSelect={() => toggleRole(role.id)}>
                    <Check className={cn("mr-2 h-4 w-4", checked ? "opacity-100" : "opacity-0")} />
                    <div className="min-w-0">
                      <p className="truncate">{role.name}</p>
                      {role.description ? (
                        <p className="truncate text-xs text-muted-foreground">{role.description}</p>
                      ) : null}
                    </div>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

export default function WorkspaceMembersPage() {
  const { isSuperuser, canAccessAnyPermission } = usePermissions();
  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const getCurrentWorkspace = useWorkspaceStore((s) => s.getCurrentWorkspace);
  const workspace = getCurrentWorkspace();

  const [addMemberDraft, setAddMemberDraft] = useState<{
    workspaceId: number | null;
    userId: string;
    roleIds: number[];
  }>({ workspaceId: null, userId: "", roleIds: [] });
  const [userComboOpen, setUserComboOpen] = useState(false);

  const canCreateMembers =
    isSuperuser ||
    (currentWorkspaceId !== null &&
      canAccessAnyPermission(["workspace_member.create"], currentWorkspaceId));
  const canUpdateMembers =
    isSuperuser ||
    (currentWorkspaceId !== null &&
      canAccessAnyPermission(["workspace_member.update"], currentWorkspaceId));
  const canDeleteMembers =
    isSuperuser ||
    (currentWorkspaceId !== null &&
      canAccessAnyPermission(["workspace_member.delete"], currentWorkspaceId));

  const { data: members, refetch: refetchMembers } = useQuery({
    queryKey: ["workspace-members", currentWorkspaceId],
    queryFn: () =>
      currentWorkspaceId ? workspaceService.getMembers(currentWorkspaceId) : Promise.resolve([]),
    enabled: !!currentWorkspaceId
  });

  const { data: allUsers } = useQuery({
    queryKey: ["rbac-users", currentWorkspaceId],
    queryFn: () => rbacService.listUsersAll({ workspace_id: currentWorkspaceId ?? undefined }),
    enabled: canCreateMembers
  });

  const { data: scopedRoles } = useQuery({
    queryKey: ["workspace-rbac-roles", currentWorkspaceId],
    queryFn: () =>
      currentWorkspaceId
        ? rbacService.listRolesAll({ workspace_id: currentWorkspaceId })
        : Promise.resolve([]),
    enabled: !!currentWorkspaceId && (canCreateMembers || canUpdateMembers)
  });

  const memberRoleId = scopedRoles?.find((role) => role.name === "member")?.id;
  const addMemberUserId =
    addMemberDraft.workspaceId === currentWorkspaceId ? addMemberDraft.userId : "";
  const selectedAddRoleIds =
    addMemberDraft.workspaceId === currentWorkspaceId ? addMemberDraft.roleIds : [];
  const addMemberRoleIds =
    selectedAddRoleIds.length > 0 ? selectedAddRoleIds : memberRoleId ? [memberRoleId] : [];

  const addMemberMutation = useMutation({
    mutationFn: () =>
      workspaceService.addMember(currentWorkspaceId!, Number(addMemberUserId), addMemberRoleIds),
    onSuccess: () => {
      refetchMembers();
      queryClient.invalidateQueries({ queryKey: ["rbac-users", currentWorkspaceId] });
      setAddMemberDraft({
        workspaceId: currentWorkspaceId,
        userId: "",
        roleIds: memberRoleId ? [memberRoleId] : []
      });
      notify.success("Member added");
    }
  });

  const removeMemberMutation = useMutation({
    mutationFn: (authUserId: number) =>
      workspaceService.removeMember(currentWorkspaceId!, authUserId),
    onSuccess: () => {
      refetchMembers();
      notify.success("Member removed");
    }
  });

  const updateRolesMutation = useMutation({
    mutationFn: ({ authUserId, roleIds }: { authUserId: number; roleIds: number[] }) =>
      workspaceService.updateMemberRole(currentWorkspaceId!, authUserId, roleIds),
    onSuccess: () => {
      refetchMembers();
      notify.success("Roles updated");
    }
  });

  if (!currentWorkspaceId) {
    return (
      <div className="flex flex-col gap-6">
        <AdminPageHeader
          title="Workspace Members"
          description="Select a workspace to manage members."
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        title="Workspace Members"
        description={`Manage who has access to ${workspace?.name ?? "this workspace"} and their RBAC roles.`}
      />

      {canCreateMembers && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Add Member</CardTitle>
            <CardDescription>Grant a user access to this workspace</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2 md:grid-cols-[minmax(180px,240px)_minmax(220px,1fr)_auto]">
              <Popover open={userComboOpen} onOpenChange={setUserComboOpen}>
                <PopoverTrigger asChild>
                  <Button variant="outline" role="combobox" className="justify-between">
                    <span className="truncate">
                      {addMemberUserId
                        ? allUsers?.find((u) => u.id === Number(addMemberUserId))?.username
                        : "Select user..."}
                    </span>
                    <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-56 p-0">
                  <Command>
                    <CommandInput placeholder="Search user..." />
                    <CommandList>
                      <CommandEmpty>No users found.</CommandEmpty>
                      <CommandGroup>
                        {(allUsers ?? [])
                          .filter(
                            (u) => !members?.some((m: WorkspaceMember) => m.auth_user_id === u.id)
                          )
                          .map((u) => (
                            <CommandItem
                              key={u.id}
                              value={u.username}
                              onSelect={() => {
                                setAddMemberDraft((current) => ({
                                  workspaceId: currentWorkspaceId,
                                  userId: String(u.id),
                                  roleIds:
                                    current.workspaceId === currentWorkspaceId
                                      ? current.roleIds
                                      : addMemberRoleIds
                                }));
                                setUserComboOpen(false);
                              }}
                            >
                              <Check
                                className={cn(
                                  "mr-2 h-4 w-4",
                                  addMemberUserId === String(u.id) ? "opacity-100" : "opacity-0"
                                )}
                              />
                              {u.username}
                            </CommandItem>
                          ))}
                      </CommandGroup>
                    </CommandList>
                  </Command>
                </PopoverContent>
              </Popover>
              <RoleMultiSelect
                roles={scopedRoles ?? []}
                value={addMemberRoleIds}
                onChange={(roleIds) =>
                  setAddMemberDraft((current) => ({
                    workspaceId: currentWorkspaceId,
                    userId: current.workspaceId === currentWorkspaceId ? current.userId : "",
                    roleIds
                  }))
                }
              />
              <Button
                onClick={() => addMemberMutation.mutate()}
                disabled={
                  !addMemberUserId || addMemberRoleIds.length === 0 || addMemberMutation.isPending
                }
              >
                <UserPlus className="mr-2 h-4 w-4" />
                Add
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Members ({members?.length ?? 0})</CardTitle>
          <CardDescription>Users with access to this workspace</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border">
            <div className="grid grid-cols-[1fr_minmax(220px,360px)_40px] gap-2 items-center px-4 py-2 bg-muted/50 text-xs font-medium text-muted-foreground border-b">
              <span>User</span>
              <span>RBAC Roles</span>
              <span />
            </div>

            {members?.length === 0 && (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                No members yet. Add a user above to get started.
              </div>
            )}

            {members?.map((m: WorkspaceMember) => (
              <div
                key={m.id}
                className="grid grid-cols-[1fr_minmax(220px,360px)_40px] gap-2 items-center px-4 py-2 border-b last:border-b-0 hover:bg-muted/30 transition-colors"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {m.username ?? `User #${m.auth_user_id}`}
                  </p>
                  {m.email ? (
                    <p className="truncate text-xs text-muted-foreground">{m.email}</p>
                  ) : null}
                </div>

                {canUpdateMembers ? (
                  <RoleMultiSelect
                    roles={scopedRoles ?? []}
                    value={(m.rbac_roles ?? []).map((role) => role.id)}
                    onChange={(roleIds) =>
                      updateRolesMutation.mutate({ authUserId: m.auth_user_id, roleIds })
                    }
                    disabled={updateRolesMutation.isPending}
                  />
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {(m.rbac_roles ?? []).map((role) => (
                      <Badge key={role.id} variant="outline" className="text-xs">
                        {role.name}
                      </Badge>
                    ))}
                  </div>
                )}

                {canDeleteMembers ? (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-destructive h-8 w-8"
                    onClick={() => removeMemberMutation.mutate(m.auth_user_id)}
                    disabled={removeMemberMutation.isPending}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                ) : (
                  <span />
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
