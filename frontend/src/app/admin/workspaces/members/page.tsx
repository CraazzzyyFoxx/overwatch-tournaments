"use client";

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Check, ChevronsUpDown, Trash2, UserPlus, Wand2 } from "lucide-react";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { usePermissions } from "@/hooks/usePermissions";
import { rbacService } from "@/services/rbac.service";
import workspaceService from "@/services/workspace.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { RbacRole } from "@/types/rbac.types";
import type { WorkspaceMember, WorkspaceSystemRole } from "@/types/workspace.types";

const SYSTEM_ROLES: WorkspaceSystemRole[] = ["owner", "admin", "member", "player"];
const SYSTEM_ROLE_LABEL: Record<WorkspaceSystemRole, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
  player: "Player"
};

function isSystemRoleName(name: string): name is WorkspaceSystemRole {
  return (SYSTEM_ROLES as string[]).includes(name);
}

function initials(member: WorkspaceMember): string {
  const source = member.username || member.email || `#${member.auth_user_id}`;
  return source.slice(0, 2).toUpperCase();
}

/** The custom (non-system) role ids currently held by a member. */
function memberCustomRoleIds(member: WorkspaceMember): number[] {
  return member.rbac_roles.filter((role) => !role.is_system).map((role) => role.id);
}

