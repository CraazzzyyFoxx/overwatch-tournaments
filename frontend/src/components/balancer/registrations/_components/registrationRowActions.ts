import { Check, History, Pencil, ShieldX, Trash2, Undo2, X } from "lucide-react";

import type { KebabAction } from "@/components/data-table";
import type { AppPermission } from "@/hooks/usePermissions";
import type { AdminRegistration } from "@/types/balancer-admin.types";

export interface RegistrationRowActionHandlers {
  /** The row carries its own workspace, which is the scope its edits were
   *  authorized against — closer to the truth than the ambient selection. */
  canAccessPermission: (permission: AppPermission, workspaceId: number) => boolean;
  openAuditTrail: (input: {
    entityType: "registration";
    entityId: number;
    workspaceId: number;
  }) => void;
  approve: (registrationId: number) => void;
  reject: (registrationId: number) => void;
  withdraw: (registrationId: number) => void;
  restore: (registrationId: number) => void;
  setBalancerInclusion: (input: { registrationId: number; include: boolean }) => void;
  setCheckIn: (input: { registrationId: number; checkedIn: boolean }) => void;
  onEdit: (registration: AdminRegistration) => void;
  onDelete: (registration: AdminRegistration) => void;
}

/** The kebab menu of one registration row, gated by its own status and scope. */
export function buildRegistrationRowActions(
  registration: AdminRegistration,
  handlers: RegistrationRowActionHandlers
): KebabAction[] {
  const inBalancer = !registration.balancer_status_meta.excludes_from_balancer;
  const isWithdrawn = registration.status === "withdrawn";
  const isPending = registration.status === "pending";
  // A custom status is organizer-defined and behaves like `approved` for
  // balancer inclusion, which is why both reach the same two actions.
  const isManageable =
    registration.status === "approved" || registration.status_meta.kind === "custom";

  return [
    {
      label: "Edit",
      icon: Pencil,
      hidden: isWithdrawn,
      onSelect: () => handlers.onEdit(registration)
    },
    {
      label: "Change history",
      icon: History,
      hidden: !handlers.canAccessPermission("audit.read", registration.workspace_id),
      onSelect: () =>
        handlers.openAuditTrail({
          entityType: "registration",
          entityId: registration.id,
          workspaceId: registration.workspace_id
        })
    },
    {
      label: "Approve",
      icon: Check,
      hidden: !isPending,
      onSelect: () => handlers.approve(registration.id)
    },
    {
      label: "Reject",
      icon: X,
      hidden: !isPending,
      onSelect: () => handlers.reject(registration.id)
    },
    {
      label: inBalancer ? "Remove from balancer" : "Add to balancer",
      icon: inBalancer ? ShieldX : Check,
      hidden: !isManageable,
      onSelect: () =>
        handlers.setBalancerInclusion({ registrationId: registration.id, include: !inBalancer })
    },
    {
      label: registration.checked_in ? "Uncheck-in" : "Check-in",
      icon: Check,
      hidden: !isManageable,
      onSelect: () =>
        handlers.setCheckIn({
          registrationId: registration.id,
          checkedIn: !registration.checked_in
        })
    },
    {
      label: "Restore",
      icon: Undo2,
      hidden: !isWithdrawn,
      onSelect: () => handlers.restore(registration.id)
    },
    {
      label: "Withdraw",
      icon: Undo2,
      hidden: isWithdrawn,
      onSelect: () => handlers.withdraw(registration.id)
    },
    {
      label: "Delete",
      icon: Trash2,
      destructive: true,
      onSelect: () => handlers.onDelete(registration)
    }
  ];
}
