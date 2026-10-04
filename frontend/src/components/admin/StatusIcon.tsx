import { IconTooltip } from "@/components/ui/icon-tooltip";
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

/** Compact status glyph: a tone-coloured icon with its label as the tooltip. */
export function StatusIcon({ icon: Icon, label, variant = "default", className }: Readonly<StatusIconProps>) {
  const tone = variantTone[variant];
  return (
    <IconTooltip label={label}>
      <Icon
        aria-hidden
        className={cn(
          "size-4",
          tone === "foreground" ? "text-foreground" : TONE_TEXT[tone],
          className
        )}
      />
    </IconTooltip>
  );
}