export default function WorkspaceMembersPage() {
  const { isSuperuser, canAccessAnyPermission } = usePermissions();
  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const getCurrentWorkspace = useWorkspaceStore((s) => s.getCurrentWorkspace);
  const workspace = getCurrentWorkspace();

  const [addOpen, setAddOpen] = useState(false);

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

  const { data: scopedRoles } = useQuery({
    queryKey: ["workspace-rbac-roles", currentWorkspaceId],
    queryFn: () =>
      currentWorkspaceId
        ? rbacService.listRolesAll({ workspace_id: currentWorkspaceId })
        : Promise.resolve([]),
    enabled: !!currentWorkspaceId && (canCreateMembers || canUpdateMembers)
  });

  const systemRoleId = useCallback(
    (name: WorkspaceSystemRole): number | undefined =>
      scopedRoles?.find((role) => role.name === name)?.id,
    [scopedRoles]
  );
  const customScopedRoles: RbacRole[] = useMemo(
    () => (scopedRoles ?? []).filter((role) => !isSystemRoleName(role.name)),
    [scopedRoles]
  );

  const invalidateMembers = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["workspace-members", currentWorkspaceId] });
  }, [queryClient, currentWorkspaceId]);

  const updateRolesMutation = useMutation({
    mutationFn: ({ authUserId, roleIds }: { authUserId: number; roleIds: number[] }) =>
      workspaceService.updateMemberRole(currentWorkspaceId!, authUserId, roleIds),
    onSuccess: () => {
      invalidateMembers();
      notify.success("Roles updated");
    },
    onError: (error) => notify.apiError(error)
  });

  const removeMemberMutation = useMutation({
    mutationFn: (authUserId: number) => workspaceService.removeMember(currentWorkspaceId!, authUserId),
    onSuccess: () => {
      invalidateMembers();
      notify.success("Member removed");
    },
    onError: (error) => notify.apiError(error)
  });

  const autofillMutation = useMutation({
    mutationFn: () => workspaceService.autofillMemberRoles(currentWorkspaceId!),
    onSuccess: ({ assigned }) => {
      invalidateMembers();
      notify.success(
        assigned > 0
          ? `Assigned "member" to ${assigned} member${assigned === 1 ? "" : "s"} without a role`
          : "Everyone already has a role"
      );
    },
    onError: (error) => notify.apiError(error)
  });

  const changePrimaryRole = useCallback(
    (member: WorkspaceMember, nextRole: WorkspaceSystemRole) => {
      if (nextRole === member.role) return;
      const sysId = systemRoleId(nextRole);
      if (sysId == null) {
        notify.error("That workspace role is not configured yet");
        return;
      }
      updateRolesMutation.mutate({
        authUserId: member.auth_user_id,
        roleIds: [sysId, ...memberCustomRoleIds(member)]
      });
    },
    [systemRoleId, updateRolesMutation]
  );

  const toggleCustomRole = useCallback(
    (member: WorkspaceMember, roleId: number) => {
      const current = new Set(memberCustomRoleIds(member));
      if (current.has(roleId)) current.delete(roleId);
      else current.add(roleId);
      const sysId = systemRoleId(member.role);
      updateRolesMutation.mutate({
        authUserId: member.auth_user_id,
        roleIds: [...(sysId != null ? [sysId] : []), ...current]
      });
    },
    [systemRoleId, updateRolesMutation]
  );

  const columns = useMemo<ColumnDef<WorkspaceMember>[]>(() => {
    const cols: ColumnDef<WorkspaceMember>[] = [
      {
        id: "user",
        header: "User",
        cell: ({ row }) => {
          const member = row.original;
          return (
            <div className="flex items-center gap-3 min-w-0">
              <Avatar className="size-8 shrink-0">
                {member.avatar_url ? <AvatarImage src={member.avatar_url} alt="" /> : null}
                <AvatarFallback className="text-[11px]">{initials(member)}</AvatarFallback>
              </Avatar>
              <div className="min-w-0">
                <p className="truncate text-[13px] font-medium text-foreground">
                  {member.username ?? `User #${member.auth_user_id}`}
                </p>
                {member.email ? (
                  <p className="truncate text-[12px] text-muted-foreground">{member.email}</p>
                ) : null}
              </div>
            </div>
          );
        }
      },
      {
        id: "role",
        header: "Role",
        size: 340,
        cell: ({ row }) => {
          const member = row.original;
          const customCount = memberCustomRoleIds(member).length;
          if (!canUpdateMembers) {
            return (
              <div className="flex flex-wrap gap-1.5">
                {member.rbac_roles.length === 0 ? (
                  <span className="text-[12px] text-muted-foreground/60">No roles</span>
                ) : (
                  member.rbac_roles.map((role) => (
                    <Badge key={role.id} variant="outline" className="text-[11px]">
                      {role.name}
                    </Badge>
                  ))
                )}
              </div>
            );
          }
          return (
            <div className="flex items-center gap-2">
              <Select
                value={member.role}
                onValueChange={(value) => changePrimaryRole(member, value as WorkspaceSystemRole)}
              >
                <SelectTrigger className="h-8 w-[130px] text-[13px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SYSTEM_ROLES.map((name) => (
                    <SelectItem key={name} value={name} className="text-[13px]">
                      {SYSTEM_ROLE_LABEL[name]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {customScopedRoles.length > 0 ? (
                <Popover>
                  <PopoverTrigger asChild>
                    <Button variant="outline" size="sm" className="h-8 gap-1 text-[12px]">
                      + custom
                      {customCount > 0 ? (
                        <Badge variant="secondary" className="ml-0.5 h-4 px-1 text-[10px]">
                          {customCount}
                        </Badge>
                      ) : null}
                      <ChevronsUpDown className="size-3 opacity-50" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-64 p-0" align="start">
                    <Command>
                      <CommandInput placeholder="Search custom roles..." />
                      <CommandList>
                        <CommandEmpty>No custom roles.</CommandEmpty>
                        <CommandGroup>
                          {customScopedRoles.map((role) => {
                            const checked = memberCustomRoleIds(member).includes(role.id);
                            return (
                              <CommandItem
                                key={role.id}
                                value={role.name}
                                onSelect={() => toggleCustomRole(member, role.id)}
                              >
                                <Check
                                  className={cn(
                                    "mr-2 size-4",
                                    checked ? "opacity-100" : "opacity-0"
                                  )}
                                />
                                <div className="min-w-0">
                                  <p className="truncate">{role.name}</p>
                                  {role.description ? (
                                    <p className="truncate text-xs text-muted-foreground">
                                      {role.description}
                                    </p>
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
              ) : null}
            </div>
          );
        }
      }
    ];

    if (canDeleteMembers) {
      cols.push({
        id: "actions",
        header: "",
        cell: ({ row }) => (
          <Button
            variant="ghost"
            size="icon"
            className="size-8 text-destructive"
            disabled={removeMemberMutation.isPending}
            onClick={() => removeMemberMutation.mutate(row.original.auth_user_id)}
            aria-label="Remove member"
          >
            <Trash2 className="size-3.5" />
          </Button>
        )
      });
    }
    return cols;
  }, [
    canUpdateMembers,
    canDeleteMembers,
    customScopedRoles,
    changePrimaryRole,
    toggleCustomRole,
    removeMemberMutation
  ]);

  if (!currentWorkspaceId) {
    return (
      <div className="flex flex-col gap-6">
        <AdminPageHeader title="Workspace Members" description="Select a workspace to manage members." />
      </div>
    );
  }

  const tableActions = (
    <>
      {canUpdateMembers ? (
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          disabled={autofillMutation.isPending}
          onClick={() => autofillMutation.mutate()}
        >
          <Wand2 className="size-3.5" />
          Fill missing roles
        </Button>
      ) : null}
      {canCreateMembers ? (
        <Button size="sm" className="gap-1.5" onClick={() => setAddOpen(true)}>
          <UserPlus className="size-3.5" />
          Add member
        </Button>
      ) : null}
    </>
  );

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        title="Workspace Members"
        description={`Manage who has access to ${workspace?.name ?? "this workspace"} and their RBAC roles.`}
      />

      <AdminDataTable<WorkspaceMember>
        queryKey={(page, search, pageSize) => [
          "workspace-members",
          currentWorkspaceId,
          { page, search, pageSize }
        ]}
        queryFn={(page, search, pageSize) =>
          workspaceService.getMembers(currentWorkspaceId, {
            page,
            per_page: pageSize,
            search
          })
        }
        columns={columns}
        initialPageSize={25}
        searchPlaceholder="Search by name or email..."
        emptyMessage="No members yet."
        actions={tableActions}
      />

      {canCreateMembers ? (
        <AddMemberDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          workspaceId={currentWorkspaceId}
          scopedRoles={scopedRoles ?? []}
          defaultRoleId={systemRoleId("member")}
          onAdded={() => {
            invalidateMembers();
            setAddOpen(false);
          }}
        />
      ) : null}
    </div>
  );
}

function AddMemberDialog({
  open,
  onOpenChange,
  workspaceId,
  scopedRoles,
  defaultRoleId,
  onAdded
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: number;
  scopedRoles: RbacRole[];
  defaultRoleId?: number;
  onAdded: () => void;
}) {
  const [userId, setUserId] = useState<string>("");
  const [roleIds, setRoleIds] = useState<number[]>([]);
  const [userComboOpen, setUserComboOpen] = useState(false);

  const effectiveRoleIds = roleIds.length > 0 ? roleIds : defaultRoleId != null ? [defaultRoleId] : [];

  const { data: allUsers } = useQuery({
    queryKey: ["rbac-users", workspaceId, "all"],
    queryFn: () => rbacService.listUsersAll({ workspace_id: workspaceId }),
    enabled: open
  });

  const addMemberMutation = useMutation({
    mutationFn: () => workspaceService.addMember(workspaceId, Number(userId), effectiveRoleIds),
    onSuccess: () => {
      setUserId("");
      setRoleIds([]);
      notify.success("Member added");
      onAdded();
    },
    onError: (error) => notify.apiError(error)
  });

  const selectedUsername = allUsers?.find((u) => u.id === Number(userId))?.username;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Add member</DialogTitle>
          <DialogDescription>
            Grant a user access to this workspace. Use this for people who have not played yet
            (e.g. staff/administrators) — players who registered are added automatically.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <Popover open={userComboOpen} onOpenChange={setUserComboOpen}>
            <PopoverTrigger asChild>
              <Button variant="outline" role="combobox" className="justify-between">
                <span className="truncate">{selectedUsername ?? "Select user..."}</span>
                <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0">
              <Command>
                <CommandInput placeholder="Search user..." />
                <CommandList>
                  <CommandEmpty>No users found.</CommandEmpty>
                  <CommandGroup>
                    {(allUsers ?? []).map((u) => (
                      <CommandItem
                        key={u.id}
                        value={u.username}
                        onSelect={() => {
                          setUserId(String(u.id));
                          setUserComboOpen(false);
                        }}
                      >
                        <Check
                          className={cn(
                            "mr-2 size-4",
                            userId === String(u.id) ? "opacity-100" : "opacity-0"
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
            roles={scopedRoles}
            value={effectiveRoleIds}
            onChange={setRoleIds}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => addMemberMutation.mutate()}
            disabled={!userId || effectiveRoleIds.length === 0 || addMemberMutation.isPending}
          >
            Add
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RoleMultiSelect({
  roles,
  value,
  onChange
}: {
  roles: RbacRole[];
  value: number[];
  onChange: (roleIds: number[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const selected = useMemo(() => roles.filter((role) => value.includes(role.id)), [roles, value]);

  const toggleRole = (roleId: number) => {
    onChange(value.includes(roleId) ? value.filter((id) => id !== roleId) : [...value, roleId]);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" role="combobox" className="w-full justify-between">
          <span className="truncate">
            {selected.length > 0 ? selected.map((role) => role.name).join(", ") : "Select roles..."}
          </span>
          <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0">
        <Command>
          <CommandInput placeholder="Search roles..." />
          <CommandList>
            <CommandEmpty>No roles found.</CommandEmpty>
            <CommandGroup>
              {roles.map((role) => {
                const checked = value.includes(role.id);
                return (
                  <CommandItem key={role.id} value={role.name} onSelect={() => toggleRole(role.id)}>
                    <Check className={cn("mr-2 size-4", checked ? "opacity-100" : "opacity-0")} />
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
