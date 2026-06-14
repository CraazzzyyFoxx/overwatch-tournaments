"use client";

import { createElement } from "react";

import { getStatusIcon } from "@/lib/status-icons";
import { cn, hexToRgba } from "@/lib/utils";
import type { StatusMeta } from "@/types/balancer-admin.types";

function getFallbackClasses(scope: string, value: string) {
  if (scope === "registration") {
    if (value === "approved") return "border-emerald-500/20 bg-emerald-500/10 text-emerald-400";
    if (value === "rejected" || value === "banned") return "border-red-500/20 bg-red-500/10 text-red-400";
    if (value === "insufficient_data" || value === "pending") return "border-orange-500/20 bg-orange-500/10 text-orange-400";
    return "border-white/10 bg-white/5 text-white/50";
  }
  if (value === "ready") return "border-emerald-500/20 bg-emerald-500/10 text-emerald-400";
  if (value === "incomplete") return "border-orange-500/20 bg-orange-500/10 text-orange-400";
  return "border-white/10 bg-white/5 text-white/45";
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
}: StatusMetaBadgeProps) {
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
  };
  const iconElement = createElement(getStatusIcon(resolvedMeta.icon_slug), {
    className: "size-3",
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
      aria-label={resolvedMeta.name}
      style={tintedStyle}
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] font-medium",
        getFallbackClasses(resolvedMeta.scope, resolvedMeta.value),
        compact && "px-1.5",
        className,
      )}
    >
      {iconElement}
      {resolvedMeta.name}
    </span>
  );
}
