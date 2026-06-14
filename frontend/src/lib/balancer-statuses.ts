import type { BalancerCustomStatus, StatusMeta, StatusScope } from "@/types/balancer-admin.types";

const BUILTIN_STATUS_META: Record<StatusScope, StatusMeta[]> = {
  registration: [
    {
      value: "pending",
      scope: "registration",
      is_builtin: true,
      kind: "builtin",
      is_override: false,
      can_edit: true,
      can_delete: false,
      can_reset: false,
      icon_slug: "Clock",
      icon_color: "#f59e0b",
      name: "Pending",
      description: "Waiting for moderator review.",
    },
    {
      value: "approved",
      scope: "registration",
      is_builtin: true,
      kind: "builtin",
      is_override: false,
      can_edit: true,
      can_delete: false,
      can_reset: false,
      icon_slug: "CheckCircle2",
      icon_color: "#10b981",
      name: "Approved",
      description: "Registration approved.",
    },
    {
      value: "rejected",
      scope: "registration",
      is_builtin: true,
      kind: "builtin",
      is_override: false,
      can_edit: true,
      can_delete: false,
      can_reset: false,
      icon_slug: "XCircle",
      icon_color: "#ef4444",
      name: "Rejected",
      description: "Registration rejected.",
    },
    {
      value: "withdrawn",
      scope: "registration",
      is_builtin: true,
      kind: "builtin",
      is_override: false,
      can_edit: true,
      can_delete: false,
      can_reset: false,
      icon_slug: "Undo2",
      icon_color: "#94a3b8",
      name: "Withdrawn",
      description: "Registration withdrawn.",
    },
    {
      value: "banned",
      scope: "registration",
      is_builtin: true,
      kind: "builtin",
      is_override: false,
      can_edit: true,
      can_delete: false,
      can_reset: false,
      icon_slug: "ShieldBan",
      icon_color: "#ef4444",
      name: "Banned",
      description: "Registration blocked.",
    },
    {
      value: "insufficient_data",
      scope: "registration",
      is_builtin: true,
      kind: "builtin",
      is_override: false,
      can_edit: true,
      can_delete: false,
      can_reset: false,
      icon_slug: "AlertTriangle",
      icon_color: "#f97316",
      name: "Incomplete",
      description: "Registration data is incomplete.",
    },
  ],
  balancer: [
    {
      value: "not_in_balancer",
      scope: "balancer",
      is_builtin: true,
      kind: "builtin",
      is_override: false,
      can_edit: true,
      can_delete: false,
      can_reset: false,
      icon_slug: "MinusCircle",
      icon_color: "#94a3b8",
      name: "Not Added",
      description: "Registration is excluded from balancer.",
    },
    {
      value: "incomplete",
      scope: "balancer",
      is_builtin: true,
      kind: "builtin",
      is_override: false,
      can_edit: true,
      can_delete: false,
      can_reset: false,
      icon_slug: "AlertTriangle",
      icon_color: "#f97316",
      name: "Incomplete",
      description: "Registration needs rank or role fixes.",
    },
    {
      value: "ready",
      scope: "balancer",
      is_builtin: true,
      kind: "builtin",
      is_override: false,
      can_edit: true,
      can_delete: false,
      can_reset: false,
      icon_slug: "CheckCircle2",
      icon_color: "#10b981",
      name: "Ready",
      description: "Registration is ready for balancer.",
    },
  ],
};

export function getBuiltinStatusMeta(scope: StatusScope): StatusMeta[] {
  return BUILTIN_STATUS_META[scope];
}

export function mergeStatusOptions(
  scope: StatusScope,
  customStatuses: BalancerCustomStatus[] | undefined,
): { system: StatusMeta[]; custom: StatusMeta[] } {
  const scopedStatuses = (customStatuses ?? []).filter((status) => status.scope === scope);
  const systemOverrides = scopedStatuses
    .filter((status) => status.kind === "builtin")
    .map((status) => ({
      value: status.slug,
      scope: status.scope,
      is_builtin: true,
      kind: "builtin" as const,
      is_override: status.is_override,
      can_edit: true,
      can_delete: false,
      can_reset: status.can_reset,
      icon_slug: status.icon_slug,
      icon_color: status.icon_color,
      name: status.name,
      description: status.description,
    }));
  const mergedSystem = BUILTIN_STATUS_META[scope].map((builtin) => {
    const override = systemOverrides.find((status) => status.value === builtin.value);
    return override ?? builtin;
  });

  return {
    system: mergedSystem,
    custom: scopedStatuses
      .filter((status) => status.kind === "custom")
      .map((status) => ({
        value: status.slug,
        scope: status.scope,
        is_builtin: false,
        kind: "custom" as const,
        is_override: false,
        can_edit: true,
        can_delete: true,
        can_reset: false,
        icon_slug: status.icon_slug,
        icon_color: status.icon_color,
        name: status.name,
        description: status.description,
      })),
  };
}
