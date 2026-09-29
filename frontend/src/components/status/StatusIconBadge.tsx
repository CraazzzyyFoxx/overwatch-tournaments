import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Semantic tone for every status surface. Both the icon badges and
 * `StatusMetaBadge`'s built-in fallback palette read from these records — they
 * used to carry two different hand-written palettes of raw Tailwind colors.
 */
export type StatusTone = "positive" | "warning" | "negative" | "info" | "neutral";

/** tone → foreground token (bare icon badges). */
const STATUS_TONE_FG: Record<StatusTone, string> = {
  positive: "text-[color:var(--aqt-emerald)]",
  warning: "text-[color:var(--aqt-amber)]",
  negative: "text-[color:var(--aqt-rose)]",
  info: "text-[color:var(--aqt-blue)]",
  neutral: "text-[color:var(--aqt-fg-faint)]"
};

/** tone → tinted pill (border + surface + text), for labelled status chips. */
export const STATUS_TONE_PILL: Record<StatusTone, string> = {
  positive:
    "border-[color:color-mix(in_srgb,var(--aqt-emerald)_22%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-emerald)_10%,transparent)] text-[color:var(--aqt-emerald)]",
  warning:
    "border-[color:color-mix(in_srgb,var(--aqt-amber)_22%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_10%,transparent)] text-[color:var(--aqt-amber)]",
  negative:
    "border-[color:color-mix(in_srgb,var(--aqt-rose)_22%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-rose)_10%,transparent)] text-[color:var(--aqt-rose)]",
  info:
    "border-[color:color-mix(in_srgb,var(--aqt-blue)_22%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-blue)_10%,transparent)] text-[color:var(--aqt-blue)]",
  neutral:
    "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg-faint)]"
};

/** Shape of a labelled status chip (icon + name); pair with `STATUS_TONE_PILL`. */
export const STATUS_CHIP_CLASS =
  "inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-label font-medium leading-none";

interface StatusIconBadgeProps {
  /** The glyph standing in for the status. */
  icon: LucideIcon;
  /** The accessible name — the only thing AT has to go on. */
  label: string;
  tone: StatusTone;
  className?: string;
}

/**
 * Icon-only status indicator. `role="img"` plus `aria-label` is what makes it
 * readable: the five badges this replaced each leaned on `title`, which no
 * screen reader announces reliably and touch devices cannot reach.
 */
export function StatusIconBadge({ icon: Icon, label, tone, className }: Readonly<StatusIconBadgeProps>) {
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex size-5 items-center justify-center",
        STATUS_TONE_FG[tone],
        className
      )}
    >
      <Icon className="size-4" aria-hidden />
    </span>
  );
}

export default StatusIconBadge;
