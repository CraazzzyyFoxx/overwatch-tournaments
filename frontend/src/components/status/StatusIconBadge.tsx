import type { LucideIcon } from "lucide-react";

import { TONE_TEXT, type Tone } from "@/components/ui/tone";
import { cn } from "@/lib/utils";

interface StatusIconBadgeProps {
  /** The glyph standing in for the status. */
  icon: LucideIcon;
  /** The accessible name — the only thing AT has to go on. */
  label: string;
  tone: Tone;
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
        TONE_TEXT[tone],
        className
      )}
    >
      <Icon className="size-4" aria-hidden />
    </span>
  );
}
