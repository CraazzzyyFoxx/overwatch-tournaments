"use client";

import { useTranslations } from "next-intl";

import { StatusDot } from "@/components/ui/status-dot";
import { cn } from "@/lib/utils";
import type { RealtimeConnectionState } from "@/types/realtime.types";

/**
 * Realtime status LED. The words live in `title` / a live region — a labelled
 * pill next to page chrome reads as a third control. Show the label only when
 * the socket is not healthy; connected is just the dot.
 */
export function ConnectionIndicator({
  connectionState,
  className
}: Readonly<{ connectionState: RealtimeConnectionState; className?: string }>) {
  const t = useTranslations("common");
  const connected = connectionState === "connected";
  const label = t(`connection.${connectionState}`);

  return (
    <span
      role="status"
      aria-live="polite"
      title={label}
      className={cn(
        "inline-flex items-center gap-1.5 text-label",
        connected ? "text-[color:var(--aqt-support)]" : "text-[color:var(--aqt-warm)]",
        className
      )}
    >
      <StatusDot className={connected ? "shadow-[0_0_6px_currentColor]" : undefined} />
      <span className={connected ? "sr-only" : undefined}>{label}</span>
    </span>
  );
}
