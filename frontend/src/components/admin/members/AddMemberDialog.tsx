"use client";

import { useId, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AuthUserSearchCombobox, type AuthUserOption } from "@/components/kit/UserSearchCombobox";
import { EntityFormDialog } from "@craazzzyyfoxx/admin-kit/kit/EntityFormDialog";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@craazzzyyfoxx/admin-kit/ui/select";
import { notify } from "@/lib/notify";
import workspaceService from "@/services/workspace.service";
import type { WorkspaceSystemRole } from "@/types/workspace.types";
import { useTranslations } from "next-intl";

import { SYSTEM_ROLES } from "./model";

export function AddMemberDialog({
  open,
  onOpenChange,
  workspaceId,
  systemRoleId,
  onAdded
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: number;
  systemRoleId: (name: WorkspaceSystemRole) => number | undefined;
  onAdded: () => void;
}>) {
  const t = useTranslations("adminAccess.common");
  const tw = useTranslations("adminAccess.workspace");
  const tm = useTranslations("adminAccess.member");
  const userFieldId = useId();
  const roleFieldId = useId();
  const [user, setUser] = useState<AuthUserOption | null>(null);
  // One system role to start with; any further roles are added from the row's editor.
  const [role, setRole] = useState<WorkspaceSystemRole>("player");

  const addMemberMutation = useMutation({
    mutationFn: ({ userId, roleId }: { userId: number; roleId: number }) =>
      workspaceService.addMember(workspaceId, userId, roleId),
    onSuccess: () => {
      setUser(null);
      setRole("player");
      notify.success(tw("memberAdded"));
      onAdded();
    },
    onError: (error) => notify.apiError(error)
  });

  // Validated on submit rather than by disabling the button, so the reason the
  // form will not go through is spoken instead of silently greyed out.
  const submit = () => {
    if (!user) {
      notify.error(tw("pickUser"));
      return;
    }
    const roleId = systemRoleId(role);
    if (roleId == null) {
      notify.error(tw("roleNotConfigured"));
      return;
    }
    addMemberMutation.mutate({ userId: user.id, roleId });
  };

  return (
    <EntityFormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("addMember")}
      description={tm("addDescription")}
      onSubmit={submit}
      submitLabel={t("addMember")}
      submittingLabel={tm("adding")}
      isSubmitting={addMemberMutation.isPending}
      contentClassName="max-w-md"
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={userFieldId}>{t("user")}</Label>
        <AuthUserSearchCombobox
          id={userFieldId}
          workspaceId={workspaceId}
          value={user?.id}
          selectedLabel={user?.label}
          onSelect={(picked) => setUser(picked ?? null)}
          placeholder={tm("selectUser")}
          searchPlaceholder={t("searchUser")}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={roleFieldId}>{t("role")}</Label>
        <Select value={role} onValueChange={(value) => setRole(value as WorkspaceSystemRole)}>
          <SelectTrigger id={roleFieldId}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SYSTEM_ROLES.map((name) => (
              <SelectItem key={name} value={name}>
                {tm(`${name}Role`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </EntityFormDialog>
  );
}
