import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { TONE_TEXT, type Tone } from "@/components/kit/tone";
import type { LucideIcon } from "lucide-react";

/** Kept as the public prop name; maps onto the shared tone vocabulary. */
type StatusVariant = "default" | "muted" | "success" | "destructive" | "warning" | "info";

const variantTone: Record<StatusVariant, Tone | "foreground"> = {
  default: "foreground",
  muted: "neutral",
  success: "success",
  destructive: "danger",
  warning: "warning",
  info: "info"
};

interface StatusIconProps {
  icon: LucideIcon;
  label: string;
  variant?: StatusVariant;
  className?: string;
}

/**
 * Compact status glyph.
 *
 * The wrapper carries `role="img"` so `aria-label` is actually honoured —
 * on a bare `<span>` the element maps to `generic`, where ARIA prohibits
 * `aria-label` and the name was silently dropped. The label is therefore the
 * accessible name regardless of whether the pointer-only tooltip is reachable.
 */
export function StatusIcon({ icon: Icon, label, variant = "default", className }: Readonly<StatusIconProps>) {
  const tone = variantTone[variant];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex cursor-default" role="img" aria-label={label}>
          <Icon
            aria-hidden
            className={cn(
              "size-4",
              tone === "foreground" ? "text-foreground" : TONE_TEXT[tone],
              className
            )}
          />
        </span>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}
