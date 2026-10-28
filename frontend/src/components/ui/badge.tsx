import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { TONE_CLASS, TONE_TINT, type Tone } from "@/components/ui/tone";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 whitespace-nowrap border px-2 py-0.5 text-label font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: TONE_CLASS.neutral,
        outline: "border-border/60 bg-transparent text-foreground"
      },
      shape: {
        badge: "rounded-md",
        pill: "rounded-full"
      },
      size: {
        default: "",
        /** The dense status chip of admin tables and registration rows. */
        sm: "px-1.5 leading-none"
      },
      voice: {
        text: "",
        /** The uppercase data/label voice: lifecycle status, "League". */
        label: "gap-1.5 py-1 font-[family-name:var(--aqt-data)] font-bold uppercase tracking-label"
      }
    },
    defaultVariants: {
      variant: "default",
      shape: "badge",
      size: "default",
      voice: "text"
    }
  }
);

interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {
  /** Semantic tone (`TONE_CLASS`); wins over `variant`. */
  tone?: Tone;
  /**
   * A hue no `Tone` names (a lifecycle status, a role colour): the same tint
   * (`TONE_TINT`) over this CSS colour. Wins over `tone`.
   */
  hue?: string;
}

function Badge({ className, variant, shape, size, voice, tone, hue, style, ...props }: BadgeProps) {
  return (
    <span
      style={hue ? ({ ...style, "--tone-hue": hue } as React.CSSProperties) : style}
      className={cn(
        badgeVariants({ variant: tone || hue ? null : variant, shape, size, voice }),
        hue ? TONE_TINT : tone && TONE_CLASS[tone],
        className
      )}
      {...props}
    />
  );
}

export { Badge };
