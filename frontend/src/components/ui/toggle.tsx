"use client";

import { cva } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * A choice between whole options (a caption over a value, a picture): each
 * option is its own bordered card, tinted in `--toggle-accent` (teal unless an
 * item sets one) once chosen. One recipe for `ToggleGroup variant="card"` and
 * `RadioGroupItem variant="card"`: both are `role="radio"`, so `aria-checked`
 * is the chosen state of either. The press is the button's 1px sink (§10).
 */
const optionCardClass =
  "rounded-lg border border-[color:var(--aqt-border-2)] px-3 py-2 text-left text-sm text-[color:var(--aqt-fg-muted)] " +
  "transition-[color,background-color,border-color,transform] duration-150 ease-out motion-safe:active:[transform:translateY(1px)] " +
  "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background " +
  "disabled:cursor-not-allowed disabled:opacity-50 not-aria-checked:not-disabled:hover:bg-[color:var(--aqt-overlay-2)] " +
  "aria-checked:border-[color:var(--toggle-accent,var(--aqt-teal))] aria-checked:text-[color:var(--aqt-fg)] " +
  "aria-checked:bg-[color:color-mix(in_srgb,var(--toggle-accent,var(--aqt-teal))_10%,transparent)]";

/**
 * `pill` is the site's segmented-control look: flat items in a
 * `segmentedFrame`, the active one tinted teal. Every segmented control on the
 * site draws it — `ToggleGroup`, the bracket's stage links, and the Radix
 * `Tabs` rows — so the variant answers to BOTH state attributes:
 * `data-state=on` (ToggleGroup, links) and `data-state=active` (Radix Tabs).
 * `card` is {@link optionCardClass}, laid out by the group's grid.
 *
 * The pill sits inside the frame's 3px padding, so its own height is the row
 * height minus that frame: an `sm` group is 32px tall like the `sm` select and
 * search field beside it. Text follows the ROW height (32px → 13px, 36/40px →
 * 14px), the same scale as every other control.
 */
const toggleVariants = cva(
  "inline-flex items-center justify-center gap-2 font-medium transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
  {
    variants: {
      variant: {
        // The on state reads `--toggle-accent` when an item sets one (teal otherwise); Tabs' `active` stays teal.
        pill: "rounded-md text-[color:var(--aqt-fg-muted)] focus-visible:ring-inset not-disabled:hover:text-[color:var(--aqt-fg)] data-[state=on]:bg-[color:color-mix(in_srgb,var(--toggle-accent,var(--aqt-teal))_14%,transparent)] data-[state=on]:text-[color:var(--toggle-accent,var(--aqt-teal))] data-[state=on]:shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--toggle-accent,var(--aqt-teal))_30%,transparent)] data-[state=active]:bg-[color:color-mix(in_srgb,var(--aqt-teal)_14%,transparent)] data-[state=active]:text-[color:var(--aqt-teal)] data-[state=active]:shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--aqt-teal)_30%,transparent)]",
        card: cn(optionCardClass, "flex-col items-stretch justify-start gap-0.5 font-normal")
      },
      size: {
        sm: "h-6 min-w-6 px-3 text-caption",
        default: "h-7 min-w-7 px-3.5 text-sm",
        lg: "h-8 min-w-8 px-4 text-sm"
      }
    },
    compoundVariants: [
      // A card holds a caption over a value, so its height is its content's.
      { variant: "card", size: ["sm", "default", "lg"], class: "h-auto min-w-0 px-3" }
    ],
    defaultVariants: {
      variant: "pill",
      size: "default"
    }
  }
);

/**
 * The frame every segmented control draws around its items: the control
 * surface (§5) with 3px of padding. With `size="sm"` items (24px) that lands on
 * a 32px row, level with the search field and sort select beside it. Red once
 * the group is `aria-invalid`.
 */
const segmentedFrame =
  "inline-flex items-center gap-1 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-[3px] aria-invalid:border-destructive";

export { optionCardClass, segmentedFrame, toggleVariants };
