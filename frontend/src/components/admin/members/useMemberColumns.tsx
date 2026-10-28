"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Trash2 } from "lucide-react";
import { createKebabColumn } from "@/components/data-table";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Combobox, ComboboxCheck } from "@/components/ui/combobox";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { notify } from "@/lib/notify";
import { initials } from "@/lib/utils";
import { workspaceQueryKeys } from "@/lib/workspace/query-keys";
import workspaceService from "@/services/workspace.service";
import type { RbacRole } from "@/types/rbac.types";
import type { WorkspaceMember } from "@/types/workspace.types";
import { useTranslations } from "next-intl";

import { memberLabel, sortRoles, useRoleLabel } from "./model";

/**
 * Every role the member holds, edited as the set the backend stores: a click
 * grants or revokes that one role and leaves the rest alone.
 */
function MemberRolesCell({
  member,
  workspaceId,
  roles
}: Readonly<{ member: WorkspaceMember; workspaceId: number; roles: readonly RbacRole[] }>) {
  const t = useTranslations("adminAccess.common");
  const tw = useTranslations("adminAccess.workspace");
  const tm = useTranslations("adminAccess.member");
  const roleLabel = useRoleLabel();
  const queryClient = useQueryClient();
  const held = member.rbac_roles.map((role) => role.id);

  const update = useMutation({
    mutationFn: (roleIds: number[]) =>
      workspaceService.updateMemberRole(workspaceId, member.auth_user_id, roleIds),
    // Pending until the list has refetched: the next click must start from the
    // saved set, not from this row's stale one.
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: workspaceQueryKeys.memberList(workspaceId) });
      notify.success(tw("rolesUpdated"));
    },
    onError: (error) => notify.apiError(error)
  });

  const toggle = (roleId: number) =>
    update.mutate(held.includes(roleId) ? held.filter((id) => id !== roleId) : [...held, roleId]);

  return (
    <Combobox
      label={held.length > 0 ? sortRoles(member.rbac_roles).map(roleLabel).join(" · ") : undefined}
      placeholder={t("noRole")}
      triggerAriaLabel={tm("userRoles", { member: memberLabel(member) })}
      size="sm"
      triggerClassName="w-auto max-w-full gap-2"
      searchPlaceholder={t("searchRoles")}
      emptyMessage={tm("noRolesMatch")}
    >
      <CommandGroup>
        {roles.map((role) => (
          <CommandItem
            key={role.id}
            value={roleLabel(role)}
            disabled={update.isPending}
            onSelect={() => toggle(role.id)}
          >
            <div className="min-w-0 flex-1">
              <p className="truncate">{roleLabel(role)}</p>
              {!role.is_system && role.description ? (
                <p className="truncate text-xs text-muted-foreground">{role.description}</p>
              ) : null}
            </div>
            <ComboboxCheck selected={held.includes(role.id)} />
          </CommandItem>
        ))}
      </CommandGroup>
    </Combobox>
  );
}

export function useMemberColumns({
  workspaceId,
  roles,
  canUpdateMembers,
  canDeleteMembers,
  requestRemoval
}: Readonly<{
  workspaceId: number;
  /** The workspace's roles, already in display order. */
  roles: readonly RbacRole[];
  canUpdateMembers: boolean;
  canDeleteMembers: boolean;
  requestRemoval: (member: WorkspaceMember) => void;
}>): ColumnDef<WorkspaceMember>[] {
  const t = useTranslations("adminAccess.common");
  const tm = useTranslations("adminAccess.member");
  const tk = useTranslations("kit.authUser");
  const roleLabel = useRoleLabel();

  return useMemo<ColumnDef<WorkspaceMember>[]>(() => {
    const cols: ColumnDef<WorkspaceMember>[] = [
      {
        id: "user",
        header: t("user"),
        enableSorting: true,
        cell: ({ row }) => {
          const member = row.original;
          return (
            <div className="flex items-center gap-3 min-w-0">
              <Avatar className="size-8 shrink-0">
                {member.avatar_url ? <AvatarImage src={member.avatar_url} alt="" /> : null}
                <AvatarFallback>{initials(memberLabel(member))}</AvatarFallback>
              </Avatar>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-foreground">
                  {member.username ?? tk("userId", { id: member.auth_user_id })}
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
        header: t("role"),
        size: 340,
        enableSorting: true,
        // Editing stays in the cell -- the one deliberate exception to "details
        // go in a dialog or an inspector": changing roles is the whole reason
        // this screen is opened.
        cell: ({ row }) => {
          const member = row.original;
          if (!canUpdateMembers) {
            return member.rbac_roles.length === 0 ? null : (
              <span className="text-sm text-muted-foreground">
                {sortRoles(member.rbac_roles).map(roleLabel).join(" · ")}
              </span>
            );
          }
          return <MemberRolesCell member={member} workspaceId={workspaceId} roles={roles} />;
        }
      }
    ];

    cols.push(
      createKebabColumn<WorkspaceMember>(
        (member) => [
          {
            label: tm("remove"),
            icon: Trash2,
            destructive: true,
            hidden: !canDeleteMembers,
            onSelect: () => requestRemoval(member)
          }
        ],
        { rowLabel: memberLabel }
      )
    );
    return cols;
  }, [workspaceId, roles, canUpdateMembers, canDeleteMembers, requestRemoval, roleLabel, t, tm, tk]);
}
