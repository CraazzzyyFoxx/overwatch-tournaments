import { cn } from "@/lib/utils";

export type OwtButtonVariant = "primary" | "outline" | "ghost";
export type OwtButtonSize = "sm" | "md" | "lg" | "icon";

const BASE =
  "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-[var(--aqt-radius-sm)] border border-transparent " +
  "font-[family-name:var(--aqt-data)] font-semibold leading-none cursor-pointer " +
  "transition-[background-color,border-color,color,transform] duration-150 active:translate-y-px " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)] " +
  "disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50 " +
  "[&_svg]:shrink-0";

const VARIANT: Record<OwtButtonVariant, string> = {
  primary:
    "bg-[color:var(--aqt-teal)] text-primary-foreground hover:bg-[color:color-mix(in_srgb,var(--aqt-teal)_88%,white)]",
  outline:
    "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)] text-[color:var(--aqt-fg)] " +
    "hover:border-[color:var(--aqt-border-3)] hover:bg-[color:var(--aqt-overlay-3)]",
  ghost:
    "text-[color:var(--aqt-fg-muted)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
};

const SIZE: Record<OwtButtonSize, string> = {
  sm: "h-8 px-3 text-caption [&_svg]:size-3.5",
  md: "h-9 px-3.5 text-body [&_svg]:size-4",
  lg: "h-11 px-[18px] text-ui [&_svg]:size-4",
  icon: "size-9 p-0 text-body [&_svg]:size-4"
};

/**
 * The open-layout pages' button (mock `.btn`): 36/44/32px, 8px radius, 600
 * weight. A class string rather than a component so a `Link`, a `<button>` and
 * a Radix trigger all wear it without `asChild` plumbing.
 */
export function owtButton({
  variant,
  size = "md",
  className
}: {
  variant: OwtButtonVariant;
  size?: OwtButtonSize;
  className?: string;
}): string {
  return cn(BASE, VARIANT[variant], SIZE[size], className);
}
