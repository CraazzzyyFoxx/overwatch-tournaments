"use client";

import { createElement } from "react";

import { getStatusIcon } from "@/lib/registration/status-icons";
import { Badge } from "@/components/ui/badge";
import type { Tone } from "@/components/ui/tone";
import type { StatusMeta } from "@/types/registration.types";

/** Built-in status value → tone, used when the status carries no `icon_color`. */
function getFallbackTone(scope: string, value: string): Tone {
  if (scope === "registration") {
    if (value === "approved") return "success";
    if (value === "rejected" || value === "banned") return "danger";
    if (value === "insufficient_data" || value === "pending") return "warning";
    return "neutral";
  }
  if (value === "ready") return "success";
  if (value === "incomplete") return "warning";
  return "neutral";
}

type StatusMetaBadgeProps = {
  meta: StatusMeta | null | undefined;
  fallbackValue?: string;
  className?: string;
};

export default function StatusMetaBadge({
  meta,
  fallbackValue = "unknown",
  className,
}: Readonly<StatusMetaBadgeProps>) {
  const resolvedMeta: StatusMeta = meta ?? {
    value: fallbackValue,
    scope: "registration",
    is_builtin: false,
    kind: "custom",
    is_override: false,
    can_edit: false,
    can_delete: false,
    can_reset: false,
    icon_slug: "BadgeHelp",
    icon_color: null,
    name: fallbackValue.replace(/_/g, " "),
    description: null,
    excludes_from_balancer: false,
    excludes_from_ready: false,
  };
  const iconElement = createElement(getStatusIcon(resolvedMeta.icon_slug), {
    className: "size-3",
    "aria-hidden": true,
  });

  return (
    <Badge
      size="sm"
      hue={resolvedMeta.icon_color ?? undefined}
      tone={getFallbackTone(resolvedMeta.scope, resolvedMeta.value)}
      title={resolvedMeta.description ?? resolvedMeta.name}
      className={className}
    >
      <span className="inline-flex shrink-0 items-center justify-center">{iconElement}</span>
      {resolvedMeta.name}
    </Badge>
  );
}
