"use client";

import { cn } from "@/lib/utils";

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

export interface ColorSwatchProps {
  /** `#rrggbb`, or anything else for "not set". */
  value: string;
  /** CSS colour painted while `value` is not set (a token, the derived default). */
  fallback?: string;
  /** Accessible name of the picker. */
  label: string;
  onValueChange: (hex: string) => void;
  disabled?: boolean;
  className?: string;
}

/**
 * A swatch that opens the system colour picker.
 *
 * The native `<input type="color">` lives here and nowhere in feature code
 * (DESIGN §6). It can only hold a literal `#rrggbb`, so an unset value cannot
 * be shown by the input itself: the swatch paints `fallback` with a dashed
 * edge instead, where the input used to paint black and read as "black is
 * set".
 */
export function ColorSwatch({
  value,
  fallback,
  label,
  onValueChange,
  disabled = false,
  className
}: Readonly<ColorSwatchProps>) {
  const set = HEX_RE.test(value);
  return (
    <span
      className={cn(
        "relative inline-flex size-9 shrink-0 overflow-hidden rounded-lg border border-[color:var(--aqt-border-2)]",
        "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-background",
        !set && "border-dashed",
        disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer",
        className
      )}
      style={{ background: set ? value : fallback }}
    >
      <input
        type="color"
        aria-label={label}
        // The input's own default when nothing is set; never painted.
        value={set ? value : "#000000"}
        disabled={disabled}
        onChange={(event) => onValueChange(event.target.value)}
        className="absolute inset-0 size-full cursor-[inherit] opacity-0"
      />
    </span>
  );
}
