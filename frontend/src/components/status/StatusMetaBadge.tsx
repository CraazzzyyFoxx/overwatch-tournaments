"use client";

import { createElement } from "react";

import { getStatusIcon } from "@/lib/registration/status-icons";
import { STATUS_TONE_PILL, type StatusTone } from "@/components/status/StatusIconBadge";
import { cn, hexToRgba } from "@/lib/utils";
import type { StatusMeta } from "@/types/registration.types";

/** Built-in status value → tone, used when the status carries no `icon_color`. */
function getFallbackTone(scope: string, value: string): StatusTone {
  if (scope === "registration") {
    if (value === "approved") return "positive";
    if (value === "rejected" || value === "banned") return "negative";
    if (value === "insufficient_data" || value === "pending") return "warning";
    return "neutral";
  }
  if (value === "ready") return "positive";
  if (value === "incomplete") return "warning";
  return "neutral";
}

type StatusMetaBadgeProps = {
  meta: StatusMeta | null | undefined;
  fallbackValue?: string;
  className?: string;
  compact?: boolean;
};

export default function StatusMetaBadge({
  meta,
  fallbackValue = "unknown",
  className,
  compact = false,
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
    style: resolvedMeta.icon_color ? { color: resolvedMeta.icon_color } : undefined,
  });
  const tintedStyle = resolvedMeta.icon_color
    ? {
        color: resolvedMeta.icon_color,
        borderColor: hexToRgba(resolvedMeta.icon_color, 0.35) ?? resolvedMeta.icon_color,
        backgroundColor: hexToRgba(resolvedMeta.icon_color, 0.12) ?? "transparent",
      }
    : undefined;

  return (
    <span
      title={resolvedMeta.description ?? resolvedMeta.name}
      style={tintedStyle}
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-label font-medium leading-none",
        STATUS_TONE_PILL[getFallbackTone(resolvedMeta.scope, resolvedMeta.value)],
        compact && "px-1.5",
        className,
      )}
    >
      <span className="inline-flex shrink-0 items-center justify-center">{iconElement}</span>
      {resolvedMeta.name}
    </span>
  );
}
