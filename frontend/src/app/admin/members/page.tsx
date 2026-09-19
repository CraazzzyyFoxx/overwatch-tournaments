"use client";

import { useCallback, useId, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Check, ChevronsUpDown, Trash2, UserPlus, Wand2 } from "lucide-react";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminDataTable, createKebabColumn } from "@/components/data-table";
import { AdminFilterBar } from "@/components/kit/AdminFilterBar";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { useAdminFilters, type FilterDef } from "@/components/kit/useAdminFilters";
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
import { Label } from "@/components/ui/label";
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

const SYSTEM_ROLES: WorkspaceSystemRole[] = ["owner", "admin", "host", "member", "player"];
const SYSTEM_ROLE_LABEL: Record<WorkspaceSystemRole, string> = {
  owner: "Owner",
  admin: "Admin",
  host: "Host",
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

/** Best human-readable handle for a member, used in control names and confirmations. */
function memberLabel(member: WorkspaceMember): string {
  return member.username ?? member.email ?? `User #${member.auth_user_id}`;
}

/** The custom (non-system) role ids currently held by a member. */
function memberCustomRoleIds(member: WorkspaceMember): number[] {
  return member.rbac_roles.filter((role) => !role.is_system).map((role) => role.id);
}

/**
 * Highest-priority system role a member holds, mirroring the backend's RBAC
 * derivation. `undefined` when the member holds no system role at all -- a real
 * state the "Fill missing roles" action exists to repair.
 */
export function memberPrimaryRole(member: WorkspaceMember): WorkspaceSystemRole | undefined {
  return SYSTEM_ROLES.find((name) =>
    member.rbac_roles.some((role) => role.is_system && role.name === name)
  );
}

export default function WorkspaceMembersPage() {
  const { isSuperuser, canAccessAnyPermission } = usePermissions();
  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const getCurrentWorkspace = useWorkspaceStore((s) => s.getCurrentWorkspace);
  const workspace = getCurrentWorkspace();

  const [addOpen, setAddOpen] = useState(false);
  const [pendingRemoval, setPendingRemoval] = useState<WorkspaceMember | null>(null);

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

  // One chip: every role scoped to this workspace, system and custom alike,
  // carrying the `role_id` the members endpoint takes. Declared even while the
  // catalogue is still loading, so `?role=` in the URL is read on mount.
  const filterDefs = useMemo<FilterDef[]>(
    () => [
      {
        key: "role",
        label: "Role",
        kind: "single",
        options: (scopedRoles ?? []).map((role) => ({ value: String(role.id), label: role.name }))
      }
    ],
    [scopedRoles]
  );
  const filters = useAdminFilters(filterDefs);
  const roleFilter = String(filters.values.role ?? "");

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
      setPendingRemoval(null);
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
      if (nextRole === memberPrimaryRole(member)) return;
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
      const primary = memberPrimaryRole(member);
      const sysId = primary != null ? systemRoleId(primary) : undefined;
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
        enableSorting: true,
        cell: ({ row }) => {
          const member = row.original;
          return (
            <div className="flex items-center gap-3 min-w-0">
              <Avatar className="size-8 shrink-0">
                {member.avatar_url ? <AvatarImage src={member.avatar_url} alt="" /> : null}
                <AvatarFallback className="text-xs">{initials(member)}</AvatarFallback>
              </Avatar>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-foreground">
                  {member.username ?? `User #${member.auth_user_id}`}
                </p>
                {member.email ? (
                  <p className="truncate text-xs text-muted-foreground">{member.email}</p>
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
        enableSorting: true,
        // Editing stays in the cell -- the one deliberate exception to "details
        // go in a dialog or an inspector": two fields, and changing a role is
        // the whole reason this screen is opened.
        cell: ({ row }) => {
          const member = row.original;
          const customCount = memberCustomRoleIds(member).length;
          if (!canUpdateMembers) {
            return (
              <div className="flex flex-wrap gap-1.5">
                {member.rbac_roles.length === 0 ? (
                  <span className="text-xs text-muted-foreground">No roles</span>
                ) : (
                  member.rbac_roles.map((role) => (
                    <Badge key={role.id} variant="outline" className="text-xs">
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
                value={memberPrimaryRole(member)}
                onValueChange={(value) => changePrimaryRole(member, value as WorkspaceSystemRole)}
              >
                <SelectTrigger
                  className="h-8 w-32 text-sm"
                  aria-label={`Workspace role for ${memberLabel(member)}`}
                >
                  <SelectValue placeholder="No role" />
                </SelectTrigger>
                <SelectContent>
                  {SYSTEM_ROLES.map((name) => (
                    <SelectItem key={name} value={name} className="text-sm">
                      {SYSTEM_ROLE_LABEL[name]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {customScopedRoles.length > 0 ? (
                <Popover>
                  <PopoverTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 gap-1 text-xs"
                      aria-label={`Custom roles for ${memberLabel(member)}`}
                    >
                      + custom
                      {customCount > 0 ? (
                        <Badge
                          variant="secondary"
                          className="ml-0.5 h-4 px-1 text-xs tabular-nums"
                        >
                          {customCount}
                        </Badge>
                      ) : null}
                      <ChevronsUpDown aria-hidden className="size-3 opacity-50" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-64 p-0" align="start">
                    <Command>
                      <CommandInput placeholder="Search custom roles…" />
                      <CommandList>
                        <CommandEmpty>No custom roles match that search.</CommandEmpty>
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
                                  aria-hidden
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

    cols.push(
      createKebabColumn<WorkspaceMember>(
        (member) => [
          {
            label: "Remove from workspace",
            icon: Trash2,
            destructive: true,
            hidden: !canDeleteMembers,
            onSelect: () => setPendingRemoval(member)
          }
        ],
        { rowLabel: memberLabel }
      )
    );
    return cols;
  }, [canUpdateMembers, canDeleteMembers, customScopedRoles, changePrimaryRole, toggleCustomRole]);

  // Exclusive branch: no workspace selected means the table below never renders,
  // so this header is the page's only `<h1>`.
  if (!currentWorkspaceId) {
    return (
      <div className="flex flex-col gap-6">
        <AdminPageHeader
          title="Workspace members"
          description="Pick a workspace from the switcher above to see and manage its members."
        />
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
          <Wand2 aria-hidden className="size-3.5" />
          Fill missing roles
        </Button>
      ) : null}
      {canCreateMembers ? (
        <Button size="sm" className="gap-1.5" onClick={() => setAddOpen(true)}>
          <UserPlus aria-hidden className="size-3.5" />
          Add member
        </Button>
      ) : null}
    </>
  );

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        title="Workspace members"
        description={`Manage who has access to ${workspace?.name ?? "this workspace"} and their RBAC roles.`}
      />

      <AdminDataTable<WorkspaceMember>
        queryKey={(page, search, pageSize, sortField, sortDir) => [
          "workspace-members",
          currentWorkspaceId,
          { page, search, pageSize, sortField, sortDir, roleId: roleFilter || null }
        ]}
        queryFn={(page, search, pageSize, sortField, sortDir) =>
          workspaceService.getMembers(currentWorkspaceId, {
            page,
            per_page: pageSize,
            search,
            role_id: roleFilter ? Number(roleFilter) : null,
            sort: sortField === "role" ? "role" : "username",
            order: sortDir
          })
        }
        columns={columns}
        initialPageSize={25}
        searchPlaceholder="Search by name or email…"
        filterKey={filters.filterKey}
        getRowId={(row) => String(row.auth_user_id)}
        toolbar={<AdminFilterBar defs={filterDefs} filters={filters} />}
        emptyMessage="No members yet. Add staff and administrators here — players who register for a tournament are added automatically."
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

      <ConfirmDialog
        open={pendingRemoval !== null}
        onOpenChange={(open) => (open ? null : setPendingRemoval(null))}
        intent={{
          title: "Remove member",
          description: pendingRemoval
            ? `${memberLabel(pendingRemoval)} loses access to ${workspace?.name ?? "this workspace"} and all roles granted here. Their tournament results are kept, and you can add them back later.`
            : "",
          confirmLabel: "Remove member",
          tone: "danger"
        }}
        onConfirm={() => {
          if (pendingRemoval) removeMemberMutation.mutate(pendingRemoval.auth_user_id);
        }}
        pending={removeMemberMutation.isPending}
      />
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
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: number;
  scopedRoles: RbacRole[];
  defaultRoleId?: number;
  onAdded: () => void;
}>) {
  const userFieldId = useId();
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

  // Validated on submit rather than by disabling the button, so the reason the
  // form will not go through is spoken instead of silently greyed out.
  const submit = () => {
    if (!userId) {
      notify.error("Pick the user you want to add first.");
      return;
    }
    if (effectiveRoleIds.length === 0) {
      notify.error("Pick at least one role for this member.");
      return;
    }
    addMemberMutation.mutate();
  };

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
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={userFieldId}>User</Label>
            <Popover open={userComboOpen} onOpenChange={setUserComboOpen}>
              <PopoverTrigger asChild>
                <Button
                  id={userFieldId}
                  variant="outline"
                  role="combobox"
                  aria-haspopup="listbox"
                  aria-expanded={userComboOpen}
                  className="justify-between"
                >
                  <span className="truncate">{selectedUsername ?? "Select user…"}</span>
                  <ChevronsUpDown aria-hidden className="ml-2 size-4 shrink-0 opacity-50" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0">
                <Command>
                  <CommandInput placeholder="Search user…" />
                  <CommandList>
                    <CommandEmpty>No user matches that search.</CommandEmpty>
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
                            aria-hidden
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
          </div>

          <RoleMultiSelect roles={scopedRoles} value={effectiveRoleIds} onChange={setRoleIds} />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={addMemberMutation.isPending}>
            {addMemberMutation.isPending ? "Adding…" : "Add member"}
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
}: Readonly<{
  roles: RbacRole[];
  value: number[];
  onChange: (roleIds: number[]) => void;
}>) {
  const fieldId = useId();
  const [open, setOpen] = useState(false);
  const selected = useMemo(() => roles.filter((role) => value.includes(role.id)), [roles, value]);

  const toggleRole = (roleId: number) => {
    onChange(value.includes(roleId) ? value.filter((id) => id !== roleId) : [...value, roleId]);
  };

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={fieldId}>Roles</Label>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            id={fieldId}
            variant="outline"
            role="combobox"
            aria-haspopup="listbox"
            aria-expanded={open}
            className="w-full justify-between"
          >
            <span className="truncate">
              {selected.length > 0 ? selected.map((role) => role.name).join(", ") : "Select roles…"}
            </span>
            <ChevronsUpDown aria-hidden className="ml-2 size-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0">
          <Command>
            <CommandInput placeholder="Search roles…" />
            <CommandList>
              <CommandEmpty>No role matches that search.</CommandEmpty>
              <CommandGroup>
                {roles.map((role) => {
                  const checked = value.includes(role.id);
                  return (
                    <CommandItem key={role.id} value={role.name} onSelect={() => toggleRole(role.id)}>
                      <Check
                        aria-hidden
                        className={cn("mr-2 size-4", checked ? "opacity-100" : "opacity-0")}
                      />
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
    </div>
  );
}
