"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * A filled button is semibold, in the same sentence case and size as every
 * other button in its row, with one 1px sheen along its top edge. Under the
 * pointer it brightens rather than fading, so it never dims into the surface.
 */
const SOLID = "font-semibold shadow-[inset_0_1px_0_var(--aqt-sheen)] hover:brightness-110";

/**
 * The tonal surface: raised off whatever it sits on (a page, a card, a dialog),
 * never a darker well punched into it. The `outline` button and every
 * select-like trigger (`SelectTrigger`, `Combobox`) wear it; the border steps
 * up while the panel the control opens is open.
 */
export const outlineSurfaceClass =
  "border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg)] shadow-[inset_0_1px_0_var(--aqt-overlay-3)] hover:border-[color:var(--aqt-border-3)] hover:bg-[color:var(--aqt-overlay-4)] aria-expanded:border-[color:var(--aqt-border-3)]";

/**
 * The trailing chevron of a select-like trigger: it turns over while the panel
 * is open, read off the `aria-expanded` of the trigger marked `group/trigger`
 * (named, so an expanded ancestor never turns it). A named group rather than a
 * `[[aria-expanded=true]>&]` selector: happy-dom keeps the `&gt;` that selector
 * serializes to inside an SVG class, and every hydration test would mismatch.
 */
export const triggerChevronClass =
  "size-4 shrink-0 opacity-50 transition-transform duration-150 group-aria-expanded/trigger:rotate-180";

const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium",
    "transition-[color,background-color,border-color,box-shadow,filter,transform] duration-150 ease-out",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
    // The press: a 1px sink, the same on every width (a scale shrinks a wide
    // button by several pixels and blurs its text), off for reduced motion.
    // `transform`, not `translate-y-*`: it adds to a caller's centring
    // `-translate-y-1/2` instead of replacing it (a 14px jump on a close X).
    "motion-safe:active:[transform:translateY(1px)]",
    "disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0"
  ],
  {
    variants: {
      variant: {
        default: cn("bg-primary text-primary-foreground", SOLID),
        destructive: cn("bg-destructive text-destructive-foreground", SOLID),
        /** A "go" confirmation the player can miss (check in): emerald fill. */
        positive: cn("bg-[color:var(--aqt-emerald)] text-[color:var(--aqt-bg)]", SOLID),
        /** The everyday button: the tonal surface (`outlineSurfaceClass`). */
        outline: outlineSurfaceClass,
        ghost: "hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]",
        /** An icon-only remove/delete beside a row: quiet at rest, the destructive tint on hover. */
        "ghost-destructive": "text-muted-foreground hover:bg-destructive/10 hover:text-destructive",
        link: "text-primary underline-offset-4 hover:underline",
        /** "Add one more" affordance: dashed outline, teal on hover (a phase, a match, a round). */
        dashed:
          "border border-dashed border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-muted)] hover:border-[color:var(--aqt-teal)] hover:text-[color:var(--aqt-teal)]",
        /** The row's primary action on the `--aqt-*` surface (open a scoreboard, report a result), and the chosen option of a choice: teal tint. */
        accent:
          "border border-[color:color-mix(in_srgb,var(--aqt-teal)_32%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_12%,transparent)] text-[color:var(--aqt-teal)] hover:bg-[color:color-mix(in_srgb,var(--aqt-teal)_18%,transparent)]"
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 px-3 text-caption",
        lg: "h-10 px-8",
        icon: "h-9 w-9",
        /** A secondary icon beside text (an explainer, a row action): 28px box, 14px glyph. */
        "icon-sm": "h-7 w-7 [&_svg]:size-3.5",
        /** A dense strip's text action (a canvas header's "+ match", a field's reset): 24px, label text, 12px glyph. */
        xs: "h-6 gap-1 rounded-md px-2 text-label [&_svg]:size-3",
        /** An icon inside a dense strip (a bracket card's footer, a wiring port): 20px box, 14px glyph or a label-size letter. */
        "icon-xs": "h-5 w-5 rounded text-label [&_svg]:size-3.5",
        /** Text action inside a sentence or row (`variant="link"`): no box, the surrounding text size, no press. */
        inline: "h-auto rounded-sm p-0 text-[length:inherit] motion-safe:active:[transform:none]",
        /** A sortable column head's own label (`variant="ghost"`): no box, the eyebrow voice, 12px glyph. Font family follows the cell. */
        label:
          "h-auto gap-1 rounded-sm p-0 text-label font-semibold uppercase tracking-label motion-safe:active:[transform:none] [&_svg]:size-3"
      }
    },
    defaultVariants: {
      variant: "default",
      size: "default"
    }
  }
);

interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />;
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
