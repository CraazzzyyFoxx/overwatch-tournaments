import type { CSSProperties } from "react";

import { TONE_TEXT, type Tone } from "@/components/ui/tone";
import { cn } from "@/lib/utils";

export interface StatusDotProps {
  /** Tone of the state this dot marks. Omit to inherit the parent's colour. */
  tone?: Tone;
  /** Breathing animation for a live/in-progress state. */
  pulse?: boolean;
  className?: string;
  /**
   * For a colour that only exists at runtime (a role tint, a server-supplied
   * status hue): `style={{ color }}`. A colour that is a token belongs in
   * `className` as `text-[color:var(--aqt-rose)]`.
   */
  style?: CSSProperties;
}

/**
 * The one status dot. Decorative by definition — it is always `aria-hidden`,
 * because the label beside it carries the state. A dot on its own would be
 * colour-only information.
 *
 * The fill is `currentColor`, so a domain hue with no `Tone` is set by colouring
 * the dot rather than by inventing a tone.
 */
export function StatusDot({ tone, pulse = false, className, style }: Readonly<StatusDotProps>) {
  return (
    <span
      aria-hidden
      style={style}
      className={cn(
        "size-1.5 shrink-0 rounded-full bg-current",
        tone ? TONE_TEXT[tone] : undefined,
        pulse && "animate-pulse motion-reduce:animate-none",
        className
      )}
    />
  );
}
