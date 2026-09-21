import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

/**
 * shadcn `bubble` — the visible message surface that sits inside a `Message`
 * (`./message.tsx`). Structure, slots and alignment behaviour are the registry
 * item's (`.../r/styles/new-york-v4/bubble.json`); two things are deliberately
 * not copied:
 *
 * - The `tinted`/`secondary`/`muted` hover recipes upstream read the theme with
 *   relative colour syntax (`oklch(from var(--primary) …)`,
 *   `color-mix(in oklch, var(--secondary) …)`). This project's shadcn tokens
 *   hold BARE HSL TRIPLETS (`DESIGN.md:50`), wrapped as `hsl(var(--primary))`,
 *   so those functions would receive `172 70% 49%` and drop the declaration.
 * - The interactive-bubble rules (`[button,a]:hover`, `BubbleReactions`) and the
 *   `asChild` escape hatch: a room chat renders text, not buttons, and an unused
 *   variant is a variant nobody keeps honest.
 */
const bubbleVariants = cva(
  "group/bubble relative flex w-fit max-w-[80%] min-w-0 flex-col gap-1 group-data-[align=end]/message:self-end data-[align=end]:self-end data-[variant=ghost]:max-w-full",
  {
    variants: {
      variant: {
        default:
          "*:data-[slot=bubble-content]:bg-primary *:data-[slot=bubble-content]:text-primary-foreground",
        muted: "*:data-[slot=bubble-content]:bg-muted",
        outline:
          "*:data-[slot=bubble-content]:border-border *:data-[slot=bubble-content]:bg-background",
        ghost:
          "border-none *:data-[slot=bubble-content]:rounded-none *:data-[slot=bubble-content]:bg-transparent *:data-[slot=bubble-content]:p-0"
      }
    },
    defaultVariants: {
      variant: "default"
    }
  }
);

function BubbleGroup({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      data-slot="bubble-group"
      className={cn("flex min-w-0 flex-col gap-2", className)}
      {...props}
    />
  );
}

function Bubble({
  variant = "default",
  align = "start",
  className,
  ...props
}: ComponentProps<"div"> & VariantProps<typeof bubbleVariants> & { align?: "start" | "end" }) {
  return (
    <div
      data-slot="bubble"
      data-variant={variant}
      data-align={align}
      className={cn(bubbleVariants({ variant }), className)}
      {...props}
    />
  );
}

function BubbleContent({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      data-slot="bubble-content"
      className={cn(
        "w-fit max-w-full min-w-0 overflow-hidden rounded-xl border border-transparent px-3 py-2 text-sm leading-relaxed wrap-break-word group-data-[align=end]/bubble:self-end",
        className
      )}
      {...props}
    />
  );
}

export { Bubble, BubbleContent, BubbleGroup };
