"use client";

import { useTranslations } from "next-intl";

import { TONE_TEXT, type Tone } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { StatusDot } from "@craazzzyyfoxx/admin-kit/ui/status-dot";
import { cn } from "@/lib/utils";

type AccessStatus = "active" | "expired" | "revoked";

const STATUS_TONE: Record<AccessStatus, Tone> = {
  active: "success",
  revoked: "warning",
  expired: "neutral"
};

/**
 * Status of a session or an API key as a tinted dot and word. `active` shows
 * only where it is news (a signed-in session), not where it is the norm (a key).
 */
export function AccessStatusCell({
  status,
  showActive
}: Readonly<{ status: AccessStatus; showActive: boolean }>) {
  const t = useTranslations("adminAccess.common");
  if (status === "active" && !showActive) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs font-medium",
        TONE_TEXT[STATUS_TONE[status]]
      )}
    >
      <StatusDot />
      {t(status)}
    </span>
  );
}
